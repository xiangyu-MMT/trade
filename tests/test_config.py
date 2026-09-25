"""A 组 · 配置与校验（TASK-001 / REQ-002 RQ01）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import assert_error, default_config, reject, temp_home  # noqa: E402

from trade_assistant.config import Settings, validate  # noqa: E402


class A01Default(unittest.TestCase):
    def test_default_config_loads(self):
        home = temp_home()
        settings = Settings(home)
        config = settings.load()
        self.assertEqual(config["schema_version"], 1)
        self.assertEqual(config["industry_provider"], "ths")
        self.assertFalse(config["auto_refresh"])
        self.assertEqual(config["ai"]["provider"], "codex")
        self.assertFalse(config["ai"]["deepseek"]["enabled"])
        self.assertTrue((home / "config.json").is_file())


class A02SchemaVersion(unittest.TestCase):
    def test_rejects_other_schema(self):
        reject(self, lambda c: c.update(schema_version=2))


class A03SecretsTopLevel(unittest.TestCase):
    def test_rejects_api_key(self):
        reject(self, lambda c: c.update(api_key="sk-abcdefghijklmnop"))

    def test_rejects_nested_secrets(self):
        cases = {
            "ai.deepseek.api_key": lambda c: c["ai"]["deepseek"].update(api_key="x"),
            "indices[0].password": lambda c: c["indices"][0].update(password="x"),
            "cookie": lambda c: c.update(cookie="a=b"),
            "secret": lambda c: c.update(secret="x"),
            "authorization": lambda c: c["ai"].update(authorization="Bearer x"),
            "access_token": lambda c: c.update(access_token="x"),
        }
        for label, mutate in cases.items():
            with self.subTest(case=label):
                reject(self, mutate)


class A05MaPeriods(unittest.TestCase):
    def test_accepts_full_set_but_normalises(self):
        config = default_config()
        config["indicators"]["ma_periods"] = [5, 20, 60, 120]
        result = validate(config)
        self.assertEqual(result["indicators"]["ma_periods"], [5, 20])

    def test_rejects_other_sets(self):
        for periods in ([5, 20, 60], [5], [10, 20], []):
            with self.subTest(periods=periods):
                reject(self, lambda c, p=periods: c["indicators"].update(ma_periods=p))

    def test_rejects_illegal_values(self):
        for periods in ([5, 20, 1], [5, 20, 501], [5, 20, "20"]):
            with self.subTest(periods=periods):
                reject(self, lambda c, p=periods: c["indicators"].update(ma_periods=p))


class A08DisplayDoesNotLeakIntoCalculation(unittest.TestCase):
    def test_saved_value_is_calculation_value(self):
        home = temp_home()
        settings = Settings(home)
        config = settings.load()
        config["indicators"]["ma_periods"] = [5, 20, 60, 120]
        settings.save(config)
        self.assertEqual(settings.load()["indicators"]["ma_periods"], [5, 20])
        technical = support.make_technical(40)
        self.assertEqual(technical["parameters"]["ma_periods"], [5, 20])
        self.assertEqual(sorted(technical["ma"].keys()), ["20", "5"])


class A09Symbols(unittest.TestCase):
    def test_stocks_reject_index_codes(self):
        reject(self, lambda c: c.update(stocks=[{"asset_id": "sh000300", "name": "沪深300"}]))

    def test_duplicate_ids_rejected(self):
        reject(self, lambda c: c.update(indices=c["indices"] + [{"asset_id": "sh000300", "name": "重复"}]))

    def test_mapping_target_must_be_tradable(self):
        reject(self, lambda c: c.update(execution_mappings={"sh000300": {"asset_id": "sh000300", "name": "指数"}}))

    def test_mapping_target_accepts_etf(self):
        config = default_config()
        config["execution_mappings"] = {"sh000300": {"asset_id": "sh510300", "name": "沪深300ETF"}}
        self.assertEqual(validate(config)["execution_mappings"]["sh000300"]["asset_id"], "sh510300")


class A12NumericBoundaries(unittest.TestCase):
    def test_top_n(self):
        for value in (-1, 91):
            with self.subTest(value=value):
                reject(self, lambda c, v=value: c.update(top_n=v))

    def test_history_bars(self):
        for value in (119, 1001):
            with self.subTest(value=value):
                reject(self, lambda c, v=value: c.update(history_bars=v))

    def test_refresh_seconds(self):
        reject(self, lambda c: c.update(refresh_seconds=3599))
        reject(self, lambda c: c.update(refresh_seconds=86401))

    def test_auto_refresh_must_be_bool(self):
        reject(self, lambda c: c.update(auto_refresh="yes"))

    def test_network_limits(self):
        for key, value in (("timeout", 2), ("workers", 9), ("budget_seconds", 601)):
            with self.subTest(key=key):
                reject(self, lambda c, k=key, v=value: c["network"].update({k: v}))


class A15AiProvider(unittest.TestCase):
    def test_provider_limited(self):
        reject(self, lambda c: c["ai"].update(provider="openai"))

    def test_provider_accepts_both(self):
        for provider in ("codex", "deepseek"):
            config = default_config()
            config["ai"]["provider"] = provider
            self.assertEqual(validate(config)["ai"]["provider"], provider)

    def test_ai_defaults_are_filled(self):
        config = default_config()
        for key in ("provider", "model", "deepseek"):
            config["ai"].pop(key, None)
        result = validate(config)
        self.assertEqual(result["ai"]["provider"], "codex")
        self.assertEqual(result["ai"]["model"], "")
        self.assertFalse(result["ai"]["deepseek"]["enabled"])

    def test_timeout_bounds(self):
        for value in (29, 901):
            with self.subTest(value=value):
                reject(self, lambda c, v=value: c["ai"].update(timeout=v))


class A17DeepSeekUrl(unittest.TestCase):
    def test_requires_https(self):
        reject(self, lambda c: c["ai"]["deepseek"].update(base_url="http://api.deepseek.com"))

    def test_rejects_credentials_and_params(self):
        for url in ("https://u:p@api.deepseek.com", "https://api.deepseek.com?v=1",
                    "https://api.deepseek.com#x"):
            with self.subTest(url=url):
                reject(self, lambda c, u=url: c["ai"]["deepseek"].update(base_url=u))

    def test_timeout_bounds(self):
        for value in (29, 901):
            with self.subTest(value=value):
                reject(self, lambda c, v=value: c["ai"]["deepseek"].update(timeout=v))


class A20OtherRules(unittest.TestCase):
    def test_fixed_industries_reject_blank(self):
        reject(self, lambda c: c.update(fixed_industries=[""]))

    def test_max_import_bytes_bounds(self):
        for value in (100, 600000000):
            with self.subTest(value=value):
                reject(self, lambda c, v=value: c.update(max_import_bytes=v))

    def test_indicator_consistency(self):
        reject(self, lambda c: c["indicators"].update(macd_fast=26, macd_slow=12))

    def test_industry_provider_fixed(self):
        reject(self, lambda c: c.update(industry_provider="em"))

    def test_unknown_keys_are_not_silently_dropped(self):
        config = default_config()
        config["user_note"] = "保留"
        self.assertEqual(validate(config)["user_note"], "保留")


if __name__ == "__main__":
    unittest.main(verbosity=2)
