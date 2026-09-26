"""US-specific descriptive calculations; no borrowed A-share strategy thresholds."""
from datetime import date
from statistics import mean

from .indicators import sma, obv
from .us_time import session_info, previous_day, forming, week_forming
from .util import number, now
from .volume_price import change, ratio

FORMULA = "us-descriptive-1"


def technical(history, parameters, future=False):
    history = history or {}
    bars, rejected = {}, 0
    for raw in history.get("bars", []):
        try:
            day = date.fromisoformat(raw["date"]).isoformat()
            vals = {k: number(raw.get(k)) for k in ("open", "high", "low", "close", "volume", "amount")}
            if any(vals[k] is None or vals[k] <= 0 for k in ("open", "high", "low", "close")) or vals["high"] < max(vals["open"], vals["close"]) or vals["low"] > min(vals["open"], vals["close"]):
                raise ValueError()
            if vals["volume"] is not None and vals["volume"] < 0:
                vals["volume"] = None
            bars[day] = dict(vals, date=day)
        except (KeyError, TypeError, ValueError):
            rejected += 1
    bars = [bars[d] for d in sorted(bars)]
    if not bars:
        return {"status": "missing", "bars": [], "weekly": [], "latest": {}, "trend_facts": [], "reasons": ["没有有效真实OHLC"], "parameters": parameters}
    closes, volumes = [x["close"] for x in bars], [x["volume"] for x in bars]
    ma = {str(n): sma(closes, n) for n in parameters["ma_periods"]}
    ov = obv(closes, volumes) if all(v is not None for v in volumes) else [None] * len(bars)
    weeks = {}
    for b in bars:
        key = date.fromisoformat(b["date"]).isocalendar()[:2]
        if key not in weeks:
            weeks[key] = dict(b, start_date=b["date"])
        else:
            w = weeks[key]
            w.update(high=max(w["high"], b["high"]), low=min(w["low"], b["low"]), close=b["close"], date=b["date"])
            for k in ("volume", "amount"):
                w[k] = w[k] + b[k] if w[k] is not None and b[k] is not None else None
    weekly = list(weeks.values())
    for w in weekly:
        w["forming"] = week_forming(w["date"])
    reasons = []
    info = session_info(bars[-1]["date"])
    if not info["calendar_verified"]:
        reasons.append("美国年度日历未核实")
    elif bars[-1]["date"] < info["expected_latest_date"]:
        reasons.append("源行情日期落后于最近美国交易日")
    if rejected:
        reasons.append("%s条无效OHLC未参与" % rejected)
    if history.get("cache_stale"):
        reasons.append("使用源失败后的历史缓存")
    flags = []
    for n, values in ma.items():
        if values[-1] is not None:
            flags.append("收盘%sMA%s" % ("高于" if closes[-1] > values[-1] else "低于" if closes[-1] < values[-1] else "等于", n))
            if len(values) > 1 and values[-2] is not None:
                flags.append("MA%s%s" % (n, "上行" if values[-1] > values[-2] else "下行" if values[-1] < values[-2] else "走平"))
    if future:
        reasons.append(history.get("definition", "期货连续序列换月影响未消除"))
    return {"bars": bars, "weekly": weekly, "ma": ma, "obv": ov, "latest": {"close": closes[-1], "ma": {k: v[-1] for k, v in ma.items()}, "obv": ov[-1]},
            "status": "partial" if reasons else "ok", "reasons": reasons, "asof": bars[-1]["date"], "forming": forming(bars[-1]["date"]) if not future else bars[-1]["date"] >= info["today"],
            "source": history.get("source"), "source_asof": history.get("source_asof"), "fetched_at": history.get("fetched_at"),
            "currency": history.get("currency"), "volume_unit": history.get("volume_unit"), "adjustment": history.get("adjustment"),
            "formula_version": FORMULA, "parameters": parameters, "trend_facts": flags, "calendar": info}


