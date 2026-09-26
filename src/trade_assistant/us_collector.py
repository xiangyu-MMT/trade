from concurrent.futures import ThreadPoolExecutor, as_completed

from .http_client import HttpClient
from .providers.us_market import USMarket
from .providers.us_macro import USMacro
from .etf_pairing import ETFPairing
from .store import Store
from .util import AppError, new_id, now
from .us_time import session_info


class USCollector:
    def __init__(self, settings, progress=None, store=None, cancelled=None):
        self.settings, self.config = settings, settings.load()
        self.progress = progress or (lambda stage, detail: None)
        self.store = store or Store(settings.home)
        net = self.config["network"]
        self.http = HttpClient(settings.home, net["timeout"], net["budget_seconds"])
        self.market = USMarket(self.http)
        self.coverage = []
        self.cancelled = cancelled

    def check_cancelled(self):
        if self.cancelled is not None and self.cancelled.is_set():
            raise AppError("cancelled", "美股本轮已停止", status=409)

    def collect(self):
        us = self.config["us"]
        candidates = [dict(x, reasons=["美国三指数" if x["kind"] == "index" else "选定美国行业"]) for x in us["indices"] + us["sectors"]]
        gold = {"asset_id": "us:GC", "symbol": "GC=F", "name": "纽约金·近月连续观察", "kind": "future", "identity": "COMEX Gold Futures near-month provider series"}
        jobs = {x["asset_id"]: lambda item=x: self.market.history(item, self.config["history_bars"]) for x in candidates + [gold]}
        for x in us["indices"]:
            symbol = x["volume_symbol"]
            jobs["volume:" + symbol] = lambda s=symbol: self.market.history({"symbol": s, "kind": "etf", "identity": s + "美国指数ETF量能观察"}, self.config["history_bars"])
        histories, macro, breadth = {}, [], None
        jobs["breadth"] = self.market.breadth
        jobs["macro"] = lambda: USMacro(self.http).collect(us["observations"])
        self.progress("美股取数", "三指数、七行业、纽约金、全市场广度及宏观")
        with ThreadPoolExecutor(max_workers=self.config["network"]["workers"]) as pool:
            pending = {pool.submit(fn): key for key, fn in jobs.items()}
            for future in as_completed(pending):
                self.check_cancelled()
                key = pending[future]
                try:
                    value = future.result()
                    if key == "macro":
                        macro = value["series"]
                        self.coverage.extend(value["coverage"])
                    elif key == "breadth":
                        breadth = value
                        self.coverage.append({"group": "NYSE＋NASDAQ广度", "status": "ok" if value.get("complete") else "partial", "detail": value["definition"] + "；历史由真实观察逐日积累"})
                    else:
                        histories[key] = value
                        info = session_info(value.get("asof"))
                        stale = value.get("cache_stale") or (info["calendar_verified"] and not info["source_date_matches_expected"])
                        self.coverage.append({"group": key, "status": "partial" if stale else "ok", "detail": ("历史缓存/日期滞后；" if stale else "") + value["asof"] + " · " + value.get("identity", key)})
                except (AppError, ValueError, KeyError, TypeError) as exc:
                    self.coverage.append({"group": key, "status": "missing", "detail": str(exc), "error": exc.as_dict() if isinstance(exc, AppError) else None})
                self.progress("美股取数", "已处理 %s/%s · %s" % (sum(f.done() for f in pending), len(pending), key))
        self.progress("境内ETF", "读取固定配对；首次按20日成交金额筛选")
        pairs = ETFPairing(self.http, self.store)
        current, paired = pairs.current(), {}
        for item in us["indices"]:
            self.check_cancelled()
            aid = item["asset_id"]
            try:
                if aid not in current:
                    preview = pairs.preview(aid)
                    if not preview["coverage_complete"] or preview["directory_stale"]:
                        raise AppError("pairing_incomplete", "ETF筛选资料未完整，尚未固定代码", preview)
                    current[aid] = pairs.bind(preview, actor="程序按翔宇已授权的20日均成交金额规则首次固定")
                paired[aid] = pairs.observations(current[aid], self.config["history_bars"])
                self.coverage.append({"group": "ETF " + aid, "status": "partial", "detail": "固定代码 " + paired[aid]["asset_id"] + "；已公布净值偏离与实时溢价分开，IOPV可靠时点暂缺"})
            except AppError as exc:
                self.coverage.append({"group": "ETF " + aid, "status": "missing", "detail": exc.message, "error": exc.as_dict()})
        dates = [histories[x["asset_id"]]["asof"] for x in us["indices"] if x["asset_id"] in histories]
        return {"schema_version": 1, "analysis_market": "US", "id": new_id(), "created_at": now(), "asof": max(dates) if dates else None,
                "config_snapshot": self.config, "candidates": candidates, "watch_instruments": [gold], "histories": histories,
                "breadth": breadth, "macro": macro, "pairings": current, "paired_etfs": paired,
                "coverage": self.coverage, "source_attempts": self.http.attempts}
