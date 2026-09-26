"""Mixed-frequency macro observations, with explicit unavailable targets."""
import csv
import io
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

from .ths import Tables
from .macro import Macro
from .us_market import USMarket, metadata
from ..util import AppError, number, now

DEFINITIONS = {
    "WALCL": ("联储总资产", "百万美元", "周三", "H.4.1总资产，周三时点，非周均值"),
    "WDTGAL": ("财政部一般账户 TGA", "百万美元", "周三", "联储负债端TGA，周三时点"),
    "RRPONTSYD": ("隔夜逆回购 ON RRP", "十亿美元", "日", "纽约联储隔夜逆回购获配金额"),
    "SOFR": ("SOFR资金利率", "%", "日", "有担保隔夜融资利率，实际发布，非实时"),
    "DGS10": ("10年美债名义收益率", "%", "日", "10年恒定期限国债市场收益率，非票息"),
    "DFII10": ("10年TIPS实际收益率", "%", "日", "10年通胀保值国债恒定期限实际收益率"),
    "T10Y2Y": ("10年－2年期限利差", "百分点", "日", "同日10年减2年名义收益率"),
    "BAMLH0A0HYM2": ("高收益债 OAS", "%", "日", "ICE BofA US High Yield期权调整利差；不是实际违约率；1%=100基点"),
    "GDPC1": ("美国实际GDP", "十亿美元（2017不变价）", "季度", "BEA实际GDP季调年率水平，当前修订版本"),
}


def series(symbol, rows, response, definition=None):
    name, unit, frequency, meaning = DEFINITIONS[symbol]
    rows = sorted({x["date"]: x for x in rows if number(x.get("value")) is not None}.values(), key=lambda x: x["date"])
    return {"symbol": symbol, "name": name, "unit": unit, "frequency": frequency, "definition": definition or meaning,
            "rows": rows, "asof": rows[-1]["date"] if rows else None, "value": rows[-1]["value"] if rows else None,
            "published_at": None, "revision_note": "提供方当前发布版本；历史可能修订，非历史时点可得数据库", **metadata(response)}


