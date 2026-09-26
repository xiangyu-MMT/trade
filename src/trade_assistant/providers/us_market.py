"""Public US observations with explicit source identities and coverage."""
import csv
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import quote

from ..util import AppError, number
from ..us_time import eastern, session_info, forming


def metadata(response):
    return {k: response.get(k) for k in ("source", "fetched_at", "cache_stale")}


class USMarket:
    def __init__(self, client):
        self.http = client

    def history(self, item, count=360):
        errors = []
        for host in (("query1", "query2") if item["symbol"] in ("^NDX", "GC=F") else ("query1",)):
            try:
                r = self.http.data("https://%s.finance.yahoo.com/v8/finance/chart/%s" % (host, quote(item["symbol"], safe="")),
                                   params={"range": "5y" if count > 500 else "2y", "interval": "1d"}, ttl=300, stale=True)
                rows = (r["data"].get("chart") or {}).get("result") or []
                if not rows:
                    raise AppError("source_format", "Yahoo行情序列为空")
                obj = rows[0]
                info = obj.get("meta") or {}
                if info.get("symbol") != item["symbol"]:
                    raise AppError("source_identity", "Yahoo返回标的身份不一致")
                q = (obj.get("indicators", {}).get("quote") or [{}])[0]
                bars = []
                for i, ts in enumerate(obj.get("timestamp") or []):
                    vals = {k: number((q.get(k) or [])[i]) if i < len(q.get(k) or []) else None for k in ("open", "high", "low", "close", "volume")}
                    if any(vals[k] is None or vals[k] <= 0 for k in ("open", "high", "low", "close")):
                        continue
                    day = eastern(datetime.fromtimestamp(ts, timezone.utc)).date().isoformat()
                    bars.append(dict(vals, date=day, amount=None))
                if not bars:
                    raise AppError("source_format", "没有有效美股OHLC")
                kind = item.get("kind")
                if kind == "index":
                    for bar in bars:
                        bar["volume"] = None
                return {"bars": bars[-count:], "asof": bars[-1]["date"], "source": r["source"], "sources": [metadata(r)],
                        "cache_stale": r["cache_stale"], "fetched_at": r["fetched_at"], "currency": info.get("currency"),
                        "timezone": info.get("exchangeTimezoneName", "America/New_York"), "provider_name": info.get("shortName"),
                        "identity": item.get("identity", item["symbol"]), "symbol": item["symbol"],
                        "volume_unit": "未采用含义不明的指数原始量" if kind == "index" else "期货合约（提供方单位）" if kind == "future" else "美国ETF成交股数",
                        "adjustment": "Yahoo原始OHLC（未以adjclose回调分红；拆股按提供方处理）",
                        "definition": "GC=F近月连续观察，合约切换由提供方维护；换月规则/价差调整未独立核实，非现货" if kind == "future" else "美国本地交易日期；不把ETF代理等同于全行业指数",
                        "source_asof": eastern(datetime.fromtimestamp(info["regularMarketTime"], timezone.utc)).isoformat() if info.get("regularMarketTime") else bars[-1]["date"]}
            except (AppError, ValueError, TypeError, KeyError) as exc:
                errors.append(str(exc))
        for fallback in (self.sina, self.stooq):
            try:
                return fallback(item, count)
            except AppError as exc:
                errors.append(str(exc))
        raise AppError("source_unavailable", "美股历史主源与后备均不可用", {"symbol": item["symbol"], "attempts": errors}, 503)

    def sina(self, item, count):
        symbol = {"^GSPC": ".inx", "^DJI": ".dji"}.get(item["symbol"], item["symbol"].lower())
        if item.get("kind") == "future" or any(c in symbol for c in "^=") or item["symbol"] == "DX-Y.NYB":
            raise AppError("source_identity", "该品种没有已核实的新浪等价映射")
        r = self.http.data("https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var%20_k=/US_MinKService.getDailyK", params={"symbol": symbol}, ttl=1800, stale=True)
        bars = []
        if isinstance(r["data"], list):
            for row in r["data"]:
                values = {k: number(row.get(v)) for k, v in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"), ("volume", "v"))}
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row.get("d", ""))) and all(values[k] is not None and values[k] > 0 for k in ("open", "high", "low", "close")):
                    if item.get("kind") == "index":
                        values["volume"] = None
                    bars.append(dict(values, date=row["d"], amount=None))
        if not bars:
            raise AppError("source_format", "新浪美股历史为空")
        bars.sort(key=lambda x: x["date"])
        return {"bars": bars[-count:], "asof": bars[-1]["date"], **metadata(r), "sources": [metadata(r)], "currency": "USD", "timezone": "America/New_York",
                "volume_unit": "美国ETF成交股数" if item.get("kind") != "index" else "无原生指数成交量", "adjustment": "新浪美国日线独立序列，复权按提供方；不与Yahoo拼接",
                "identity": item.get("identity", item["symbol"]), "symbol": item["symbol"]}

    def stooq(self, item, count):
        symbols = {"^DJI": "^dji", "^GSPC": "^spx"}
        symbol = symbols.get(item["symbol"], item["symbol"].lower() + ".us")
        if item.get("kind") == "future" or item["symbol"] in ("DX-Y.NYB", "^NDX"):
            raise AppError("source_unavailable", "该标的没有已核实的Stooq等价映射")
        r = self.http.get("https://stooq.com/q/d/l/", params={"s": symbol, "i": "d"}, ttl=1800, stale=True)
        bars = []
        for row in csv.DictReader(io.StringIO(r["text"])):
            vals = {k: number(row.get(k.title())) for k in ("open", "high", "low", "close", "volume")}
            if row.get("Date") and all(vals[k] is not None and vals[k] > 0 for k in ("open", "high", "low", "close")):
                if item.get("kind") == "index":
                    vals["volume"] = None
                bars.append(dict(vals, date=row["Date"], amount=None))
        if not bars:
            raise AppError("source_format", "Stooq未返回有效日线")
        return {"bars": bars[-count:], "asof": bars[-1]["date"], **metadata(r), "sources": [metadata(r)], "currency": "USD",
                "timezone": "America/New_York", "volume_unit": "提供方成交股数" if item.get("kind") != "index" else "无原生指数成交量",
                "adjustment": "Stooq独立序列，复权由提供方维护；不与Yahoo拼接", "symbol": item["symbol"], "identity": item.get("identity")}

    def breadth(self):
        # Only aggregated counts leave this adapter; no full stock list enters AI.
        historical_error = None
        try:
            from .us_breadth import USBreadth
            return USBreadth(self.http).collect()
        except AppError as exc:
            historical_error = exc.as_dict()
        try:
            result = self.nasdaq_breadth()
            result["history_error"] = historical_error
            return result
        except AppError as exc:
            first = exc.as_dict()
            try:
                result = self.wsj_breadth()
                result["primary_error"] = first
                return result
            except AppError as other:
                raise AppError("source_unavailable", "NYSE＋NASDAQ广度源暂不可用", {"attempts": [first, other.as_dict()]}, 503)

    def nasdaq_breadth(self):
        sources, groups, errors = [], [], []
        directory = {}
        for filename, exchange, symbol_key in (("nasdaqlisted.txt", "NASDAQ", "Symbol"), ("otherlisted.txt", "NYSE", "ACT Symbol")):
            try:
                r = self.http.get("https://www.nasdaqtrader.com/dynamic/SymDir/" + filename, ttl=3600, stale=True)
                sources.append(metadata(r))
                for row in csv.DictReader(io.StringIO(r["text"]), delimiter="|"):
                    if row.get(symbol_key) and (exchange == "NASDAQ" or row.get("Exchange") == "N"):
                        directory[(exchange, row[symbol_key])] = row
            except AppError as exc:
                errors.append(exc.message)
        for exchange in ("NYSE", "NASDAQ"):
            r = self.http.data("https://api.nasdaq.com/api/screener/stocks", params={"tableonly": "true", "limit": 10000, "exchange": exchange.lower()},
                               ttl=300, stale=True, referer="https://www.nasdaq.com/")
            data = r["data"].get("data") or {}
            rows = (data.get("table") or {}).get("rows") or []
            total = int(data.get("totalrecords") or 0)
            match = re.search(r"([A-Z][a-z]{2} \d{1,2}, \d{4})", data.get("asof") or "")
            if not rows or not match:
                raise AppError("source_format", "Nasdaq广度缺少目录或报价日期")
            asof = datetime.strptime(match.group(1), "%b %d, %Y").date().isoformat()
            counts = dict(advancing=0, declining=0, unchanged=0, unknown_prices=0, excluded=0, unclassified=0, eligible_count=0)
            seen = set()
            for row in rows:
                symbol = row.get("symbol")
                if not symbol or symbol in seen:
                    continue
                seen.add(symbol)
                meta = directory.get((exchange, symbol)) or {}
                name = meta.get("Security Name") or row.get("name", "")
                if meta.get("ETF") == "Y" or meta.get("Test Issue") == "Y" or re.search(r"preferred|warrant|\bunits?\b|\bET[FN]\b|closed.end|rights", name, re.I):
                    counts["excluded"] += 1
                    continue
                if not meta or not re.search(r"common|ordinary|depositary|\bADS\b|\bADR\b|capital stock|shares of beneficial", name, re.I):
                    counts["unclassified"] += 1
                    continue
                counts["eligible_count"] += 1
                close = number(str(row.get("lastsale", "")).replace("$", "").replace(",", ""))
                delta = number(str(row.get("netchange", "")).replace(",", ""))
                if close is None or close <= 0 or delta is None or close - delta <= 0:
                    counts["unknown_prices"] += 1
                else:
                    counts["advancing" if delta > 0 else "declining" if delta < 0 else "unchanged"] += 1
            groups.append(dict(counts, exchange=exchange, date=asof, directory_count=len(seen), directory_reported=total,
                               complete=total == len(seen) and not counts["unknown_prices"] and not counts["unclassified"]))
            sources.append(metadata(r))
        if groups[0]["date"] != groups[1]["date"]:
            raise AppError("source_date", "NYSE与NASDAQ源日期不一致，不能相加", {"groups": groups})
        totals = {key: sum(x[key] for x in groups) for key in ("advancing", "declining", "unchanged", "unknown_prices", "excluded", "unclassified", "eligible_count")}
        date_value = groups[0]["date"]
        definition = "NYSE＋NASDAQ源目录，按前收净变化统计；目录与证券名称识别普通/普通存托股票，剔除ETF/优先股/权证/单位等。未识别类别单列，非完整普通股覆盖保证。"
        point = dict(totals, date=date_value, asof=date_value, scope_id="nasdaq-directory-common-v1", complete=all(x["complete"] for x in groups),
                     forming=forming(date_value), source=sources[-1]["source"], definition=definition, exchanges=["NYSE", "NASDAQ"])
        return {**point, "rows": [point], "groups": groups, "sources": sources, "fetched_at": sources[-1]["fetched_at"],
                "limitations": errors + ["免费广度历史按本地实际观察逐日累积；尚未取得启动前完整历史"]}

    def wsj_breadth(self):
        # Schema is intentionally checked. A changed page cannot become zero breadth.
        r = self.http.get("https://www.wsj.com/market-data/stocks/marketsdiary", ttl=300, stale=True)
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', r["text"], re.S)
        nodes = []
        def walk(value):
            if isinstance(value, dict):
                if "advances" in value and "declines" in value:
                    nodes.append(value)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        for script in scripts:
            try:
                matched = re.search(r"window\.__STATE__\s*=\s*", script)
                walk(json.JSONDecoder().raw_decode(script[matched.end():])[0] if matched else json.loads(script))
            except ValueError:
                continue
        groups = {}
        for node in nodes:
            exchange = str(node.get("exchange") or node.get("market") or node.get("name") or "").upper()
            if exchange not in ("NYSE", "NASDAQ"):
                continue
            day = str(node.get("date") or node.get("asof") or node.get("asOf") or "")[:10]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                continue
            values = {key: number(node.get(source)) for key, source in (("advancing", "advances"), ("declining", "declines"), ("unchanged", "unchanged"))}
            if any(v is None or v < 0 or v != int(v) for v in values.values()):
                continue
            total = number(node.get("issuesTraded"))
            if total is None or sum(values.values()) > total:
                continue
            groups[exchange] = dict(values, date=day, unknown_prices=int(total - sum(values.values())), eligible_count=int(total))
        if set(groups) != {"NYSE", "NASDAQ"} or groups["NYSE"]["date"] != groups["NASDAQ"]["date"]:
            raise AppError("source_format", "WSJ公开日记未返回可核实的NYSE/NASDAQ同日家数，未采用", {"source": r["source"]})
        totals = {key: int(sum(x[key] for x in groups.values())) for key in ("advancing", "declining", "unchanged", "unknown_prices", "eligible_count")}
        day = groups["NYSE"]["date"]
        point = dict(totals, date=day, asof=day, scope_id="wsj-listed-issues-v1", forming=forming(day), complete=not totals["unknown_prices"],
                     definition="WSJ NYSE＋NASDAQ上市证券统计，可能含普通股以外证券；与普通股目录序列不拼接", source=r["source"], exchanges=["NYSE", "NASDAQ"])
        return {**point, "rows": [point], "groups": groups, "sources": [metadata(r)], "limitations": ["后备统计为上市证券范围，非严格普通股/ADR范围"]}
