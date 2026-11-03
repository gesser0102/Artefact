from datetime import UTC, datetime, timedelta

import pytest

from emporio_agent.infrastructure import clock as clock_module
from emporio_agent.infrastructure.clock import SystemClock


@pytest.mark.parametrize(
    ("utc_moment", "store_day"),
    [
        (datetime(2026, 3, 2, 3, 59, tzinfo=UTC), 1),
        (datetime(2026, 3, 2, 4, 0, tzinfo=UTC), 2),
    ],
)
def test_system_clock_uses_the_store_calendar_day(monkeypatch, utc_moment, store_day):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return utc_moment.astimezone(tz)

    monkeypatch.setattr(clock_module, "datetime", FrozenDatetime)

    assert SystemClock().today().day == store_day


def test_store_timezone_is_four_hours_behind_utc():
    assert clock_module.STORE_TIMEZONE.utcoffset(None) == timedelta(hours=-4)
