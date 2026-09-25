"""Exchange calendar metadata. Unknown calendar years are explicit, not guessed."""
import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from .util import CN


@lru_cache(maxsize=1)
def calendar():
    return json.loads((Path(__file__).parent / "defaults" / "calendar.json").read_text(encoding="utf-8"))


def is_session_day(day):
    data = calendar()
    return day.weekday() < 5 and day.isoformat() not in data["closed_dates"]


def session_info(source_asof=None):
    clock = datetime.now(CN)
    today = clock.date()
    data = calendar()
    known = today.year in data["years"]
    trading_day = is_session_day(today)
    before_open = (clock.hour, clock.minute) < (9, 30)
    expected = today
    if not trading_day or before_open:
        expected -= timedelta(days=1)
    while not is_session_day(expected):
        expected -= timedelta(days=1)
    if not known:
        phase = "本年度交易日历未核实"
    elif not trading_day:
        phase = data["closed_dates"].get(today.isoformat(), "周末休市")
    elif before_open:
        phase = "盘前"
    elif clock.hour >= 15:
        phase = "已收盘"
    elif (clock.hour, clock.minute) >= (11, 30) and clock.hour < 13:
        phase = "午间休市"
    else:
        phase = "交易时段"
    source_date = str(source_asof or "")[:10]
    return {"today": today.isoformat(), "calendar_verified": known, "phase": phase,
            "is_session_day": trading_day if known else None,
            "expected_latest_date": expected.isoformat() if known else None,
            "source_date_matches_expected": source_date == expected.isoformat() if known and source_date else None,
            "source": data["source"], "valid_years": data["years"]}


def week_forming(last_bar_date):
    clock = datetime.now(CN)
    last = datetime.strptime(last_bar_date, "%Y-%m-%d").date()
    if last.isocalendar()[:2] != clock.date().isocalendar()[:2]:
        return False
    friday = last + timedelta(days=4 - last.weekday())
    last_session = friday
    while not is_session_day(last_session) and last_session.weekday() > 0:
        last_session -= timedelta(days=1)
    if clock.date() < last_session:
        return True
    if clock.date() == last_session:
        return clock.hour < 15 or last < last_session
    return last < last_session
