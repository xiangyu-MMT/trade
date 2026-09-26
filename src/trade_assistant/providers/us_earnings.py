"""Published EPS and net margins, keeping periods, vintages and forecasts distinct."""
import calendar
import hashlib
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from html import unescape
from urllib.parse import urljoin, urlsplit

from ..dependencies import load
from ..util import AppError, number, now, write_json
from .us_market import metadata

SHILLER = "https://shillerdata.com/"
FACTSET = "https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/Earnings%20Insight/"
PARSE_VERSION = "earnings-2"
MARGIN_DEF = "FactSet发布的标普500季度净利润率历史回顾值；保留该提供方盈利口径，不等同于Shiller EPS或经营利润率"
EPS_DEF = "Shiller Data的名义E列，S&P四季度合计EPS；仅取季度末月份，排除月内插值，不使用通胀调整后的Real Earnings"


def quarter_end(year, quarter):
    month = quarter * 3
    return date(year, month, calendar.monthrange(year, month)[1]).isoformat()


def quarter_shift(year, quarter, offset):
    y, q = divmod(year * 4 + quarter - 1 + offset, 4)
    return y, q + 1


class USEarnings:
    def __init__(self, client):
        self.http = client
        self.coverage = []

    def collect(self):
        result = {}
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [("SP500_EPS", pool.submit(self.shiller)), ("SP500_NET_MARGIN", pool.submit(self.factset))]
            for symbol, future in jobs:
                try:
                    item = future.result()
                    result[symbol] = item
                    self.coverage.append({"group": item["name"], "status": "partial" if item.get("warnings") else "ok",
                                          "detail": "%s条已发布观测，截至%s；%s" % (len(item["rows"]), item["asof"], item["period"]),
                                          "warnings": item.get("warnings", []), "source": item["source"]})
                except (AppError, ValueError, KeyError, TypeError) as exc:
                    self.coverage.append({"group": symbol, "status": "missing", "detail": str(exc)})
        return result

    def shiller(self):
        page = self.http.get(SHILLER, ttl=86400, stale=True, user_agent="stdlib")
        matches = re.findall(r'href=["\']([^"\']*/ie_data\.xls(?:\?[^"\']*)?)["\']', page["text"], re.I)
        urls = [urljoin(SHILLER, unescape(x)) for x in matches]
        url = next((x for x in urls if urlsplit(x).scheme == "https" and urlsplit(x).hostname in ("img1.wsimg.com", "shillerdata.com", "www.shillerdata.com")), None)
        if not url:
            raise AppError("earnings_source", "Shiller当前公开下载链接未识别")
        response = self.http.get(url, encoding=None, ttl=86400, stale=True, user_agent="stdlib")
        try:
            workbook = load("xlrd").open_workbook(file_contents=response["bytes"], on_demand=True)
            sheet = workbook.sheet_by_name("Data")
            header_index = next(i for i in range(min(20, sheet.nrows)) if "Date" in sheet.row_values(i) and "E" in sheet.row_values(i) and "Fraction" in sheet.row_values(i))
            header = sheet.row_values(header_index)
            date_col, eps_col, fraction_col = (header.index(k) for k in ("Date", "E", "Fraction"))
            rows = []
            for i in range(header_index + 1, sheet.nrows):
                raw_date, value, fraction = (number(sheet.cell_value(i, col)) for col in (date_col, eps_col, fraction_col))
                if raw_date is None or value is None or fraction is None:
                    continue
                year = int(fraction)
                month = int((fraction - year) * 12 + .5 + 1e-6)
                # Numeric 2025.1 is October, not January; cross-check both date columns.
                if month not in (3, 6, 9, 12) or int(raw_date) != year or int(round((raw_date-year)*100)) != month:
                    continue
                observed = quarter_end(year, month // 3)
                if year < 2016 or observed > date.today().isoformat():
                    continue
                rows.append({"date": observed, "value": value, "unit": "美元/指数份额", "value_type": "actual", "sample": "标普500（Shiller/S&P四季度合计）", "region": "美国",
                             "period": "TTM", "definition": EPS_DEF, "published_at": None, "source": url, "fetched_at": response["fetched_at"],
                             "revision_note": "来源当前文件版本，未逐季度提供发布日期；历史可能修订"})
            workbook.release_resources()
        except AppError:
            raise
        except Exception as exc:
            raise AppError("earnings_format", "Shiller EPS表解析失败", {"reason": str(exc)})
        rows.sort(key=lambda x: x["date"])
        if not rows:
            raise AppError("earnings_missing", "Shiller表没有有效季度末名义TTM EPS")
        return {"symbol": "SP500_EPS", "name": "标普500 EPS", "unit": "美元/指数份额", "frequency": "季度末", "period": "TTM · 四季度合计",
                "rows": rows, "asof": rows[-1]["date"], "value": rows[-1]["value"], "definition": EPS_DEF, "published_at": None,
                "revision_note": "来源未逐季度提供发布日期；保留文件来源与本次抓取时间", "source_page": SHILLER, **metadata(response),
                "warnings": ["使用来源失败后的缓存"] if response.get("cache_stale") or page.get("cache_stale") else []}

    def report(self, release):
        url = FACTSET + "EarningsInsight_" + release.strftime("%m%d%y") + ".pdf"
        response = self.http.get(url, encoding=None, ttl=86400, stale=True, user_agent="stdlib")
        raw = response["bytes"]
        if not raw.startswith(b"%PDF"):
            raise AppError("earnings_format", "FactSet返回的内容不是PDF")
        key = hashlib.sha256(PARSE_VERSION.encode() + raw).hexdigest()
        cache = self.http.cache / ("earnings-parsed-" + key + ".json")
        try:
            parsed = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            parsed = self.parse_report(raw, release)
            write_json(cache, parsed)
        if parsed.get("published_at") != release.isoformat():
            raise AppError("earnings_date", "报告封面日期与请求日期不符")
        for row in parsed["rows"] + parsed["forecasts"]:
            row.update(source=url, fetched_at=response["fetched_at"])
        return {**parsed, **metadata(response)}

    @staticmethod
    def parse_report(raw, release):
        try:
            reader = load("pypdf").PdfReader(io.BytesIO(raw))
            if len(reader.pages) > 80:
                raise ValueError("公开报告页数异常")
            first = " ".join(reader.pages[0].extract_text().split())
            dates = re.findall(r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}", first)
            if not dates or datetime.strptime(dates[0], "%B %d, %Y").date() != release:
                raise ValueError("无法核实报告封面日期")
            rows, forecasts = [], []
            numeric = r"([0-9]+(?:\s*[0-9]+)?(?:\s*\.\s*[0-9]+)?)\s*%"
            for i, page in enumerate(reader.pages[:30]):
                content = page.get_contents()
                if content is not None and len(content.get_data()) > 4000000:
                    continue
                text = " ".join(page.extract_text().split())
                pattern = r"The (estimated|blended) net profit margin for the S\s*&\s*P 500 for Q\s*([1-4])\s*(20\d{2}) is\s*" + numeric
                for match in re.finditer(pattern, text, re.I):
                    kind, quarter, year, value = match.groups()
                    year, quarter = int(year), int(quarter)
                    common = {"unit": "%", "sample": "标普500（FactSet季度口径）", "region": "美国", "period": "季度", "definition": MARGIN_DEF,
                              "published_at": release.isoformat(), "source_page": i + 1, "revision_note": "该周报引用的历史季度值；以较新报告修订为准"}
                    current = number(re.sub(r"\s", "", value))
                    if current is None or not -100 <= current <= 100:
                        continue
                    forecasts.append({**common, "date": quarter_end(year, quarter), "value": current, "value_type": "estimate" if kind.lower() == "estimated" else "mixed",
                                      "definition": "FactSet当前季度净利润率预估/混合值，单独观察，不并入历史实际曲线", "revision_note": "以该报告发布日期为准的当期预估"})
                    # Parse only the same paragraph's explicit historical comparisons.
                    context = text[match.end():match.end() + 850].split("At the sector level")[0]
                    patterns = ((r"previous quarter[’']s (?:net profit )?margin of\s*" + numeric, -1, "previous_quarter"),
                                (r"year[- ]ago (?:net profit )?margin of\s*" + numeric, -4, "year_ago_quarter"))
                    for rule, offset, basis in patterns:
                        found = re.search(rule, context, re.I)
                        if not found:
                            continue
                        value = number(re.sub(r"\s", "", found.group(1)))
                        observed = quarter_end(*quarter_shift(year, quarter, offset))
                        if value is not None and -100 <= value <= 100 and observed < release.isoformat():
                            rows.append({**common, "date": observed, "value": value, "value_type": "actual", "reported_basis": basis})
            if not rows:
                raise ValueError("正文没有可核实的季度净利润率历史比较值")
            unique = {}
            for row in rows:
                key = (row["date"], row["published_at"])
                if key in unique and unique[key]["value"] != row["value"]:
                    raise ValueError("同份报告中的同季度净利润率冲突")
                unique[key] = row
            return {"published_at": release.isoformat(), "rows": list(unique.values()), "forecasts": forecasts}
        except AppError:
            raise
        except Exception as exc:
            raise AppError("earnings_format", "FactSet季度净利润率解析失败", {"reason": str(exc)})

    def factset(self):
        today = date.today()
        current_quarter = (today.month - 1) // 3 + 1
        targets = []
        for offset in range(5):
            year, quarter = quarter_shift(today.year, current_quarter, -offset)
            end = min(today, date.fromisoformat(quarter_end(year, quarter)))
            targets.append(end - timedelta(days=(end.weekday()-4) % 7))
        def read(target):
            errors = []
            for weeks in range(3):
                day = target - timedelta(weeks=weeks)
                try:
                    return self.report(day), errors
                except AppError as exc:
                    errors.append({"date": day.isoformat(), "message": exc.message, "details": exc.details})
            return None, errors
        reports, errors = [], []
        with ThreadPoolExecutor(max_workers=3) as pool:
            for report, failures in pool.map(read, targets):
                errors.extend(failures)
                if report:
                    reports.append(report)
        if not reports:
            raise AppError("earnings_missing", "FactSet已尝试最近及历史周报，仍未取得有效净利润率", {"attempts": errors})
        vintages = sorted((x for report in reports for x in report["rows"]), key=lambda x: (x["date"], x["published_at"]))
        latest = {}
        for row in vintages:
            latest[row["date"]] = row
        rows = [latest[d] for d in sorted(latest)]
        newest = max(reports, key=lambda x: x["published_at"])
        warnings = []
        if len(reports) < len(targets):
            warnings.append("部分历史周报不可用；仅绘制实际取得季度")
        if any(x.get("cache_stale") for x in reports):
            warnings.append("部分周报使用历史缓存")
        return {"symbol": "SP500_NET_MARGIN", "name": "标普500净利润率", "unit": "%", "frequency": "季度", "period": "单季度 · FactSet发布口径",
                "rows": rows, "vintages": vintages, "forecasts": newest["forecasts"], "value": rows[-1]["value"], "asof": rows[-1]["date"],
                "definition": MARGIN_DEF, "published_at": newest["published_at"], "source": newest["source"], "fetched_at": newest["fetched_at"],
                "revision_note": "历史回顾值与当前季度预估分开；原发布版本逐条保留", "warnings": warnings, "attempts": errors}
