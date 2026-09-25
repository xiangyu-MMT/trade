"""H 组（校验部分）· AI 输入收敛与引用校验（TASK-004/007/008）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import ANCHOR, assert_error, make_technical, settings  # noqa: E402

from trade_assistant.engine import Engine  # noqa: E402


def candidate_row(asset_id, name, kind, reasons):
    return {"asset_id": asset_id, "name": name, "kind": kind, "reasons": reasons,
            "evidence_id": "technical:" + asset_id, "technical": make_technical(40),
            "quote": None, "excluded": False, "execution_asset": None}


class H09IndustryScope(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(settings())

    def facts(self, industry_count=90):
        industries = [{"asset_id": "ths:%03d" % i, "name": "行业%d（全量 %d）" % (i, industry_count),
                       "change_pct": 1.0, "net_flow": 100.0, "filters_complete": True}
                      for i in range(industry_count)]
        candidates = [candidate_row("ths:000", "行业0", "industry", ["固定关注行业"]),
                      candidate_row("sh000300", "沪深300", "index", ["配置指定"])]
        return {"asof": ANCHOR, "candidates": candidates, "industries": industries,
                "evidence": {"technical:ths:000": {"a": 1}, "technical:sh000300": {"a": 1}},
                "market": {}, "industry_ranking": {}, "coverage": [], "limitations": [], "calendar": {}}

    def test_only_selected_industries_are_sent(self):
        payload = self.engine.analysis_input(self.facts())
        self.assertEqual(len(payload["industry_structure"]), 1)
        self.assertEqual(payload["industry_structure"][0]["asset_id"], "ths:000")
        self.assertEqual(payload["input_scope"]["industry_details"], 1)

    def test_no_full_industry_list_in_payload(self):
        payload = self.engine.analysis_input(self.facts())
        text = __import__("json").dumps(payload, ensure_ascii=False)
        self.assertNotIn("行业77（全量 90）", text)
        self.assertIn("policy", payload["input_scope"])

    def test_scope_policy_mentions_ranking_is_program_side(self):
        payload = self.engine.analysis_input(self.facts())
        self.assertIn("程序筛选", payload["input_scope"]["policy"])
        self.assertEqual(payload["requirements"]["orders_allowed"], False)
        self.assertEqual(payload["requirements"]["moving_averages_days"], [5, 20])

    def test_evidence_is_not_duplicated_for_candidates(self):
        payload = self.engine.analysis_input(self.facts())
        entry = payload["evidence"]["technical:ths:000"]
        self.assertNotIn("latest", entry)
        self.assertNotIn("trend_facts", entry)
        self.assertEqual(entry["details_in_candidate"], "ths:000")


class ValidateAnalysisCase(unittest.TestCase):
    @staticmethod
    def payload():
        return {"candidates": [{"asset_id": "sh000300", "excluded": False, "status": "ok"},
                               {"asset_id": "sh600000", "excluded": False, "status": "ok"}],
                "confirmed_knowledge": [{"ref": "k1@1", "kind": "logic"}, {"ref": "m1@1", "kind": "mode"}],
                "evidence": {"technical:sh000300": {}, "technical:sh600000": {}},
                "ranking_eligible_ids": ["sh000300", "sh600000"]}

    @staticmethod
    def result():
        return {"market": {"mode_refs": ["m1@1"], "evidence_refs": ["technical:sh000300"]},
                "candidates": [
                    {"asset_id": "sh000300", "stance": "candidate", "logic_refs": ["k1@1"],
                     "mode_refs": [], "evidence_refs": ["technical:sh000300"]},
                    {"asset_id": "sh600000", "stance": "observe", "logic_refs": [], "mode_refs": [],
                     "evidence_refs": []}],
                "knowledge_proposals": [], "ranked_asset_ids": ["sh000300", "sh600000"], "limitations": []}

    def validate(self, result=None, payload=None):
        return Engine.validate_analysis(result or self.result(), payload or self.payload())


class H11ReferenceChecks(ValidateAnalysisCase):
    def test_unknown_mode_reference(self):
        result = self.result()
        result["market"]["mode_refs"] = ["nope@1"]
        assert_error(self, "invalid_ai_reference", self.validate, result)

    def test_unknown_evidence_reference(self):
        result = self.result()
        result["candidates"][0]["evidence_refs"] = ["technical:nope"]
        assert_error(self, "invalid_ai_reference", self.validate, result)

    def test_unknown_logic_reference(self):
        result = self.result()
        result["candidates"][0]["logic_refs"] = ["k9@1"]
        assert_error(self, "invalid_ai_reference", self.validate, result)

    def test_unknown_proposal_reference(self):
        result = self.result()
        result["knowledge_proposals"] = [{"kind": "logic", "title": "t", "body": "b",
                                          "evidence_refs": ["technical:nope"]}]
        assert_error(self, "invalid_ai_reference", self.validate, result)

    def test_knowledge_without_logic_layer_is_not_allowed(self):
        payload = self.payload()
        payload["confirmed_knowledge"] = [{"ref": "k1@1", "kind": "technical", "layers": ["technical"]},
                                          {"ref": "m1@1", "kind": "mode"}]
        result = self.result()
        assert_error(self, "invalid_ai_reference", self.validate, result, payload)


class H12ScopeChecks(ValidateAnalysisCase):
    def test_out_of_scope_candidate(self):
        result = self.result()
        result["candidates"][1]["asset_id"] = "sh999999"
        assert_error(self, "invalid_ai_scope", self.validate, result)

    def test_duplicate_candidate(self):
        result = self.result()
        result["candidates"][1]["asset_id"] = "sh000300"
        assert_error(self, "invalid_ai_scope", self.validate, result)


class H13BasisChecks(ValidateAnalysisCase):
    def test_candidate_without_logic(self):
        result = self.result()
        result["candidates"][0]["logic_refs"] = []
        assert_error(self, "invalid_ai_basis", self.validate, result)

    def test_candidate_without_evidence(self):
        result = self.result()
        assert_error(self, "invalid_ai_basis", self.validate,
                     self.result_without_evidence())

    @staticmethod
    def result_without_evidence():
        result = ValidateAnalysisCase.result()
        result["candidates"][0]["evidence_refs"] = []
        return result

    def test_excluded_candidate_cannot_be_promoted(self):
        payload = self.payload()
        payload["candidates"][1]["excluded"] = True
        result = self.result()
        result["candidates"][1]["stance"] = "candidate"
        result["candidates"][1]["logic_refs"] = ["k1@1"]
        result["candidates"][1]["evidence_refs"] = ["technical:sh600000"]
        assert_error(self, "invalid_ai_basis", self.validate, result, payload)

    def test_missing_technical_cannot_be_promoted(self):
        payload = self.payload()
        payload["candidates"][1]["status"] = "missing"
        result = self.result()
        result["candidates"][1]["stance"] = "candidate"
        result["candidates"][1]["logic_refs"] = ["k1@1"]
        result["candidates"][1]["evidence_refs"] = ["technical:sh600000"]
        assert_error(self, "invalid_ai_basis", self.validate, result, payload)

    def test_observe_stance_needs_no_basis(self):
        self.validate()


class H15RankingChecks(ValidateAnalysisCase):
    def test_missing_member(self):
        result = self.result()
        result["ranked_asset_ids"] = ["sh000300"]
        assert_error(self, "invalid_ai_ranking", self.validate, result)

    def test_duplicate_member(self):
        result = self.result()
        result["ranked_asset_ids"] = ["sh000300", "sh000300"]
        assert_error(self, "invalid_ai_ranking", self.validate, result)

    def test_extra_member(self):
        result = self.result()
        result["ranked_asset_ids"] = ["sh000300", "sh600000", "sh999999"]
        assert_error(self, "invalid_ai_ranking", self.validate, result)

    def test_empty_ranking_is_rejected(self):
        result = self.result()
        result["ranked_asset_ids"] = []
        assert_error(self, "invalid_ai_ranking", self.validate, result)


class H17CoverageAndLimitations(ValidateAnalysisCase):
    def test_uncovered_candidate_recorded(self):
        result = self.result()
        result["candidates"] = [result["candidates"][0]]
        coverage = self.validate(result)
        self.assertEqual(coverage["missing"], ["sh600000"])
        self.assertEqual(coverage["covered"], 1)
        self.assertEqual(coverage["requested"], 2)
        self.assertTrue(any("sh600000" in x for x in result["limitations"]))

    def test_full_coverage_has_no_missing(self):
        coverage = self.validate()
        self.assertEqual(coverage["missing"], [])
        self.assertEqual(coverage["covered"], coverage["requested"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
