"""G 组 · 呈现与排序（TASK-006/007 / REQ-002 RQ03、RQ05）。"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import ANCHOR, make_technical, temp_home  # noqa: E402

from trade_assistant.presentation import eligible_ids, reference_key, select  # noqa: E402
from trade_assistant.volume_price import volume_price  # noqa: E402

SRC = support.SRC

INDEX_IDS = ["sh000016", "sh000300", "sh000905", "sh000852", "csi932000", "sz399006", "sz399673", "sh000688"]
FIXED_IDS = ["ths:881105", "ths:881155", "ths:881145", "ths:881168"]
# 与固定行业代码不重叠，避免夹具自身造出重复对象。
DYNAMIC_IDS = ["ths:88%04d" % i for i in range(2000, 2010)]


def make_row(asset_id, kind, reasons, drift=0.1, count=40, excluded=False, asof=ANCHOR, eligible=None):
    technical = make_technical(count, drift=drift)
    technical["asof"] = asof
    facts_row = {"asset_id": asset_id, "name": asset_id, "kind": kind, "reasons": list(reasons),
                 "technical": technical, "volume_price": volume_price(technical),
                 "excluded": excluded, "execution_asset": None}
    if eligible is False:
        facts_row["volume_price"] = dict(facts_row["volume_price"], eligible=False)
    return facts_row


def base_facts():
    rows = []
    for i, aid in enumerate(INDEX_IDS):
        rows.append(make_row(aid, "index", ["配置指定"], drift=0.10 + i * 0.01))
    for i, aid in enumerate(FIXED_IDS):
        rows.append(make_row(aid, "industry", ["固定关注行业"], drift=0.30 + i * 0.01))
    for i, aid in enumerate(DYNAMIC_IDS):
        rows.append(make_row(aid, "industry", ["同花顺行业成交额前10"], drift=0.50 + i * 0.01))
    rows.append(make_row("sh600000", "stock", ["配置指定"], drift=0.70))
    return {"asof": ANCHOR, "candidates": rows, "market": {}, "coverage": []}


class G01EligibleIds(unittest.TestCase):
    def test_filters(self):
        facts = base_facts()
        facts["candidates"].append(make_row("ths:999999", "industry", ["同花顺行业成交额前10"], excluded=True))
        facts["candidates"].append(make_row("ths:888888", "industry", ["同花顺行业成交额前10"], eligible=False))
        facts["candidates"].append(make_row("ths:777777", "industry", ["同花顺行业成交额前10"], asof="2026-09-01"))
        ids = eligible_ids(facts)
        for banned in ("ths:999999", "ths:888888", "ths:777777"):
            self.assertNotIn(banned, ids)
        self.assertIn("sh000300", ids)

    def test_all_clean_candidates_are_eligible(self):
        facts = base_facts()
        self.assertEqual(len(eligible_ids(facts)), len(facts["candidates"]))


class G02StableOrder(unittest.TestCase):
    def test_tie_break_by_asset_id(self):
        left = make_row("sh000001", "index", ["配置指定"], drift=0.1, count=40)
        right = make_row("sh000002", "index", ["配置指定"], drift=0.1, count=40)
        self.assertLess(reference_key(left), reference_key(right))

    def test_sorting_is_repeatable(self):
        facts = base_facts()
        first = select(facts)["ordered_ids"]
        second = select(base_facts())["ordered_ids"]
        self.assertEqual(first, second)


class G03ProgramFallbackLabelled(unittest.TestCase):
    def test_no_ai_source_is_flagged(self):
        result = select(base_facts(), None)
        self.assertEqual(result["source"], "program_volume_price")
        self.assertIn("缺AI", result["label"])
        self.assertIn("非胜率", result["reference_method"])


class G04PartialAiRankingRejected(unittest.TestCase):
    def test_incomplete_ranking_falls_back(self):
        facts = base_facts()
        allowed = eligible_ids(facts)
        analysis = {"result": {"ranked_asset_ids": allowed[:3]}}
        result = select(facts, analysis)
        self.assertEqual(result["source"], "program_volume_price")
        self.assertEqual(result["ordered_ids"], select(base_facts())["ordered_ids"])

    def test_duplicated_ranking_falls_back(self):
        facts = base_facts()
        allowed = eligible_ids(facts)
        analysis = {"result": {"ranked_asset_ids": allowed + [allowed[0]]}}
        self.assertEqual(select(facts, analysis)["source"], "program_volume_price")


class G05AiRankingUsed(unittest.TestCase):
    def test_full_ranking_is_adopted(self):
        facts = base_facts()
        allowed = eligible_ids(facts)
        reversed_ids = list(reversed(allowed))
        result = select(facts, {"result": {"ranked_asset_ids": reversed_ids}})
        self.assertEqual(result["source"], "ai_comprehensive")
        self.assertEqual(result["ordered_ids"], reversed_ids)
        self.assertEqual(result["overall_top3"], reversed_ids[:3])
        self.assertEqual(result["label"], "逻辑、模式与量价综合排序")


class G06GroupsDoNotOverlap(unittest.TestCase):
    def test_no_duplicate_across_groups(self):
        result = select(base_facts())
        seen = []
        for group in result["groups"]:
            seen.extend(group["asset_ids"])
        self.assertEqual(len(seen), len(set(seen)), "同一对象不应出现在两个分组")

    def test_fixed_industry_wins_first_match(self):
        facts = base_facts()
        facts["candidates"].append(make_row("sh000300", "index", ["配置指定"]))
        result = select(facts)
        index_group = next(g for g in result["groups"] if g["title"] == "宽基与指数")
        self.assertIn("sh000300", index_group["asset_ids"])

    def test_index_count_matches_config(self):
        result = select(base_facts())
        self.assertEqual(len(next(g for g in result["groups"] if g["title"] == "宽基与指数")["asset_ids"]), 8)


class G07IndustryTop3(unittest.TestCase):
    def test_top3_from_dynamic_ten(self):
        result = select(base_facts())
        self.assertLessEqual(len(result["industry_top3"]), 3)
        self.assertEqual(len(result["industry_top3"]), 3)
        for aid in result["industry_top3"]:
            self.assertIn(aid, DYNAMIC_IDS)

    def test_group_uses_top3_in_order(self):
        result = select(base_facts())
        group = next(g for g in result["groups"] if "前三" in g["title"])
        self.assertEqual(group["asset_ids"], result["industry_top3"])


class G08DynamicStillAllAnalysed(unittest.TestCase):
    def test_dynamic_analyzed_is_ten(self):
        result = select(base_facts())
        self.assertEqual(result["dynamic_analyzed"], 10)
        self.assertEqual(result["analyzed_count"], len(base_facts()["candidates"]))

    def test_eligible_count_reported(self):
        result = select(base_facts())
        self.assertEqual(result["eligible_count"], len(eligible_ids(base_facts())))


class G09OverallTop3(unittest.TestCase):
    def test_top3_within_ordering(self):
        result = select(base_facts())
        self.assertEqual(len(result["overall_top3"]), 3)
        for aid in result["overall_top3"]:
            self.assertIn(aid, result["ordered_ids"])

    def test_rank_missing_lists_ineligible(self):
        facts = base_facts()
        facts["candidates"].append(make_row("ths:999999", "industry", ["同花顺行业成交额前10"], excluded=True))
        result = select(facts)
        self.assertIn("ths:999999", result["rank_missing"])


class G10SharedContract(unittest.TestCase):
    def test_page_and_report_share_one_selector(self):
        server = (SRC / "trade_assistant" / "server.py").read_text(encoding="utf-8")
        report = (SRC / "trade_assistant" / "report_v2.py").read_text(encoding="utf-8")
        self.assertIn("from .presentation import select", server)
        self.assertIn("presentation import select", report.replace("from .presentation import select", "presentation import select"))

    def test_no_second_ranking_implementation(self):
        hits = []
        for path in (SRC / "trade_assistant").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "reference_key" in text and path.name != "presentation.py":
                hits.append(path.name)
        self.assertEqual(hits, [], "排序键不应在 presentation 之外重复实现")


if __name__ == "__main__":
    unittest.main(verbosity=2)
