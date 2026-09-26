import threading

from .ai_router import AIRouter
from .collector import Collector
from .facts import compute
from .knowledge import Knowledge
from .presentation import eligible_ids
from .store import Store
from .util import AppError, digest, now
from .markets import market as validate_market


class Engine:
    def __init__(self, settings, store=None):
        self.settings = settings
        self.store = store or Store(settings.home)
        self.knowledge = Knowledge(self.store)
        self.knowledge.seed()
        self.cancelled = threading.Event()
        self.bridge = AIRouter(settings, self.cancelled)
        self.collector = None

    def cancel(self):
        self.cancelled.set()
        if self.collector:
            self.collector.http.deadline = 0
        self.bridge.cancel()

    def analysis_input(self, facts, run_id=None):
        selected_market = validate_market(facts.get("analysis_market", "CN"))
        candidates = []
        for item in facts["candidates"]:
            tech = item["technical"]
            week = tech.get("weekly", [])
            candidates.append({"asset_id": item["asset_id"], "name": item["name"], "kind": item["kind"],
                               "reasons": item["reasons"], "execution_asset": item.get("execution_asset"),
                               "excluded": item.get("excluded", False), "evidence_id": item["evidence_id"],
                               "quote": item.get("quote"), "technical_latest": tech.get("latest"),
                               "volume_price": item.get("volume_price"),
                               "price_structure": item.get("price_structure"),
                               "technical_asof": tech.get("asof"), "trend_facts": tech.get("trend_facts", []),
                               "weekly": week[-8:], "status": tech["status"], "missing": tech.get("reasons", [])})
        selected_industries = {x["asset_id"] for x in candidates if x["kind"] == "industry"}
        industry_brief = [{k: row.get(k) for k in ("asset_id", "name", "change_pct", "net_flow")} for row in facts["industries"] if row["asset_id"] in selected_industries]
        # Candidate technical fields already occur above. Keep the stable evidence
        # key and provenance without sending every indicator twice to the model.
        candidate_evidence = {x["evidence_id"]: x["asset_id"] for x in candidates}
        evidence = {}
        for key, value in facts["evidence"].items():
            if key in candidate_evidence:
                evidence[key] = {k: v for k, v in value.items() if k not in ("latest", "trend_facts", "volume_price")}
                evidence[key]["details_in_candidate"] = candidate_evidence[key]
            elif key == "market:volume":
                series = value.get("series") or value.get("reference") or value.get("exact") or {}
                evidence[key] = {"asof": series.get("asof"), "summary": series.get("summary"),
                                 "previous_ratio": series.get("previous_ratio"), "mean5_ratio": series.get("mean5_ratio"),
                                 "mean20_ratio": series.get("mean20_ratio"), "notes": value.get("notes", []),
                                 "rows": [{"date": r["date"], "amount": r["amount"]} for r in series.get("rows", [])]}
            elif key.startswith("basis:"):
                evidence[key] = {k: value.get(k) for k in ("name", "asof", "unit", "covered", "expected", "definition")}
                evidence[key]["rows"] = [{"date": r["date"], "value": r["value"]} for r in value.get("rows", [])]
            elif key == "market:limits_history":
                evidence[key] = {"definition": value.get("definition"), "covered": value.get("covered"),
                                 "rows": [{k: r.get(k) for k in ("date", "up", "down")} for r in value.get("rows", [])]}
            elif key == "margin:balance":
                evidence[key] = {k: v for k, v in value.items() if k not in ("rows", "source")}
                evidence[key]["rows"] = [{"date": r["date"], "financing_balance": r["financing_balance"]} for r in value.get("rows", [])]
            elif key in ("market:breadth", "industry:ranking", "data:coverage"):
                evidence[key] = {"details_in": {"market:breadth": "market", "industry:ranking": "industry_ranking", "data:coverage": "coverage"}[key]}
            else:
                evidence[key] = value
        payload = {"run_id": run_id, "asof": facts["asof"], "requested_at": now(),
                "ranking_eligible_ids": eligible_ids(facts),
                "market_calendar": facts.get("calendar"),
                "candidates": candidates, "market": facts["market"], "industry_ranking": facts["industry_ranking"],
                "industry_structure": industry_brief, "evidence": evidence,
                "coverage": facts["coverage"], "limitations": facts["limitations"],
                "confirmed_knowledge": self.knowledge.context(selected_market),
                "requirements": {"holding_period": "几天到几周", "primary_period": "日线", "secondary_period": "周线",
                                 "industry_definition": "同花顺", "moving_averages_days": [5, 20], "orders_allowed": False}}
        payload["input_scope"] = {"industry_details": len(industry_brief), "candidate_count": len(candidates),
                                  "policy": "基础成交额排行榜由程序筛选，AI只接收选定行业详情；全市场盘面只接收汇总事实"}
        payload["analysis_market"] = selected_market
        if selected_market == "US":
            payload["market"] = {k: v for k, v in facts["market"].items() if k not in ("rows", "sources")}
            payload["requirements"].update(industry_definition="选定七个美国行业的已标注美国ETF观察代理", moving_averages_days=facts["parameters"]["ma_periods"],
                                            technical_parameters=facts["parameters"], market_framework="短期流动性；中期信用/期限利差/实际及名义利率/美元；长期实际盈利和增长")
            payload["input_scope"]["policy"] = "仅所选美国指数和行业、NYSE＋NASDAQ聚合广度及宏观摘要；不把A股体系自动套用，不发送全市场个股明细"
            payload["us_context"] = {"breadth_history": facts.get("breadth", {}).get("rows", [])[-24:],
                                     "paired_etfs": [{"index_id": key, "asset_id": value["asset_id"], "pairing_ref": value["pairing_ref"], "premium": value["premium"]} for key, value in facts.get("paired_etfs", {}).items()]}
        def compact(value):
            if isinstance(value, float):
                return round(value, 6)
            if isinstance(value, dict):
                return {k: compact(v) for k, v in value.items()}
            if isinstance(value, list):
                return [compact(v) for v in value]
            return value
        return compact(payload)

    @staticmethod
    def validate_analysis(result, payload):
        candidate_map = {x["asset_id"]: x for x in payload["candidates"]}
        knowledge = {x["ref"]: x for x in payload["confirmed_knowledge"]}
        allowed_logic = {k for k, v in knowledge.items() if v["kind"] == "logic" or "logic" in v.get("layers", [])}
        allowed_modes = {k for k, v in knowledge.items() if v["kind"] == "mode" or "mode" in v.get("layers", [])}
        evidence = set(payload["evidence"])
        seen = set()

        def refs(values, allowed, label):
            if any(v not in allowed for v in values):
                raise AppError("invalid_ai_reference", "Codex 引用了输入中不存在的" + label, status=503)

        refs(result["market"]["mode_refs"], allowed_modes, "模式")
        refs(result["market"]["evidence_refs"], evidence, "事实")
        for row in result["candidates"]:
            aid = row["asset_id"]
            if aid not in candidate_map or aid in seen:
                raise AppError("invalid_ai_scope", "Codex 候选超出范围或重复", {"asset_id": aid}, 503)
            seen.add(aid)
            refs(row["logic_refs"], allowed_logic, "逻辑")
            refs(row["mode_refs"], allowed_modes, "模式")
            refs(row["evidence_refs"], evidence, "事实")
            if row["stance"] == "candidate" and (not row["logic_refs"] or not row["evidence_refs"] or candidate_map[aid]["excluded"] or candidate_map[aid]["status"] == "missing"):
                raise AppError("invalid_ai_basis", "可关注候选缺乏已确认逻辑/证据，或属于排除范围", {"asset_id": aid}, 503)
        for proposal in result["knowledge_proposals"]:
            refs(proposal["evidence_refs"], evidence, "事实")
        missing = sorted(set(candidate_map) - seen)
        if missing:
            result["limitations"].append("以下候选本轮未获AI覆盖：" + "、".join(missing))
        order = result.get("ranked_asset_ids", [])
        if len(order) != len(set(order)) or set(order) != set(payload["ranking_eligible_ids"]):
            raise AppError("invalid_ai_ranking", "AI综合排序未完整覆盖可排序候选，或存在重复/越界", status=503)
        return {"requested": len(candidate_map), "covered": len(seen), "missing": missing}

    def analyze(self, facts, run_id=None):
        payload = self.analysis_input(facts, run_id)
        reply = self.bridge.call("analysis", payload, lambda result: self.validate_analysis(result, payload))
        reply["coverage"] = self.validate_analysis(reply["result"], payload)
        reply["knowledge_refs"] = [x["ref"] for x in payload["confirmed_knowledge"]]
        return reply

    def run(self, progress=None, snapshot=None, no_ai=False, trigger="manual", market=None):
        progress = progress or (lambda stage, detail: None)
        selected = validate_market(market or ((snapshot or {}).get("analysis_market", "CN") if snapshot else self.settings.load().get("active_market", "CN")))
        if snapshot and validate_market(snapshot.get("analysis_market", "CN")) != selected:
            raise AppError("market_mismatch", "快照所属市场与运行目标不同")
        input_mode = "saved_snapshot" if snapshot else "live"
        context = {"trigger": trigger, "input_mode": input_mode, "analysis_market": selected}
        ident = self.store.create_run(metadata=context)
        self.cancelled.clear()
        try:
            if snapshot is None:
                if selected == "US":
                    from .us_collector import USCollector
                    self.collector = USCollector(self.settings, progress, self.store, self.cancelled)
                else:
                    self.collector = Collector(self.settings, progress)
                snapshot = self.collector.collect()
                self.collector = None
            self.store.update_run(ident, snapshot=snapshot)
            progress("计算", "技术指标与全市场盘面")
            facts = compute(snapshot, market_history=self.store.us_breadth_history() if selected == "US" else self.store.market_history())
            self.store.update_run(ident, facts=facts, metadata={**context, "asof": facts["asof"], "snapshot_id": snapshot["id"]})
            reply, ai_error = None, None
            if no_ai:
                ai_error = {"code": "ai_skipped", "message": "本轮按请求只计算程序事实，未调用AI"}
            else:
                if self.cancelled.is_set():
                    raise AppError("cancelled", "本轮已停止，已取得资料保留", status=409)
                progress("AI解读", "对照逻辑、模式与量价；失败时按配置使用后备")
                try:
                    reply = self.analyze(facts, ident)
                except AppError as exc:
                    ai_error = exc.as_dict()
            status = "partial" if ai_error or facts["limitations"] or (reply and reply["coverage"]["missing"]) else "completed"
            self.store.update_run(ident, status=status, finished_at=now(), analysis=reply, error=ai_error,
                                  metadata={**context, "asof": facts["asof"], "snapshot_id": snapshot["id"],
                                            "facts_hash": digest(facts), "knowledge_refs": reply["knowledge_refs"] if reply else []})
            progress("完成", "轮次 " + ident)
            return self.store.get_run(ident)
        except Exception as exc:
            error = exc.as_dict() if isinstance(exc, AppError) else {"code": "run_failed", "message": str(exc)}
            self.store.update_run(ident, status="failed", finished_at=now(), error=error)
            raise
