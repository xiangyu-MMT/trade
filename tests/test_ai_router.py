"""H 组（接入部分）· 模型路由、降级链与凭据隔离（TASK-004/007 / REQ-002 RQ01）。"""
import json
import os
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import assert_error, settings, temp_home  # noqa: E402

from trade_assistant.ai_router import AIRouter  # noqa: E402
from trade_assistant.codex_bridge import RESOURCES  # noqa: E402
from trade_assistant.credentials import Credentials  # noqa: E402
from trade_assistant.util import AppError  # noqa: E402


def trace_for(home, provider="codex"):
    record = Path(home) / "ai" / ("%032x" % 7)
    record.mkdir(parents=True, exist_ok=True)
    return {"record_id": record.name, "record": str(record), "provider": provider, "status": "running"}


class RouterCase(unittest.TestCase):
    def setUp(self):
        self.settings = settings()
        self.router = AIRouter(self.settings, __import__("threading").Event())
        self.calls = []

    def configure(self, provider="codex", deepseek=False):
        config = self.settings.load()
        config["ai"]["provider"] = provider
        config["ai"]["deepseek"]["enabled"] = deepseek
        self.settings.save(config)

    def fake_codex(self, outcome="ok"):
        def call(purpose, payload):
            self.calls.append("codex")
            if outcome == "fail":
                raise AppError("codex_failed", "Codex 未完成本轮推导", status=503)
            return {"result": {"marker": "codex"}, "trace": trace_for(self.settings.home)}
        self.router.codex.call = call
        return call

    def fake_deepseek(self, outcome="ok"):
        def call(purpose, payload):
            self.calls.append("deepseek")
            if outcome == "fail":
                raise AppError("deepseek_timeout", "DeepSeek调用超时", status=503)
            return {"result": {"marker": "deepseek"}, "trace": trace_for(self.settings.home, "deepseek")}
        self.router.deepseek = call
        return call


class H01Disabled(RouterCase):
    def test_disabled_keeps_program_facts(self):
        config = self.settings.load()
        config["ai"]["enabled"] = False
        self.settings.save(config)
        self.fake_codex()
        assert_error(self, "ai_disabled", self.router.call, "analysis", {})
        self.assertEqual(self.calls, [])


class H02FallbackToDeepSeek(RouterCase):
    def test_codex_failure_falls_back(self):
        self.configure("codex", deepseek=True)
        self.fake_codex("fail")
        self.fake_deepseek()
        reply = self.router.call("analysis", {})
        self.assertEqual(self.calls, ["codex", "deepseek"])
        self.assertEqual(reply["trace"]["provider"], "deepseek")
        self.assertTrue(reply["trace"]["fallback_used"])
        self.assertEqual(reply["trace"]["attempts"][0]["provider"], "codex")

    def test_no_fallback_when_disabled(self):
        self.configure("codex", deepseek=False)
        self.fake_codex("fail")
        self.fake_deepseek()
        assert_error(self, "ai_unavailable", self.router.call, "analysis", {})
        self.assertEqual(self.calls, ["codex"])


class H03DeepSeekOnly(RouterCase):
    def test_codex_not_called(self):
        self.configure("deepseek", deepseek=True)
        self.fake_codex()
        self.fake_deepseek()
        self.router.call("analysis", {})
        self.assertEqual(self.calls, ["deepseek"])


class H04NoFallbackOnSuccess(RouterCase):
    def test_deepseek_not_called(self):
        self.configure("codex", deepseek=True)
        self.fake_codex()
        self.fake_deepseek()
        reply = self.router.call("analysis", {})
        self.assertEqual(self.calls, ["codex"])
        self.assertFalse(reply["trace"]["fallback_used"])


class H05CancelStopsFallback(RouterCase):
    def test_cancel_after_first_failure(self):
        self.configure("codex", deepseek=True)
        cancelled = self.router.cancelled

        def fail(purpose, payload):
            self.calls.append("codex")
            cancelled.set()
            raise AppError("codex_failed", "x", status=503)

        self.router.codex.call = fail
        self.fake_deepseek()
        assert_error(self, "cancelled", self.router.call, "analysis", {})
        self.assertEqual(self.calls, ["codex"])


class H06BothFail(RouterCase):
    def test_reports_attempts(self):
        self.configure("codex", deepseek=True)
        self.fake_codex("fail")
        self.fake_deepseek("fail")
        exc = assert_error(self, "ai_unavailable", self.router.call, "analysis", {})
        self.assertEqual([x["provider"] for x in exc.details["attempts"]], ["codex", "deepseek"])


class H07DeepSeekUnconfigured(RouterCase):
    def test_missing_key(self):
        self.configure("deepseek", deepseek=True)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)
            assert_error(self, "deepseek_unconfigured", self.router.deepseek, "analysis", {})


class H08ProviderIsRecorded(RouterCase):
    def test_deepseek_trace_not_labelled_codex(self):
        self.configure("deepseek", deepseek=True)
        self.fake_deepseek()
        reply = self.router.call("analysis", {})
        self.assertEqual(reply["trace"]["provider"], "deepseek")
        self.assertNotEqual(reply["trace"]["provider"], "codex")


class H18TraceWrittenBack(RouterCase):
    def test_trace_file_updated(self):
        self.configure("codex", deepseek=True)
        self.fake_codex("fail")
        self.fake_deepseek()
        reply = self.router.call("analysis", {})
        path = Path(reply["trace"]["record"]) / "trace.json"
        self.assertTrue(path.is_file())
        written = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(written["provider"], "deepseek")
        self.assertTrue(written["fallback_used"])


class H17PromptsAndSchemas(unittest.TestCase):
    def test_three_purposes_present(self):
        for purpose in ("analysis", "plan", "review"):
            prompt = RESOURCES / "prompts" / (purpose + ".txt")
            schema = RESOURCES / "schemas" / (purpose + ".json")
            self.assertTrue(prompt.is_file(), purpose)
            self.assertTrue(schema.is_file(), purpose)
            json.loads(schema.read_text(encoding="utf-8"))
            self.assertTrue(prompt.read_text(encoding="utf-8").strip(), purpose)


class H19Credentials(unittest.TestCase):
    def setUp(self):
        self.home = temp_home()
        self.credentials = Credentials(self.home)

    def test_save_and_read(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)
            self.credentials.save("sk-test-key-1234567890")
            self.assertEqual(self.credentials.key(), "sk-test-key-1234567890")
            self.assertTrue(self.credentials.status()["key_configured"])

    def test_file_permission_is_owner_only(self):
        self.credentials.save("sk-test-key")
        mode = stat.S_IMODE((self.home / "credentials.json").stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_rejects_multiline_and_oversized(self):
        assert_error(self, "validation_error", self.credentials.save, "line1\nline2")
        assert_error(self, "validation_error", self.credentials.save, "x" * 5000)

    def test_key_not_in_config_or_archive(self):
        self.credentials.save("sk-secret-value")
        from trade_assistant.config import Settings
        from trade_assistant.store import Store
        config_text = json.dumps(Settings(self.home).load(), ensure_ascii=False)
        self.assertNotIn("sk-secret-value", config_text)
        store = Store(temp_home())
        archive = store.export_data(Settings(store.home).load())
        self.assertNotIn("sk-secret-value", json.dumps(archive, ensure_ascii=False))
        self.assertFalse((store.home / "credentials.json").exists())

    def test_environment_key_is_used_when_no_file(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}):
            self.assertEqual(self.credentials.key(), "env-key")
            self.assertTrue(self.credentials.status()["environment_key"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
