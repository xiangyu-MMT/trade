"""Provenance-required supplemental observations; never fabricate a missing series."""
from datetime import date, datetime
from urllib.parse import urlsplit

from .util import AppError, number, require_text

SERIES = {"US_DEFAULT_RATE", "SP500_EPS", "SP500_NET_MARGIN"}


def public_source(value):
    value = require_text(value, "资料来源URL", 2000)
    url = urlsplit(value)
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise AppError("validation_error", "补充资料需有无凭据的HTTPS来源链接")
    return value


def day(value):
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise AppError("validation_error", "观测/发布日期需为YYYY-MM-DD")


def validate_observations(rows):
    if not isinstance(rows, list) or len(rows) > 3000:
        raise AppError("validation_error", "us.observations需为不超过3000条的列表")
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or row.get("symbol") not in SERIES or row.get("value_type") not in ("actual", "estimate", "mixed"):
            raise AppError("validation_error", "补充指标需标明指标代码和actual/estimate/mixed")
        item = dict(row)
        for key in ("unit", "definition", "sample", "region", "period", "revision_note"):
            item[key] = require_text(row.get(key), key, 1500)
        item["source"] = public_source(row.get("source"))
        if item["region"].strip().lower() not in ("美国", "us", "usa", "united states"):
            raise AppError("validation_error", "该入口仅接受美国范围；全球违约率不能代替美国")
        if item["symbol"].startswith("SP500") and not any(x in item["sample"].lower() for x in ("标普500", "s&p500", "s&p 500")):
            raise AppError("validation_error", "盈利观察需明确标普500统计样本")
        item["date"], item["published_at"] = day(row.get("date")), day(row.get("published_at"))
        item["value"] = number(row.get("value"))
        if item["value"] is None or type(row.get("value")) is bool:
            raise AppError("validation_error", "补充指标数值必须有限且有效")
        if item["published_at"] > date.today().isoformat() or (item["value_type"] == "actual" and item["date"] > item["published_at"]):
            raise AppError("validation_error", "补充资料实际观测/发布日期存在未来值")
        key = (item["symbol"], item["date"], item["published_at"], item["sample"], item["value_type"])
        if key in seen:
            raise AppError("validation_error", "补充资料同一发布版本重复")
        seen.add(key)
        result.append(item)
    return result


def validate_breadth(rows):
    if not isinstance(rows, list) or len(rows) > 3000:
        raise AppError("validation_error", "us.breadth_history需为不超过3000条的历史列表")
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise AppError("validation_error", "广度历史条目需为对象")
        item = dict(row, date=day(row.get("date")), source=public_source(row.get("source")))
        for field in ("scope_id", "definition"):
            item[field] = require_text(row.get(field), field, 1500)
        if row.get("exchanges") != ["NYSE", "NASDAQ"]:
            raise AppError("validation_error", "广度历史需明确NYSE与NASDAQ范围")
        for field in ("advancing", "declining", "unchanged", "unknown_prices"):
            if type(row.get(field)) is not int or row[field] < 0:
                raise AppError("validation_error", "广度家数需为非负整数，未知不能填零冒充完整")
        if type(row.get("complete")) is not bool:
            raise AppError("validation_error", "广度历史需声明complete")
        if item["date"] > date.today().isoformat() or (item["scope_id"], item["date"]) in seen:
            raise AppError("validation_error", "广度历史存在未来日期或重复")
        seen.add((item["scope_id"], item["date"]))
        result.append(item)
    return result