def volume_price(tech, parameters):
    bars = tech.get("bars", [])
    if tech.get("forming"):
        bars = bars[:-1]
    result = {"asof": bars[-1]["date"] if bars else None, "current_forming": bool(tech.get("forming")), "eligible": False,
              "source": tech.get("source"), "unit": tech.get("volume_unit"), "missing": [], "observations": [], "period": "美国最近完整交易日日线"}
    if len(bars) < 2:
        result["summary"] = "完整美国日线不足"
        return result
    last, previous = bars[-1], bars[-2]
    adjacent = previous_day(last["date"]) == previous["date"]
    result["price_change_pct"] = change(last["close"], previous["close"]) if adjacent else None
    result["volume_vs_previous"] = ratio(last.get("volume"), previous.get("volume")) if adjacent else None
    for n in sorted(set(parameters["volume_periods"]) | {5, 20}):
        window = bars[-n-1:-1]
        consecutive = len(window) == n and all(a["date"] == previous_day(b["date"]) for a, b in zip(window, window[1:] + [last]))
        volumes = [x.get("volume") for x in window]
        avg = mean(volumes) if consecutive and all(v is not None and v >= 0 for v in volumes) else None
        result["volume_vs_" + str(n)] = ratio(last.get("volume"), avg)
        result["return_%sd_pct" % n] = change(last["close"], window[0]["close"]) if consecutive else None
        if not consecutive:
            result["missing"].append("前%s个美国交易日历史不连续或不足" % n)
    high = max(x["high"] for x in bars[-20:])
    result["drawdown_20d_pct"] = change(last["close"], high)
    result["ma_support_count"] = sum(last["close"] > mean(x["close"] for x in bars[-n:]) for n in parameters["ma_periods"] if len(bars) >= n)
    ovs = obv([x["close"] for x in bars], [x.get("volume") for x in bars]) if all(x.get("volume") is not None for x in bars) else []
    n = parameters["obv_lookback"]
    delta = ovs[-1] - ovs[-n-1] if len(ovs) > n and ovs[-1] is not None and ovs[-n-1] is not None else None
    result["obv_change"] = delta
    result["obv_lookback"] = n
    result["eligible"] = result.get("return_20d_pct") is not None and result.get("volume_vs_5") is not None and bool(last.get("volume")) and bool(tech.get("calendar", {}).get("calendar_verified"))
    text = "最近完整日涨跌%.2f%%" % result["price_change_pct"] if result["price_change_pct"] is not None else "完整日价格比较不足"
    if result["volume_vs_5"] is not None:
        text += "；量为前5日均量%.2f倍" % result["volume_vs_5"]
    if delta is not None:
        text += "；OBV%s日净%s" % (n, "升" if delta > 0 else "降" if delta < 0 else "平")
    result["summary"] = text
    return result


