"""NYSE sessions, with a stdlib-only US/Eastern clock for Python 3.8."""
from datetime import date, datetime, timedelta, timezone

SOURCE = "https://www.nyse.com/trade/hours-calendars"
CLOSED = {
    2026: "01-01 01-19 02-16 04-03 05-25 06-19 07-03 09-07 11-26 12-25",
    2027: "01-01 01-18 02-15 03-26 05-31 06-18 07-05 09-06 11-25 12-24",
    2028: "01-17 02-21 04-14 05-29 06-19 07-04 09-04 11-23 12-25",
}
EARLY = {"2026-11-27", "2026-12-24", "2027-11-26", "2028-07-03", "2028-11-24"}


def eastern(stamp=None):
    stamp = stamp or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        raise ValueError("A timestamp with timezone is required")
    utc = stamp.astimezone(timezone.utc)
    year = utc.year
    # US law since 2007: second Sunday in March at 07 UTC, first in November at 06 UTC.
    march, november = date(year, 3, 1), date(year, 11, 1)
    start = datetime(year, 3, 1 + (6 - march.weekday()) % 7 + 7, 7, tzinfo=timezone.utc)
    end = datetime(year, 11, 1 + (6 - november.weekday()) % 7, 6, tzinfo=timezone.utc)
    hours = -4 if start <= utc < end else -5
    return utc.astimezone(timezone(timedelta(hours=hours), "EDT" if hours == -4 else "EST"))


def is_session(day):
    return day.weekday() < 5 and day.strftime("%m-%d") not in CLOSED.get(day.year, "").split()


def previous_day(value):
    day = date.fromisoformat(value[:10]) - timedelta(days=1)
    while not is_session(day):
        day -= timedelta(days=1)
    return day.isoformat()


def session_info(source_asof=None, stamp=None):
    clock = eastern(stamp)
    today = clock.date()
    known = today.year in CLOSED
    trading = is_session(today)
    hour = 13 if today.isoformat() in EARLY else 16
    before = (clock.hour, clock.minute) < (9, 30)
    expected = previous_day(today.isoformat()) if not trading or before else today.isoformat()
    complete = today.isoformat() if trading and clock.hour >= hour else previous_day(today.isoformat())
    return {"timezone": "America/New_York", "clock": clock.isoformat(), "today": today.isoformat(),
            "calendar_verified": known, "is_session_day": trading if known else None,
            "phase": ("本年度日历未核实" if not known else "休市" if not trading else "盘前" if before else "已收盘" if clock.hour >= hour else "交易时段"),
            "expected_latest_date": expected if known else None, "latest_completed_date": complete if known else None,
            "source_date_matches_expected": str(source_asof or "")[:10] == expected if known and source_asof else None,
            "close_hour": hour, "source": SOURCE, "valid_years": sorted(CLOSED)}


def forming(day, stamp=None):
    info = session_info(day, stamp)
    return not info["calendar_verified"] or day > info["latest_completed_date"]


def week_forming(day):
    last = date.fromisoformat(day)
    friday = last + timedelta(days=4 - last.weekday())
    while not is_session(friday):
        friday -= timedelta(days=1)
    return last < friday or forming(friday.isoformat())
