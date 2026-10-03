"""Static gate for legacy Theme reads that bypass authority routing (#474).

Retirement criterion 4 of the economic taxonomy audit: no API route, Celery
task or MCP tool may reach a legacy authority model unless it routes through
``EconomicThemeReader`` (or another authority check) first.

How it decides, per entry point:

- **Reachability** follows an AST call graph over ``app/``. Names resolve
  through module and function-local imports and literal ``import_module``
  calls. Attribute calls resolve through simple typing: annotations,
  ``x = Cls(...)``, ``x = factory()`` (inferred from its returns),
  ``self.attr = ...``, constructor-injected dependencies, ``injected or
  Default(...)`` and module-level singletons. A method call also follows its
  overrides in subclasses and, for a ``Protocol`` port, its implementations.
  Celery dispatch (``task.delay``) is not followed; the task is its own entry
  point.
- **A legacy read** is a reference to a legacy model class (outside type
  annotations) or a SQL string naming one of their tables.
- **Routing:** an authority check in ``ROUTING_MARKERS`` decides by mode, so
  what a function reads or calls after its first check is routed and the walk
  does not follow it. Only checks that run unconditionally count: in
  straight-line code, a ``with`` item, a decorator or an ``if`` test, but not
  inside a branch, loop or handler body, nor in an annotation. Reads before the
  check stay unrouted. A route is also routed when it depends on
  ``GUARD_DEPENDENCIES`` (409 in economic mode).

ponytail: a static over/under-approximation, not a proof. Calls on objects it
cannot type are not followed, ORM relationship loads are invisible, and a check
is assumed to divert economic mode (return or raise) rather than proven to;
when a miss turns up, tighten these rules rather than add a runtime harness.
"""

from __future__ import annotations

import ast
import inspect
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "app"

LEGACY_MODELS = frozenset({
    "ThemeCluster", "ThemeMention", "ThemeConstituent", "ThemeAlias",
    "ThemeMetrics", "ThemeAlert", "ThemeEmbedding", "ThemeMergeSuggestion",
    "ThemeMergeHistory", "ThemeRelationship", "ThemeLifecycleTransition",
    "ThemeEquivalenceOperation", "ThemeDevelopmentTheme",
    "SocialThemeAssociation", "SocialThemeDecision",
})

ROUTING_MARKERS = frozenset({
    # Authority-routed reads.
    "app.services.economic_theme_read_service.EconomicThemeReader",
    "app.api.v1.themes_queries._economic_reader",
    "app.api.v1.themes_taxonomy._reject_economic_mode",
    # Writers that are skipped, refused or fenced outside legacy write modes (#472).
    "app.services.legacy_theme_write_guard.legacy_theme_writes_blocked",
    "app.services.legacy_theme_write_guard.skip_in_economic_authority",
    "app.services.legacy_theme_write_guard.ensure_legacy_theme_writes_allowed",
    "app.services.legacy_theme_write_guard.exit_if_legacy_theme_writes_blocked",
    "app.services.theme_discovery_service.ThemeDiscoveryService._fenced_legacy_mutation",
    "app.services.economic_taxonomy_runtime.EconomicTaxonomyRuntimeService.legacy_producer_write",
})

GUARD_DEPENDENCIES = frozenset({"app.api.v1.themes_common.reject_legacy_theme_writes"})

_CELERY_DISPATCH = frozenset({"delay", "apply_async", "s", "si", "signature", "map", "starmap", "chunks"})
_SQL_VERB = re.compile(r"\b(FROM|JOIN|UPDATE|INTO|TABLE)\b", re.IGNORECASE)


@dataclass
class Module:
    name: str
    tree: ast.Module
    package: str
    imports: dict[str, str] = field(default_factory=dict)
    defs: dict[str, ast.AST] = field(default_factory=dict)
    var_types: dict[str, Class] = field(default_factory=dict)


