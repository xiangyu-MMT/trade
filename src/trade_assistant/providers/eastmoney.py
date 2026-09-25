import concurrent.futures
import re
from datetime import datetime, timedelta

from ..util import AppError, CN, date_text, epoch_time, number
from .ths import meta

FIELDS = "f12,f13,f14,f2,f3,f5,f6,f15,f16,f17,f18,f124"


def secid(asset_id):
    if asset_id.startswith("csi"):
        return "2." + asset_id[3:]
    if asset_id == "sh932000":  # Compatibility with the first local configuration draft.
        return "2.932000"
    return ("1." if asset_id.startswith("sh") else "0.") + asset_id[2:]


def stock_row(row):
    code = str(row.get("f12", ""))
    exchange = "sh" if row.get("f13") == 1 else "sz"
    v = number(row.get("f5"))
    return {"asset_id": exchange + code, "code": code, "name": row.get("f14", code),
            "close": number(row.get("f2")), "previous_close": number(row.get("f18")),
            "change_pct": number(row.get("f3")), "open": number(row.get("f17")),
            "high": number(row.get("f15")), "low": number(row.get("f16")),
            "volume": v * 100 if v is not None else None, "amount": number(row.get("f6")),
            "asof": epoch_time(row.get("f124")), "volume_unit": "股", "amount_unit": "元"}


def eligible(row):
    code = str(row.get("code", row.get("asset_id", "")[2:]))
    return code.startswith(("00", "30", "60", "68")) and "ST" not in str(row.get("name", "")).upper()


