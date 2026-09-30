import pytest

from app.services.price_cache_service import _period_days


@pytest.mark.parametrize(
    ("period", "days"),
    [("5y", 1825), ("2y", 730), ("1y", 365), ("max", 3650), ("6mo", 730)],
)
def test_period_days_maps_known_periods_and_defaults_to_two_years(period, days):
    assert _period_days(period) == days