def compute(snapshot, breadth_history=None):
    parameters = snapshot["config_snapshot"]["us"]["technical"]
    histories = snapshot.get("histories", {})
    evidence, candidates, watches = {}, [], []
    for item in snapshot["candidates"] + snapshot.get("watch_instruments", []):
        aid = item["asset_id"]
        tech = technical(histories.get(aid), parameters, item.get("kind") == "future")
        vtech = tech
        if item.get("volume_symbol"):
            vtech = technical(histories.get("volume:" + item["volume_symbol"]), parameters)
            tech["volume_proxy"] = {"symbol": item["volume_symbol"], "bars": vtech.get("bars", []), "weekly": vtech.get("weekly", []), "source": vtech.get("source")}
        v = volume_price(vtech, parameters)
        if item.get("volume_symbol"):
            v["proxy_symbol"] = item["volume_symbol"]
            v["summary"] = item["volume_symbol"] + "美国ETF量价代理：" + v["summary"]
            v["missing"].append("指数量价代理只作辅助；OBV以代理自己的价格和成交量计算")
            v["eligible"] = v["eligible"] and tech.get("asof") == vtech.get("asof") and tech["status"] != "missing"
        bars = tech.get("bars", [])
        quote = {"close": bars[-1]["close"], "asof": tech.get("asof"), "change_pct": change(bars[-1]["close"], bars[-2]["close"]) if len(bars) > 1 else None} if bars else None
        row = {**item, "technical": tech, "volume_price": v, "quote": quote, "evidence_id": "technical:" + aid, "excluded": False}
        complete_bars = bars[:-1] if tech.get("forming") else bars
        row["price_structure"] = {"asof": complete_bars[-1]["date"] if complete_bars else None,
                                  "return_20d_pct": change(complete_bars[-1]["close"], complete_bars[-21]["close"]) if len(complete_bars) > 20 else None,
                                  "definition": "分析对象自身价格，不用ETF代理替代指数回报"}
        evidence[row["evidence_id"]] = {"name": item["name"], "asof": tech.get("asof"), "source": tech.get("source"), "identity": item.get("identity"), "identity_source": item.get("identity_source"), "volume_proxy": item.get("volume_symbol"), "status": tech["status"],
                                       "latest": tech.get("latest"), "trend_facts": tech.get("trend_facts", []), "limitations": tech.get("reasons", [])}
        (watches if item.get("kind") == "future" else candidates).append(row)
    breadth = snapshot.get("breadth") or {"rows": [], "scope_id": "missing", "definition": "NYSE＋NASDAQ广度未取得"}
    accumulated = {}
    for x in (breadth_history or []) + snapshot["config_snapshot"]["us"].get("breadth_history", []) + breadth.get("rows", []):
        if x.get("scope_id") == breadth.get("scope_id"):
            accumulated[x["date"]] = x
    breadth = dict(breadth, rows=[accumulated[d] for d in sorted(accumulated)][-180:])
    market = {**breadth, "counts_complete": bool(breadth.get("complete")), "amount": None, "advance_ratio": ratio(breadth.get("advancing"), breadth.get("eligible_count"))}
    evidence["market:breadth"] = {k: v for k, v in breadth.items() if k != "rows"}
    paired = {}
    from .indicators import calculate
    from .volume_price import volume_price as cn_volume_price
    for ident, data in snapshot.get("paired_etfs", {}).items():
        tech = calculate(data["history"], snapshot["config_snapshot"]["indicators"])
        row = {k: v for k, v in data.items() if k != "history"}
        row.update(technical=tech, volume_price=cn_volume_price(tech))
        paired[ident] = row
        evidence["premium:" + ident] = {"name": row["name"], "pairing_ref": row["pairing_ref"], **row["premium"]}
        for candidate in candidates:
            if candidate["asset_id"] == ident:
                candidate["execution_asset"] = {"asset_id": row["asset_id"], "name": row["name"], "execution_market": "CN", "pairing_ref": row["pairing_ref"]}
    macro = snapshot.get("macro", [])
    for x in macro:
        evidence["macro:" + x["symbol"]] = {**x, "rows": x.get("rows", [])[-24:]}
    asof = snapshot.get("asof")
    calendar = session_info(asof)
    evidence["market:calendar"] = calendar
    evidence["data:coverage"] = {"coverage": snapshot.get("coverage", []), "asof": asof}
    return {"schema_version": 1, "analysis_market": "US", "snapshot_id": snapshot["id"], "created_at": now(), "asof": asof,
            "formula_version": FORMULA, "parameters": parameters, "calendar": calendar, "candidates": candidates, "watch_indices": watches,
            "market": market, "breadth": breadth, "industries": [x for x in candidates if x["kind"] == "industry"], "industry_ranking": {},
            "macro": macro, "paired_etfs": paired, "pairings": snapshot.get("pairings", {}), "evidence": evidence, "coverage": snapshot.get("coverage", []),
            "limitations": [x["detail"] for x in snapshot.get("coverage", []) if x["status"] != "ok"]}
