import csv
import io
import re
from datetime import datetime, timedelta

from ..util import AppError, CN, epoch_time, number
from .ths import Tables, meta


class Macro:
    def __init__(self, client):
        self.http = client

    def yahoo(self, item):
        r = self.http.data("https://query1.finance.yahoo.com/v8/finance/chart/" + item["symbol"],
                           params={"range": "6mo", "interval": "1d"}, ttl=900, stale=True)
        results = (r["data"].get("chart") or {}).get("result") or []
        if not results:
            raise AppError("source_format", "宏观观察序列暂不可得", item, 503)
        obj = results[0]
        q = (obj.get("indicators", {}).get("quote") or [{}])[0]
        closes = q.get("close") or []
        rows = []
        for i, timestamp in enumerate(obj.get("timestamp") or []):
            close = number(closes[i]) if i < len(closes) else None
            if close is not None:
                rows.append({"time": epoch_time(timestamp), "value": close})
        info = obj.get("meta") or {}
        if not rows:
            raise AppError("source_format", "宏观序列没有有效值", item, 503)
        return {**item, "rows": rows, "provider_name": info.get("shortName", item["symbol"]),
                "currency": info.get("currency"), "value": rows[-1]["value"],
                "definition": "配置指定的市场报价代理；期货序列含换月影响，不是现货或政策利率",
                **meta(r, epoch_time(info.get("regularMarketTime")) or rows[-1]["time"])}

    def tips(self):
        try:
            return self._fred_tips()
        except AppError:
            return self._fed_tips()

    def _fred_tips(self):
        start = (datetime.now(CN) - timedelta(days=180)).strftime("%Y-%m-%d")
        r = self.http.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": "DFII10", "cosd": start},
                          ttl=3600, stale=True)
        rows = []
        for row in csv.DictReader(io.StringIO(r["text"])):
            value = number(row.get("DFII10"))
            date = row.get("observation_date", row.get("DATE"))
            if date and value is not None:
                rows.append({"time": date, "value": value})
        if not rows:
            raise AppError("source_format", "FRED 10年TIPS实际收益率暂不可得", status=503)
        return {"name": "美国10年TIPS实际收益率", "symbol": "DFII10", "unit": "%", "rows": rows,
                "value": rows[-1]["value"], "definition": "FRED 日频发布序列，非盘中实时值",
                **meta(r, rows[-1]["time"])}

    def _fed_tips(self):
        r = self.http.get("https://www.federalreserve.gov/releases/h15/", ttl=3600, stale=True)
        parser = Tables()
        parser.feed(r["text"])
        dates, target, inflation = [], None, False
        for row in parser.rows:
            cells = [x["text"] for x in row]
            if cells and cells[0] == "Instruments":
                for text in cells[1:]:
                    try:
                        dates.append(datetime.strptime(re.sub(r"\s+", "", text), "%Y%b%d").strftime("%Y-%m-%d"))
                    except ValueError:
                        dates.append(None)
            if cells and "Inflation indexed" in cells[0]:
                inflation = True
            if inflation and cells and cells[0] == "10-year":
                target = cells[1:]
                break
        rows = [{"time": d, "value": number(v)} for d, v in zip(dates, target or []) if d and number(v) is not None]
        if not rows:
            raise AppError("source_format", "美联储H.15实际收益率表格暂不可解析", status=503)
        return {"name": "美国10年TIPS实际收益率", "symbol": "DFII10", "unit": "%", "rows": rows,
                "value": rows[-1]["value"], "definition": "美联储H.15 Inflation indexed 10-year 日频发布；非盘中实时值",
                **meta(r, rows[-1]["time"])}
