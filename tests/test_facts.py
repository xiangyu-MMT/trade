"""F 组（事实部分）· 全市场盘面与补充数据口径（TASK-003 / TASK-008）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import ANCHOR, candidate, history_for, make_snapshot, stock  # noqa: E402

from trade_assistant.facts import compute  # noqa: E402
from trade_assistant.volume_price import previous_day  # noqa: E402

CANDIDATES = [candidate("sh000300", "沪深300")]
HISTORIES = {"sh000300": history_for("sh000300")}


def compute_with(market=None, **extra):
    snapshot = make_snapshot(CANDIDATES, HISTORIES, market=market, **extra)
    return compute(snapshot, market_history=[])


class F08Breadth(unittest.TestCase):
    def market(self, complete=True):
        return {"stocks": [
            stock("sh600000", 11.0, 10.0, name="浦发银行"),
            stock("sz000001", 9.5, 10.0, name="平安银行"),
            stock("sz300750", 10.0, 10.0, name="宁德时代"),
            stock("sh600519", 20.0, 19.0, name="ST测试"),
            stock("bj430047", 5.0, 4.9, name="北交所样本"),
            stock("sh900901", 1.0, 1.0, name="B股样本"),
            stock("sh600001", None, 10.0, name="缺报价"),
        ], "received": 7, "total_reported": 7, "complete": complete, "asof": ANCHOR}

    def test_scope_and_counts(self):
        facts = compute_with(market=self.market())
        mf = facts["market"]
        self.assertEqual((mf["advancing"], mf["declining"], mf["unchanged"]), (1, 1, 1))
        # 合格证券＝代码属沪深主板/创业/科创且名称不含 ST；缺报价者仍属合格范围但单列。
        self.assertEqual(mf["eligible_count"], 4)
        self.assertEqual(mf["excluded_count"], 3)
        self.assertEqual(mf["unknown_prices"], 1)

    def test_incomplete_when_unknown_price(self):
        self.assertFalse(compute_with(market=self.market())["market"]["counts_complete"])

    def test_complete_without_unknown(self):
        market = self.market()
        market["stocks"] = [x for x in market["stocks"] if x["asset_id"] != "sh600001"]
        mf = compute_with(market=market)["market"]
        self.assertTrue(mf["counts_complete"])
        self.assertEqual(mf["unknown_prices"], 0)
        self.assertAlmostEqual(mf["advance_ratio"], 1 / 3)

    def test_directory_incomplete_propagates(self):
        market = self.market()
        market["complete"] = False
        self.assertFalse(compute_with(market=market)["market"]["counts_complete"])


class F09AmountScope(unittest.TestCase):
    def test_amount_scope_is_shsz_a_including_st(self):
        market = {"stocks": [
            stock("sh600000", 11.0, 10.0, amount=100.0),
            stock("sh600519", 20.0, 19.0, amount=50.0, name="ST测试"),
            stock("bj430047", 5.0, 4.9, amount=7.0, name="北交所样本"),
        ], "received": 3, "total_reported": 3, "complete": True, "asof": ANCHOR}
        mf = compute_with(market=market)["market"]
        self.assertEqual(mf["amount_scope"], "shsz_a")
        self.assertEqual(mf["amount_count"], 2)          # 北交所不计入
        self.assertAlmostEqual(mf["amount"], 150.0)      # ST 计入成交额
        self.assertEqual(mf["eligible_count"], 1)        # 但涨跌家数不含 ST
        self.assertTrue(mf["amount_complete"])
        self.assertIn("沪深A股全范围", mf["definition"])

    def test_missing_amount_marks_incomplete(self):
        market = {"stocks": [stock("sh600000", 11.0, 10.0, amount=None)],
                  "received": 1, "total_reported": 1, "complete": True, "asof": ANCHOR}
        mf = compute_with(market=market)["market"]
        self.assertFalse(mf["amount_complete"])


class F11Margin(unittest.TestCase):
    def margin(self, previous):
        return {"rows": [{"date": ANCHOR, "financing_balance": 200.0},
                         {"date": previous, "financing_balance": 100.0}],
                "asof": ANCHOR, "source": "测试来源", "definition": "融资余额日频汇总"}

    def test_adjacent_session_gives_change(self):
        facts = compute_with(margin=self.margin(previous_day(ANCHOR)))
        margin = facts["margin"]
        self.assertTrue(margin["previous_session_matched"])
        self.assertAlmostEqual(margin["change"], 100.0)

    def test_gap_does_not_claim_previous_session(self):
        facts = compute_with(margin=self.margin("2026-09-18"))
        margin = facts["margin"]
        self.assertFalse(margin["previous_session_matched"])
        self.assertIsNone(margin["change"])
        self.assertEqual(len(margin["rows"]), 2)


class F12SealRate(unittest.TestCase):
    def pools(self, asof, complete=True):
        return {"up": {"rows": [{"code": "600001"}], "complete": complete, "asof": asof},
                "down": {"rows": [], "complete": complete, "asof": asof},
                "broken": {"rows": [{"code": "600001"}, {"code": "600002"}], "complete": complete, "asof": asof}}

    def test_same_day_complete_pools(self):
        # 封板率 = 涨停池 / （涨停池 ∪ 炸板池）= 1 / 2
        facts = compute_with(limit_pools=self.pools(ANCHOR))
        self.assertAlmostEqual(facts["market"]["seal_rate"], 0.5)

    def test_mismatched_day_leaves_none(self):
        facts = compute_with(limit_pools=self.pools("2026-09-23"))
        self.assertIsNone(facts["market"]["seal_rate"])

    def test_incomplete_pool_leaves_none(self):
        facts = compute_with(limit_pools=self.pools(ANCHOR, complete=False))
        self.assertIsNone(facts["market"]["seal_rate"])

    def test_definition_present(self):
        facts = compute_with(limit_pools=self.pools(ANCHOR))
        self.assertIn("不是全交易所无排除统计", facts["market"]["limit_definition"])


class F13Limitations(unittest.TestCase):
    def test_non_ok_coverage_becomes_limitation(self):
        coverage = [{"group": "行业资金", "status": "partial", "detail": "行业资金表缺失"}]
        facts = compute_with(coverage=coverage)
        self.assertIn("行业资金表缺失", facts["limitations"])

    def test_ok_coverage_is_not_a_limitation(self):
        coverage = [{"group": "行业目录", "status": "ok", "detail": "90 个行业"}]
        facts = compute_with(coverage=coverage)
        self.assertNotIn("90 个行业", facts["limitations"])


class F14MarketVolume(unittest.TestCase):
    def test_independent_of_candidates(self):
        facts = compute_with()
        volume = facts["market_volume"]
        self.assertTrue(any("独立于候选集合" in x for x in volume["notes"]))
        self.assertEqual(volume["series"]["scope_id"], "shsz_a")
        self.assertTrue(any("盘中累计成交额" in x for x in volume["notes"]))

    def test_evidence_entry(self):
        facts = compute_with()
        self.assertIn("market:volume", facts["evidence"])


class F15Basis(unittest.TestCase):
    def basis(self, prefix):
        return {prefix: {"name": prefix + "加权基差", "asset_id": "sh000300", "unit": "点",
                         "asof": ANCHOR, "covered": 25, "expected": 25, "complete": True,
                         "definition": "全部在市同系列合约按持仓量加权：(期货同日收盘－指数同日收盘)；正数升水，负数贴水",
                         "rows": [{"date": ANCHOR, "value": 12.5, "contracts": []}]}}

    def test_if_and_im_entered_evidence(self):
        facts = compute_with(basis={**self.basis("IF"), **self.basis("IM")})
        for prefix in ("IF", "IM"):
            entry = facts["evidence"]["basis:" + prefix]
            self.assertEqual(entry["unit"], "点")
            self.assertIn("持仓量加权", entry["definition"])
            self.assertIn("正数升水", entry["definition"])
            self.assertEqual((entry["covered"], entry["expected"]), (25, 25))

    def test_absent_basis_is_absent(self):
        facts = compute_with()
        self.assertFalse([k for k in facts["evidence"] if k.startswith("basis:")])


class F16LimitHistory(unittest.TestCase):
    def test_missing_dates_are_not_zero_filled(self):
        rows = [{"date": "2026-09-23", "up": 40, "down": 5}, {"date": ANCHOR, "up": 22, "down": 9}]
        facts = compute_with(limit_history={"rows": rows, "complete": False, "covered": 2,
                                           "definition": "提供方股池口径"})
        entry = facts["evidence"]["market:limits_history"]
        self.assertEqual([x["date"] for x in entry["rows"]], ["2026-09-23", ANCHOR])
        self.assertNotIn("2026-09-24T00:00:00", [x["date"] for x in entry["rows"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
