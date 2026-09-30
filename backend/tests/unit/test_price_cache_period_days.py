import pytest

from app.services.price_cache_service import _period_days


# "6mo" deliberately falls back to 2y: the incremental refresh trims the merged
# frame to this window and writes it back to the shared Redis key, so a 180-day
# window from the chart warmup would truncate history scans depend on.
@pytest.mark.parametrize(
    ("period", "days"),
    [("5y", 1825), ("2y", 730), ("1y", 365), ("max", 3650), ("6mo", 730), ("unknown", 730)],
)
def test_period_days_maps_known_periods_and_defaults_to_two_years(period, days):
    assert _period_days(period) == days
