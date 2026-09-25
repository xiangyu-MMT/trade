"""CFFEX daily close/open-interest basket vs the same day's spot index close."""
import csv
import io
import re
import zipfile
from datetime import datetime, timedelta

from ..market_time import is_session_day
from ..util import AppError, number
from .ths import meta


class WeightedBasis:
    SERIES = {"IF": ("sh000300", "沪深300加权基差"), "IM": ("sh000852", "中证1000加权基差")}

    def __init__(self, http):
        self.http = http

    def history(self, asof, histories, count=25):
        dates, day = [], datetime.strptime(asof[:10], "%Y-%m-%d").date()
        while len(dates) < count:
            if is_session_day(day):
                dates.append(day.isoformat())
            day -= timedelta(days=1)
        grouped = {p: {} for p in self.SERIES}
        sources, errors = [], []
        for month in sorted({d[:7].replace("-", "") for d in dates}):
            try:
                # The exchange publishes this public archive over HTTP. No
                # credentials are attached; individual CSV members stay in memory.
                r = self.http.get("http://www.cffex.com.cn/sj/historysj/%s/zip/%s.zip" % (month, month),
                                  encoding=None, ttl=3600, stale=True, referer="http://www.cffex.com.cn/")
                sources.append(meta(r))
                with zipfile.ZipFile(io.BytesIO(r["bytes"])) as archive:
                    if len(archive.infolist()) > 1000:
                        raise ValueError("期货月档成员数量异常")
                    for date in dates:
                        if not date.replace("-", "").startswith(month):
                            continue
                        name = date.replace("-", "") + "_1.csv"
                        if name not in archive.namelist():
                            continue
                        info = archive.getinfo(name)
                        if info.file_size > 8 * 1024 * 1024:
                            raise ValueError("期货单日文件过大")
                        reader = csv.DictReader(io.StringIO(archive.read(name).decode("gb18030")))
                        if not {"合约代码", "今收盘", "持仓量"}.issubset(set(reader.fieldnames or [])):
                            raise ValueError("期货日文件字段不匹配")
                        for row in reader:
                            symbol = str(row.get("合约代码", "")).strip().upper()
                            if not re.fullmatch(r"(?:IF|IM)\d{4}", symbol):
                                continue
                            grouped[symbol[:2]].setdefault(date, []).append({
                                "contract": symbol, "close": number(row.get("今收盘")),
                                "open_interest": number(row.get("持仓量")), "source_file": name})
            except (AppError, OSError, ValueError, zipfile.BadZipFile, UnicodeError, csv.Error) as exc:
                errors.append({"month": month, "reason": str(exc)})
        result = {}
        for prefix, (asset_id, name) in self.SERIES.items():
            history = histories.get(asset_id) or {}
            spots = {b["date"]: b["close"] for b in history.get("bars", []) if number(b.get("close")) is not None}
            rows = []
            for date in sorted(dates):
                contracts = grouped[prefix].get(date, [])
                spot, value, total, why = spots.get(date), None, None, None
                if not contracts:
                    why = "无该日期完整合约记录"
                elif spot is None:
                    why = "缺少同日指数收盘"
                elif len({x["contract"] for x in contracts}) != len(contracts):
                    why = "合约记录重复"
                elif any(x["open_interest"] is None or x["open_interest"] < 0 or (x["open_interest"] > 0 and (x["close"] is None or x["close"] <= 0)) for x in contracts):
                    why = "合约持仓或收盘缺失，不以剩余合约代替完整篮子"
                else:
                    total = sum(x["open_interest"] for x in contracts)
                    if total > 0:
                        value = sum(x["open_interest"] * (x["close"] - spot) for x in contracts if x["open_interest"] > 0) / total
                        for x in contracts:
                            x["weight"] = x["open_interest"] / total
                    else:
                        why = "总持仓量为零"
                rows.append({"date": date, "value": value, "spot_close": spot, "open_interest": total,
                             "weighted_future_close": spot + value if value is not None else None,
                             "contracts": contracts, "missing": why})
            valid = [x for x in rows if x["value"] is not None]
            result[prefix] = {"name": name, "asset_id": asset_id, "rows": rows, "unit": "点",
                              "asof": valid[-1]["date"] if valid else None, "complete": len(valid) == len(rows),
                              "covered": len(valid), "expected": len(rows), "sources": sources,
                              "spot_source": history.get("source"), "errors": errors,
                              "definition": "全部在市同系列合约按持仓量加权：(期货同日收盘－指数同日收盘)；正数升水，负数贴水"}
        result["complete"] = all(result[p]["complete"] for p in self.SERIES)
        result["missing"] = [p for p in self.SERIES if not result[p]["complete"]]
        return result
