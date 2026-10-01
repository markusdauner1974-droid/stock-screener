"""No route may be unreachable behind an earlier route with the same method.

FastAPI matches routes in declaration order, and a ``{param}`` segment matches
any text before type validation, so ``PUT /reorder`` declared after
``PUT /{item_id}`` is routed to the update endpoint and answers 422.
"""

import re

from fastapi.routing import APIRoute
from starlette.routing import Match

from app.main import app


def _shadowed_routes() -> list[str]:
    routes = [route for route in app.router.routes if isinstance(route, APIRoute)]
    shadowed = []
    for index, later in enumerate(routes):
        concrete = re.sub(r"\{[^}]+\}", "__param__", later.path)
        for earlier in routes[:index]:
            methods = earlier.methods & later.methods
            if not methods or earlier.path == later.path:
                continue
            scope = {"type": "http", "path": concrete, "method": next(iter(methods))}
            if earlier.matches(scope)[0] == Match.FULL:
                shadowed.append(f"{sorted(methods)} {later.path} <- {earlier.path}")
                break
    return shadowed


def test_no_route_is_shadowed_by_an_earlier_route():
    assert _shadowed_routes() == []
