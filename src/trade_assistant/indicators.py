"""Deterministic indicators; no trading decisions or win-rate estimates."""
from collections import deque
from datetime import datetime

from .util import CN, number

FORMULA_VERSION = "p03-indicators-1"


def sma(values, period):
    window, result = deque(), []
    for value in values:
        window.append(value)
        if len(window) > period:
            window.popleft()
        result.append(sum(window) / period if len(window) == period and all(x is not None for x in window) else None)
    return result


def ema(values, period):
    seed, current, result = [], None, []
    alpha = 2.0 / (period + 1)
    for value in values:
        if value is None:
            seed, current = [], None
            result.append(None)
            continue
        if current is None:
            seed.append(value)
            if len(seed) == period:
                current = sum(seed) / period
        else:
            current = value * alpha + current * (1 - alpha)
        result.append(current)
    return result


def obv(closes, volumes):
    value, valid, result = 0.0, True, []
    for i, close in enumerate(closes):
        if i:
            if close is None or closes[i - 1] is None or volumes[i] is None:
                valid = False
            if valid:
                if close > closes[i - 1]:
                    value += volumes[i]
                elif close < closes[i - 1]:
                    value -= volumes[i]
        result.append(value if valid else None)
    return result


def cci(bars, period):
    tp = [(b["high"] + b["low"] + b["close"]) / 3 for b in bars]
    result = []
    for i, point in enumerate(tp):
        if i + 1 < period:
            result.append(None)
            continue
        window = tp[i - period + 1:i + 1]
        mean = sum(window) / period
        deviation = sum(abs(x - mean) for x in window) / period
        result.append((point - mean) / (0.015 * deviation) if deviation > 0 else None)
    return result


def weekly(bars):
    result, group = [], None
    today = datetime.now(CN)
    current_week = today.isocalendar()[:2]
    for bar in bars:
        day = datetime.strptime(bar["date"], "%Y-%m-%d")
        key = day.isocalendar()[:2]
        if not group or group["key"] != key:
            group = dict(bar, key=key, start_date=bar["date"])
            result.append(group)
        else:
            group["high"] = max(group["high"], bar["high"])
            group["low"] = min(group["low"], bar["low"])
            group["close"], group["date"] = bar["close"], bar["date"]
            for name in ("volume", "amount"):
                a, b = group.get(name), bar.get(name)
                group[name] = a + b if a is not None and b is not None else None
    for group in result:
        group["forming"] = group["key"] == current_week and (
            today.weekday() < 4 or (today.weekday() == 4 and (today.hour < 15 or group["date"] < today.strftime("%Y-%m-%d"))))
        group.pop("key")
    return result


def calculate(history, parameters):
    bars, rejected = [], 0
    for raw in history.get("bars", []):
        try:
            datetime.strptime(raw["date"], "%Y-%m-%d")
            values = {key: number(raw.get(key)) for key in ("open", "high", "low", "close", "volume", "amount")}
            if any(values[k] is None or values[k] <= 0 for k in ("open", "high", "low", "close")):
                raise ValueError()
            if values["high"] < max(values["open"], values["close"], values["low"]) or values["low"] > min(values["open"], values["close"]):
                raise ValueError()
            bars.append(dict(values, date=raw["date"]))
        except (ValueError, KeyError, TypeError):
            rejected += 1
    unique = {b["date"]: b for b in bars}
    bars = [unique[d] for d in sorted(unique)]
    if not bars:
        return {"status": "missing", "reason": "没有有效 OHLC 历史", "bars": [], "weekly": [], "latest": {}, "formula_version": FORMULA_VERSION}
    close = [x["close"] for x in bars]
    volume = [x["volume"] for x in bars]
    ma = {str(p): sma(close, p) for p in parameters["ma_periods"]}
    fast, slow = ema(close, parameters["macd_fast"]), ema(close, parameters["macd_slow"])
    dif = [a - b if a is not None and b is not None else None for a, b in zip(fast, slow)]
    dea = ema(dif, parameters["macd_signal"])
    histogram = [2 * (a - b) if a is not None and b is not None else None for a, b in zip(dif, dea)]
    obv_values, cci_values = obv(close, volume), cci(bars, parameters["cci_period"])
    latest = {"close": close[-1], "ma": {p: a[-1] for p, a in ma.items()},
              "dif": dif[-1], "dea": dea[-1], "macd_histogram": histogram[-1],
              "obv": obv_values[-1], "cci": cci_values[-1]}
    flags = []
    for period, values in ma.items():
        if values[-1] is not None:
            flags.append("日线收盘价%sMA%s" % ("高于" if close[-1] > values[-1] else "低于" if close[-1] < values[-1] else "等于", period))
            if len(values) > 1 and values[-2] is not None:
                flags.append("MA%s%s" % (period, "上行" if values[-1] > values[-2] else "下行" if values[-1] < values[-2] else "走平"))
    reasons = []
    if len(bars) < max(parameters["ma_periods"]):
        reasons.append("历史不足以计算全部均线")
    if cci_values[-1] is None:
        reasons.append("CCI 历史不足或典型价平均偏差为零")
    if histogram[-1] is None:
        reasons.append("MACD 未完成初始化所需历史")
    if obv_values[-1] is None:
        reasons.append("OBV 成交量历史存在缺口")
    if rejected:
        reasons.append("有 %s 条 OHLC 无效，未参与计算" % rejected)
    clock = datetime.now(CN)
    forming = bars[-1]["date"] == clock.strftime("%Y-%m-%d") and clock.weekday() < 5 and clock.hour < 15
    return {"status": "partial" if reasons else "ok", "reasons": reasons, "bars": bars,
            "weekly": weekly(bars), "ma": ma, "dif": dif, "dea": dea, "histogram": histogram,
            "obv": obv_values, "cci": cci_values, "latest": latest, "trend_facts": flags,
            "asof": bars[-1]["date"], "forming": forming, "formula_version": FORMULA_VERSION,
            "parameters": parameters, "adjustment": history.get("adjustment"),
            "volume_unit": history.get("volume_unit"), "source": history.get("source"),
            "definition": "MACD柱=2*(DIF-DEA)，EMA以首段SMA初始化；OBV首值0；CCI常数0.015"}
