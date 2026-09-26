"""Fixed mainland ETF instruments for US index observations; no order API."""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from .providers.eastmoney import Eastmoney
from .providers.ths import Tables, Ths
from .providers.us_market import metadata
from .market_time import session_info, is_session_day
from .util import AppError, CN, new_id, number, now

TARGETS = {"us:DJI": ("道琼斯", "道琼斯工业平均"), "us:NDX": ("纳", "纳斯达克100"), "us:SPX": ("标普500", "标普500")}


def cn_window(count=20):
    info = session_info()
    if not info["calendar_verified"]:
        raise AppError("calendar_unknown", "境内日历未核实，不能选取20个完整交易日")
    clock = datetime.now(CN)
    day = clock.date()
    if clock.hour < 15 or not is_session_day(day):
        day -= timedelta(days=1)
    rows = []
    while len(rows) < count:
        if is_session_day(day):
            rows.append(day.isoformat())
        day -= timedelta(days=1)
    return list(reversed(rows))


class ETFPairing:
    def __init__(self, client, store):
        self.http, self.store = client, store
        self.cn = Eastmoney(client)

    def current(self):
        return {x["payload"]["index_id"]: x for x in self.store.list_objects("pairing", analysis_market="US")}

    def preview(self, index_id):
        if index_id not in TARGETS:
            raise AppError("invalid_pairing", "仅三大美股指数支持境内ETF配对")
        window = cn_window()
        r = self.http.get("https://fund.eastmoney.com/js/fundcode_search.js", ttl=86400, stale=True)
        try:
            catalog = json.loads(r["text"].lstrip("\ufeff").split("=", 1)[1].strip().rstrip(";"))
        except (ValueError, IndexError):
            raise AppError("source_format", "基金目录结构已变化")
        keyword, tracking = TARGETS[index_id]
        choices = [x for x in catalog if len(x) >= 4 and re.fullmatch(r"(?:51|15)\d{4}", x[0]) and keyword in x[2] and "ETF" in x[2] and "联接" not in x[2]]
        if not choices:
            raise AppError("no_etf", "目录未发现对应境内ETF")
        def inspect(row):
            code, _, name = row[:3]
            aid = ("sh" if code.startswith("5") else "sz") + code
            item = {"asset_id": aid, "name": name, "eligible": False, "amount_mean20": None}
            try:
                identity = self.identity(code)
                item.update(identity)
                target = re.sub(r"\s|[-－]", "", identity["tracking"])
                matches = (tracking in target or (index_id == "us:SPX" and ("标准普尔500" in target or re.search(r"S&P\s*500", target, re.I))) or (index_id == "us:NDX" and re.search(r"NASDAQ\s*100", target, re.I)))
                if not matches:
                    item.update(reason="跟踪标的不同，排除", conclusively_excluded=True)
                    return item
                hist = self.history(aid, 65)
                by_day = {x["date"]: x for x in hist["bars"]}
                points = [by_day.get(d) for d in window]
                item.update(history_source=hist["source"], missing_dates=[d for d, p in zip(window, points) if not p or number(p.get("amount")) is None],
                            days=[{"date": d, "amount": p.get("amount") if p else None} for d, p in zip(window, points)])
                if item["missing_dates"] or any(p["amount"] < 0 for p in points if p and p.get("amount") is not None):
                    item["reason"] = "同一20日窗口的真实成交金额不足"
                else:
                    item.update(eligible=True, amount_mean20=sum(p["amount"] for p in points) / 20, reason="同窗口资料完整")
            except AppError as exc:
                item.update(reason=exc.message, error=exc.as_dict())
            return item
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(inspect, choices))
        valid = sorted((x for x in rows if x["eligible"] and x["amount_mean20"] > 0), key=lambda x: (-x["amount_mean20"], x["asset_id"]))
        complete = bool(valid) and all(x["eligible"] or x.get("conclusively_excluded") for x in rows)
        return {"id": new_id(), "index_id": index_id, "created_at": now(), "window": window, "rows": rows,
                "selected": valid[0]["asset_id"] if complete else None, "coverage_complete": complete,
                "source": r["source"], "directory_stale": r["cache_stale"],
                "policy": "公开基金目录按指数名称发现，逐一核实跟踪标的；在已核实目录的同20日完整成交金额中择最大，名称遗漏风险保留。首次选择后固定，不随日常排名轮换"}

    def identity(self, code):
        r = self.http.get("https://fundf10.eastmoney.com/jbgk_%s.html" % code, ttl=86400, stale=True)
        parser = Tables(); parser.feed(r["text"])
        fields = {}
        for row in parser.rows:
            cells = [x["text"] for x in row]
            for i in range(len(cells) - 1):
                if cells[i] in ("跟踪标的", "基金全称", "基金类型", "业绩比较基准"):
                    fields[cells[i]] = cells[i + 1]
        if not fields.get("跟踪标的") or "交易型开放式" not in fields.get("基金全称", ""):
            raise AppError("fund_identity", "未能核实场内ETF身份与跟踪标的", {"code": code, "source": r["source"]})
        return {"tracking": fields["跟踪标的"], "full_name": fields.get("基金全称"), "identity_source": r["source"], "identity_fetched_at": r["fetched_at"]}

    def bind(self, preview, asset_id=None, expected_revision=None, actor="用户明确确认"):
        aid = asset_id or preview.get("selected")
        row = next((x for x in preview["rows"] if x["asset_id"] == aid and x.get("eligible")), None)
        if not row:
            raise AppError("incomplete_pairing", "没有可绑定的已核实ETF；请先补足20日金额与身份资料")
        payload = {"index_id": preview["index_id"], "asset_id": aid, "name": row["name"], "analysis_market": "US", "execution_market": "CN",
                   "tracking": row["tracking"], "identity_source": row["identity_source"], "selected_at": now(), "selection": preview,
                   "actor": actor, "selection_policy": "user_choice" if asset_id else "max_mean20_once"}
        return self.store.record_pairing(payload, expected_revision)

    def observations(self, pairing, count=360):
        p = pairing["payload"]
        aid = p["asset_id"]
        history = self.history(aid, count)
        try:
            quote = self.cn.quote(aid)
        except AppError:
            last = history["bars"][-1]
            # Adjusted history is not a current exchange price for premium.
            quote = {"asset_id": aid, "close": None, "asof": last["date"], "source": history["source"]}
        premium = {"value": None, "unit": "%", "basis_type": "missing", "price": quote.get("close"), "price_asof": quote.get("asof"),
                   "currency": "CNY", "basis_currency": "CNY", "iopv_status": "未取得带可靠源时点的IOPV，不冒称实时溢价"}
        try:
            r = self.http.data("https://api.fund.eastmoney.com/f10/lsjz", params={"fundCode": aid[2:], "pageIndex": 1, "pageSize": 10}, ttl=3600, stale=True,
                               referer="https://fundf10.eastmoney.com/")
            rows = (r["data"].get("Data") or {}).get("LSJZList") or []
            valid = [x for x in rows if number(x.get("DWJZ")) is not None and number(x["DWJZ"]) > 0 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", x.get("FSRQ", ""))]
            if not valid:
                raise AppError("nav_missing", "基金已公布单位净值为空")
            point = sorted(valid, key=lambda x: x["FSRQ"])[-1]
            nav, day = number(point["DWJZ"]), point["FSRQ"]
            premium.update(basis_type="published_nav", basis_value=nav, basis_date=day, published_at=None, source=r["source"], fetched_at=r["fetched_at"],
                           label="相对已公布净值偏离", definition="(人民币市场价/人民币已公布单位净值−1)×100；两地交易时差与净值滞后，非实时公平价值溢价")
            price = number(quote.get("close"))
            if price and price > 0 and quote.get("asof") and day <= str(quote["asof"])[:10]:
                premium["value"] = (price / nav - 1) * 100
            else:
                premium["reason"] = "市场价、时点或净值日不可比，未计算偏离"
        except AppError as exc:
            premium["reason"] = exc.message
        return {"asset_id": aid, "name": p["name"], "kind": "etf", "analysis_market": "US", "execution_market": "CN",
                "pairing_ref": pairing["ref"], "index_id": p["index_id"], "history": history, "quote": quote, "premium": premium,
                "selection": {"window": p["selection"]["window"], "selected_at": p["selected_at"], "policy": p["selection"]["policy"]}}

    def history(self, aid, count):
        rows, sources = {}, []
        try:
            urls = ["https://d.10jqka.com.cn/v6/line/hs_%s/01/last.js" % aid[2:]]
            if count > 140:
                urls += ["https://d.10jqka.com.cn/v4/line/hs_%s/01/%s.js" % (aid[2:], year) for year in range(datetime.now(CN).year, datetime.now(CN).year - 3, -1)]
            for url in urls:
                try:
                    r = self.http.data(url, ttl=1800, stale=True, referer="https://stockpage.10jqka.com.cn/")
                    Ths._bars(r["data"].get("data", ""), rows)
                    sources.append(metadata(r))
                except AppError:
                    continue
                if len(rows) >= count:
                    break
            if not rows:
                raise AppError("source_format", "同花顺ETF历史为空")
            bars = [rows[d] for d in sorted(rows)][-count:]
            return {"bars": bars, "source": "同花顺境内ETF日线", "sources": sources, "asof": bars[-1]["date"],
                    "adjustment": "同花顺01日线原始价格序列", "volume_unit": "ETF份", "amount_unit": "元"}
        except AppError:
            return self.cn.history(aid, count, "etf")