@dataclass
class Func:
    qualname: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    module: Module
    cls: Class | None
    _nodes: list[ast.AST] | None = None

    @property
    def nodes(self):
        if self._nodes is None:
            self._nodes = list(ast.walk(self.node))
        return self._nodes


@dataclass
class Class:
    qualname: str
    node: ast.ClassDef
    module: Module
    methods: dict[str, Func] = field(default_factory=dict)
    bases: list[Class] = field(default_factory=list)
    subclasses: list[Class] = field(default_factory=list)
    attr_types: dict[str, Class] = field(default_factory=dict)
    is_protocol: bool = False

    def mro(self):
        seen, queue = [], [self]
        while queue:
            cls = queue.pop(0)
            if cls not in seen:
                seen.append(cls)
                queue.extend(cls.bases)
        return seen

    def method(self, name):
        for cls in self.mro():
            if name in cls.methods:
                return cls.methods[name]
        return None

    def attr_type(self, name):
        for cls in self.mro():
            if name in cls.attr_types:
                return cls.attr_types[name]
        return None


@dataclass
class Finding:
    entry: str
    model: str
    path: list[str]


class Index:
    def __init__(self, legacy_models: set[str], legacy_tables: set[str], root: Path = APP_ROOT):
        self.legacy_models = legacy_models  # qualified class names
        self.modules: dict[str, Module] = {}
        self.funcs: dict[str, Func] = {}
        self.classes: dict[str, Class] = {}
        self._table_pattern = (
            re.compile(r"\b(" + "|".join(sorted(legacy_tables)) + r")\b") if legacy_tables else None
        )
        for path in root.rglob("*.py"):
            parts = path.relative_to(root.parent).with_suffix("").parts
            if "db_migrations" in parts:
                continue  # historical schema migrations
            name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
            self._load(name, path, is_package=parts[-1] == "__init__")
        self._module_scopes: dict[str, dict[str, str]] = {}
        self._func_scopes: dict[str, dict[str, str]] = {}
        self._returns: dict[str, Class | None] = {}
        for cls in self.classes.values():
            self._link_class(cls)
        for module in self.modules.values():  # module-level singletons
            scope = self._scope(module, None)
            for node in module.tree.body:
                if (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Call)
                ):
                    typed = self._resolve_expr(node.value, scope, {})
                    if isinstance(typed, Class):
                        module.var_types[node.targets[0].id] = typed
        self._module_scopes.clear()  # cached before the singletons were known
        self._func_scopes.clear()
        self._returns.clear()
        # Learn self.attr types up front, including dependencies injected
        # through constructor arguments (e.g. use-case factories).
        for func in list(self.funcs.values()):
            self._local_types(func, self._scope(func.module, func))
        self._edges: dict[str, tuple[dict[str, tuple], dict[str, tuple], tuple | None]] = {}
        self._overrides: dict[str, list[Func]] = {}

    # -- indexing ---------------------------------------------------------

    def _load(self, name, path, *, is_package):
        tree = ast.parse(path.read_text(), filename=str(path))
        package = name if is_package else name.rpartition(".")[0]
        module = Module(name, tree, package)
        self.modules[name] = module
        for node in tree.body:
            self._collect_imports(node, package, module.imports)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func = Func(f"{name}.{node.name}", node, module, None)
                module.defs[node.name] = node
                self.funcs[func.qualname] = func
            elif isinstance(node, ast.ClassDef):
                cls = Class(f"{name}.{node.name}", node, module)
                module.defs[node.name] = node
                self.classes[cls.qualname] = cls
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method = Func(f"{cls.qualname}.{item.name}", item, module, cls)
                        cls.methods[item.name] = method
                        self.funcs[method.qualname] = method
            elif isinstance(node, (ast.If, ast.Try)):  # TYPE_CHECKING / optional imports
                for child in ast.walk(node):
                    self._collect_imports(child, package, module.imports)

    @staticmethod
    def _collect_imports(node, package, into):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    into[alias.asname] = alias.name
                else:
                    head = alias.name.split(".")[0]
                    into[head] = head
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")
                anchor = anchor[: len(anchor) - (node.level - 1)]
                base = ".".join([*anchor, base] if base else anchor)
            for alias in node.names:
                into[alias.asname or alias.name] = f"{base}.{alias.name}"

    def _link_class(self, cls):
        scope = self._scope(cls.module, None)
        for base in cls.node.bases:
            resolved = self._resolve_expr(base, scope, {})
            if isinstance(resolved, Class):
                cls.bases.append(resolved)
                resolved.subclasses.append(cls)
            elif (getattr(base, "id", None) or getattr(base, "attr", None)) == "Protocol":
                cls.is_protocol = True
        for item in cls.node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                typed = self._annotation_class(item.annotation, scope)
                if typed:
                    cls.attr_types[item.target.id] = typed

    def resolve(self, dotted, _depth=0):
        """Resolve a dotted name to a Module, Class or Func in app/."""
        if _depth > 10 or not dotted.startswith("app"):
            return None
        if dotted in self.modules:
            return self.modules[dotted]
        if dotted in self.funcs:
            return self.funcs[dotted]
        if dotted in self.classes:
            return self.classes[dotted]
        head, _, attr = dotted.rpartition(".")
        owner = self.resolve(head, _depth + 1) if head else None
        if isinstance(owner, Module):
            if attr in owner.var_types:
                return owner.var_types[attr]
            if attr in owner.imports:
                return self.resolve(owner.imports[attr], _depth + 1)
            return None
        if isinstance(owner, Class):
            return owner.method(attr)
        return None

    def _scope(self, module, func):
        if module.name not in self._module_scopes:
            scope = dict(module.imports)
            scope.update({name: f"{module.name}.{name}" for name in module.defs})
            scope.update({name: f"{module.name}.{name}" for name in module.var_types})
            self._module_scopes[module.name] = scope
        if func is None:
            return self._module_scopes[module.name]
        if func.qualname not in self._func_scopes:
            scope = dict(self._module_scopes[module.name])
            for node in func.nodes:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    self._collect_imports(node, module.package, scope)
            self._func_scopes[func.qualname] = scope
        return self._func_scopes[func.qualname]

    # -- expression typing ------------------------------------------------

    def _resolve_expr(self, expr, scope, local_types):
        """The Module/Class/Func an expression names, or the Class of its value."""
        if isinstance(expr, ast.Name):
            if expr.id in local_types:
                return local_types[expr.id]
            if expr.id in scope:
                return self.resolve(scope[expr.id])
            return None
        if isinstance(expr, ast.Attribute):
            base = self._resolve_expr(expr.value, scope, local_types)
            if isinstance(base, Module):
                return self.resolve(f"{base.name}.{expr.attr}")
            if isinstance(base, Class):
                return base.method(expr.attr) or base.attr_type(expr.attr)
            return None
        if isinstance(expr, ast.Call):
            imported = self._import_module_call(expr)
            if imported is not None:
                return imported
            callee = self._resolve_expr(expr.func, scope, local_types)
            if isinstance(callee, Class):
                return callee
            if isinstance(callee, Func):
                return self._return_class(callee)
            return None
        if isinstance(expr, ast.Subscript):  # e.g. Annotated[X, ...]
            return self._resolve_expr(expr.value, scope, local_types)
        if isinstance(expr, (ast.BoolOp, ast.IfExp)):  # injected or Default(...)
            options = expr.values if isinstance(expr, ast.BoolOp) else [expr.body, expr.orelse]
            for option in options:
                resolved = self._resolve_expr(option, scope, local_types)
                if isinstance(resolved, Class):
                    return resolved
        return None

    def _return_class(self, func):
        """The Class (or Module, for ``return import_module("...")``) a call returns."""
        if func.qualname not in self._returns:
            self._returns[func.qualname] = None  # recursion guard
            if func.node.returns is not None:
                self._returns[func.qualname] = self._annotation_class(
                    func.node.returns, self._scope(func.module, None)
                )
            else:  # unannotated factories: infer from what every return yields
                returns = [n.value for n in func.nodes if isinstance(n, ast.Return) and n.value is not None]
                scope = self._scope(func.module, func)
                types = self._local_types(func, scope)
                inferred = {id(t): t for t in (self._resolve_expr(r, scope, types) for r in returns)}
                if len(inferred) == 1:
                    typed = next(iter(inferred.values()))
                    if isinstance(typed, (Class, Module)):
                        self._returns[func.qualname] = typed
        return self._returns[func.qualname]

    def _import_module_call(self, expr):
        if not (isinstance(expr, ast.Call) and expr.args):
            return None
        name = getattr(expr.func, "id", None) or getattr(expr.func, "attr", None)
        target = expr.args[0]
        if name == "import_module" and isinstance(target, ast.Constant) and isinstance(target.value, str):
            return self.modules.get(target.value)
        return None

    def _annotation_class(self, annotation, scope):
        if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
            try:
                annotation = ast.parse(annotation.value, mode="eval").body
            except SyntaxError:
                return None
        for node in ast.walk(annotation):
            if isinstance(node, (ast.Name, ast.Attribute)):
                resolved = self._resolve_expr(node, scope, {})
                if isinstance(resolved, Class):
                    return resolved
        return None

    def _local_types(self, func, scope):
        types: dict[str, Class | Module] = {}
        if func.cls is not None:
            args = func.node.args.posonlyargs + func.node.args.args
            if args:
                types[args[0].arg] = func.cls
        for arg in [*func.node.args.posonlyargs, *func.node.args.args, *func.node.args.kwonlyargs]:
            if arg.annotation is not None:
                typed = self._annotation_class(arg.annotation, scope)
                if typed:
                    types[arg.arg] = typed
        for node in func.nodes:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                typed = self._resolve_expr(node.value, scope, types)
                target = node.targets[0]
                if isinstance(typed, Module) and isinstance(target, ast.Name):
                    types[target.id] = typed  # e.g. x = import_module("app....")
                elif isinstance(typed, Class):
                    if isinstance(target, ast.Name):
                        types[target.id] = typed
                    elif (
                        func.cls is not None
                        and isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        func.cls.attr_types.setdefault(target.attr, typed)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                typed = self._annotation_class(node.annotation, scope)
                if typed:
                    types[node.target.id] = typed
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if isinstance(item.optional_vars, ast.Name):
                        typed = self._resolve_expr(item.context_expr, scope, types)
                        if isinstance(typed, Class):
                            types[item.optional_vars.id] = typed
        for node in func.nodes:
            if isinstance(node, ast.Call):
                cls = self._resolve_expr(node.func, scope, types)
                if isinstance(cls, Class) and not isinstance(node.func, ast.Call):
                    self._bind_constructor_args(cls, node, scope, types)
        return types

    def _bind_constructor_args(self, cls, call, scope, types):
        """``Cls(writer=Writer(...))`` types ``Cls.writer`` when ``__init__``
        stores the parameter as ``self.writer`` (or ``Cls`` has no ``__init__``)."""
        init = cls.method("__init__")
        if init is None:
            params, stored = [], None  # dataclass-style: keyword == attribute
        else:
            args = init.node.args
            params = [a.arg for a in [*args.posonlyargs, *args.args][1:]]
            stored = {
                node.value.id: node.targets[0].attr
                for node in init.nodes
                if isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Attribute)
                and isinstance(node.targets[0].value, ast.Name)
                and node.targets[0].value.id == "self"
                and isinstance(node.value, ast.Name)
            }
        bound = list(zip(params, call.args)) + [(kw.arg, kw.value) for kw in call.keywords if kw.arg]
        for param, value in bound:
            attr = param if stored is None else stored.get(param)
            if attr is None:
                continue
            typed = self._resolve_expr(value, scope, types)
            if isinstance(typed, Class):
                cls.attr_types.setdefault(attr, typed)

    # -- per-function facts -----------------------------------------------

    def facts(self, func):
        """(callees, legacy models read, routing point).

        Callees and models map to the source position where they first occur;
        the routing point is the position of the first unconditional authority
        check, or None.
        """
        if func.qualname in self._edges:
            return self._edges[func.qualname]
        scope = self._scope(func.module, func)
        types = self._local_types(func, scope)
        annotations = _annotation_nodes(func.nodes)
        conditional = _conditional_nodes(func.node)
        dispatched = {
            id(node.value) for node in func.nodes
            if isinstance(node, ast.Attribute) and node.attr in _CELERY_DISPATCH
        }
        callees: dict[str, tuple] = {}
        models: dict[str, tuple] = {}
        routing: tuple | None = None

        def note(found, key, position):
            if key not in found or position < found[key]:
                found[key] = position

        for node in func.nodes:
            position = (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if self._table_pattern and _SQL_VERB.search(node.value):
                    for table in self._table_pattern.findall(node.value):
                        note(models, f"table:{table}", position)
                continue
            if not isinstance(node, (ast.Name, ast.Attribute)) or id(node) in dispatched:
                continue
            if isinstance(node, ast.Name) and node.id in types:
                continue  # a typed local value, not a reference to a definition
            resolved = self._resolve_expr(node, scope, types)
            if resolved is None:
                continue
            if id(node) in annotations:
                continue  # type hints neither read nor route
            qualname = resolved.qualname if isinstance(resolved, (Func, Class)) else None
            if qualname in ROUTING_MARKERS and id(node) not in conditional:
                routing = position if routing is None else min(routing, position)
            if isinstance(resolved, Class):
                if resolved.qualname in self.legacy_models:
                    note(models, resolved.node.name, position)
                    continue
                for ctor in ("__init__", "__post_init__"):
                    method = resolved.method(ctor)
                    if method:
                        note(callees, method.qualname, position)
            elif isinstance(resolved, Func) and resolved is not func:
                note(callees, resolved.qualname, position)
                for override in self.overrides(resolved):
                    note(callees, override.qualname, position)
        self._edges[func.qualname] = (callees, models, routing)
        return self._edges[func.qualname]

    def overrides(self, method):
        """Virtual dispatch: the method's overrides in app subclasses and, for a
        Protocol (e.g. a use-case port), in the app classes implementing it."""
        if method.cls is None:
            return []
        if method.qualname not in self._overrides:
            name, owner = method.node.name, method.cls
            found, stack = [], list(owner.subclasses)
            while stack:
                cls = stack.pop()
                stack.extend(cls.subclasses)
                if name in cls.methods:
                    found.append(cls.methods[name])
            if owner.is_protocol:
                required = set(owner.methods) - {"__init__"}
                for cls in self.classes.values():
                    if not cls.is_protocol and name in cls.methods and required <= {
                        m for c in cls.mro() for m in c.methods
                    }:
                        found.append(cls.methods[name])
            self._overrides[method.qualname] = found
        return self._overrides[method.qualname]

    def legacy_reads(self, entry, roots):
        """Unrouted legacy reads reachable from ``roots``: model -> call path."""
        found: dict[str, list[str]] = {}
        parents: dict[str, str | None] = {}
        queue = deque()
        for root in roots:
            if root.qualname not in parents:
                parents[root.qualname] = None
                queue.append(root.qualname)
        while queue:
            qualname = queue.popleft()
            callees, models, routing = self.facts(self.funcs[qualname])
            for model, position in models.items():
                if model not in found and (routing is None or position < routing):
                    found[model] = _path(parents, qualname)
            for callee, position in callees.items():
                if routing is not None and position >= routing:
                    continue  # reached only after the authority check
                if callee not in parents:
                    parents[callee] = qualname
                    queue.append(callee)
        return [Finding(entry, model, path) for model, path in sorted(found.items())]

    def func_for(self, obj):
        target = inspect.unwrap(obj)
        module = getattr(target, "__module__", None)
        qualname = getattr(target, "__qualname__", "")
        if module is None or "<locals>" in qualname:
            return None
        return self.funcs.get(f"{module}.{qualname}")


def _annotation_nodes(nodes):
    ids = set()
    roots = []
    for node in nodes:
        if isinstance(node, ast.arg) and node.annotation is not None:
            roots.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            roots.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            roots.append(node.annotation)
    for root in roots:
        ids.update(id(child) for child in ast.walk(root))
    return ids


def _conditional_nodes(func_node):
    """Nodes that run only on some paths through the function: branch, loop
    and handler bodies, short-circuited operands, nested functions."""
    whole = (ast.Match, ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef,
             ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
    conditional: set[int] = set()
    for node in ast.walk(func_node):
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            parts = [*node.body, *node.orelse]
        elif isinstance(node, ast.Try):
            parts = [*node.handlers, *node.orelse]
        elif isinstance(node, ast.IfExp):
            parts = [node.body, node.orelse]
        elif isinstance(node, ast.BoolOp):
            parts = node.values[1:]
        elif isinstance(node, whole) and node is not func_node:
            parts = [node]
        else:
            continue
        for part in parts:
            conditional.update(id(child) for child in ast.walk(part))
    return conditional


def _path(parents, qualname):
    path = []
    while qualname is not None:
        path.append(qualname)
        qualname = parents[qualname]
    return list(reversed(path))


# -- entry points -----------------------------------------------------------


def api_entry_points(index, app):
    from fastapi.routing import APIRoute, APIWebSocketRoute

    for route in app.routes:
        if not isinstance(route, (APIRoute, APIWebSocketRoute)):
            continue
        methods = ",".join(sorted(getattr(route, "methods", None) or {"WS"}))
        entry = f"{methods} {route.path}"
        dependency_calls = []
        stack = list(route.dependant.dependencies)
        while stack:
            dependant = stack.pop()
            dependency_calls.append(dependant.call)
            stack.extend(dependant.dependencies)
        roots = [index.func_for(call) for call in [route.endpoint, *dependency_calls] if call]
        guarded = any(
            func is not None and func.qualname in GUARD_DEPENDENCIES
            for func in roots
        )
        yield entry, [f for f in roots if f is not None], guarded


def celery_entry_points(index, celery_app):
    celery_app.loader.import_default_modules()
    for name, task in sorted(celery_app.tasks.items()):
        if name.startswith("celery."):
            continue
        func = index.func_for(task.run)
        if func is not None:
            yield f"task {name}", [func], False


def mcp_entry_points(index):
    service = index.classes["app.interfaces.mcp.market_copilot.MarketCopilotService"]
    for node in ast.walk(service.node):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "ToolSpec"):
            continue
        keywords = {kw.arg: kw.value for kw in node.keywords}
        handler = keywords.get("handler")
        if isinstance(handler, ast.Attribute) and handler.attr in service.methods:
            yield f"mcp {keywords['name'].value}", [service.methods[handler.attr]], False


def unrouted_legacy_reads(app, celery_app):
    """Every entry point -> its unrouted legacy reads (empty when clean)."""
    from app.database import Base

    legacy = [m.class_ for m in Base.registry.mappers if m.class_.__name__ in LEGACY_MODELS]
    assert {cls.__name__ for cls in legacy} == LEGACY_MODELS, "a legacy model was renamed or removed"
    index = Index(
        {f"{cls.__module__}.{cls.__qualname__}" for cls in legacy},
        {cls.__tablename__ for cls in legacy},
    )
    stale = sorted(m for m in ROUTING_MARKERS | GUARD_DEPENDENCIES if index.resolve(m) is None)
    assert not stale, f"routing markers no longer exist; update ROUTING_MARKERS: {stale}"
    results: dict[str, list[Finding]] = {}
    for entry, roots, guarded in [
        *api_entry_points(index, app),
        *celery_entry_points(index, celery_app),
        *mcp_entry_points(index),
    ]:
        results[entry] = [] if guarded else index.legacy_reads(entry, roots)
    return results
