"""Range filters through the shared SQL compiler: NULL handling and cost.

``_range_predicate`` no longer wraps each bound in an explicit
``IS NOT NULL``. That is only safe because compiled predicates combine through
AND/OR alone and land in a WHERE clause, where an UNKNOWN comparison rejects
the row just as FALSE does. These tests pin that on a real database: rows whose
field is missing, explicitly null, or whose whole JSON column is NULL must be
excluded from every range filter, including inside ANY groups where the other
branch decides the outcome.
"""

from __future__ import annotations

import pytest
from sqlalchemy import JSON, Column, Float, Integer, Text, create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, declarative_base

from app.domain.common.query import RangeFilter
from app.domain.scanning.filter_expression_model import (
    FilterExpression,
    FilterGroup,
    MatchOperator,
)
from app.infra.query.sql_filter_compiler import (
    SqlFilterFieldResolver,
    column_bindings,
    compile_sql_expression,
    json_bindings,
)

_Base = declarative_base()


class _Row(_Base):
    __tablename__ = "range_filter_rows"

    id = Column(Integer, primary_key=True)
    symbol = Column(Text, nullable=False)
    composite_score = Column(Float, nullable=True)
    details = Column(JSON, nullable=True)


_RESOLVER = SqlFilterFieldResolver(
    source_name="range-filter-test",
    bindings=column_bindings({"composite_score": _Row.composite_score})
    | json_bindings({"rs_rating": ("rs_rating",), "se_setup_score": ("setup_engine", "setup_score")}),
    json_column=_Row.details,
    symbol_column=_Row.symbol,
    company_name_column=_Row.symbol,
)

# symbol -> (composite_score, details)
_ROWS = {
    "HIGH": (90.0, {"rs_rating": 95, "setup_engine": {"setup_score": 80.0}}),
    "MID": (60.0, {"rs_rating": 70, "setup_engine": {"setup_score": 40.0}}),
    "LOW": (20.0, {"rs_rating": 10, "setup_engine": {"setup_score": 5.0}}),
    "MISSING_KEY": (85.0, {"setup_engine": {}}),
    "JSON_NULL": (None, {"rs_rating": None, "setup_engine": None}),
    "NULL_DETAILS": (75.0, None),
}


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    _Base.metadata.create_all(engine)
    with Session(engine) as db:
        for index, (symbol, (score, details)) in enumerate(_ROWS.items(), start=1):
            db.add(_Row(id=index, symbol=symbol, composite_score=score, details=details))
        db.commit()
        yield db


def _matching(session: Session, expression: FilterExpression) -> set[str]:
    query = session.query(_Row.symbol)
    query = query.filter(compile_sql_expression(query, expression, _RESOLVER))
    return {row[0] for row in query.all()}


def _required(*conditions: RangeFilter) -> FilterExpression:
    return FilterExpression(required_conditions=conditions)


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        (RangeFilter("rs_rating", min_value=50), {"HIGH", "MID"}),
        (RangeFilter("rs_rating", max_value=50), {"LOW"}),
        (RangeFilter("rs_rating", min_value=50, max_value=80), {"MID"}),
        (RangeFilter("se_setup_score", min_value=0), {"HIGH", "MID", "LOW"}),
        (RangeFilter("se_setup_score", max_value=50), {"MID", "LOW"}),
        (RangeFilter("composite_score", min_value=50), {"HIGH", "MID", "MISSING_KEY", "NULL_DETAILS"}),
        (RangeFilter("composite_score", max_value=100), {"HIGH", "MID", "LOW", "MISSING_KEY", "NULL_DETAILS"}),
    ],
)
def test_range_excludes_null_values(session, condition, expected) -> None:
    """Missing, JSON-null and NULL-column values never satisfy a bound."""
    assert _matching(session, _required(condition)) == expected


def test_any_group_with_null_branch_matches_only_the_other_branch(session) -> None:
    """NULL OR FALSE stays excluded; NULL OR TRUE is included -- as before."""
    expression = FilterExpression(
        groups=(
            FilterGroup(
                id="g1",
                name="either",
                match=MatchOperator.ANY,
                conditions=(
                    RangeFilter("rs_rating", min_value=90),
                    RangeFilter("composite_score", min_value=80),
                ),
            ),
        ),
    )
    # HIGH via rs_rating; MISSING_KEY via composite_score despite a null
    # rs_rating; JSON_NULL has neither and must stay out.
    assert _matching(session, expression) == {"HIGH", "MISSING_KEY"}


def test_any_join_across_groups_with_null_fields(session) -> None:
    expression = FilterExpression(
        group_join=MatchOperator.ANY,
        groups=(
            FilterGroup(id="a", name="a", conditions=(RangeFilter("rs_rating", max_value=20),)),
            FilterGroup(id="b", name="b", conditions=(RangeFilter("se_setup_score", min_value=75),)),
        ),
    )
    assert _matching(session, expression) == {"LOW", "HIGH"}


@pytest.mark.parametrize(
    ("condition", "extractions"),
    [
        (RangeFilter("rs_rating", min_value=50), 1),
        (RangeFilter("rs_rating", max_value=50), 1),
        (RangeFilter("rs_rating", min_value=10, max_value=50), 2),
    ],
)
def test_each_bound_extracts_the_json_key_once(session, condition, extractions) -> None:
    """PostgreSQL re-parses the JSON per extraction, so the count is the cost."""
    query = session.query(_Row.symbol)
    predicate = compile_sql_expression(query, _required(condition), _RESOLVER)
    sql = str(predicate.compile(dialect=postgresql.dialect()))
    assert sql.count("->>") == extractions
    assert "IS NOT NULL" not in sql
