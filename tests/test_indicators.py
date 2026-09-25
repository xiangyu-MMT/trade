"""E 组 · 指标计算（TASK-003 / REQ-004）。"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import PARAMS, make_bars, make_technical, trading_days  # noqa: E402

from trade_assistant.indicators import MA_PERIODS, cci, calculate, ema, obv, sma  # noqa: E402


class E01Sma(unittest.TestCase):
    def test_values(self):
        result = sma([float(x) for x in range(1, 11)], 5)
        self.assertEqual(result[:4], [None] * 4)
        self.assertAlmostEqual(result[4], 3.0)
        self.assertAlmostEqual(result[9], 8.0)

    def test_window_not_ready(self):
        self.assertEqual(sma([1.0, 2.0], 5), [None, None])


class E02Ema(unittest.TestCase):
    def test_constant_series(self):
        result = ema([5.0] * 10, 3)
        self.assertEqual(result[:2], [None, None])
        for value in result[2:]:
            self.assertAlmostEqual(value, 5.0)

    def test_none_resets(self):
        result = ema([1.0, 2.0, None, 3.0, 4.0, 5.0], 3)
        self.assertIsNone(result[2])
        self.assertIsNone(result[3])


class E03Obv(unittest.TestCase):
    def test_adds_and_subtracts(self):
        self.assertEqual(obv([1.0, 2.0, 1.0, 3.0], [10.0, 20.0, 30.0, 40.0]), [0.0, 20.0, -10.0, 30.0])

    def test_gap_turns_none(self):
        self.assertEqual(obv([1.0, 2.0, 3.0], [10.0, None, 30.0]), [0.0, None, None])


class E05Cci(unittest.TestCase):
    def test_formula(self):
        bars = [{"high": 3.0, "low": 1.0, "close": 2.0},
                {"high": 5.0, "low": 3.0, "close": 4.0},
                {"high": 7.0, "low": 5.0, "close": 6.0}]
        self.assertAlmostEqual(cci(bars, 3)[-1], 100.0)

    def test_zero_deviation_returns_none(self):
        bars = [{"high": 3.0, "low": 1.0, "close": 2.0}] * 3
        self.assertIsNone(cci(bars, 3)[-1])


class E06RejectsBadBars(unittest.TestCase):
    def test_invalid_rows_dropped_and_counted(self):
        bars = make_bars(30)
        bars[5]["open"] = 0
        bars[6]["high"] = bars[6]["low"] - 1
        bars[7]["close"] = bars[7]["high"] + 5
        technical = calculate({"bars": bars}, dict(PARAMS))
        self.assertEqual(len(technical["bars"]), 27)
        self.assertTrue(any("3 条 OHLC 无效" in r for r in technical["reasons"]), technical["reasons"])


class E07DedupAndSort(unittest.TestCase):
    def test_later_row_wins_for_same_date(self):
        """去重规则：输入中后出现的同日期记录覆盖先出现的。"""
        bars = make_bars(6)
        duplicate = dict(bars[2], close=bars[2]["close"] + 0.05, high=bars[2]["high"] + 0.05)
        technical = calculate({"bars": bars + [duplicate]}, dict(PARAMS))
        dates = [b["date"] for b in technical["bars"]]
        self.assertEqual(len(dates), len(set(dates)))
        row = next(b for b in technical["bars"] if b["date"] == duplicate["date"])
        self.assertAlmostEqual(row["close"], duplicate["close"])

    def test_output_sorted_by_date(self):
        bars = list(reversed(make_bars(6)))
        technical = calculate({"bars": bars}, dict(PARAMS))
        dates = [b["date"] for b in technical["bars"]]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(len(dates), 6)


class E08MaPeriods(unittest.TestCase):
    def test_only_five_and_twenty(self):
        technical = calculate({"bars": make_bars(140)}, dict(PARAMS, ma_periods=[5, 20, 60, 120]))
        self.assertEqual(sorted(technical["ma"].keys()), ["20", "5"])
        self.assertEqual(technical["parameters"]["ma_periods"], [5, 20])
        self.assertEqual(list(MA_PERIODS), [5, 20])


class E09ShortHistory(unittest.TestCase):
    def test_partial_with_reasons(self):
        technical = calculate({"bars": make_bars(10)}, dict(PARAMS))
        self.assertEqual(technical["status"], "partial")
        self.assertTrue(any("历史不足" in r for r in technical["reasons"]), technical["reasons"])


class E10EmptyHistory(unittest.TestCase):
    def test_missing(self):
        technical = calculate({"bars": []}, dict(PARAMS))
        self.assertEqual(technical["status"], "missing")
        self.assertEqual(technical["bars"], [])
        self.assertEqual(technical["latest"], {})


class E11Weekly(unittest.TestCase):
    def test_aggregation_matches_source(self):
        bars = make_bars(21)
        technical = calculate({"bars": bars}, dict(PARAMS))
        groups = {}
        order = []
        for bar in technical["bars"]:
            key = datetime.strptime(bar["date"], "%Y-%m-%d").isocalendar()[:2]
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(bar)
        self.assertEqual(len(technical["weekly"]), len(order))
        self.assertGreater(len(technical["weekly"]), 2)
        for key, week in zip(order, technical["weekly"]):
            source = groups[key]
            self.assertAlmostEqual(week["high"], max(x["high"] for x in source))
            self.assertAlmostEqual(week["low"], min(x["low"] for x in source))
            self.assertAlmostEqual(week["close"], source[-1]["close"])
            self.assertAlmostEqual(week["volume"], sum(x["volume"] for x in source))
            self.assertEqual(week["date"], source[-1]["date"])
            self.assertIn("forming", week)


class E12Traceability(unittest.TestCase):
    def test_version_and_definition(self):
        technical = make_technical(40)
        self.assertEqual(technical["formula_version"], "p03-indicators-2")
        self.assertIn("MACD柱=2*(DIF-DEA)", technical["definition"])
        self.assertTrue(trading_days(1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
