"""Official exchange A-share turnover reference, including ST; separate scope."""
import concurrent.futures
from datetime import datetime, timedelta

from .eastmoney import Eastmoney
from .ths import meta
from ..market_time import is_session_day
from ..util import AppError, number


class MarketVolume:
    def __init__(self, client):
        self.http = client

    def daily(self, date):
        sh = self.http.data("https://query.sse.com.cn/commonQuery.do", params={
            "sqlId": "COMMON_SSE_SJ_GPSJ_CJGK_MRGK_C", "PRODUCT_CODE": "01,02,03,11,17", "type": "inParams", "SEARCH_DATE": date},
            referer="https://www.sse.com.cn/", ttl=86400, stale=True)
        items = [x for x in sh["data"].get("result", []) if x.get("PRODUCT_CODE") in ("01", "03") and x.get("TRADE_DATE") == date.replace("-", "")]
        if len(items) != 2 or any(number(x.get("TRADE_AMT")) is None for x in items):
            raise AppError("market_history_missing", "沪市A股每日成交额未取得对应日期", status=503)
        sh_amount = sum(number(x["TRADE_AMT"]) for x in items) * 1e8
        sz = self.http.get("https://www.szse.cn/api/report/ShowReport", params={
            "SHOWTYPE": "xlsx", "CATALOGID": "1803_sczm", "TABKEY": "tab1", "txtQueryDate": date},
            encoding=None, referer="https://www.szse.cn/", ttl=86400, stale=True)
        rows = Eastmoney.xlsx_rows(sz["bytes"])
        if not rows or "成交金额(元)" not in rows[0]:
            raise AppError("market_history_unit", "深圳成交额文件单位或结构无法核实", status=503)
        index = rows[0].index("成交金额(元)")
        selected = [row for row in rows[1:] if row and row[0].strip() in ("主板A股", "创业板A股")]
        if len(selected) != 2 or any(len(x) <= index or number(x[index]) is None for x in selected):
            raise AppError("market_history_missing", "深圳A股每日成交额未齐", status=503)
        sz_amount = sum(number(x[index]) for x in selected)
        return {"date": date, "amount": sh_amount + sz_amount, "sh_amount": sh_amount, "sz_amount": sz_amount,
                "sources": [meta(sh, date), meta(sz, date)], "date_basis": "上海源日期校核；深圳按交易所日期参数查询，文件未单列日期"}

    def history(self, asof, count=25):
        date = datetime.strptime(asof[:10], "%Y-%m-%d").date()
        dates = []
        while len(dates) < count:
            if is_session_day(date):
                dates.append(date.isoformat())
            date -= timedelta(days=1)
        rows, errors = [], []
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            tasks = {pool.submit(self.daily, date): date for date in dates}
            for future in concurrent.futures.as_completed(tasks):
                try:
                    rows.append(future.result())
                except (AppError, ValueError, KeyError) as exc:
                    errors.append({"date": tasks[future], "reason": str(exc)})
        # A server returning one identical workbook for every date cannot provide
        # a trustworthy daily series. Do not turn its repeated values into history.
        if len(rows) >= 3 and len({x["sz_amount"] for x in rows}) == 1:
            errors.append({"reason": "深圳不同日期返回相同金额，历史日期有效性不足"})
            rows = []
        return {"rows": sorted(rows, key=lambda x: x["date"]), "expected": len(dates), "complete": len(rows) == len(dates),
                "errors": errors, "unit": "元", "scope": "沪深A股（含ST），排除B股/北交所/基金/回购；交易所原发布范围",
                "scope_id": "sse_szse_a_including_st", "source": "上交所每日股票情况 + 深交所证券类别统计",
                "limitations": ["此历史含ST，不与沪深非ST快照拼接", "深圳日期以查询参数为依据，下载表未单列日期"]}
