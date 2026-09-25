import concurrent.futures
from datetime import datetime

from .http_client import HttpClient
from .providers.eastmoney import Eastmoney, eligible
from .providers.macro import Macro
from .providers.market_volume import MarketVolume
from .volume_price import previous_day
from .providers.ths import Ths
from .util import AppError, CN, new_id, now


class Collector:
    def __init__(self, settings, progress=None):
        self.settings, self.config = settings, settings.load()
        net = self.config["network"]
        self.http = HttpClient(settings.home, net["timeout"], net["budget_seconds"])
        self.workers = net["workers"]
        self.ths, self.em, self.macro = Ths(self.http), Eastmoney(self.http, self.workers), Macro(self.http)
        self.progress = progress or (lambda stage, detail: None)
        self.gaps = []

    def safe(self, label, fn):
        try:
            return fn()
        except AppError as exc:
            self.gaps.append({"group": label, **exc.as_dict()})
            return None
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            self.gaps.append({"group": label, "code": "source_format", "message": str(exc)})
            return None

    def parallel(self, values, fn, label):
        result = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(fn, value): value for value in values}
            completed = 0
            for future in concurrent.futures.as_completed(futures):
                value = futures[future]
                result[value] = self.safe(label + ":" + str(value), future.result)
                completed += 1
                if completed % 15 == 0 or completed == len(values):
                    self.progress(label, "%s/%s" % (completed, len(values)))
        return result

    def collect(self):
        self.progress("取数", "读取同花顺行业目录")
        catalog = self.ths.catalog()
        industry_names = catalog["items"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as background:
            market_future = background.submit(self.em.market)
            summaries_future = background.submit(self.ths.summary)
            industry_quotes = self.parallel(list(industry_names), self.ths.today, "行业行情")
            market = self.safe("market", market_future.result) or {
                "stocks": [], "received": 0, "complete": False, "total_reported": None,
                "asof": None, "errors": [], "sources": []}
            summaries = self.safe("industry_flow", summaries_future.result) or {"items": {}, "errors": []}

        self.progress("成份口径", "核对同花顺成份与沪深非ST成交额")
        members = self.parallel(list(industry_names), self.ths.members, "行业成份")
        stocks_by_code = {s["code"]: s for s in market["stocks"]}
        industries = []
        for code, name in industry_names.items():
            quote = industry_quotes.get(code)
            summary = summaries["items"].get(code, {})
            member = members.get(code) or {"codes": [], "complete": False, "sources": [], "errors": []}
            allowed_codes = [c for c in member["codes"] if c.startswith(("00", "30", "60", "68"))]
            missing = [c for c in allowed_codes if c not in stocks_by_code]
            valid = [stocks_by_code[c] for c in allowed_codes if c in stocks_by_code and eligible(stocks_by_code[c])]
            filter_complete = member["complete"] and market["complete"] and not missing and bool(valid)
            if any(s["amount"] is None for s in valid):
                filter_complete = False
            q_dates = {s["asof"][:10] for s in valid if s.get("asof")}
            if quote and (len(q_dates) != 1 or quote["asof"][:10] not in q_dates or any(not s.get("asof") for s in valid)):
                filter_complete = False
            industries.append({
                "asset_id": "ths:" + code, "code": code, "name": name,
                "quote": quote, "published_amount": quote.get("amount") if quote else None,
                "filtered_amount": sum(s["amount"] or 0 for s in valid) if filter_complete else None,
                "filters_complete": filter_complete, "member_count": len(member["codes"]),
                "eligible_member_count": len(valid), "membership_complete": member["complete"],
                "missing_members": missing, "membership_sources": member["sources"],
                "change_pct": summary.get("change_pct"), "net_flow": summary.get("net_flow"),
                "flow_source": {k: summary.get(k) for k in ("source", "asof", "fetched_at", "flow_definition")},
            })
        filtered = bool(industries) and all(x["filters_complete"] for x in industries)
        key = "filtered_amount" if filtered else "published_amount"
        ready = [i for i in industries if i[key] is not None and i.get("quote")]
        dates = {x["quote"]["asof"][:10] for x in ready}
        rank_complete = len(ready) == len(industry_names) and len(dates) == 1
        ranked = sorted(ready, key=lambda row: (-row[key], row["asset_id"]))
        rank_basis = "同花顺成份 + 沪深非ST成交额汇总" if filtered else "同花顺行业公布成交额（未统一剔除ST/范围外成份）"
        ranking = {"complete": rank_complete, "filters_complete": filtered, "basis": rank_basis,
                   "date": next(iter(dates)) if len(dates) == 1 else None,
                   "covered": len(ready), "expected": len(industry_names),
                   "top": [{"asset_id": x["asset_id"], "name": x["name"], "amount": x[key]} for x in ranked[:self.config["top_n"]]]}
        if not filtered:
            self.gaps.append({"group": "industry_filter", "code": "scope_gap",
                              "message": "行业原指数/资金口径与沪深非ST股票统计不同；成份尚未全部核齐，排名明确使用同花顺原公布口径"})
        if not rank_complete:
            self.gaps.append({"group": "industry_ranking", "code": "incomplete",
                              "message": "行业目录或同日成交额未齐，动态前10暂不加入候选"})

        selected = {}
        def add(asset, reason):
            asset = dict(asset)
            aid = asset["asset_id"]
            if aid not in selected:
                selected[aid] = dict(asset, reasons=[])
            selected[aid]["reasons"].append(reason)

        if rank_complete:
            for row in ranked[:self.config["top_n"]]:
                add({"asset_id": row["asset_id"], "name": row["name"], "kind": "industry"}, "同花顺行业成交额前10")
        aliases = {"煤炭": "煤炭开采加工"}
        reverse = {n: c for c, n in industry_names.items()}
        for name in self.config["fixed_industries"]:
            code = name.replace("ths:", "") if name.replace("ths:", "") in industry_names else reverse.get(aliases.get(name, name))
            if code:
                add({"asset_id": "ths:" + code, "name": industry_names[code], "kind": "industry"}, "固定关注行业")
            else:
                self.gaps.append({"group": "configuration", "code": "unknown_industry", "message": "同花顺行业无法对应：" + name})
        for kind, field in (("index", "indices"), ("stock", "stocks")):
            for item in self.config[field]:
                add(dict(item, kind=kind), "配置指定")
        candidates = list(selected.values())
        extra = {x["asset_id"]: dict(x, kind="index") for x in self.config["watch_indices"]}
        for source, target in self.config["execution_mappings"].items():
            extra[target["asset_id"]] = dict(target, kind="etf", role="user_execution_mapping")
        instruments = {**extra, **selected}
        self.progress("历史数据", "读取候选日线与观察指数")

        def history(aid):
            if aid.startswith("ths:"):
                return self.ths.history(aid.split(":")[1], self.config["history_bars"], industry_quotes.get(aid.split(":")[1]))
            return self.em.history(aid, self.config["history_bars"], instruments[aid]["kind"])
        histories = self.parallel(list(instruments), history, "历史数据")
        market_by_id = {x["asset_id"]: x for x in market["stocks"]}
        quote_ids = [aid for aid in instruments if not aid.startswith("ths:") and aid not in market_by_id]
        extra_quotes = self.parallel(quote_ids, self.em.quote, "指数报价")
        quotes = {**market_by_id, **extra_quotes, **{"ths:" + k: v for k, v in industry_quotes.items()}}
        for item in candidates:
            item["quote"] = quotes.get(item["asset_id"])
            item["execution_asset"] = self.config["execution_mappings"].get(item["asset_id"])
            if item["kind"] == "stock" and item.get("quote") and not eligible(item["quote"]):
                item["excluded"] = True
                item["exclusion_reason"] = "不在沪深非ST范围"
            if item["kind"] == "stock" and item["asset_id"] not in market_by_id:
                item["excluded"] = True
                item["exclusion_reason"] = "未在本轮获取的沪深A股目录中确认该个股，不将其作为已核实候选"

        market_day = (market.get("asof") or ranking.get("date") or "")[:10]
        if not market_day:
            latest = [h["asof"] for h in histories.values() if h]
            market_day = max(latest) if latest else datetime.now(CN).strftime("%Y-%m-%d")
        self.progress("补充数据", "融资、ETF份额、涨跌停与跨市场观察")
        supplements = {
            "market_turnover": lambda: MarketVolume(self.http).history(previous_day(market_day) if market_day == datetime.now(CN).strftime("%Y-%m-%d") and datetime.now(CN).hour < 15 else market_day),
            "margin": self.em.margin,
            "etf_shares": lambda: self.em.etf_shares(self.config["etf_observations"], market_day),
            "limits_up": lambda: self.em.limit_pool(market_day, "up"),
            "limits_down": lambda: self.em.limit_pool(market_day, "down"),
            "limits_broken": lambda: self.em.limit_pool(market_day, "broken"),
            "tips": self.macro.tips,
        }
        for item in self.config["macro_symbols"]:
            supplements["macro:" + item["symbol"]] = lambda x=item: self.macro.yahoo(x)
        supplements = self.parallel(list(supplements), lambda key: supplements[key](), "补充数据")
        valid_histories = {k: v for k, v in histories.items() if v}
        if not valid_histories:
            raise AppError("no_core_data", "没有取得可用核心历史行情，无法进行分析", self.gaps, 503)
        coverage = [
            {"group": "同花顺行业目录", "status": catalog["status"], "detail": "%s 个行业" % len(industry_names)},
            {"group": "同花顺行业行情与排名", "status": "ok" if rank_complete else "partial", "detail": "%s/%s；%s" % (len(ready), len(industry_names), rank_basis)},
            {"group": "全市场数据目录", "status": "ok" if market["complete"] else "partial", "detail": "%s/%s；统计使用沪深非ST证券，源目录可能包含待排除项" % (market["received"], market["total_reported"])},
            {"group": "候选/观察历史", "status": "ok" if len(valid_histories) == len(instruments) else "partial", "detail": "%s/%s" % (len(valid_histories), len(instruments))},
            {"group": "行业资金", "status": "ok" if len(summaries["items"]) == len(industry_names) else "partial", "detail": "%s/%s，同花顺原发布口径，源时间精度未单列" % (len(summaries["items"]), len(industry_names))},
        ]
        for key, value in supplements.items():
            status = "ok" if value else "missing"
            if isinstance(value, dict) and (value.get("missing") or value.get("complete") is False):
                status = "partial"
            coverage.append({"group": key, "status": status, "detail": "已取得真实来源" if status == "ok" else "见缺口及来源记录"})
        coverage.append({"group": "逻辑证据", "status": "partial", "detail": "依赖用户档案和证据；价格走势不能单独核实分红/周期等逻辑"})
        for item in self.config.get("unresolved_observations", []):
            coverage.append({"group": "待配置观察项", "status": "missing", "detail": item})
        self.progress("取数完成", "%s 个候选，%s 份有效历史" % (len(candidates), len(valid_histories)))
        return {"schema_version": 1, "id": new_id(), "created_at": now(), "asof": market_day,
                "industry_provider": "ths", "config_snapshot": self.config,
                "candidates": candidates, "watch_instruments": list(extra.values()), "quotes": {k: quotes.get(k) for k in instruments},
                "histories": valid_histories, "market": market, "industries": industries, "industry_ranking": ranking,
                "macro": [v for k, v in supplements.items() if (k.startswith("macro:") or k == "tips") and v],
                "margin": supplements.get("margin"), "etf_shares": supplements.get("etf_shares"),
                "market_turnover": supplements.get("market_turnover"),
                "limit_pools": {key: supplements.get("limits_" + key) for key in ("up", "down", "broken")},
                "coverage": coverage, "gaps": self.gaps, "attempts": self.http.attempts}
