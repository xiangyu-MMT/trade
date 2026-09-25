import statistics

from .indicators import FORMULA_VERSION, calculate
from .providers.eastmoney import eligible
from .util import AppError, now


def compute(snapshot, config=None):
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
        raise AppError("validation_error", "快照版本或结构无效")
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
        evidence[evidence_id] = {"asset_id": aid, "name": item["name"], "latest": tech.get("latest"),
                                 "trend_facts": tech.get("trend_facts", []), "asof": tech.get("asof"),
                                 "source": tech.get("source"), "status": tech["status"],
                                 "limitations": tech.get("reasons", [])}
        (candidate_facts if aid in candidate_ids else watches).append(row)

    market = snapshot.get("market") or {}
    eligible_rows = [x for x in market.get("stocks", []) if eligible(x)]
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
    amount_missing = sum(x.get("amount") is None for x in eligible_rows)
    volume_missing = sum(x.get("volume") is None for x in eligible_rows)
    mf = {"eligible_count": len(eligible_rows), "directory_count": market.get("received", 0),
          "directory_reported": market.get("total_reported"), "directory_complete": bool(market.get("complete")),
          "advancing": ups, "declining": downs, "unchanged": flats, "unknown_prices": unknown,
          "counts_complete": complete, "asof": market.get("asof"),
          "advance_ratio": ups / len(eligible_rows) if complete and eligible_rows else None,
          "amount": sum(x.get("amount") or 0 for x in eligible_rows),
          "amount_complete": bool(market.get("complete")) and not amount_missing,
          "volume": sum(x.get("volume") or 0 for x in eligible_rows),
          "volume_complete": bool(market.get("complete")) and not volume_missing,
          "median_change_pct": statistics.median(changes) if changes and complete else None,
          "excluded_count": len(market.get("stocks", [])) - len(eligible_rows),
          "undated_prices": sum(not x.get("asof") for x in eligible_rows),
          "definition": "来源A股目录中沪深非ST证券；北交所/B股及名称含ST证券剔除，缺报价单列"}
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
        rows = margin["rows"]
        margin_fact = {"latest": rows[0], "previous": rows[1] if len(rows) > 1 else None,
                       "change": rows[0]["financing_balance"] - rows[1]["financing_balance"] if len(rows) > 1 and rows[0]["date"] != rows[1]["date"] else None,
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
    return {"schema_version": 1, "snapshot_id": snapshot["id"], "created_at": now(),
            "asof": snapshot.get("asof"), "formula_version": FORMULA_VERSION,
            "candidates": candidate_facts, "watch_indices": watches,
            "market": mf, "industries": snapshot.get("industries", []),
            "industry_ranking": snapshot.get("industry_ranking"), "margin": margin_fact,
            "etf_shares": etfs, "macro": macro, "evidence": evidence,
            "coverage": snapshot.get("coverage", []), "gaps": snapshot.get("gaps", []),
            "limitations": [x["detail"] for x in snapshot.get("coverage", []) if x["status"] not in ("ok",)]}
