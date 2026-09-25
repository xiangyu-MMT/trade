"""F 组（量价部分）· 同一对象、完整交易日的量价事实（TASK-003 / REQ-002 RQ06）。"""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import CN, make_technical, trading_days  # noqa: E402

from trade_assistant.volume_price import (completed_asof, previous_day, ratio,  # noqa: E402
                                          turnover_summary, volume_price)


class F01PreviousDay(unittest.TestCase):
    def test_skips_closed_dates(self):
        # 2026-09-28 周一 → 09-27 周日 → 09-26 周六 → 09-25 中秋休市 → 09-24 四
        self.assertEqual(previous_day("2026-09-28"), "2026-09-24")

    def test_plain_weekday(self):
        self.assertEqual(previous_day("2026-09-24"), "2026-09-23")


class F02CompletedAsOf(unittest.TestCase):
    def test_date_only_in_the_past_is_complete(self):
        self.assertTrue(completed_asof(support.past_day(30)))

    def test_intraday_is_not_complete(self):
        self.assertFalse(completed_asof(support.past_day(30) + "T10:30:00"))

    def test_after_close_is_complete(self):
        self.assertTrue(completed_asof(support.past_day(30) + "T15:00:00"))

    def test_unparsable_is_not_complete(self):
        self.assertFalse(completed_asof(None))
        self.assertFalse(completed_asof("not-a-date"))


class F03NonContiguous(unittest.TestCase):
    def test_no_previous_day_comparison_when_gap(self):
        technical = make_technical(40)
        del technical["bars"][-2]
        result = volume_price(technical)
        self.assertIsNone(result["price_change_pct"])
        self.assertIsNone(result["volume_vs_previous"])
        self.assertTrue(result["missing"])


class F04FormingBar(unittest.TestCase):
    def test_forming_bar_is_excluded(self):
        technical = make_technical(40)
        technical["forming"] = True
        result = volume_price(technical)
        self.assertTrue(result["current_forming"])
        self.assertEqual(result["asof"], technical["bars"][-2]["date"])
        self.assertTrue(any("形成中" in x for x in result["missing"]))


class F05Eligible(unittest.TestCase):
    def test_eligible_needs_full_comparison(self):
        self.assertTrue(volume_price(make_technical(40))["eligible"])
        self.assertFalse(volume_price(make_technical(3))["eligible"])

    def test_zero_volume_is_not_eligible(self):
        technical = make_technical(40)
        for bar in technical["bars"]:
            bar["volume"] = 0
        self.assertFalse(volume_price(technical)["eligible"])


class F06UpDownVolumeRatio(unittest.TestCase):
    def test_alternating_series(self):
        bars = []
        for i, day in enumerate(trading_days(21)):
            close = 10.0 + (i % 2) * 0.2
            bars.append({"date": day, "open": close - 0.05, "high": close + 0.05, "low": close - 0.1,
                         "close": close, "volume": 100.0, "amount": close * 100})
        result = volume_price({"bars": bars, "volume_unit": "股", "source": "夹具"})
        self.assertAlmostEqual(result["up_down_volume_ratio"], 1.0)

    def test_no_down_days_returns_none(self):
        technical = make_technical(40, drift=0.1)
        closes = [b["close"] for b in technical["bars"]]
        self.assertEqual(closes, sorted(closes))
        self.assertIsNone(volume_price(technical)["up_down_volume_ratio"])

    def test_ratio_helper(self):
        self.assertAlmostEqual(ratio(6.0, 3.0), 2.0)
        self.assertIsNone(ratio(1.0, 0))
        self.assertIsNone(ratio(None, 3.0))


class F07TurnoverSummary(unittest.TestCase):
    def test_gap_prevents_previous_day_claim(self):
        rows = [{"date": "2026-09-18", "amount": 1.0e12}, {"date": "2026-09-24", "amount": 2.0e12}]
        result = turnover_summary(rows)
        self.assertIsNone(result["previous_ratio"])
        self.assertIn("不足", result["summary"])

    def test_contiguous_rows_are_compared(self):
        rows = [{"date": "2026-09-23", "amount": 1.0e12}, {"date": "2026-09-24", "amount": 1.5e12}]
        result = turnover_summary(rows)
        self.assertAlmostEqual(result["previous_ratio"], 1.5)
        self.assertEqual(result["asof"], "2026-09-24")

    def test_empty_rows(self):
        result = turnover_summary([])
        self.assertEqual(result["asof"], None)
        self.assertIsNone(result["previous_ratio"])

    def test_sorted_by_date(self):
        rows = [{"date": "2026-09-24", "amount": 2.0}, {"date": "2026-09-23", "amount": 1.0}]
        self.assertEqual([x["date"] for x in turnover_summary(rows)["rows"]], ["2026-09-23", "2026-09-24"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