class USMacro:
    def __init__(self, client):
        self.http = client
        self.coverage = []

    def attempt(self, label, function):
        try:
            value = function()
            self.coverage.append({"group": label, "status": "ok", "detail": "已读取真实发布资料；观测日和来源见各序列"})
            return value
        except (AppError, ValueError, KeyError, TypeError) as exc:
            self.coverage.append({"group": label, "status": "missing", "detail": str(exc), "error": exc.as_dict() if isinstance(exc, AppError) else None})
            return None

    def fred(self):
        result = {}
        def read(symbol):
            r = self.http.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": symbol}, ttl=3600, stale=True, user_agent="stdlib")
            rows = list(csv.DictReader(io.StringIO(r["text"])))
            values = [{"date": x.get("observation_date", x.get("DATE")), "value": number(x.get(symbol))} for x in rows if x.get("observation_date", x.get("DATE", "")) >= ("2018-01-01" if symbol == "GDPC1" else "2023-01-01") and number(x.get(symbol)) is not None]
            if not values:
                raise AppError("source_format", "FRED单序列CSV未取得有效值：" + symbol)
            return series(symbol, values, r)
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = [(s, pool.submit(read, s)) for s in DEFINITIONS]
            for symbol, job in jobs:
                try:
                    result[symbol] = job.result()
                except (AppError, ValueError, TypeError) as exc:
                    self.coverage.append({"group": "FRED " + symbol, "status": "missing", "detail": str(exc)})
        if not result:
            raise AppError("source_format", "FRED公共CSV未返回有效指标")
        return result

    def newyork(self, symbol):
        if symbol == "SOFR":
            r = self.http.data("https://markets.newyorkfed.org/api/rates/secured/sofr/search.json", params={"startDate": "2024-01-01"}, ttl=3600, stale=True)
            rows = [{"date": x["effectiveDate"], "value": number(x.get("percentRate")), "revision_note": x.get("revisionIndicator")} for x in r["data"].get("refRates", [])]
        else:
            r = self.http.data("https://markets.newyorkfed.org/api/rp/reverserepo/propositions/search.json", params={"startDate": "2024-01-01"}, ttl=3600, stale=True)
            rows = [{"date": x["operationDate"], "value": number(x["totalAmtAccepted"]) / 1e9} for x in (r["data"].get("repo") or {}).get("operations", []) if number(x.get("totalAmtAccepted")) is not None]
        if not rows:
            raise AppError("source_format", "纽约联储未返回观测值")
        return series(symbol, rows, r)

    def h41_page(self, url):
        r = self.http.get(url, ttl=86400, stale=True)
        table = Tables(); table.feed(r["text"])
        day, assets, tga = None, None, None
        for row in table.rows:
            cells = [re.sub(r"\s+", " ", x["text"]) for x in row]
            if cells and cells[0] == "Assets, liabilities, and capital" and "Eliminations from consolidation" in cells:
                m = re.search(r"Wednesday\s*([A-Za-z]+ \d+, \d{4})", " ".join(cells))
                if m:
                    day = datetime.strptime(m.group(1), "%b %d, %Y").date().isoformat()
            if len(cells) == 5 and cells[0] == "Total assets" and day:
                assets = number(cells[2])
            if len(cells) == 5 and cells[0] == "U.S. Treasury, General Account" and not cells[1] and day:
                tga = number(cells[2])
        if day is None or assets is None or tga is None:
            raise AppError("source_format", "H.4.1合并表周三列解析失败")
        return {"date": day, "WALCL": assets, "WDTGAL": tga, **metadata(r)}

    def h41(self):
        latest = self.h41_page("https://www.federalreserve.gov/releases/h41/current/")
        observation = date.fromisoformat(latest["date"])
        urls = ["https://www.federalreserve.gov/releases/h41/%s/" % (observation - timedelta(weeks=i) + timedelta(days=1)).strftime("%Y%m%d") for i in range(1, 13)]
        points = [latest]
        def read(url):
            try:
                return self.h41_page(url)
            except AppError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            points.extend(x for x in pool.map(read, urls) if x)
        result = {}
        for symbol in ("WALCL", "WDTGAL"):
            result[symbol] = series(symbol, [{"date": p["date"], "value": p[symbol], "source": p["source"]} for p in points], latest)
            result[symbol]["published_at"] = (observation + timedelta(days=1)).isoformat()
            result[symbol]["history_note"] = "官方H.4.1已取得%s周；非日频值" % len(points)
        return result

    def h15(self):
        r = self.http.get("https://www.federalreserve.gov/datadownload/Output.aspx", params={"rel": "H15", "series": "bf17364827e38702b42a58cf8eaa3f78", "lastobs": 100, "from": "", "to": "",
                             "filetype": "csv", "label": "include", "layout": "seriescolumn", "type": "package"}, ttl=3600, stale=True)
        rows = list(csv.reader(io.StringIO(r["text"])))
        description = next((x for x in rows if x and x[0] == "Series Description"), [])
        columns = {}
        for i, text in enumerate(description):
            for symbol, words in (("DGS10", "10-year"), ("DGS2", "2-year")):
                if words in text and "constant maturity" in text and "inflation" not in text.lower():
                    columns[symbol] = i
        if set(columns) != {"DGS10", "DGS2"}:
            raise AppError("source_format", "H.15未识别2年和10年恒定期限序列")
        values = {symbol: [] for symbol in columns}
        for row in rows:
            if not row or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row[0]):
                continue
            for symbol, i in columns.items():
                if i < len(row) and number(row[i]) is not None:
                    values[symbol].append({"date": row[0], "value": number(row[i])})
        a = {x["date"]: x["value"] for x in values["DGS2"]}
        spread = [{"date": x["date"], "value": x["value"] - a[x["date"]]} for x in values["DGS10"] if x["date"] in a]
        if not spread:
            raise AppError("source_format", "H.15收益率没有共同日期")
        return {"DGS10": series("DGS10", values["DGS10"], r), "T10Y2Y": series("T10Y2Y", spread, r)}

    def collect(self, observations):
        output = self.attempt("FRED公共序列", self.fred) or {}
        # Independent official fallbacks; preserve their actual, often shorter histories.
        jobs = {}
        if not all(x in output for x in ("WALCL", "WDTGAL")):
            jobs["联储H.4.1"] = self.h41
        if not all(x in output for x in ("DGS10", "T10Y2Y")):
            jobs["联储H.15"] = self.h15
        for symbol in ("SOFR", "RRPONTSYD"):
            if symbol not in output:
                jobs[symbol] = lambda symbol=symbol: {symbol: self.newyork(symbol)}
        if "DFII10" not in output:
            def tips():
                value = Macro(self.http)._fed_tips()
                return {"DFII10": series("DFII10", [{"date": x["time"], "value": x["value"]} for x in value["rows"]], value)}
            jobs["联储TIPS"] = tips
        jobs["美元指数"] = lambda: {"DXY": self.dxy()}
        if "GDPC1" not in output:
            jobs["BEA实际GDP"] = lambda: {"GDPC1": self.bea()}
        if "BAMLH0A0HYM2" not in output:
            jobs["FRED高收益债OAS独立下载"] = lambda: {"BAMLH0A0HYM2": self.high_yield()}
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [(name, pool.submit(fn)) for name, fn in jobs.items()]
            for name, future in futures:
                try:
                    output.update(future.result())
                    self.coverage.append({"group": name, "status": "ok", "detail": "已取得免费替代资料，按源观测日展示"})
                except (AppError, ValueError, TypeError, KeyError) as exc:
                    self.coverage.append({"group": name, "status": "missing", "detail": str(exc)})
        # The public S&P workbook is an actual attempted source, not assumed accessible.
        for name, url in (("标普实际盈利资料", "https://www.spglobal.com/spdji/en/documents/additional-material/sp-500-eps-est.xlsx"),
                          ("企业实际违约资料", "https://www.spglobal.com/ratings/en/research/credit-market-research")):
            try:
                response = self.http.get(url, ttl=86400, stale=True, encoding=None)
                detail = "公开资料已访问，但未取得可验证的结构化实际序列；请从配置补充带来源、样本与发布日期的观测"
            except AppError as exc:
                detail = exc.message + "；补充资料入口：配置 us.observations"
            self.coverage.append({"group": name, "status": "missing", "detail": detail, "source": url})
        for symbol, name in (("US_DEFAULT_RATE", "美国企业实际违约率"), ("SP500_EPS", "标普500已报告EPS"), ("SP500_NET_MARGIN", "标普500净利润率")):
            points = [x for x in observations if x["symbol"] == symbol]
            if points:
                # Retain vintages, samples and actual/estimate flags. No silent merging.
                output[symbol] = {"symbol": symbol, "name": name, "unit": points[-1]["unit"], "frequency": "来源定义期间", "rows": sorted(points, key=lambda x: (x["date"], x["published_at"])),
                                  "asof": max(x["date"] for x in points), "definition": "结构化补充记录；逐条保留样本、实际/预测、发布版本", "source": "用户补充资料，各点附公开来源", "fetched_at": now(), "published_at": None}
        for symbol in list(DEFINITIONS) + ["US_DEFAULT_RATE", "SP500_EPS", "SP500_NET_MARGIN"]:
            if symbol not in output:
                name = DEFINITIONS.get(symbol, (symbol,))[0]
                self.coverage.append({"group": name, "status": "missing", "detail": "未取得可核实免费序列；保留缺口，不以代理或预测填充实际值"})
        if all(x in output for x in ("WALCL", "WDTGAL", "RRPONTSYD")):
            maps = [{x["date"]: x["value"] for x in output[s]["rows"]} for s in ("WALCL", "WDTGAL", "RRPONTSYD")]
            common = set(maps[0]) & set(maps[1]) & set(maps[2])
            points = [{"date": day, "value": maps[0][day] / 1000 - maps[1][day] / 1000 - maps[2][day],
                       "assets_bn": maps[0][day] / 1000, "tga_bn": maps[1][day] / 1000, "rrp_bn": maps[2][day]} for day in sorted(common) if date.fromisoformat(day).weekday() == 2]
            output["NET_LIQUIDITY"] = {"symbol": "NET_LIQUIDITY", "name": "流动性参考", "unit": "十亿美元", "frequency": "周三", "rows": points,
                "asof": points[-1]["date"] if points else None, "source": "WALCL/WDTGAL/RRPONTSYD原始发布分量", "fetched_at": now(), "published_at": None,
                "definition": "同周三 WALCL/1000−WDTGAL/1000−RRPONTSYD；非可投资现金", "component_sources": [output[x]["source"] for x in ("WALCL", "WDTGAL", "RRPONTSYD")]}
        if output.get("GDPC1"):
            original = output["GDPC1"]
            mapping = {x["date"]: x["value"] for x in original["rows"]}
            points = [{"date": d, "value": (v / mapping[str(int(d[:4])-1)+d[4:]] - 1) * 100} for d, v in sorted(mapping.items()) if str(int(d[:4])-1)+d[4:] in mapping and mapping[str(int(d[:4])-1)+d[4:]] > 0]
            output["GDP_YOY"] = {**original, "symbol": "GDP_YOY", "name": "实际GDP同比", "unit": "%", "rows": points, "definition": "实际GDP同季度上年同比；非环比折年率"}
        if output.get("SP500_EPS"):
            actual = [x for x in output["SP500_EPS"]["rows"] if x.get("value_type") == "actual"]
            groups = {}
            for row in actual:
                period = row.get("period", "")
                frequency = "TTM" if "TTM" in period.upper() or "12个月" in period else "季度" if "季度" in period or re.search(r"Q[1-4]", period, re.I) else None
                if frequency is None:
                    continue
                key = (row["sample"], row["unit"], row["definition"], frequency)
                point = date.fromisoformat(row["date"])
                q = (point.year, (point.month - 1) // 3 + 1)
                old = groups.setdefault(key, {}).get(q)
                if not old or row["published_at"] > old["published_at"]:
                    groups[key][q] = row
            derived = []
            for key, quarters in groups.items():
                for (year, quarter), row in quarters.items():
                    previous = quarters.get((year - 1, quarter))
                    if previous and previous["value"] > 0:
                        derived.append({**row, "value": (row["value"] / previous["value"] - 1) * 100, "unit": "%", "basis_date": previous["date"],
                                        "definition": "同样本、同定义、同期间类型的已报告EPS同比；基期EPS须正数", "component_sources": [row["source"], previous["source"]]})
            if derived:
                original = output["SP500_EPS"]
                output["SP500_EPS_YOY"] = {**original, "symbol": "SP500_EPS_YOY", "name": "标普500实际EPS同比", "unit": "%", "rows": sorted(derived, key=lambda x: (x["date"], x["published_at"])), "asof": max(x["date"] for x in derived),
                                          "definition": "实际已报告EPS同比；严格同样本、定义和期间类型，基期非正不生成百分比"}
        return {"series": list(output.values()), "coverage": self.coverage}

    def dxy(self):
        h = USMarket(self.http).history({"symbol": "DX-Y.NYB", "name": "美元指数", "kind": "macro"}, 360)
        return {"symbol": "DXY", "name": "美元指数 DXY", "unit": "点", "frequency": "日", "rows": [{"date": x["date"], "value": x["close"]} for x in h["bars"]],
                "asof": h["asof"], "source": h["source"], "fetched_at": h["fetched_at"], "published_at": None, "definition": "美元指数市场报价，非贸易加权广义美元指数"}

    def bea(self):
        from ..xlsx import sheet_rows
        r = self.http.get("https://apps.bea.gov/national/Release/XLS/Survey/Section1All_xls.xlsx", encoding=None, ttl=86400, stale=True)
        try:
            rows = sheet_rows(r["bytes"], "T10106-Q")
        except Exception as exc:
            raise AppError("source_format", "BEA公开工作簿不可解析", {"reason": str(exc)})
        header = next((x for x in rows if x.get("A") == "Line"), {})
        body = next((x for x in rows if x.get("C") == "A191RX" and "Gross domestic product" in x.get("B", "")), {})
        unit = next((x.get("A", "") for x in rows if "chained (2017) dollars" in x.get("A", "")), "")
        if "Millions" not in unit or not header or not body:
            raise AppError("source_format", "BEA表1.1.6的实际GDP或不变价单位未识别")
        points = []
        for column, quarter in header.items():
            m = re.fullmatch(r"(\d{4})Q([1-4])", quarter)
            value = number(body.get(column))
            if m and value is not None and int(m.group(1)) >= 2018:
                points.append({"date": "%s-%02d-01" % (m.group(1), (int(m.group(2))-1)*3+1), "value": value / 1000, "period": quarter})
        if not points:
            raise AppError("source_format", "BEA表未返回有效季度值")
        result = series("GDPC1", points, r, "BEA NIPA表1.1.6 A191RX：百万2017不变美元除1000转十亿美元，季调年率水平")
        published = next((re.search(r"Data published (.+)", x.get("A", "")) for x in rows if "Data published" in x.get("A", "")), None)
        if published:
            try:
                result["published_at"] = datetime.strptime(published.group(1), "%B %d, %Y").date().isoformat()
            except ValueError:
                pass
        return result

    def high_yield(self):
        r = self.http.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": "BAMLH0A0HYM2"}, ttl=3600, stale=True, user_agent="stdlib")
        rows = [{"date": x.get("observation_date", x.get("DATE")), "value": number(x.get("BAMLH0A0HYM2"))} for x in csv.DictReader(io.StringIO(r["text"])) if x.get("observation_date", x.get("DATE")) and number(x.get("BAMLH0A0HYM2")) is not None]
        if not rows:
            raise AppError("source_format", "FRED高收益债OAS独立CSV为空")
        return series("BAMLH0A0HYM2", rows[-800:], r)
