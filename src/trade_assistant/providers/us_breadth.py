"""Anonymous recent daily breadth reconstruction; no constituent data is sent to AI."""
import base64
import csv
import hashlib
import io
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from ..dependencies import PARQUET_RUNTIME, node_command
from ..us_time import eastern, is_session, previous_day, session_info
from ..util import AppError, number, write_json
from .us_market import metadata

SCOPE = "marketparquet-current-roster-common-v1"


def symbol_key(value):
    return str(value).upper().replace("-", ".")


class USBreadth:
    def __init__(self, client):
        self.http = client

    def directory(self):
        roster, excluded, unclassified, sources = {}, 0, 0, []
        for filename, exchange, field in (("nasdaqlisted.txt", "NASDAQ", "Symbol"), ("otherlisted.txt", "NYSE", "ACT Symbol")):
            r = self.http.get("https://www.nasdaqtrader.com/dynamic/SymDir/" + filename, ttl=3600, stale=True)
            sources.append(metadata(r))
            found = 0
            for row in csv.DictReader(io.StringIO(r["text"]), delimiter="|"):
                symbol = row.get(field)
                if not symbol or symbol.startswith("File Creation Time") or (exchange == "NYSE" and row.get("Exchange") != "N"):
                    continue
                name = row.get("Security Name", "")
                if row.get("ETF") == "Y" or row.get("Test Issue") == "Y" or re.search(r"preferred|warrant|\bunits?\b|\bET[FN]\b|closed.end|rights", name, re.I):
                    excluded += 1
                    continue
                if not re.search(r"common|ordinary|american depositary|\bADS\b|\bADR\b|capital stock|shares of beneficial", name, re.I):
                    unclassified += 1
                    continue
                key = symbol_key(symbol)
                if key in roster and roster[key] != exchange:
                    raise AppError("breadth_directory", "证券目录跨交易所标识冲突")
                roster[key] = exchange
                found += 1
            if found < 500:
                raise AppError("breadth_directory", exchange + "证券目录覆盖异常")
        return roster, excluded, unclassified, sources

    def prices(self, day):
        url = "https://marketparquet.com/api/data/download/stock_daily/" + day + ".parquet"
        response = self.http.get(url, encoding=None, ttl=21600, stale=True, referer="https://marketparquet.com/")
        raw = response["bytes"]
        key = hashlib.sha256(b"breadth-prices-1" + raw).hexdigest()
        cache = self.http.cache / ("breadth-prices-" + key + ".json")
        try:
            result = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            worker = Path(__file__).resolve().parents[1] / "parquet_worker.mjs"
            try:
                reply = subprocess.run([node_command(), str(worker), str(PARQUET_RUNTIME)], input=json.dumps({"data": base64.b64encode(raw).decode("ascii")}),
                                       capture_output=True, text=True, timeout=30)
                payload = json.loads(reply.stdout)
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                raise AppError("breadth_decode", "全市场日线文件未解析成功", {"reason": str(exc)})
            if reply.returncode or payload.get("error"):
                raise AppError("breadth_decode", "全市场日线解析失败", {"reason": payload.get("error")})
            prices = {}
            rows = payload.get("rows", [])
            for row in rows:
                if str(row.get("date", ""))[:10] != day:
                    raise AppError("breadth_date", "行情文件内部日期与请求日期不符")
                if str(row.get("asset_type", "")).lower() != "stock":
                    continue
                symbol = symbol_key(row.get("symbol", ""))
                close = number(row.get("close"))
                if not symbol or close is None or close <= 0:
                    continue
                if symbol in prices and prices[symbol] != close:
                    raise AppError("breadth_duplicate", "同日证券有冲突收盘价")
                prices[symbol] = close
            if len(prices) < 3000:
                raise AppError("breadth_coverage", "全美股票文件覆盖异常，未用于重建")
            result = {"date": day, "prices": prices, "file_count": len(rows)}
            write_json(cache, result)
        if result.get("date") != day:
            raise AppError("breadth_date", "历史解析缓存日期不符")
        return {**result, **metadata(response)}

    def collect(self):
        roster, excluded, unclassified, sources = self.directory()
        clock = eastern().date()
        calendar = session_info()
        if not calendar["calendar_verified"]:
            raise AppError("calendar_unknown", "美国日历未核实，不能比较相邻交易日涨跌")
        complete = calendar["latest_completed_date"]
        dates = sorted((clock - timedelta(days=i)).isoformat() for i in range(7) if is_session(clock - timedelta(days=i)) and (clock - timedelta(days=i)).isoformat() <= complete)
        history, errors = {}, []
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [(d, pool.submit(self.prices, d)) for d in dates]
            for day, job in jobs:
                try:
                    history[day] = job.result()
                    sources.append(metadata(history[day]))
                except AppError as exc:
                    errors.append({"date": day, "error": exc.as_dict()})
        rows = []
        definition = "NYSE＋NASDAQ当前普通股/ADR目录，逐日比较提供方拆股调整收盘价；历史按当前目录重建，未识别类型及缺前收单列"
        universe_hash = hashlib.sha256(json.dumps(roster, sort_keys=True).encode()).hexdigest()
        for day, value in sorted(history.items()):
            before = previous_day(day)
            if before not in history:
                continue
            groups = {ex: {"exchange": ex, "advancing": 0, "declining": 0, "unchanged": 0, "unknown_prices": 0, "eligible_count": 0} for ex in ("NYSE", "NASDAQ")}
            for symbol, exchange in roster.items():
                group = groups[exchange]
                group["eligible_count"] += 1
                close, prior = value["prices"].get(symbol), history[before]["prices"].get(symbol)
                if close is None or prior is None:
                    group["unknown_prices"] += 1
                else:
                    group["advancing" if close > prior else "declining" if close < prior else "unchanged"] += 1
            counts = {k: sum(x[k] for x in groups.values()) for k in ("advancing", "declining", "unchanged", "unknown_prices", "eligible_count")}
            if counts["eligible_count"] - counts["unknown_prices"] < 3000:
                continue
            rows.append({**counts, "date": day, "asof": day, "scope_id": SCOPE, "forming": False, "complete": False,
                         "groups": list(groups.values()), "source": value["source"], "previous_source": history[before]["source"],
                         "definition": definition, "exchanges": ["NYSE", "NASDAQ"], "universe_date": clock.isoformat(), "universe_hash": universe_hash})
        if not rows:
            raise AppError("breadth_history", "匿名历史窗口没有足够的相邻交易日收盘价", {"attempts": errors})
        last = rows[-1]
        return {**last, "rows": rows, "excluded": excluded, "unclassified": unclassified, "sources": sources,
                "fetched_at": max(x["fetched_at"] for x in sources), "history_start": rows[0]["date"], "history_days": len(rows), "attempts": errors,
                "limitations": ["无需登录仅可取得最近7天文件；首个交易日缺窗口内前收，后续通过本地快照积累历史",
                                "当前目录用于历史重建，存在上市/退市及证券分类覆盖偏差；不代表历史时点完整目录"]}
