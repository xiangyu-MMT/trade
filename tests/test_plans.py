"""I 组 · 计划、回填与复盘（TASK-005）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import ANCHOR, assert_error, settings  # noqa: E402

from trade_assistant.engine import Engine  # noqa: E402
from trade_assistant.plans import Plans  # noqa: E402
from trade_assistant.util import AppError  # noqa: E402

OBSERVATION = {
    "asset_id": "sh000300", "name": "沪深300", "plan_type": "observation",
    "basis": {"logic": "红利逻辑", "technical": "量价配合", "mode": "增量普涨"},
    "entry": "待补充", "exit": "待补充", "position_risk": "待补充", "validity": "待补充", "missing": [],
}
COMPLETE_ACTION = dict(OBSERVATION, plan_type="action", execution_asset_id="sh510300",
                       entry="回踩5日线", exit="跌破20日线", position_risk="不超过两成",
                       validity="2026-10-10", missing=[])


class PlansCase(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(settings())
        self.plans = Plans(self.engine)
        self.store = self.engine.store

    def confirmed(self, payload=None):
        plan = self.plans.manual(dict(payload or COMPLETE_ACTION))
        self.plans.confirm(plan["id"], 1, "翔宇")
        return plan

    def backfill(self, plan, **over):
        payload = {"asset_id": "sh510300", "action": "buy", "price": 4.0, "quantity": 1000,
                   "occurred_at": "2026-09-24T10:00:00+08:00", "plan_ref": plan["ref"]}
        payload.update(over)
        return self.plans.execution(payload)


class I01ActionNeedsTradable(PlansCase):
    def test_action_without_execution_asset(self):
        assert_error(self, "validation_error", self.plans.manual,
                     dict(COMPLETE_ACTION, execution_asset_id=None))

    def test_index_is_not_tradable(self):
        assert_error(self, "validation_error", self.plans.manual,
                     dict(COMPLETE_ACTION, execution_asset_id="sh000300"))

    def test_etf_is_accepted(self):
        plan = self.plans.manual(dict(COMPLETE_ACTION))
        self.assertEqual(plan["payload"]["execution_asset_id"], "sh510300")


class I03ValidityFormat(PlansCase):
    def test_bad_format(self):
        assert_error(self, "validation_error", self.plans.manual,
                     dict(OBSERVATION, validity_until="2026/10/10"))

    def test_good_format(self):
        plan = self.plans.manual(dict(OBSERVATION, validity_until="2026-10-10"))
        self.assertEqual(plan["payload"]["validity_until"], "2026-10-10")


class I04KnowledgeReferences(PlansCase):
    def test_draft_reference_rejected(self):
        draft = self.store.create("logic", {"title": "草稿", "body": "x", "layers": ["logic"]})
        assert_error(self, "validation_error", self.plans.manual,
                     dict(OBSERVATION, knowledge_refs=[draft["ref"]]))

    def test_confirmed_reference_accepted(self):
        item = self.store.create("logic", {"title": "已确认", "body": "x", "layers": ["logic"]})
        self.store.confirm(item["id"], 1, "翔宇")
        plan = self.plans.manual(dict(OBSERVATION, knowledge_refs=[item["ref"]]))
        self.assertEqual(plan["payload"]["knowledge_refs"], [item["ref"]])

    def test_unknown_run_rejected(self):
        assert_error(self, "not_found", self.plans.manual, dict(OBSERVATION, run_id="deadbeef"))


class I05ObservationPlan(PlansCase):
    def test_saved_as_observation(self):
        plan = self.plans.manual(dict(OBSERVATION))
        self.assertEqual(plan["payload"]["origin"], "user")
        self.assertIsNone(plan["payload"].get("execution_asset_id"))

    def test_observation_can_be_confirmed_with_gaps(self):
        plan = self.plans.manual(dict(OBSERVATION))
        confirmed = self.plans.confirm(plan["id"], 1, "翔宇")
        self.assertEqual(confirmed["status"], "confirmed")


class I06IncompleteActionCannotBeConfirmed(PlansCase):
    def test_pending_fields_block_confirmation(self):
        plan = self.plans.manual(dict(COMPLETE_ACTION, entry="待补充"))
        assert_error(self, "incomplete_plan", self.plans.confirm, plan["id"], 1, "翔宇")

    def test_missing_list_blocks_confirmation(self):
        plan = self.plans.manual(dict(COMPLETE_ACTION, missing=["待补充仓位"]))
        assert_error(self, "incomplete_plan", self.plans.confirm, plan["id"], 1, "翔宇")

    def test_empty_basis_blocks_confirmation(self):
        plan = self.plans.manual(dict(COMPLETE_ACTION, basis={"logic": "", "technical": "x", "mode": "y"}))
        assert_error(self, "incomplete_plan", self.plans.confirm, plan["id"], 1, "翔宇")

    def test_complete_action_is_confirmed(self):
        plan = self.confirmed()
        self.assertEqual(self.store.get_object(plan["id"])["status"], "confirmed")


class I08BackfillValidation(PlansCase):
    def test_unknown_action(self):
        plan = self.confirmed()
        assert_error(self, "validation_error", self.backfill, plan, action="hold")

    def test_buy_requires_tradable_code(self):
        plan = self.confirmed()
        assert_error(self, "validation_error", self.backfill, plan, asset_id="sh000300")

    def test_note_does_not_require_code(self):
        plan = self.confirmed()
        row = self.backfill(plan, action="note", asset_id="观察记录", price=None, quantity=None)
        self.assertEqual(row["payload"]["action"], "note")

    def test_negative_number_rejected(self):
        plan = self.confirmed()
        assert_error(self, "validation_error", self.backfill, plan, price=-1)


class I10AmountComputed(PlansCase):
    def test_amount_from_price_and_quantity(self):
        plan = self.confirmed()
        row = self.backfill(plan)
        self.assertAlmostEqual(row["payload"]["amount"], 4000.0)
        self.assertIn("未扣费用", row["payload"]["amount_origin"])

    def test_explicit_amount_kept(self):
        plan = self.confirmed()
        row = self.backfill(plan, amount=4000.5)
        self.assertAlmostEqual(row["payload"]["amount"], 4000.5)
        self.assertNotIn("amount_origin", row["payload"])


class I11TimeHandling(PlansCase):
    def test_naive_time_treated_as_cn(self):
        plan = self.confirmed()
        row = self.backfill(plan, occurred_at="2026-09-24T10:00:00")
        self.assertIn("+08:00", row["payload"]["occurred_at"])

    def test_bad_time_rejected(self):
        plan = self.confirmed()
        assert_error(self, "validation_error", self.backfill, plan, occurred_at="2026年9月24日")

    def test_missing_time_rejected(self):
        plan = self.confirmed()
        assert_error(self, "validation_error", self.backfill, plan, occurred_at="")


class I12Deviations(PlansCase):
    def test_different_instrument(self):
        plan = self.confirmed()
        row = self.backfill(plan, asset_id="sh510500")
        self.assertTrue(any("实际品种与计划指定品种不同" in d for d in row["payload"]["deviations"]))

    def test_plan_without_instrument(self):
        plan = self.confirmed(dict(OBSERVATION))
        row = self.backfill(plan, plan_ref=plan["ref"])
        self.assertTrue(any("未指定实际交易品种" in d for d in row["payload"]["deviations"]))

    def test_no_plan_reference(self):
        row = self.plans.execution({"asset_id": "sh510300", "action": "buy", "price": 4.0, "quantity": 100,
                                    "occurred_at": "2026-09-24T10:00:00+08:00"})
        self.assertTrue(any("计划外记录" in d for d in row["payload"]["deviations"]))

    def test_unconfirmed_plan_flagged(self):
        plan = self.plans.manual(dict(COMPLETE_ACTION))
        row = self.backfill(plan)
        self.assertTrue(any("尚未确认" in d for d in row["payload"]["deviations"]))

    def test_beyond_validity_window(self):
        plan = self.confirmed(dict(COMPLETE_ACTION, validity_until="2026-09-20"))
        row = self.backfill(plan, occurred_at="2026-09-24T10:00:00+08:00")
        self.assertTrue(any("晚于计划明确有效期" in d for d in row["payload"]["deviations"]))

    def test_clean_backfill_still_requires_review_note(self):
        plan = self.confirmed()
        plan = self.plans.manual(dict(COMPLETE_ACTION))
        assert_error(self, "validation_error", self.backfill, plan, occurred_at="bad")

    def test_note_does_not_create_instrument_deviation(self):
        plan = self.confirmed()
        row = self.backfill(plan, action="note", asset_id="观察记录", price=None, quantity=None)
        self.assertFalse(any("实际品种与计划指定品种不同" in d for d in row["payload"]["deviations"]))


class I13ReviewNeedsBackfill(PlansCase):
    def test_no_execution_record(self):
        plan = self.confirmed()
        assert_error(self, "no_execution_record", self.plans.review, plan["id"])


class ReviewWithStubAi(PlansCase):
    def stub(self, proposals):
        calls = []

        def call(purpose, payload, validator=None):
            calls.append(purpose)
            result = {"market_state": "缩量整理", "observations": [], "knowledge_proposals": proposals}
            if validator:
                validator(result)
            return {"result": result, "trace": {"provider": "codex", "record_id": "%032x" % 3,
                                                "record": str(self.engine.settings.home) + "/ai/x"}}
        self.engine.bridge.call = call
        return calls


class I14ReviewReferenceCheck(ReviewWithStubAi):
    def test_unknown_evidence_rejected(self):
        plan = self.confirmed()
        self.backfill(plan)
        self.stub([{"kind": "logic", "title": "t", "body": "b", "evidence_refs": ["nope"]}])
        assert_error(self, "invalid_ai_reference", self.plans.review, plan["id"])

    def test_valid_evidence_accepted(self):
        plan = self.confirmed()
        self.backfill(plan)
        self.stub([{"kind": "logic", "title": "t", "body": "b", "evidence_refs": ["plan:" + plan["ref"]]}])
        self.plans.review(plan["id"])


class I15ReviewTraceability(ReviewWithStubAi):
    def test_review_keeps_versions_and_refs(self):
        plan = self.confirmed()
        execution = self.backfill(plan)
        self.stub([])
        review = self.plans.review(plan["id"])
        payload = review["payload"]
        self.assertEqual(payload["plan_ref"], plan["ref"])
        self.assertEqual(payload["plan_versions"], [plan["ref"]])
        self.assertEqual(payload["execution_refs"], [execution["ref"]])
        self.assertEqual(payload["ai_trace"]["provider"], "codex")
        self.assertEqual(review["status"], "generated")

    def test_proposal_becomes_draft_only(self):
        plan = self.confirmed()
        self.backfill(plan)
        self.stub([{"kind": "logic", "title": "复盘建议", "body": "x", "evidence_refs": ["plan:" + plan["ref"]]}])
        review = self.plans.review(plan["id"])
        draft = self.plans.knowledge_from_review(review["id"], 0)
        self.assertEqual(draft["status"], "draft")
        self.assertIn("待用户确认", draft["payload"]["source"])
        self.assertEqual(self.store.get_object(draft["id"], 1)["status"], "draft")

    def test_bad_proposal_index(self):
        plan = self.confirmed()
        self.backfill(plan)
        self.stub([])
        review = self.plans.review(plan["id"])
        assert_error(self, "not_found", self.plans.knowledge_from_review, review["id"], 3)


class I16PlanRevision(PlansCase):
    def test_revise_allowed_fields(self):
        plan = self.plans.manual(dict(COMPLETE_ACTION))
        revised = self.plans.revise(plan["id"], {"entry": "改为回踩20日线"}, 1)
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(revised["status"], "draft")
        self.assertEqual(revised["payload"]["entry"], "改为回踩20日线")
        self.assertIn("待重新确认", revised["payload"]["revision_note"])

    def test_revise_rejects_protected_fields(self):
        plan = self.plans.manual(dict(COMPLETE_ACTION))
        for field in ("knowledge_refs", "run_id", "ai_trace"):
            with self.subTest(field=field):
                assert_error(self, "validation_error", self.plans.revise, plan["id"], {field: "x"}, 1)

    def test_revise_validates_result(self):
        plan = self.plans.manual(dict(COMPLETE_ACTION))
        assert_error(self, "validation_error", self.plans.revise, plan["id"], {"validity_until": "bad"}, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
