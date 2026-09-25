from datetime import datetime

from .config import SYMBOL
from .knowledge import Knowledge
from .store import reference, split_reference
from .util import AppError, CN, number, now, require_text

PLAN_FIELDS = ("entry", "exit", "position_risk", "validity")


class Plans:
    def __init__(self, engine):
        self.engine, self.store = engine, engine.store
        self.knowledge = engine.knowledge

    def validate(self, payload):
        if not isinstance(payload, dict):
            raise AppError("validation_error", "计划内容需要 JSON 对象")
        result = dict(payload)
        result["asset_id"] = require_text(payload.get("asset_id"), "分析标的", 100)
        result["name"] = require_text(payload.get("name", payload["asset_id"]), "标的名称", 150)
        if payload.get("plan_type") not in ("observation", "action"):
            raise AppError("validation_error", "计划类型必须为 observation 或 action")
        execution = payload.get("execution_asset_id")
        if execution is not None and not SYMBOL.fullmatch(str(execution)):
            raise AppError("validation_error", "实际交易品种须是明确的沪深ETF/个股代码")
        if payload["plan_type"] == "action" and not execution:
            raise AppError("validation_error", "具体品种计划需要实际ETF/个股，板块指数应保存为观察计划")
        basis = payload.get("basis")
        if not isinstance(basis, dict):
            raise AppError("validation_error", "计划需要逻辑、技术和模式依据")
        result["basis"] = {k: require_text(basis.get(k, ""), k, allow_empty=True) for k in ("logic", "technical", "mode")}
        for key in PLAN_FIELDS:
            result[key] = require_text(payload.get(key, ""), key, allow_empty=True)
        missing = payload.get("missing", [])
        if not isinstance(missing, list) or any(not isinstance(x, str) for x in missing):
            raise AppError("validation_error", "missing 应为待补充事项列表")
        result["missing"] = missing
        if payload.get("validity_until"):
            value = require_text(payload["validity_until"], "明确有效期", 10)
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                raise AppError("validation_error", "明确有效期应为 YYYY-MM-DD")
        refs = payload.get("knowledge_refs", [])
        if not isinstance(refs, list):
            raise AppError("validation_error", "knowledge_refs 应为列表")
        for ref in refs:
            row = self.store.get_ref(ref)
            if row["kind"] not in ("logic", "technical", "mode") or row["status"] != "confirmed":
                raise AppError("validation_error", "计划知识引用必须已确认")
        if payload.get("run_id"):
            self.store.get_run(payload["run_id"])
        return result

    def manual(self, payload):
        result = self.validate(payload)
        result["origin"] = "user"
        return self.store.create("plan", result)

    def draft(self, run_id, asset_id):
        run = self.store.get_run(run_id)
        if not run.get("facts") or not run.get("analysis"):
            raise AppError("missing_analysis", "该轮尚无有效Codex解读，可先自行记录观察计划")
        match = next((x for x in run["facts"]["candidates"] if x["asset_id"] == asset_id), None)
        if not match or match.get("excluded"):
            raise AppError("validation_error", "标的不在本轮有效候选范围")
        opinion = next((x for x in run["analysis"]["result"]["candidates"] if x["asset_id"] == asset_id), None)
        if not opinion:
            raise AppError("missing_analysis", "本轮没有该候选的AI解读")
        refs = run["analysis"].get("knowledge_refs", [])
        archive = [{"ref": ref, **self.store.get_ref(ref)["payload"]} for ref in refs]
        risk = [x for x in self.knowledge.context() if x.get("usage") == "risk"]
        known_refs = set(refs) | {x["ref"] for x in risk}
        config = self.engine.settings.load()
        execution = config["execution_mappings"].get(asset_id)
        if not execution and match["kind"] == "stock" and any(x["asset_id"] == asset_id for x in config["stocks"]):
            execution = {"asset_id": asset_id, "name": match["name"]}
        input_data = {"run_id": run_id, "asset_id": asset_id, "name": match["name"],
                      "execution_asset": execution, "asof": run["facts"]["asof"],
                      "analysis": opinion, "market": run["analysis"]["result"]["market"],
                      "evidence": run["facts"]["evidence"], "confirmed_knowledge": archive,
                      "risk_rules": risk, "orders_allowed": False}
        input_data["selected_technical"] = {
            "quote": match.get("quote"), "asof": match["technical"].get("asof"),
            "latest": match["technical"].get("latest"),
            "daily_bars": match["technical"].get("bars", [])[-30:],
            "weekly_bars": match["technical"].get("weekly", [])[-12:],
            "trend_facts": match["technical"].get("trend_facts", []),
        }
        reply = self.engine.bridge.call("plan", input_data)
        result = reply["result"]
        if result["asset_id"] != asset_id:
            raise AppError("invalid_ai_scope", "计划返回了不同标的", status=503)
        expected_execution = execution["asset_id"] if execution else None
        if result["execution_asset_id"] != expected_execution:
            raise AppError("invalid_ai_scope", "计划擅自改变实际交易品种", status=503)
        if not execution and result["plan_type"] != "observation":
            raise AppError("invalid_ai_scope", "未指定实际品种时只能形成观察计划", status=503)
        if set(result["knowledge_refs"]) - known_refs or set(result["evidence_refs"]) - set(input_data["evidence"]):
            raise AppError("invalid_ai_reference", "计划包含未知知识或事实引用", status=503)
        if not risk:
            result["position_risk"] = "待补充：尚未提供已确认的个人仓位与风险限制；本系统不代填数值。"
            result["missing"] = list(dict.fromkeys(result["missing"] + ["个人仓位与风险规则未提供"]))
        result.update({"name": match["name"], "run_id": run_id, "origin": "codex", "ai_trace": reply["trace"]})
        return self.store.create("plan", self.validate(result))

    def revise(self, ident, payload, expected_revision):
        old = self.store.get_object(ident)
        if old["kind"] != "plan":
            raise AppError("validation_error", "对象不是交易计划")
        allowed = {"name", "asset_id", "execution_asset_id", "plan_type", "basis", *PLAN_FIELDS, "missing", "validity_until"}
        if not isinstance(payload, dict) or set(payload) - allowed:
            raise AppError("validation_error", "计划修订包含不可编辑的字段")
        updated = {**old["payload"], **payload}
        updated["revision_note"] = "用户修改，待重新确认"
        return self.store.revise(ident, self.validate(updated), expected_revision)

    def confirm(self, ident, revision, actor):
        plan = self.store.get_object(ident, revision)
        if plan["kind"] != "plan":
            raise AppError("validation_error", "对象不是计划")
        data = self.validate(plan["payload"])
        if data["plan_type"] == "action":
            if data["missing"] or any(not data[k].strip() for k in PLAN_FIELDS) or any(not x.strip() for x in data["basis"].values()):
                raise AppError("incomplete_plan", "具体品种计划仍有待补充项，请先完善；也可保留为观察计划")
        return self.store.confirm(ident, revision, actor)

    def execution(self, payload):
        if not isinstance(payload, dict):
            raise AppError("validation_error", "回填内容需要对象")
        data = dict(payload)
        data["asset_id"] = require_text(payload.get("asset_id"), "实际品种或观察标的", 100)
        if payload.get("action") not in ("buy", "sell", "note"):
            raise AppError("validation_error", "记录动作应为 buy、sell 或 note")
        if payload["action"] in ("buy", "sell") and not SYMBOL.fullmatch(data["asset_id"]):
            raise AppError("validation_error", "买卖回填需要实际ETF或个股代码")
        raw_time = require_text(payload.get("occurred_at"), "实际发生时间", 40)
        try:
            when = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        except ValueError:
            raise AppError("validation_error", "时间需为 ISO 格式，例如 2026-09-25T14:00:00+08:00")
        if when.tzinfo is None:
            when = when.replace(tzinfo=CN)
        data["occurred_at"] = when.isoformat()
        data["note"] = require_text(payload.get("note", ""), "回填说明", allow_empty=True)
        for field in ("price", "quantity", "amount"):
            original = payload.get(field)
            parsed = number(original)
            if original not in (None, "") and (parsed is None or parsed <= 0):
                raise AppError("validation_error", field + " 需要正数或留空")
            data[field] = parsed
        if data["amount"] is None and data["price"] is not None and data["quantity"] is not None:
            data["amount"] = data["price"] * data["quantity"]
            data["amount_origin"] = "根据回填价格与数量计算，未扣费用"
        data["recorded_by"] = require_text(payload.get("recorded_by", "翔宇"), "记录人", 100)
        deviations = []
        plan_ref = payload.get("plan_ref")
        if plan_ref:
            plan = self.store.get_ref(plan_ref)
            if plan["kind"] != "plan":
                raise AppError("validation_error", "plan_ref 必须引用计划")
            if plan["status"] != "confirmed":
                deviations.append("关联的计划版本尚未确认")
            if plan["confirmed_at"]:
                confirmed = datetime.fromisoformat(plan["confirmed_at"])
                if when < confirmed and payload["action"] != "note":
                    deviations.append("回填交易发生在该计划确认之前")
            target = plan["payload"].get("execution_asset_id")
            if payload["action"] != "note":
                if not target:
                    deviations.append("关联计划仅为方向观察，未指定实际交易品种")
                elif target != data["asset_id"]:
                    deviations.append("实际品种与计划指定品种不同")
            until = plan["payload"].get("validity_until")
            if until:
                try:
                    if when.date() > datetime.fromisoformat(until).date():
                        deviations.append("发生时间晚于计划明确有效期")
                except ValueError:
                    deviations.append("有效期无法自动解析，需人工复核")
        elif payload["action"] != "note":
            deviations.append("计划外记录：没有关联计划")
        data["deviations"] = deviations
        data["review_needed"] = ["自然语言买入/退出条件与仓位限制须结合回填资料复核"]
        return self.store.create("execution", data, status="recorded")

    def review(self, plan_id, revision=None):
        plan = self.store.get_object(plan_id, revision)
        if plan["kind"] != "plan":
            raise AppError("validation_error", "对象不是计划")
        history = self.store.versions(plan_id)
        executions = [x for x in self.store.list_objects("execution") if str(x["payload"].get("plan_ref", "")).startswith(plan_id + "@")]
        if not executions:
            raise AppError("no_execution_record", "尚无回填记录，不能生成交易结果复盘")
        evidence = {"plan:" + x["ref"]: x["payload"] for x in history}
        evidence.update({"execution:" + x["ref"]: x["payload"] for x in executions})
        payload = {"plan": plan, "plan_versions": history, "executions": executions,
                   "evidence": evidence, "orders_allowed": False}
        reply = self.engine.bridge.call("review", payload)
        for proposal in reply["result"]["knowledge_proposals"]:
            if set(proposal["evidence_refs"]) - set(evidence):
                raise AppError("invalid_ai_reference", "复盘引用了未提供的证据", status=503)
        content = {**reply["result"], "plan_ref": reference(plan), "execution_refs": [x["ref"] for x in executions],
                   "plan_versions": [x["ref"] for x in history], "ai_trace": reply["trace"], "input_evidence": evidence}
        return self.store.create("review", content, status="generated")

    def knowledge_from_review(self, review_id, index):
        review = self.store.get_object(review_id)
        if review["kind"] != "review" or type(index) is not int:
            raise AppError("validation_error", "复盘或建议编号无效")
        proposals = review["payload"].get("knowledge_proposals", [])
        if not 0 <= index < len(proposals):
            raise AppError("not_found", "复盘建议不存在", status=404)
        p = proposals[index]
        return self.knowledge.create(p["kind"], {"title": p["title"], "body": p["body"], "layers": [p["kind"]],
                                               "source": "Codex复盘提议，待用户确认", "origin_ref": review["ref"],
                                               "evidence": p["evidence_refs"]})
