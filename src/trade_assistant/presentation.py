"""One selection contract shared by the live page and offline report."""
from .volume_price import volume_price


def eligible_ids(facts):
    return [x["asset_id"] for x in facts.get("candidates", []) if not x.get("excluded")
            and (x.get("volume_price") or {}).get("eligible")
            and (x.get("technical") or {}).get("asof") == facts.get("asof")]


def reference_key(item):
    v = item.get("volume_price") or {}
    # Continuous signed participation, then price structure: units cancel inside
    # each instrument. These are comparison keys, not scores or probabilities.
    pc = v.get("price_change_pct") or 0
    participation = pc * min(v.get("volume_vs_5") or 0, 3)
    return (-(v.get("up_down_volume_ratio") or 0), -participation,
            -v.get("ma_support_count", 0), -(v.get("return_20d_pct") or 0),
            -(v.get("drawdown_20d_pct") or 0), item["asset_id"])


def select(facts, analysis=None):
    candidates = facts.get("candidates", [])
    for item in candidates:
        if "volume_price" not in item:
            item["volume_price"] = volume_price(item.get("technical") or {})
    allowed = set(eligible_ids(facts))
    proposed = ((analysis or {}).get("result") or {}).get("ranked_asset_ids")
    is_ai = isinstance(proposed, list) and len(proposed) == len(set(proposed)) and set(proposed) == allowed
    ordered = proposed if is_ai else [x["asset_id"] for x in sorted((x for x in candidates if x["asset_id"] in allowed), key=reference_key)]
    dynamic_ids = {x["asset_id"] for x in candidates if "同花顺行业成交额前10" in x.get("reasons", [])}
    industry_top = [x for x in ordered if x in dynamic_ids][:3]
    picked, groups = set(), []
    for title, predicate in (
        ("宽基与指数", lambda x: x.get("kind") == "index"),
        ("固定关注行业", lambda x: "固定关注行业" in x.get("reasons", [])),
        ("成交额前十 · 综合前三" if is_ai else "成交额前十 · 量价参考前三", lambda x: x["asset_id"] in industry_top),
        ("配置个股", lambda x: x.get("kind") == "stock")):
        items = [x["asset_id"] for x in candidates if predicate(x) and x["asset_id"] not in picked]
        if "前三" in title:
            items.sort(key=lambda aid: industry_top.index(aid))
        picked.update(items)
        groups.append({"title": title, "asset_ids": items})
    return {"overall_top3": ordered[:3], "industry_top3": industry_top, "ordered_ids": ordered,
            "groups": groups, "source": "ai_comprehensive" if is_ai else "program_volume_price",
            "label": "逻辑、模式与量价综合排序" if is_ai else "量价参考排序 · 缺AI综合判断",
            "eligible_count": len(allowed), "analyzed_count": len(candidates), "dynamic_analyzed": len(dynamic_ids),
            "rank_missing": [x["asset_id"] for x in candidates if x["asset_id"] not in allowed],
            "reference_method": "仅程序参考：涨跌日均量比、单日涨幅×前5日量比(最多3)、均线支撑数、20日涨幅与回撤依序比较；非胜率"}
