"""Same-instrument, completed-session volume/price facts; never trade signals."""
from datetime import datetime, timedelta
from statistics import mean

from .market_time import is_session_day
from .indicators import MA_PERIODS
from .util import CN, number


def ratio(a, b):
    return a / b if a is not None and b is not None and b > 0 else None


def change(a, b):
    value = ratio(a, b)
    return (value - 1) * 100 if value is not None else None


def previous_day(day):
    day = datetime.strptime(day[:10], "%Y-%m-%d").date() - timedelta(days=1)
    while not is_session_day(day):
        day -= timedelta(days=1)
    return day.isoformat()


def completed_asof(asof):
    try:
        stamp = datetime.fromisoformat(asof)
        if len(asof) <= 10:
            return stamp.date() < datetime.now(CN).date()
        return (stamp.hour, stamp.minute) >= (15, 0)
    except (TypeError, ValueError):
        return False


def volume_price(technical):
    all_bars = technical.get("bars", [])
    bars = all_bars[:-1] if technical.get("forming") else all_bars
    result = {"asof": bars[-1]["date"] if bars else None, "current_forming": bool(technical.get("forming")),
              "unit": technical.get("volume_unit"), "source": technical.get("source"), "eligible": False,
              "period": "最近完整交易日日线", "observations": [], "missing": []}
    if len(bars) < 2:
        result["missing"].append("完整日线不足两日，不能比较量价")
        return result
    last, prev = bars[-1], bars[-2]
    contiguous = prev["date"] == previous_day(last["date"])
    result.update(price_change_pct=change(last["close"], prev["close"]) if contiguous else None,
                  volume=last.get("volume"), amount=last.get("amount"),
                  volume_vs_previous=ratio(last.get("volume"), prev.get("volume")) if contiguous else None)
    for n in (5, 20):
        window = bars[-n-1:-1]
        consecutive = len(window) == n and all(a["date"] == previous_day(b["date"]) for a, b in zip(window, window[1:] + [last]))
        valid = consecutive and all(number(x.get("volume")) is not None and x["volume"] >= 0 for x in window)
        average = mean(x["volume"] for x in window) if valid else None
        result["volume_mean_" + str(n)] = average
        result["volume_vs_" + str(n)] = ratio(last.get("volume"), average)
        result["return_" + str(n) + "d_pct"] = change(last["close"], window[0]["close"]) if consecutive else None
        if not consecutive:
            result["missing"].append("前%s个连续交易日历史不足或有缺口" % n)
    window = bars[-20:]
    high, low = max(b["high"] for b in window), min(b["low"] for b in window)
    result.update(drawdown_20d_pct=change(last["close"], high), position_20d=ratio(last["close"] - low, high - low))
    up, down = [], []
    for a, b in list(zip(bars[:-1], bars[1:]))[-20:]:
        if number(b.get("volume")) is None:
            continue
        if b["close"] > a["close"]:
            up.append(b["volume"])
        elif b["close"] < a["close"]:
            down.append(b["volume"])
    result["up_down_volume_ratio"] = ratio(mean(up) if up else None, mean(down) if down else None)
    result["ma_support_count"] = sum(last["close"] > mean(b["close"] for b in bars[-n:]) for n in MA_PERIODS if len(bars) >= n)
    result["eligible"] = result["volume_vs_5"] is not None and result["return_20d_pct"] is not None and last.get("volume", 0) > 0
    pc, vr = result["price_change_pct"], result["volume_vs_previous"]
    if pc is not None:
        direction = "上涨" if pc > 0 else "下跌" if pc < 0 else "收平"
        if vr is not None:
            result["observations"].append("%s%.2f%%；成交量为前日%.2f倍" % (direction, abs(pc), vr))
        else:
            result["observations"].append("%s%.2f%%；量能比较缺失" % (direction, abs(pc)))
    if result["volume_vs_5"] is not None:
        result["observations"].append("成交量为前5日均量%.2f倍" % result["volume_vs_5"])
    if technical.get("forming"):
        result["missing"].append("当日日线形成中；以上量价比较止于最近完整日，不将盘中量与完整日相除")
    result["summary"] = "；".join(result["observations"][:2]) or "量价比较资料不足"
    return result


def turnover_summary(rows):
    rows = sorted((x for x in rows if number(x.get("amount")) is not None and x["amount"] > 0), key=lambda x: x["date"])
    result = {"rows": rows, "asof": rows[-1]["date"] if rows else None, "previous_ratio": None, "mean5_ratio": None, "mean20_ratio": None,
              "summary": "尚无可比成交额历史"}
    if not rows:
        return result
    last = rows[-1]
    if len(rows) > 1 and rows[-2]["date"] == previous_day(last["date"]):
        result["previous_ratio"] = ratio(last["amount"], rows[-2]["amount"])
    for n in (5, 20):
        w = rows[-n-1:-1]
        if len(w) == n and all(a["date"] == previous_day(b["date"]) for a, b in zip(w, w[1:] + [last])):
            result["mean%s_ratio" % n] = ratio(last["amount"], mean(x["amount"] for x in w))
    if result["previous_ratio"] is not None:
        result["summary"] = "最近完整日成交额较前一交易日%s%.1f%%" % ("增加" if result["previous_ratio"] >= 1 else "减少", abs(result["previous_ratio"] - 1) * 100)
    else:
        result["summary"] = "仅有%s个有效日，前一交易日对比不足" % len(rows)
    return result
