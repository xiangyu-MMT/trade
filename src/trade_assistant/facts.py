import statistics

from .indicators import FORMULA_VERSION, calculate
from .market_time import session_info
from .providers.eastmoney import eligible
from .util import AppError, now
from .volume_price import volume_price, turnover_summary, completed_asof, previous_day


def compute(snapshot, config=None, market_history=None):
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise AppError("validation_error", "快照版本或结构无效")
    from .markets import market
    if market(snapshot.get("analysis_market", "CN")) == "US":
        from .us_facts import compute as us_compute
        return us_compute(snapshot, market_history)
    config = config or snapshot["config_snapshot"]
    evidence, candidate_facts, watches = {}, [], []
    histories = snapshot.get("histories", {})
    quotes = snapshot.get("quotes", {})
    items = snapshot.get("candidates", []) + snapshot.get("watch_instruments", [])
    seen = set()
    candidate_ids = {x["asset_id"] for x in snapshot.get("candidates", [])}
    for item in items:
        aid = item["asset_id"]
        if aid in seen:
            continue
        seen.add(aid)
        tech = calculate(histories[aid], config["indicators"]) if aid in histories else {
            "status": "missing", "reasons": ["缺少该对象真实历史"], "bars": [], "weekly": [], "latest": {}, "trend_facts": []}
        quote = quotes.get(aid) or item.get("quote")
        evidence_id = "technical:" + aid
        row = {"asset_id": aid, "name": item["name"], "kind": item.get("kind", "index"),
               "reasons": item.get("reasons", []), "execution_asset": item.get("execution_asset"),
               "quote": quote, "technical": tech, "evidence_id": evidence_id,
               "excluded": item.get("excluded", False), "exclusion_reason": item.get("exclusion_reason")}
        row["volume_price"] = volume_price(tech)
        evidence[evidence_id] = {"asset_id": aid, "name": item["name"], "latest": tech.get("latest"),
                                 "trend_facts": tech.get("trend_facts", []), "asof": tech.get("asof"),
                                 "source": tech.get("source"), "status": tech["status"],
                                 "limitations": tech.get("reasons", [])}
        evidence[evidence_id]["volume_price"] = row["volume_price"]
        (candidate_facts if aid in candidate_ids else watches).append(row)

    market = snapshot.get("market") or {}
    eligible_rows = [x for x in market.get("stocks", []) if eligible(x)]
    amount_rows = [x for x in market.get("stocks", []) if str(x.get("asset_id", "")).startswith(("sh60", "sh68", "sz00", "sz30"))]
    ups = downs = flats = unknown = 0
    changes = []
    for stock in eligible_rows:
        price, prior = stock.get("close"), stock.get("previous_close")
        if price is None or prior is None or price <= 0 or prior <= 0:
            unknown += 1
            continue
        changes.append((price / prior - 1) * 100)
        if price > prior:
            ups += 1
        elif price < prior:
            downs += 1
        else:
            flats += 1
    complete = bool(market.get("complete")) and not unknown
    amount_missing = sum(x.get("amount") is None for x in amount_rows)
    volume_missing = sum(x.get("volume") is None for x in amount_rows)
    mf = {"eligible_count": len(eligible_rows), "directory_count": market.get("received", 0),
          "directory_reported": market.get("total_reported"), "directory_complete": bool(market.get("complete")),
          "advancing": ups, "declining": downs, "unchanged": flats, "unknown_prices": unknown,
          "counts_complete": complete, "asof": market.get("asof"),
          "advance_ratio": ups / len(eligible_rows) if complete and eligible_rows else None,
          "amount": sum(x.get("amount") or 0 for x in amount_rows),
          "amount_scope": "shsz_a", "amount_count": len(amount_rows), "amount_source": "沪深A股快照累计成交额",
          "amount_complete": bool(market.get("complete")) and not amount_missing,
          "volume": sum(x.get("volume") or 0 for x in amount_rows),
          "volume_complete": bool(market.get("complete")) and not volume_missing,
          "median_change_pct": statistics.median(changes) if changes and complete else None,
          "excluded_count": len(market.get("stocks", [])) - len(eligible_rows),
          "undated_prices": sum(not x.get("asof") for x in eligible_rows),
          "definition": "涨跌家数按沪深非ST统计，缺报价单列；成交额与成交量采用沪深A股全范围"}
    pools = snapshot.get("limit_pools") or {}
    for key in ("up", "down", "broken"):
        pool = pools.get(key)
        mf["limit_" + key] = len(pool["rows"]) if pool and pool.get("complete") else None
    up, broken = pools.get("up"), pools.get("broken")
    mf["seal_rate"] = None
    if up and broken and up.get("complete") and broken.get("complete") and up.get("asof") == broken.get("asof") == snapshot.get("asof"):
        up_codes, broken_codes = {x["code"] for x in up["rows"]}, {x["code"] for x in broken["rows"]}
        denominator = len(up_codes | broken_codes)
        mf["seal_rate"] = len(up_codes) / denominator if denominator else None
    mf["limit_definition"] = "提供方当前涨停池/炸板池口径，排除部分连续一字新股；封板率=当前涨停/两池并集，不是全交易所无排除统计"
    evidence["market:breadth"] = mf
    evidence["industry:ranking"] = snapshot.get("industry_ranking") or {}

    margin = snapshot.get("margin")
    margin_fact = None
    if margin and margin.get("rows"):
        rows = sorted({x["date"]: x for x in margin["rows"] if x.get("date")}.values(), key=lambda x: x["date"], reverse=True)
        adjacent = len(rows) > 1 and rows[1]["date"] == previous_day(rows[0]["date"])
        margin_fact = {"latest": rows[0], "previous": rows[1] if len(rows) > 1 else None,
                       "rows": list(reversed(rows)), "previous_session_matched": adjacent,
                       "change": rows[0]["financing_balance"] - rows[1]["financing_balance"] if adjacent else None,
                       "unit": "元", "asof": margin["asof"], "source": margin["source"], "definition": margin["definition"]}
        evidence["margin:balance"] = margin_fact
    etfs = []
    for obj in (snapshot.get("etf_shares") or {}).get("items", []):
        rows = obj.get("rows", [])
        change = None
        if len(rows) > 1 and rows[0]["date"] and rows[1]["date"] and rows[0]["date"] != rows[1]["date"]:
            change = rows[0]["shares"] - rows[1]["shares"]
        row = {**obj, "change": change, "evidence_id": "etf:" + obj["asset_id"]}
        etfs.append(row)
        evidence[row["evidence_id"]] = row
    macro = []
    for obj in snapshot.get("macro", []):
        rows = obj.get("rows", [])
        change = rows[-1]["value"] - rows[-2]["value"] if len(rows) > 1 and rows[-1]["time"] != rows[-2]["time"] else None
        row = {**obj, "change": change, "evidence_id": "macro:" + obj["symbol"]}
        macro.append(row)
        evidence[row["evidence_id"]] = {k: v for k, v in row.items() if k != "rows"}
    evidence["data:coverage"] = {"coverage": snapshot.get("coverage", []), "asof": snapshot.get("asof")}
    market_calendar = session_info(snapshot.get("asof"))
    evidence["market:calendar"] = market_calendar
    exact_rows = {x["date"]: x for x in (market_history or []) if x["date"] <= str(snapshot.get("asof", ""))[:10] and x.get("scope_id") == "shsz_a"}
    if mf["amount_complete"] and mf["counts_complete"] and not mf["undated_prices"] and completed_asof(mf["asof"]):
        exact_rows[str(mf["asof"])[:10]] = {"date": str(mf["asof"])[:10], "amount": mf["amount"], "source": "本地实际完整收盘快照"}
    exact_turnover = {**turnover_summary(list(exact_rows.values())), "scope": "沪深A股完整收盘快照", "scope_id": "shsz_a", "unit": "元"}
    exchange = snapshot.get("market_turnover") or {}
    exchange_turnover = {**exchange, **turnover_summary(exchange.get("rows", []))}
    same_day = next((x for x in exchange.get("rows", []) if x["date"] == snapshot.get("asof")), None)
    if same_day and completed_asof(mf["asof"]):
        mf.update(amount=same_day["amount"], amount_complete=True, amount_source="交易所公布沪深A股成交额")
    market_volume = {"series": exchange_turnover if exchange_turnover["rows"] else exact_turnover,
                     "current_asof": mf["asof"], "current_amount": mf["amount"], "current_complete": mf["amount_complete"],
                     "notes": ["全市场量能独立于候选集合", "盘中累计成交额不直接与完整日总量比较"]}
    evidence["market:volume"] = market_volume
    limit_history = snapshot.get("limit_history") or {"rows": [], "complete": False, "covered": 0}
    evidence["market:limits_history"] = limit_history
    basis = snapshot.get("basis") or {}
    for prefix in ("IF", "IM"):
        if prefix in basis:
            evidence["basis:" + prefix] = basis[prefix]
    return {"schema_version": 1, "analysis_market": "CN", "snapshot_id": snapshot["id"], "created_at": now(),
            "asof": snapshot.get("asof"), "formula_version": FORMULA_VERSION, "calendar": market_calendar,
            "candidates": candidate_facts, "watch_indices": watches,
            "market": mf, "industries": snapshot.get("industries", []),
            "market_volume": market_volume,
            "limit_history": limit_history, "basis": basis,
            "industry_ranking": snapshot.get("industry_ranking"), "margin": margin_fact,
            "etf_shares": etfs, "macro": macro, "evidence": evidence,
            "coverage": snapshot.get("coverage", []), "gaps": snapshot.get("gaps", []),
            "limitations": [x["detail"] for x in snapshot.get("coverage", []) if x["status"] not in ("ok",)]}
