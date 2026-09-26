"""Market identity is separate from the place where a user executes a trade."""
import re

from .util import AppError

MARKETS = {"CN", "US"}
US_EQUITY = re.compile(r"^us-equity:[A-Z][A-Z0-9.-]{0,19}$")


def market(value="CN"):
    if not isinstance(value, str) or value not in MARKETS:
        raise AppError("invalid_market", "分析市场仅支持 CN（A股）或 US（美股）")
    return value


def scope(payload):
    values = payload.get("market_scope", ["CN"])
    if not isinstance(values, list) or not values or any(not isinstance(x, str) for x in values) or len(values) != len(set(values)):
        raise AppError("invalid_market_scope", "档案适用市场需要非空、无重复列表")
    return [market(x) for x in values]


def belongs(payload, selected):
    return selected in scope(payload) if "market_scope" in payload else market(payload.get("analysis_market", "CN")) == selected


def run_market(run):
    return market((run.get("metadata") or {}).get("analysis_market", (run.get("facts") or {}).get("analysis_market", "CN")))


def asset_market(ident):
    us_ids = {"us:DJI", "us:NDX", "us:SPX", "us:GC"} | {"us-sector:" + x for x in ("financials", "healthcare", "staples", "discretionary", "semiconductors", "software", "industrials")}
    if isinstance(ident, str) and (ident in us_ids or US_EQUITY.fullmatch(ident)):
        return "US"
    if isinstance(ident, str) and re.fullmatch(r"(?:(?:sh|sz|csi)\d{6}|ths:\d{6})", ident):
        return "CN"
    raise AppError("invalid_asset", "无法识别标的市场，请使用明确的市场标识", {"asset_id": ident})
