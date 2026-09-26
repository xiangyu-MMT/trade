"""Fitch's anonymously published US high-yield bond defaults, not loan forecasts."""
import calendar
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from html import unescape
from urllib.parse import urlsplit

from ..util import AppError, number
from .us_market import metadata

LISTING = "https://www.lsta.org/content/fitch-ratings-commentary-page/"
API = "https://api.fitchratings.com"
QUERY = "query RAC($slug: String!) { getResearchItem(slug: $slug) { title publishedDate reportType paragraphs { content header } marketing { contentAccessType { name slug } } } }"
SEEDS = [
    "corporate-finance/us-corporate-default-rates-stay-broadly-flat-in-july-volume-to-build-17-08-2026",
    "corporate-finance/us-corporate-high-yield-default-rate-reflects-dish-dbs-bankruptcy-as-ll-rate-declines-17-07-2026",
]
MONTHS = "January February March April May June July August September October November December".split()
DEFINITION = "Fitch美国高收益企业债市场TTM实际违约率，按公开评论原发布值；不代表全部美国企业债，不包含贷款或私募信用违约率"


def month_end(year, month, offset=0):
    year, month0 = divmod(year * 12 + month - 1 + offset, 12)
    month = month0 + 1
    return date(year, month, calendar.monthrange(year, month)[1]).isoformat()


class USCredit:
    def __init__(self, client):
        self.http = client

    def slugs(self):
        slugs = set(SEEDS)
        try:
            r = self.http.get(LISTING, ttl=21600, stale=True)
            for raw in re.findall(r'href=["\']([^"\']+)', r["text"]):
                url = urlsplit(unescape(raw))
                if url.hostname not in ("www.fitchratings.com", "fitchratings.com") or not url.path.startswith("/research/corporate-finance/"):
                    continue
                slug = url.path[len("/research/"):]
                if re.search(r"us-corporate-(?:high-yield-)?default", slug) and not any(x in slug for x in ("private-credit", "forecast")):
                    slugs.add(slug)
        except AppError:
            pass
        def stamp(slug):
            match = re.search(r"(\d{2})-(\d{2})-(\d{4})$", slug)
            return (match.group(3), match.group(2), match.group(1)) if match else ("0", "0", "0")
        return sorted(slugs, key=stamp, reverse=True)[:8]

    def article(self, slug):
        response = self.http.data(API, transport="curl", json_body={"operationName": "RAC", "query": QUERY, "variables": {"slug": slug}},
                                  extra_headers={"Origin": "https://www.fitchratings.com"}, referer="https://www.fitchratings.com/", ttl=21600, stale=True)
        obj = (response["data"].get("data") or {}).get("getResearchItem") or {}
        access = ((obj.get("marketing") or {}).get("contentAccessType") or {}).get("slug", "").lower()
        if access not in ("anonymous", "free", "public"):
            raise AppError("credit_access", "资料不是可匿名读取的公开评论，未采用")
        if obj.get("reportType") != "Non-Rating Action Commentary":
            raise AppError("credit_type", "来源不是已核实的公开评论类型")
        if not re.search(r"(?:U\.S\.|US)\s+Corporate", str(obj.get("title", "")), re.I):
            raise AppError("credit_scope", "评论标题不是美国企业信用范围，未采用")
        published = str(obj.get("publishedDate") or "")[:10]
        try:
            date.fromisoformat(published)
        except ValueError:
            raise AppError("credit_date", "实际违约资料未提供有效发布日期")
        if published > date.today().isoformat():
            raise AppError("credit_date", "违约资料发布日期晚于当前日期")
        source = "https://www.fitchratings.com/research/" + slug
        rows = []
        for paragraph in obj.get("paragraphs") or []:
            text = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]*>", " ", paragraph.get("content") or "")))
            # Public commentaries begin their actual observation with an explicit month/year.
            match = re.search(r"\bIn (" + "|".join(MONTHS) + r") (20\d{2}),", text)
            if not match:
                continue
            month, year = MONTHS.index(match.group(1)) + 1, int(match.group(2))
            observed = month_end(year, month)
            if observed >= published:
                continue
            actual_text = text[match.end():match.end() + 1000]
            actual_text = re.split(r"Fitch (?:expects|maintains|forecasts)|These moves", actual_text, flags=re.I)[0]
            rule = r"(?:\bHY\b|high[- ]yield(?:\s*\(HY\))?)\s+(?:bond\s+)?(?:(?:TTM|trailing\s+12\s+months?\s*\(TTM\))\s+)?(?:default\s+)?rate\s+(?:increased|declined|rose|fell|decreased|stood|was|remained)(?:\s+(?:sharply|slightly|unchanged|broadly|flat))?(?:\s+(?:to|at))?\s+(\d+(?:\.\d+)?)%\s*(?:from\s+(\d+(?:\.\d+)?)%)?"
            rate = re.search(rule, actual_text, re.I)
            if not rate:
                continue
            for offset, raw in ((0, rate.group(1)), (-1, rate.group(2))):
                value = number(raw)
                if value is None or not 0 <= value <= 100:
                    continue
                rows.append({"date": month_end(year, month, offset), "value": value, "unit": "%", "value_type": "actual", "period": "TTM / 月末",
                             "sample": "Fitch美国高收益企业债市场", "region": "美国市场", "definition": DEFINITION,
                             "published_at": published, "source": source, "fetched_at": response["fetched_at"],
                             "revision_note": "按该公开评论的本月值/前月回顾值；更新报告优先", "weighting": "本公开评论未列权重明细，保留Fitch原统计口径"})
        if not rows:
            raise AppError("credit_format", "公开评论未识别到明确的HY实际违约率，未以贷款或预测值填充", {"source": source})
        return {"rows": rows, "published_at": published, "article_source": source, **metadata(response)}

    def collect(self):
        records, errors = [], []
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = [(slug, pool.submit(self.article, slug)) for slug in self.slugs()]
            for slug, job in jobs:
                try:
                    records.append(job.result())
                except AppError as exc:
                    errors.append({"source": "https://www.fitchratings.com/research/" + slug, "error": exc.as_dict()})
        if not records:
            raise AppError("credit_missing", "未取得可解析的Fitch公开实际违约记录", {"attempts": errors})
        versions = sorted((row for record in records for row in record["rows"]), key=lambda x: (x["date"], x["published_at"]))
        latest = {}
        for row in versions:
            latest[row["date"]] = row
        rows = [latest[d] for d in sorted(latest)]
        last = rows[-1]
        return {"symbol": "US_DEFAULT_RATE", "name": "美国高收益企业债实际违约率", "unit": "%", "frequency": "月", "period": "TTM · Fitch高收益债样本",
                "rows": rows, "vintages": versions, "asof": last["date"], "value": last["value"], "published_at": last["published_at"],
                "source": last["source"], "fetched_at": max(x["fetched_at"] for x in records), "definition": DEFINITION,
                "revision_note": "只使用公开报道明确的实际值；历史未覆盖月份不补值", "attempts": errors}
