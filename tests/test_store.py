"""B 组 · 档案版本与确认 / C 组 · 回收站与生命周期（TASK-002、TASK-005）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import assert_error, temp_home  # noqa: E402

from trade_assistant.config import Settings  # noqa: E402
from trade_assistant.engine import Engine  # noqa: E402
from trade_assistant.plans import Plans  # noqa: E402
from trade_assistant.store import Store  # noqa: E402

LOGIC = {"title": "红利高股息", "body": "测试定义", "layers": ["logic"], "source": "测试"}
PLAN = {"asset_id": "sh000300", "name": "沪深300", "plan_type": "observation",
        "basis": {"logic": "逻辑", "technical": "技术", "mode": "模式"},
        "entry": "待补充", "exit": "待补充", "position_risk": "待补充", "validity": "待补充", "missing": []}


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.home = temp_home()
        self.store = Store(self.home)


class BGroup(StoreCase):
    def test_b01_create(self):
        row = self.store.create("logic", LOGIC)
        self.assertEqual((row["revision"], row["status"], row["ref"]), (1, "draft", row["id"] + "@1"))

    def test_b02_confirm_needs_actor(self):
        ident = self.store.create("logic", LOGIC)["id"]
        for actor in ("", "   ", None):
            with self.subTest(actor=actor):
                assert_error(self, "validation_error", self.store.confirm, ident, 1, actor)

    def test_b03_confirm_records_identity(self):
        ident = self.store.create("logic", LOGIC)["id"]
        row = self.store.confirm(ident, 1, "翔宇")
        self.assertEqual(row["status"], "confirmed")
        self.assertEqual(row["confirmed_by"], "翔宇")
        self.assertTrue(row["confirmed_at"])

    def test_b04_confirm_is_idempotent(self):
        ident = self.store.create("logic", LOGIC)["id"]
        self.store.confirm(ident, 1, "翔宇")
        again = self.store.confirm(ident, 1, "翔宇")
        self.assertEqual(again["revision"], 1)
        self.assertEqual(len(self.store.versions(ident)), 1)

    def test_b05_revise_creates_new_version(self):
        ident = self.store.create("logic", LOGIC)["id"]
        revised = self.store.revise(ident, dict(LOGIC, title="修订"), 1)
        self.assertEqual((revised["revision"], revised["status"]), (2, "draft"))
        self.assertEqual(self.store.get_object(ident, 1)["payload"]["title"], "红利高股息")

    def test_b06_stale_expected_revision_rejected(self):
        ident = self.store.create("logic", LOGIC)["id"]
        self.store.revise(ident, LOGIC, 1)
        assert_error(self, "conflict", self.store.revise, ident, LOGIC, 1)
        self.assertEqual(len(self.store.versions(ident)), 2)

    def test_b07_cannot_confirm_expired_draft(self):
        ident = self.store.create("logic", LOGIC)["id"]
        self.store.revise(ident, LOGIC, 1)
        assert_error(self, "conflict", self.store.confirm, ident, 1, "翔宇")

    def test_b08_immutable_kinds(self):
        for kind in ("execution", "review"):
            with self.subTest(kind=kind):
                ident = self.store.create(kind, {"note": "x"})["id"]
                assert_error(self, "validation_error", self.store.revise, ident, {"note": "y"}, 1)

    def test_b09_kind_and_identifier(self):
        assert_error(self, "validation_error", self.store.create, "unknown", LOGIC)
        assert_error(self, "validation_error", self.store.create, "logic", LOGIC, "has space")

    def test_b10_duplicate_id(self):
        ident = self.store.create("logic", LOGIC)["id"]
        assert_error(self, "conflict", self.store.create, "logic", LOGIC, ident)

    def test_b11_list_returns_latest_only(self):
        ident = self.store.create("plan", PLAN)["id"]
        self.store.revise(ident, PLAN, 1)
        rows = [x for x in self.store.list_objects("plan") if x["id"] == ident]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["revision"], 2)

    def test_b12_draft_does_not_hide_confirmed(self):
        ident = self.store.create("plan", PLAN)["id"]
        self.store.confirm(ident, 1, "翔宇")
        self.store.revise(ident, dict(PLAN, entry="改动"), 1)
        confirmed = [x for x in self.store.list_objects("plan", confirmed=True) if x["id"] == ident]
        self.assertEqual([x["revision"] for x in confirmed], [1])
        self.assertEqual(confirmed[0]["status"], "confirmed")

    def test_b13_versions_descending(self):
        ident = self.store.create("logic", LOGIC)["id"]
        self.store.revise(ident, LOGIC, 1)
        self.assertEqual([x["revision"] for x in self.store.versions(ident)], [2, 1])

    def test_b14_reference_format(self):
        assert_error(self, "validation_error", self.store.get_ref, "bad")
        assert_error(self, "validation_error", self.store.get_ref, "abc@0")


class CGroup(StoreCase):
    def setUp(self):
        super().setUp()
        self.plan_id = self.store.create("plan", PLAN)["id"]

    def test_c01_plan_can_be_trashed(self):
        row = self.store.recycle(self.plan_id, True, 1, "翔宇")
        self.assertTrue(row["is_deleted"])
        self.assertNotIn(self.plan_id, [x["id"] for x in self.store.list_objects("plan")])
        self.assertIn(self.plan_id, [x["id"] for x in self.store.list_objects("plan", include_deleted=True)])

    def test_c02_execution_can_be_trashed(self):
        ident = self.store.create("execution", {"asset_id": "sh510300", "action": "note"}, status="recorded")["id"]
        self.assertTrue(self.store.recycle(ident, True, 1, "翔宇")["is_deleted"])

    def test_c03_only_plan_and_execution(self):
        for kind in ("logic", "technical", "mode", "review"):
            with self.subTest(kind=kind):
                ident = self.store.create(kind, {"title": "x", "body": "y", "layers": ["logic"]})["id"]
                assert_error(self, "validation_error", self.store.recycle, ident, True, 1, "翔宇")

    def test_c04_restore_keeps_everything(self):
        self.store.confirm(self.plan_id, 1, "翔宇")
        before = self.store.get_object(self.plan_id, 1)
        self.store.recycle(self.plan_id, True, 1, "翔宇")
        after = self.store.recycle(self.plan_id, False, 1, "翔宇")
        self.assertFalse(after["is_deleted"])
        for key in ("revision", "status", "confirmed_by", "confirmed_at", "payload"):
            self.assertEqual(after[key], before[key], key)

    def test_c05_revision_mismatch(self):
        assert_error(self, "conflict", self.store.recycle, self.plan_id, True, 99, "翔宇")

    def test_c06_no_revise_after_delete(self):
        self.store.recycle(self.plan_id, True, 1, "翔宇")
        assert_error(self, "object_deleted", self.store.revise, self.plan_id, PLAN, 1)

    def test_c07_no_confirm_after_delete(self):
        self.store.recycle(self.plan_id, True, 1, "翔宇")
        assert_error(self, "object_deleted", self.store.confirm, self.plan_id, 1, "翔宇")

    def test_c11_no_permanent_purge(self):
        names = [n for n in dir(self.store) if not n.startswith("_")]
        for banned in ("delete", "purge", "destroy", "remove", "clear"):
            self.assertNotIn(banned, names, "不应存在永久清空能力：" + banned)

    def test_c12_lifecycle_survives_archive(self):
        self.store.recycle(self.plan_id, True, 1, "翔宇")
        archive = self.store.export_data(Settings(self.home).load())
        self.assertEqual(archive["archive_version"], 2)
        other = Store(temp_home())
        result = other.import_data(archive)
        self.assertEqual(result["lifecycle"], 1)
        restored = other.get_object(self.plan_id)
        self.assertTrue(restored["is_deleted"])
        self.assertEqual([d for d in archive["lifecycle"] if d["object_id"] == self.plan_id][0]["actor"], "翔宇")

    def test_c13_actor_required(self):
        assert_error(self, "validation_error", self.store.recycle, self.plan_id, True, 1, "")


class DeletedPlanBlocksDownstream(unittest.TestCase):
    """C-08 / C-09 / C-10：删除后对下游的影响。"""

    def setUp(self):
        self.home = temp_home()
        self.engine = Engine(Settings(self.home))
        self.store = self.engine.store
        self.plans = Plans(self.engine)

    def confirmed_plan(self):
        plan = self.plans.manual(dict(PLAN, plan_type="observation"))
        self.plans.confirm(plan["id"], 1, "翔宇")
        return plan

    def test_c08_cannot_backfill_on_deleted_plan(self):
        plan = self.confirmed_plan()
        self.store.recycle(plan["id"], True, 1, "翔宇")
        assert_error(self, "object_deleted", self.plans.execution,
                     {"asset_id": "sh510300", "action": "buy", "price": 1.0, "quantity": 100,
                      "occurred_at": support.ANCHOR + "T10:00:00+08:00", "plan_ref": plan["ref"]})

    def test_c09_cannot_review_deleted_plan(self):
        plan = self.confirmed_plan()
        self.store.recycle(plan["id"], True, 1, "翔宇")
        assert_error(self, "object_deleted", self.plans.review, plan["id"])

    def test_c10_history_review_unchanged(self):
        plan = self.confirmed_plan()
        review = self.store.create("review", {"summary": "当时复盘", "plan_ref": plan["ref"],
                                              "knowledge_proposals": []}, status="generated")
        self.store.recycle(plan["id"], True, 1, "翔宇")
        again = self.store.get_object(review["id"])
        self.assertEqual(again["payload"]["plan_ref"], plan["ref"])
        self.assertEqual(again["payload"]["summary"], "当时复盘")


if __name__ == "__main__":
    unittest.main(verbosity=2)
