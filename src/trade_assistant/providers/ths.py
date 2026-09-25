import json
import re
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from ..util import AppError, CN, cn_number, date_text, number


class Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell = [], None, None
        self.link = None

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell, self.link = [], None
        elif tag == "a" and self.cell is not None:
            self.link = data.get("href", self.link)

    def handle_data(self, text):
        if self.cell is not None:
            self.cell.append(text)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append({"text": "".join(self.cell).strip(), "href": self.link})
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row, self.cell = None, None


def pages(text):
    match = re.search(r'page_info[^>]*>\s*\d+/(\d+)', text)
    return min(100, int(match.group(1))) if match else 1


def meta(response, asof=None):
    return {"source": response["source"], "fetched_at": response["fetched_at"],
            "asof": asof, "cache_stale": response.get("cache_stale", False)}


class Ths:
    def __init__(self, client):
        self.http = client
        self.referer = "https://q.10jqka.com.cn/"

    def catalog(self):
        try:
            r = self.http.get(self.referer + "thshy/", encoding="gb18030", ttl=86400,
                              referer=self.referer, stale=True)
            matches = re.findall(
                r'href=["\'](?:https?:)?//q\.10jqka\.com\.cn/thshy/detail/code/(\d+)/["\'][^>]*>(.*?)</a>',
                r["text"], re.S)
            items = {code: unescape(re.sub(r"<[^>]+>", "", name)).strip() for code, name in matches}
            if len(items) < 30:
                raise AppError("source_format", "同花顺行业目录不完整", status=503)
            return {"items": items, "status": "ok", **meta(r)}
        except AppError as exc:
            bundled = Path(__file__).parents[1] / "defaults" / "ths_industries.json"
            if not bundled.exists():
                raise
            data = json.loads(bundled.read_text(encoding="utf-8"))
            return {"items": data["items"], "status": "cached_catalog", "source": data["source"],
                    "asof": data["captured_at"], "fetched_at": data["captured_at"],
                    "cache_stale": True, "reason": exc.message}

    def summary(self):
        first = self.http.get(self.referer + "thshy/", encoding="gb18030", referer=self.referer, stale=True)
        responses, errors = [first], []
        for page in range(2, pages(first["text"]) + 1):
            try:
                responses.append(self.http.get(
                    self.referer + "thshy/index/field/199112/order/desc/page/%s/" % page,
                    encoding="gb18030", referer=self.referer, stale=True))
            except AppError as exc:
                errors.append(exc.as_dict())
        result = {}
        for response in responses:
            parser = Tables()
            parser.feed(response["text"])
            for cells in parser.rows:
                if len(cells) < 12:
                    continue
                match = re.search(r"/thshy/detail/code/(\d+)", cells[1].get("href") or "")
                if not match:
                    continue
                code = match.group(1)
                result[code] = {
                    "name": cells[1]["text"], "change_pct": number(cells[2]["text"]),
                    "volume": cn_number(cells[3]["text"], 1e6),
                    "amount": cn_number(cells[4]["text"], 1e8),
                    "net_flow": cn_number(cells[5]["text"], 1e8),
                    "advancing": number(cells[6]["text"]), "declining": number(cells[7]["text"]),
                    "flow_definition": "同花顺行业一览表净流入，原发布口径；页面未单独提供源时间",
                    **meta(response),
                }
        return {"items": result, "errors": errors, "pages": len(responses)}

    def today(self, code):
        try:
            return self._today(code)
        except AppError as exc:
            r = self.http.data("https://d.10jqka.com.cn/v6/line/bk_%s/01/last.js" % code,
                               referer=self.referer, ttl=900, stale=True)
            rows = {}
            self._bars(r["data"].get("data", ""), rows)
            if not rows:
                raise exc
            bar = rows[max(rows)]
            return {"asset_id": "ths:" + code, "name": r["data"].get("name", code),
                    **{k: bar[k] for k in ("open", "high", "low", "close", "volume", "amount")},
                    "volume_unit": "股（提供方行业汇总）", "amount_unit": "元", "precision": "date",
                    "fallback": "当日接口不可用，读取同花顺最近日线；保留该日日期，不冒充盘中值",
                    **meta(r, bar["date"])}

    def _today(self, code):
        r = self.http.data("https://d.10jqka.com.cn/v6/line/bk_%s/01/today.js" % code,
                           referer=self.referer)
        obj = r["data"].get("bk_" + code)
        if not isinstance(obj, dict) or not date_text(obj.get("1")):
            raise AppError("source_format", "同花顺行业当日数据格式变化", {"code": code}, 503)
        return {"asset_id": "ths:" + code, "name": obj.get("name", code),
                "open": number(obj.get("7")), "high": number(obj.get("8")),
                "low": number(obj.get("9")), "close": number(obj.get("11")),
                "volume": number(obj.get("13")), "amount": number(obj.get("19")),
                "volume_unit": "股（提供方行业汇总）", "amount_unit": "元",
                "precision": "date", **meta(r, date_text(obj.get("1")))}

    def history(self, code, count=360, quote=None):
        rows, sources, errors = {}, [], []
        year = datetime.now(CN).year
        for y in range(year, year - 3, -1):
            try:
                r = self.http.data("https://d.10jqka.com.cn/v4/line/bk_%s/01/%s.js" % (code, y),
                                   referer=self.referer, ttl=3600 if y == year else 86400,
                                   stale=True)
                sources.append(meta(r))
                self._bars(r["data"].get("data", ""), rows)
            except AppError as exc:
                errors.append(exc.as_dict())
            if len(rows) >= count:
                break
        if len(rows) < 120:
            try:
                r = self.http.data("https://d.10jqka.com.cn/v6/line/bk_%s/01/last.js" % code,
                                   referer=self.referer, ttl=3600, stale=True)
                sources.append(meta(r))
                self._bars(r["data"].get("data", ""), rows)
            except AppError as exc:
                errors.append(exc.as_dict())
        if quote and quote.get("asof") and all(quote.get(k) is not None for k in ("open", "high", "low", "close", "volume")):
            d = quote["asof"][:10]
            rows[d] = {"date": d, **{k: quote.get(k) for k in ("open", "high", "low", "close", "volume", "amount")}}
        bars = [rows[d] for d in sorted(rows)][-count:]
        if not bars:
            raise AppError("source_unavailable", "同花顺行业历史暂不可得", {"code": code, "attempts": errors}, 503)
        return {"bars": bars, "source": "同花顺行业指数", "sources": sources,
                "asof": bars[-1]["date"], "adjustment": "同花顺行业指数原序列",
                "volume_unit": "股（提供方行业汇总）", "amount_unit": "元", "errors": errors}

    @staticmethod
    def _bars(text, rows):
        for item in str(text).split(";"):
            fields = item.split(",")
            if len(fields) < 7:
                continue
            d = date_text(fields[0])
            values = [number(x) for x in fields[1:7]]
            if d and all(x is not None for x in values[:5]) and min(values[:4]) > 0:
                rows[d] = dict(zip(("open", "high", "low", "close", "volume", "amount"), values), date=d)

    def members(self, code):
        first = self.http.get(self.referer + "thshy/detail/code/%s/" % code,
                              encoding="gb18030", referer=self.referer, ttl=86400, stale=True)
        sources, codes, errors = [meta(first)], set(), []
        total_pages = pages(first["text"])
        texts = [first["text"]]
        for page in range(2, total_pages + 1):
            try:
                r = self.http.get(self.referer + "thshy/detail/field/199112/order/desc/page/%s/code/%s/" % (page, code),
                                  encoding="gb18030", referer=self.referer, ttl=86400, stale=True)
                texts.append(r["text"])
                sources.append(meta(r))
            except AppError as exc:
                errors.append(exc.as_dict())
        page_sets = []
        for text in texts:
            parser = Tables()
            parser.feed(text)
            page_codes = set()
            for row in parser.rows:
                for cell in row[:4]:
                    match = re.search(r"stockpage\.10jqka\.com\.cn/(\d{6})", cell.get("href") or "")
                    if match:
                        page_codes.add(match.group(1))
            page_sets.append(page_codes)
            codes.update(page_codes)
        no_repeated_pages = len({tuple(sorted(x)) for x in page_sets if x}) == total_pages
        return {"codes": sorted(codes), "complete": not errors and bool(codes) and no_repeated_pages,
                "sources": sources, "errors": errors, "pages": total_pages,
                "definition": "同花顺行业成份公开页面，保存获取时点"}
