"""J 组（图表部分）· K线、均线显示与仪表盘曲线（TASK-006/007/009 / REQ-004 R2）。"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import ANCHOR, make_technical  # noqa: E402

from trade_assistant.charts import candles, curves, dashboard_charts, turnover  # noqa: E402


def ma_points(svg, period):
    match = re.search(r'data-ma="%s" points="([^"]*)"' % period, svg)
    return match.group(1).split() if match else []


class J17DefaultSingleMa(unittest.TestCase):
    def test_default_draws_only_ma20(self):
        svg = candles(make_technical(60))
        self.assertEqual(re.findall(r'data-ma="(\d+)"', svg), ["20"])
        self.assertTrue(ma_points(svg, 20))

    def test_explicit_single(self):
        svg = candles(make_technical(60), display_ma=(5,))
        self.assertEqual(re.findall(r'data-ma="(\d+)"', svg), ["5"])


class J18AllFourSelectable(unittest.TestCase):
    def test_four_lines(self):
        svg = candles(make_technical(150), display_ma=(5, 20, 60, 120))
        self.assertEqual(sorted(re.findall(r'data-ma="(\d+)"', svg)), ["120", "20", "5", "60"])
        for period in (5, 20, 60, 120):
            self.assertTrue(ma_points(svg, period), "MA%s 应有折线点" % period)

    def test_none_selected_draws_no_line(self):
        svg = candles(make_technical(60), display_ma=())
        self.assertEqual(re.findall(r'data-ma="(\d+)"', svg), [])
        self.assertIn("<rect", svg)


class J19UnknownPeriodIgnored(unittest.TestCase):
    def test_unknown_period_is_skipped(self):
        svg = candles(make_technical(60), display_ma=(7, 20))
        self.assertEqual(re.findall(r'data-ma="(\d+)"', svg), ["20"])


class J20WeeklyUsesDailyAverage(unittest.TestCase):
    def test_weekly_sample_matches_daily_average(self):
        technical = make_technical(80, drift=0.12)
        weekly = technical["weekly"]
        self.assertGreater(len(weekly), 8)
        svg = candles(technical, "weekly", display_ma=(5,))
        points = ma_points(svg, 5)
        # 日均线在周K结束日取样：几乎每个周K都能取到值（只有开头不足 5 日的那一周例外）。
        # 若误用"5 周均线"，点数会比周K数少约 4 个，据此可区分。
        self.assertGreaterEqual(len(points), len(weekly) - 1)

    def test_implementation_samples_daily_not_weekly(self):
        source = (support.SRC / "trade_assistant" / "charts.py").read_text(encoding="utf-8")
        self.assertIn("sma(daily_closes, p)", source)
        self.assertIn('by_date.get(b["date"]) for b in source', source)

    def test_weekly_axis_labels_use_weekly_dates(self):
        technical = make_technical(80)
        svg = candles(technical, "weekly")
        self.assertIn(technical["weekly"][-1]["date"], svg)


class J21VolumeAlignedWithBars(unittest.TestCase):
    def test_every_bar_gets_a_volume_rect(self):
        technical = make_technical(30)
        svg = candles(technical, count=30)
        bars = technical["bars"][-30:]
        # 每根 K 线一个实体矩形，另加一个量柱矩形
        self.assertEqual(svg.count("<rect"), len(bars) * 2)

    def test_missing_volume_skips_bar(self):
        technical = make_technical(30)
        technical["bars"][-1]["volume"] = None
        svg = candles(technical, count=30)
        bars = technical["bars"][-30:]
        # 实体仍在，量柱少一根
        self.assertEqual(svg.count("<rect"), len(bars) * 2 - 1)


class J22InsufficientData(unittest.TestCase):
    def test_short_history_message(self):
        technical = {"bars": [{"date": ANCHOR, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]}
        svg = candles(technical)
        self.assertIn("暂无足够的真实K线资料", svg)
        self.assertNotIn("<polyline", svg)


class J23Dashboard(unittest.TestCase):
    def facts(self, **over):
        base = {"market_volume": {"series": {"rows": [{"date": "2026-09-23", "amount": 1.0e12},
                                                     {"date": ANCHOR, "amount": 1.2e12}]}},
                "margin": {"rows": [{"date": "2026-09-23", "financing_balance": 1.5e12},
                                    {"date": ANCHOR, "financing_balance": 1.52e12}]},
                "limit_history": {"rows": [{"date": "2026-09-23", "up": 30, "down": 4},
                                           {"date": ANCHOR, "up": 22, "down": 9}]},
                "basis": {"IF": {"rows": [{"date": ANCHOR, "value": 12.5}]},
                          "IM": {"rows": [{"date": ANCHOR, "value": -8.0}]}}}
        base.update(over)
        return base

    def test_all_five_charts_returned(self):
        charts = dashboard_charts(self.facts())
        self.assertEqual(sorted(charts.keys()), ["basisIF", "basisIM", "limits", "margin", "turnover"])
        for name, svg in charts.items():
            self.assertIn("<svg", svg, name)

    def test_turnover_has_no_data_message(self):
        charts = dashboard_charts(self.facts(market_volume={"series": {"rows": []}}))
        self.assertIn("暂无可用全市场成交额历史", charts["turnover"])

    def test_empty_series_message(self):
        charts = dashboard_charts(self.facts(margin={"rows": []}, limit_history={"rows": []},
                                             basis={"IF": {"rows": []}, "IM": {"rows": []}}))
        for name in ("margin", "limits", "basisIF", "basisIM"):
            self.assertIn("暂无可核实的历史数据", charts[name], name)


class J24BasisCurveZeroAxis(unittest.TestCase):
    def test_zero_axis_and_signed_values(self):
        rows = [{"date": "2026-09-23", "value": -8.0}, {"date": ANCHOR, "value": 12.5}]
        svg = curves(rows, [("value", "沪深300加权基差", "#4e849f")], "点", True)
        self.assertIn('stroke-dasharray="4 4"', svg)
        self.assertIn(">0<", svg)
        self.assertEqual(svg.count("<circle"), 2)

    def test_gap_breaks_line_instead_of_zero(self):
        rows = [{"date": "2026-09-23", "value": 1.0}, {"date": ANCHOR, "value": None},
                {"date": "2026-09-25", "value": 3.0}]
        svg = curves(rows, [("value", "测试", "#4e849f")], "点", True)
        self.assertEqual(svg.count("<circle"), 2)
        path = re.search(r'<path d="([^"]*)" fill="none"', svg).group(1)
        self.assertEqual(path.count("M"), 2, "缺值处应断开为两段而不是连成一条")

    def test_no_rows_message(self):
        self.assertIn("暂无可核实的历史数据", curves([], [("value", "x", "#000")]))

    def test_turnover_empty_message(self):
        self.assertIn("暂无可用全市场成交额历史", turnover([]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