class Eastmoney:
    def __init__(self, client, workers=4):
        self.http, self.workers = client, workers

    def market(self):
        try:
            return self._em_market()
        except AppError as exc:
            result = self._sina_market()
            result["fallback_reason"] = exc.as_dict()
            return result

    def _em_market(self):
        params = {"pn": 1, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                  "fid": "f12", "fs": "m:1 t:2,m:1 t:23,m:0 t:6,m:0 t:80", "fields": FIELDS}
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        first = self.http.data(url, params=params, referer="https://quote.eastmoney.com/")
        data = first["data"].get("data") or {}
        initial = data.get("diff") or []
        total = int(data.get("total") or 0)
        if not initial or total > 15000:
            raise AppError("source_format", "沪深股票列表无效或分页范围异常", status=503)
        count = len(initial)
        all_rows, errors, sources = list(initial), [], [meta(first)]

        def page(n):
            p = dict(params, pn=n)
            r = self.http.data(url, params=p, referer="https://quote.eastmoney.com/")
            d = r["data"].get("data") or {}
            return d.get("diff") or [], meta(r), d.get("total")

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            future_map = {pool.submit(page, n): n for n in range(2, (total + count - 1) // count + 1)}
            for future in concurrent.futures.as_completed(future_map):
                try:
                    rows, source, advertised = future.result()
                    all_rows.extend(rows)
                    sources.append(source)
                    if advertised != total:
                        errors.append({"page": future_map[future], "reason": "分页期间证券数量变化"})
                except AppError as exc:
                    errors.append({"page": future_map[future], **exc.as_dict()})
        unique = {}
        for row in all_rows:
            q = stock_row(row)
            q["source"] = "东方财富沪深A股快照"
            unique[q["asset_id"]] = q
        rows = sorted(unique.values(), key=lambda x: x["asset_id"])
        return {"stocks": rows, "total_reported": total, "received": len(rows),
                "complete": len(rows) == total and not errors,
                "sources": sources, "errors": errors,
                "asof": max((r["asof"] for r in rows if r["asof"]), default=None),
                "definition": "沪深A股源列表，计算时剔除ST和范围外证券"}

    def _sina_market(self):
        base = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center."
        count_reply = self.http.get(base + "getHQNodeStockCount", params={"node": "hs_a"}, referer="https://finance.sina.com.cn/")
        match = re.fullmatch(r'\s*"?(\d+)"?\s*', count_reply["text"])
        total = int(match.group(1)) if match else 0
        if not 1 <= total <= 15000:
            raise AppError("source_format", "新浪股票目录总数无效", status=503)
        errors, sources, items = [], [meta(count_reply)], {}

        def page(n):
            return self.http.data(base + "getHQNodeData", params={
                "page": n, "num": 80, "sort": "symbol", "asc": 1, "node": "hs_a", "symbol": "", "_s_r_a": "page"},
                referer="https://finance.sina.com.cn/")

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(page, n): n for n in range(1, (total + 79) // 80 + 1)}
            for future in concurrent.futures.as_completed(futures):
                try:
                    r = future.result()
                    if not isinstance(r["data"], list):
                        raise AppError("source_format", "新浪快照分页格式变化", status=503)
                    sources.append(meta(r))
                    for x in r["data"]:
                        aid = x.get("symbol", "")
                        if not aid:
                            continue
                        items[aid] = {"asset_id": aid, "code": x.get("code", aid[2:]), "name": x.get("name", aid),
                                      "close": number(x.get("trade")), "previous_close": number(x.get("settlement")),
                                      "change_pct": number(x.get("changepercent")), "open": number(x.get("open")),
                                      "high": number(x.get("high")), "low": number(x.get("low")),
                                      "volume": number(x.get("volume")), "amount": number(x.get("amount")),
                                      "asof": None, "source": "新浪全市场快照（仅提供时分秒）",
                                      "ticktime": x.get("ticktime"), "volume_unit": "股", "amount_unit": "元"}
                except AppError as exc:
                    errors.append({"page": futures[future], **exc.as_dict()})
        ids = [aid for aid in items if aid.startswith(("sh", "sz"))]
        batches = [ids[i:i + 100] for i in range(0, len(ids), 100)]
        quote_errors = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = [pool.submit(self.tencent_batch, group) for group in batches]
            for future in concurrent.futures.as_completed(futures):
                try:
                    rows, source = future.result()
                    sources.append(source)
                    for aid, row in rows.items():
                        if aid in items:
                            items[aid].update(row)
                except AppError as exc:
                    quote_errors.append(exc.as_dict())
        rows = sorted(items.values(), key=lambda x: x["asset_id"])
        dated = sum(bool(x.get("asof")) for x in rows if eligible(x))
        return {"stocks": rows, "total_reported": total, "received": len(rows),
                "complete": len(rows) == total and not errors, "dated_eligible": dated,
                "sources": sources, "errors": errors, "quote_errors": quote_errors,
                "asof": max((x["asof"] for x in rows if x.get("asof")), default=None),
                "definition": "新浪A股完整目录 + 腾讯时间戳报价替代；统计时剔除北交所/ST，未补齐日期项明确保留时效缺口"}

    def tencent_batch(self, ids):
        r = self.http.get("https://qt.gtimg.cn/q=" + ",".join(ids), encoding="gb18030")
        rows = {}
        for aid, body in re.findall(r'v_((?:sh|sz)\d{6})="([^"]*)"', r["text"]):
            try:
                rows[aid] = self._tencent_row(aid, body.split("~"), r)
            except AppError:
                continue
        if not rows:
            raise AppError("source_format", "腾讯批量报价为空", status=503)
        return rows, meta(r)

    def quote(self, asset_id):
        try:
            r = self.http.data("https://push2.eastmoney.com/api/qt/stock/get", params={
                "secid": secid(asset_id), "fltt": 2,
                "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f86"},
                referer="https://quote.eastmoney.com/")
            d = r["data"].get("data") or {}
            if number(d.get("f43")) is None:
                raise AppError("source_format", "未取得有效报价", status=503)
            volume = number(d.get("f47"))
            close, previous = number(d.get("f43")), number(d.get("f60"))
            return {"asset_id": asset_id, "name": d.get("f58", asset_id), "close": close,
                    "previous_close": previous,
                    "change_pct": (close / previous - 1) * 100 if previous else None,
                    "open": number(d.get("f46")), "high": number(d.get("f44")),
                    "low": number(d.get("f45")), "volume": volume * 100 if volume is not None else None,
                    "amount": number(d.get("f48")), "volume_unit": "股/提供方指数汇总", "amount_unit": "元",
                    **meta(r, epoch_time(d.get("f86")))}
        except AppError:
            return self.tencent_quote(asset_id)

    def tencent_quote(self, asset_id):
        r = self.http.get("https://qt.gtimg.cn/q=" + asset_id, encoding="gb18030")
        match = re.search(r'="(.*?)"', r["text"])
        cells = match.group(1).split("~") if match else []
        return self._tencent_row(asset_id, cells, r)

    @staticmethod
    def _tencent_row(asset_id, cells, r):
        if len(cells) < 38 or number(cells[3]) is None:
            raise AppError("source_format", "腾讯报价暂不可解析", {"asset_id": asset_id}, 503)
        try:
            asof = datetime.strptime(cells[30], "%Y%m%d%H%M%S").replace(tzinfo=CN).isoformat()
        except ValueError:
            asof = None
        return {"asset_id": asset_id, "name": cells[1], "close": number(cells[3]),
                "previous_close": number(cells[4]), "open": number(cells[5]),
                "high": number(cells[33]), "low": number(cells[34]),
                "volume": number(cells[36]) * 100 if number(cells[36]) is not None else None,
                "amount": number(cells[37]) * 10000 if number(cells[37]) is not None else None,
                "change_pct": number(cells[32]), "volume_unit": "股/提供方指数汇总", "amount_unit": "元",
                **meta(r, asof)}

    def history(self, asset_id, count=360, kind="index"):
        try:
            params = {
                "secid": secid(asset_id), "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": 101, "fqt": 1 if kind in ("stock", "etf") else 0,
                "beg": (datetime.now(CN) - timedelta(days=count * 2 + 30)).strftime("%Y%m%d"),
                "end": "20500101"}
            try:
                r = self.http.data("https://push2his.eastmoney.com/api/qt/stock/kline/get", params=params,
                                   ttl=1800, stale=True, referer="https://quote.eastmoney.com/")
            except AppError:
                r = self.http.data("https://7.push2his.eastmoney.com/api/qt/stock/kline/get", params=params,
                                   ttl=1800, stale=True, referer="https://quote.eastmoney.com/")
            obj = r["data"].get("data") or {}
            bars = []
            for line in obj.get("klines", []):
                f = line.split(",")
                if len(f) < 7:
                    continue
                v = [number(x) for x in f[1:7]]
                if all(x is not None for x in v[:5]) and min(v[:4]) > 0:
                    bars.append({"date": f[0], "open": v[0], "close": v[1], "high": v[2],
                                 "low": v[3], "volume": v[4] * 100, "amount": v[5]})
            if not bars:
                raise AppError("source_format", "东方财富历史为空", status=503)
            return {"bars": bars[-count:], "source": "东方财富日线", "sources": [meta(r)],
                    "asof": bars[-1]["date"], "volume_unit": "股/提供方指数汇总", "amount_unit": "元",
                    "adjustment": "前复权" if kind in ("stock", "etf") else "指数原序列"}
        except AppError:
            if asset_id.startswith("csi"):
                raise AppError("source_unavailable", "中证指数历史接口暂不可得，保留缺口", {"asset_id": asset_id, "provider_id": secid(asset_id)}, 503)
            r = self.http.data("https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_k=/CN_MarketDataService.getKLineData",
                               params={"symbol": asset_id, "scale": 240, "ma": "no", "datalen": count},
                               ttl=1800, stale=True, referer="https://finance.sina.com.cn/")
            bars = []
            if isinstance(r["data"], list):
                for item in r["data"]:
                    bar = {key: number(item.get(key)) for key in ("open", "high", "low", "close", "volume")}
                    if date_text(item.get("day")) and all(x is not None for x in bar.values()):
                        bars.append(dict(bar, date=date_text(item["day"]), amount=None))
            if not bars:
                raise AppError("source_format", "替代历史数据为空", {"asset_id": asset_id}, 503)
            return {"bars": bars, "source": "新浪日线（替代）", "sources": [meta(r)],
                    "asof": bars[-1]["date"], "volume_unit": "股/提供方指数汇总", "amount_unit": "缺失",
                    "adjustment": "未复权替代源，不与前复权历史拼接"}

    def margin(self):
        r = self.http.data("https://datacenter-web.eastmoney.com/api/data/v1/get", params={
            "reportName": "RPTA_WEB_MARGIN_DAILYTRADE", "columns": "ALL", "sortColumns": "STATISTICS_DATE",
            "sortTypes": -1, "pageSize": 10, "pageNumber": 1}, ttl=3600, stale=True)
        rows = (r["data"].get("result") or {}).get("data") or []
        result = []
        for row in rows:
            if number(row.get("FIN_BALANCE")) is not None:
                result.append({"date": date_text(row["STATISTICS_DATE"]),
                               "financing_balance": number(row["FIN_BALANCE"]) * 1e8,
                               "securities_lending_balance": number(row.get("LOAN_BALANCE")) * 1e8 if number(row.get("LOAN_BALANCE")) is not None else None})
        if not result:
            raise AppError("source_format", "融资余额汇总暂不可得", status=503)
        return {"rows": result, "unit": "元（源单位亿元）", "definition": "两融账户统计原发布口径，日频",
                **meta(r, result[0]["date"])}

    def limit_pool(self, day, which):
        route = {"up": "getTopicZTPool", "broken": "getTopicZBPool", "down": "getTopicDTPool"}[which]
        r = self.http.data("https://push2ex.eastmoney.com/" + route, params={
            "ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt", "Pageindex": 0,
            "pagesize": 10000, "sort": "fbt:asc" if which != "down" else "fund:asc",
            "date": day.replace("-", "")}, referer="https://quote.eastmoney.com/")
        d = r["data"].get("data")
        if not isinstance(d, dict) or not isinstance(d.get("pool"), list):
            raise AppError("source_format", "涨跌停股池未返回所需日期数据", {"day": day, "kind": which}, 503)
        rows = [{"code": str(x.get("c")), "name": x.get("n", ""),
                 "asset_id": ("sh" if x.get("m") == 1 else "sz") + str(x.get("c"))} for x in d["pool"]]
        total = int(d.get("tc", len(rows)))
        return {"rows": [x for x in rows if eligible(x)], "complete": len(rows) == total,
                "total_reported": total, "definition": "提供方涨停/炸板池排除部分连续一字新股；非完整交易所涨停统计",
                **meta(r, date_text(d.get("qdate", day)))}

    def etf_shares(self, observations, day):
        wanted = {x["asset_id"][2:]: x for x in observations if x["asset_id"].startswith("sh")}
        result, errors, sources = {}, [], []
        if wanted:
            base_day = datetime.strptime(day, "%Y-%m-%d")
            found_days = 0
            for delta in range(8):
                d = (base_day - timedelta(days=delta)).strftime("%Y-%m-%d")
                try:
                    r = self.http.data("https://query.sse.com.cn/commonQuery.do", params={
                        "isPagination": "true", "pageHelp.pageSize": 10000, "pageHelp.pageNo": 1,
                        "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L", "STAT_DATE": d},
                        referer="https://www.sse.com.cn/", ttl=3600, stale=True)
                    rows = (r["data"].get("pageHelp") or {}).get("data") or r["data"].get("result") or []
                    found = False
                    for row in rows:
                        code = str(row.get("SEC_CODE", ""))
                        shares = number(row.get("TOT_VOL"))
                        date = date_text(row.get("STAT_DATE"))
                        if code in wanted and shares is not None and date:
                            asset_id = wanted[code]["asset_id"]
                            obj = result.setdefault(asset_id, {**wanted[code], "rows": []})
                            if date not in {x["date"] for x in obj["rows"]}:
                                obj["rows"].append({"date": date, "shares": shares * 10000})
                                found = True
                    sources.append(meta(r, d))
                    if found:
                        found_days += 1
                    if found_days >= 2:
                        break
                except AppError as exc:
                    errors.append(exc.as_dict())
                    break
        # SZSE reports provide current shares; do not infer a publication date from retrieval time.
        sz_wanted = {x["asset_id"][2:]: x for x in observations if x["asset_id"].startswith("sz")}
        if sz_wanted:
            try:
                r = self.http.data("https://fund.szse.cn/api/report/ShowReportJson", params={
                    "SHOWTYPE": "JSON", "CATALOGID": "1000_lf", "TABKEY": "tab1", "PAGENO": 1,
                    "PAGESIZE": 10000}, referer="https://fund.szse.cn/marketdata/fundslist/index.html", ttl=3600, stale=True)
                groups = r["data"] if isinstance(r["data"], list) else [r["data"]]
                for group in groups:
                    for row in group.get("data", []):
                        code = re.sub(r"<[^>]+>", "", str(row.get("jjdm", row.get("基金代码", ""))))
                        raw = row.get("dqgm", row.get("当前规模(份)"))
                        shares = number(re.sub(r"<[^>]+>", "", str(raw)))
                        if code in sz_wanted and shares is not None:
                            item = sz_wanted[code]
                            result[item["asset_id"]] = {**item, "rows": [{"date": None, "shares": shares}],
                                                       "limitation": "源未提供可核对的份额日期，暂不计算跨日变化"}
                sources.append(meta(r))
            except AppError as exc:
                errors.append(exc.as_dict())
        missing = [x["asset_id"] for x in observations if x["asset_id"] not in result]
        for row in result.values():
            row["rows"].sort(key=lambda x: x["date"] or "", reverse=True)
            row["unit"] = "份"
        return {"items": list(result.values()), "missing": missing, "sources": sources, "errors": errors,
                "definition": "配置的ETF观察篮子，仅用于份额观察；非自动交易映射、非全指数ETF总份额"}
