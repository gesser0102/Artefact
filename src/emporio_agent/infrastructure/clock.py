from datetime import date, datetime, timedelta, timezone

STORE_TIMEZONE = timezone(timedelta(hours=-4), "America/Campo_Grande")


class SystemClock:
    def today(self) -> date:
        return datetime.now(STORE_TIMEZONE).date()
