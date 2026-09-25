"""J/K 组 · 本机 HTTP 接口、报告与运行调度（TASK-006）。"""
import http.client
import json
import os
import re
import subprocess
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import support  # noqa: E402
from support import ANCHOR, assert_error, candidate, history_for, make_snapshot, temp_home  # noqa: E402

from trade_assistant.config import Settings  # noqa: E402
from trade_assistant.facts import compute  # noqa: E402
from trade_assistant.server import App, LocalServer, handler_for  # noqa: E402
from trade_assistant.util import InstanceLock, now  # noqa: E402

PROJECT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
EXTERNAL = re.compile(r'(?:src|href)\s*=\s*"https?://|@import\s+url\(', re.I)


def build_run(store, run_id=None):
    snapshot = make_snapshot([candidate("sh000300", "沪深300")], {"sh000300": history_for("sh000300")},
                             coverage=[{"group": "行业资金", "status": "partial", "detail": "行业资金表缺失"}])
    facts = compute(snapshot, market_history=[])
    ident = store.create_run(run_id, metadata={"trigger": "manual", "input_mode": "saved_snapshot"})
    store.update_run(ident, snapshot=snapshot, facts=facts, status="partial", finished_at=now(),
                     metadata={"trigger": "manual", "input_mode": "saved_snapshot", "asof": facts["asof"]})
    return ident


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = temp_home()
        cls.settings = Settings(cls.home)
        cls.app = App(cls.settings)
        cls.httpd = LocalServer(("127.0.0.1", 0), handler_for(cls.app))
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.app.runner.stop()
        cls.httpd.server_close()

    def request(self, method, path, body=None, token=True, host=None, origin=None,
                content_type="application/json", raw_body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        if token is True:
            headers["X-P03-Token"] = self.app.token
        elif isinstance(token, str):
            headers["X-P03-Token"] = token
        if host:
            headers["Host"] = host
        if origin:
            headers["Origin"] = origin
        payload = raw_body if raw_body is not None else (json.dumps(body).encode("utf-8") if body is not None else b"")
        if body is None and raw_body is None:
            payload = None
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        try:
            return response.status, json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return response.status, data.decode("utf-8", "replace")


class J01Page(ServerCase):
    def test_token_is_injected(self):
        status, html = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("<!doctype html>", html)
        self.assertNotIn("__P03_TOKEN__", html)
        self.assertIn(self.app.token, html)

    def test_static_assets(self):
        for path in ("/app.js", "/style.css"):
            with self.subTest(path=path):
                status, text = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertTrue(text.strip())


class J02NoExternalDependencies(ServerCase):
    def test_page_and_assets_are_local(self):
        for path in ("/", "/app.js", "/style.css"):
            with self.subTest(path=path):
                _, text = self.request("GET", path)
                self.assertIsNone(EXTERNAL.search(text), "不应引用外部资源")


class J03State(ServerCase):
    def test_state_shape_and_no_secret(self):
        status, data = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        for key in ("trash", "lifecycle", "plans", "confirmed_plans", "executions", "knowledge", "runs"):
            self.assertIn(key, data)
        text = json.dumps(data, ensure_ascii=False)
        self.assertNotIn("api_key", text)
        self.assertNotIn("DEEPSEEK_API_KEY", text)

    def test_version_reported(self):
        _, data = self.request("GET", "/api/state")
        self.assertTrue(data["version"])


class J04AiConfigEndpoint(ServerCase):
    def test_no_key_echo(self):
        status, data = self.request("GET", "/api/ai")
        self.assertEqual(status, 200)
        self.assertIn("key_configured", data)
        self.assertIsInstance(data["key_configured"], bool)
        self.assertIn("environment_key", data)
        self.assertNotIn("deepseek_api_key", json.dumps(data))

    def test_save_config_without_key(self):
        (self.home / "credentials.json").unlink(missing_ok=True)
        payload = dict(self.settings.load()["ai"], provider="codex")
        status, data = self.request("POST", "/api/ai", {"config": payload})
        self.assertEqual(status, 200)
        self.assertEqual(data["config"]["provider"], "codex")
        self.assertFalse(data["key_configured"])
        self.assertFalse((self.home / "credentials.json").exists())

    def test_save_config_with_key_writes_credentials_only(self):
        status, data = self.request("POST", "/api/ai", {"config": self.settings.load()["ai"],
                                                        "api_key": "sk-local-test-key"})
        self.assertEqual(status, 200)
        self.assertTrue(data["key_configured"])
        self.assertTrue((self.home / "credentials.json").is_file())
        self.assertNotIn("sk-local-test-key", (self.home / "config.json").read_text(encoding="utf-8"))


class J05WriteAuthorization(ServerCase):
    def test_missing_token(self):
        status, data = self.request("POST", "/api/config", {"config": self.settings.load()}, token=False)
        self.assertEqual(status, 403)
        self.assertEqual(data["error"]["code"], "forbidden")

    def test_wrong_token(self):
        status, _ = self.request("POST", "/api/config", {"config": self.settings.load()}, token="0" * 64)
        self.assertEqual(status, 403)

    def test_bad_origin(self):
        status, _ = self.request("POST", "/api/config", {"config": self.settings.load()},
                                 origin="http://evil.example")
        self.assertEqual(status, 403)

    def test_foreign_host(self):
        status, _ = self.request("POST", "/api/config", {"config": self.settings.load()},
                                 host="192.168.31.9:%d" % self.port)
        self.assertEqual(status, 403)

    def test_read_does_not_need_token(self):
        status, _ = self.request("GET", "/api/status", token=False)
        self.assertEqual(status, 200)


class J08RequestValidation(ServerCase):
    def test_wrong_content_type(self):
        status, data = self.request("POST", "/api/config", {"config": {}}, content_type="text/plain")
        self.assertEqual(status, 415)
        self.assertEqual(data["error"]["code"], "validation_error")

    def test_empty_body(self):
        status, data = self.request("POST", "/api/config", raw_body=b"")
        self.assertEqual(status, 413)

    def test_invalid_json(self):
        status, data = self.request("POST", "/api/config", raw_body=b"{not json",
                                   content_type="application/json")
        self.assertEqual(status, 400)

    def test_non_object_body(self):
        status, data = self.request("POST", "/api/config", raw_body=b"[1,2,3]")
        self.assertEqual(status, 400)

    def test_unknown_route(self):
        status, data = self.request("GET", "/api/nope")
        self.assertEqual(status, 404)
        self.assertEqual(data["error"]["code"], "not_found")

    def test_error_envelope_has_no_traceback(self):
        status, data = self.request("POST", "/api/config", {"config": {"schema_version": 9}})
        self.assertEqual(status, 400)
        self.assertEqual(set(data["error"]), {"code", "message", "details"})
        self.assertNotIn("Traceback", json.dumps(data))


class J10ReadEndpoints(ServerCase):
    def test_all_read_routes(self):
        for path in ("/api/runs", "/api/knowledge", "/api/plans", "/api/executions", "/api/trash",
                     "/api/status", "/api/state", "/api/codex", "/api/ai"):
            with self.subTest(path=path):
                status, _ = self.request("GET", path)
                self.assertEqual(status, 200, path)


class J11TrashEndpoints(ServerCase):
    def test_trash_and_restore(self):
        from trade_assistant.plans import Plans
        plans = Plans(self.app.engine)
        plan = plans.manual({"asset_id": "sh000300", "name": "沪深300", "plan_type": "observation",
                             "basis": {"logic": "x", "technical": "y", "mode": "z"},
                             "entry": "", "exit": "", "position_risk": "", "validity": "", "missing": []})
        status, data = self.request("POST", "/api/objects/%s/trash" % plan["id"],
                                    {"expected_revision": 1, "actor": "翔宇"})
        self.assertEqual(status, 200)
        self.assertTrue(data["is_deleted"])
        self.assertIn(plan["id"], [x["id"] for x in self.request("GET", "/api/trash")[1]])

        status, data = self.request("POST", "/api/objects/%s/restore" % plan["id"],
                                    {"expected_revision": 1, "actor": "翔宇"})
        self.assertEqual(status, 200)
        self.assertFalse(data["is_deleted"])

    def test_revision_conflict(self):
        from trade_assistant.plans import Plans
        plans = Plans(self.app.engine)
        plan = plans.manual({"asset_id": "sh000300", "name": "沪深300", "plan_type": "observation",
                             "basis": {"logic": "x", "technical": "y", "mode": "z"},
                             "entry": "", "exit": "", "position_risk": "", "validity": "", "missing": []})
        status, data = self.request("POST", "/api/objects/%s/trash" % plan["id"],
                                    {"expected_revision": 99, "actor": "翔宇"})
        self.assertEqual(status, 409)

    def test_knowledge_cannot_be_trashed(self):
        item = self.app.engine.knowledge.create("logic", {"title": "t", "body": "b", "layers": ["logic"]})
        status, data = self.request("POST", "/api/objects/%s/trash" % item["id"],
                                    {"expected_revision": 1, "actor": "翔宇"})
        self.assertEqual(status, 400)


class J12Report(ServerCase):
    def setUp(self):
        self.run_id = build_run(self.app.store)

    def test_report_is_self_contained(self):
        status, html = self.request("GET", "/api/runs/%s/report" % self.run_id)
        self.assertEqual(status, 200)
        self.assertIn("<!doctype html>", html)
        self.assertIsNone(EXTERNAL.search(html))
        self.assertNotIn("__P03_TOKEN__", html)
        self.assertNotIn(self.app.token, html)
        self.assertGreater(len(html), 2000)

    def test_report_shows_gaps(self):
        _, html = self.request("GET", "/api/runs/%s/report" % self.run_id)
        self.assertIn("行业资金表缺失", html)

    def test_run_view_contains_presentation_and_charts(self):
        status, data = self.request("GET", "/api/runs/%s" % self.run_id)
        self.assertEqual(status, 200)
        for key in ("presentation", "charts", "market_charts"):
            self.assertIn(key, data)
        self.assertIn("sh000300", data["charts"])
        for period in ("daily", "weekly"):
            self.assertIn(period, data["charts"]["sh000300"])

    def test_missing_run(self):
        status, data = self.request("GET", "/api/runs/doesnotexist")
        self.assertEqual(status, 404)


class J14ScheduleControl(ServerCase):
    """REQ-002 RQ02：每次启动默认关闭；用户主动打开后按小时运行。"""

    def test_startup_forces_schedule_off(self):
        config = self.settings.load()
        config["auto_refresh"] = True
        self.settings.save(config)
        try:
            fresh = App(self.settings)
            try:
                self.assertFalse(self.settings.load()["auto_refresh"])
                self.assertIsNone(fresh.runner.status()["next_refresh"])
            finally:
                fresh.runner.stop()
        finally:
            config["auto_refresh"] = False
            self.settings.save(config)

    def test_user_can_open_schedule_from_the_page(self):
        config = self.settings.load()
        config["auto_refresh"] = True
        try:
            status, _ = self.request("PUT", "/api/config", {"config": config})
            self.assertEqual(status, 200)
            self.assertTrue(self.settings.load()["auto_refresh"])
            _, data = self.request("GET", "/api/status")
            self.assertTrue(data["auto_refresh"])
            self.assertTrue(data["next_refresh"], "打开后应给出下一次触发时间")
            self.assertEqual(data["refresh_seconds"], 3600)
        finally:
            config["auto_refresh"] = False
            self.settings.save(config)

    def test_closed_schedule_has_no_next_run(self):
        _, data = self.request("GET", "/api/status")
        self.assertFalse(data["auto_refresh"])
        self.assertIsNone(data["next_refresh"])
        self.assertIsNone(data["active"])


class J16Export(ServerCase):
    def test_archive_is_versioned_and_secret_free(self):
        status, data = self.request("GET", "/api/export")
        self.assertEqual(status, 200)
        self.assertEqual(data["archive_version"], 2)
        self.assertFalse(data["config"]["auto_refresh"])
        self.assertNotIn("api_key", json.dumps(data, ensure_ascii=False))


class K02JobMutex(ServerCase):
    def test_second_job_is_rejected(self):
        started, release = threading.Event(), threading.Event()

        def handler():
            started.set()
            release.wait(10)
            return {"ok": True}

        first = self.app.runner.start("analysis", handler)
        self.assertTrue(started.wait(5))
        try:
            status, data = self.request("POST", "/api/run", {})
            self.assertEqual(status, 409)
            self.assertEqual(data["error"]["code"], "busy")
            job = self.request("GET", "/api/jobs/%s" % first["job_id"])[1]
            self.assertEqual(job["id"], first["job_id"])
        finally:
            release.set()
            self.app.runner.worker.join(timeout=10)

    def test_cancel_endpoint_is_acknowledged(self):
        status, data = self.request("POST", "/api/cancel", {})
        self.assertEqual(status, 200)
        self.assertTrue(data["requested"])


class K01InstanceLock(unittest.TestCase):
    def test_second_lock_is_rejected(self):
        home = temp_home()
        with InstanceLock(home):
            assert_error(self, "already_running", InstanceLock(home).__enter__)

    def test_lock_is_reusable_after_release(self):
        home = temp_home()
        with InstanceLock(home):
            pass
        with InstanceLock(home):
            pass


class K05Interrupted(ServerCase):
    def test_running_rows_are_marked_interrupted(self):
        ident = self.app.store.create_run(metadata={})
        self.app.store.mark_interrupted()
        self.assertEqual(self.app.store.get_run(ident)["status"], "interrupted")
        error = self.app.store.get_run(ident)["error"]
        self.assertEqual(error["code"], "interrupted")


class K07RunWithoutAi(ServerCase):
    def test_partial_with_skip_reason(self):
        snapshot = make_snapshot([candidate("sh000300")], {"sh000300": history_for("sh000300")})
        run = self.app.engine.run(lambda *a: None, snapshot=snapshot, no_ai=True, trigger="manual")
        self.assertEqual(run["status"], "partial")
        self.assertEqual(run["error"]["code"], "ai_skipped")
        self.assertEqual(run["metadata"]["input_mode"], "saved_snapshot")

    def test_evidence_keeps_snapshot_date(self):
        snapshot = make_snapshot([candidate("sh000300")], {"sh000300": history_for("sh000300")})
        run = self.app.engine.run(lambda *a: None, snapshot=snapshot, no_ai=True)
        self.assertEqual(run["metadata"]["asof"], ANCHOR)
        self.assertEqual(run["facts"]["asof"], ANCHOR)

    def test_failed_snapshot_marks_run_failed(self):
        bad = {"schema_version": 1}
        with self.assertRaises(Exception):
            self.app.engine.run(lambda *a: None, snapshot=bad, no_ai=True)
        failed = [x for x in self.app.store.list_runs(50) if x["status"] == "failed"]
        self.assertTrue(failed, "失败轮次必须留痕")
        self.assertTrue(failed[0]["error"]["message"])


class J25FrontendContract(ServerCase):
    """REQ-004 R2：每卡独立的均线显示配置，默认只有 MA20，选择保存在浏览器本地。"""

    def assets(self):
        return self.request("GET", "/app.js")[1], self.request("GET", "/")[1]

    def test_default_is_only_ma20(self):
        script, _ = self.assets()
        self.assertIn("chartMaChoices[id]=Array.isArray(saved)", script)
        self.assertIn(":[20];", script)

    def test_choice_persisted_in_browser_storage(self):
        script, _ = self.assets()
        self.assertIn("localStorage.getItem('p03.chart.ma.'+id)", script)
        self.assertIn("localStorage.setItem('p03.chart.ma.'+id", script)

    def test_only_supported_periods_are_accepted(self):
        script, _ = self.assets()
        self.assertIn("[5,20,60,120].includes(x)", script)
        self.assertIn("![5,20,60,120].includes(p)", script)

    def test_period_switch_is_per_card(self):
        script, _ = self.assets()
        self.assertIn("chartPeriods[id]=period", script)
        self.assertIn('data-action="card-period"', script)

    def test_no_page_level_period_switch(self):
        _, html = self.assets()
        self.assertNotIn('data-action="period"', html)
        self.assertIn("card-period", self.assets()[0])

    def test_ma_choices_are_rendered_per_card(self):
        script, _ = self.assets()
        self.assertIn('data-ma-period="${p}"', script)
        self.assertIn('data-ma="${p}"', script)


class K11CommandLine(unittest.TestCase):
    def run_cli(self, *args, home=None):
        home = home or temp_home()
        command = [PYTHON, str(PROJECT / "src" / "trade.py"), "--home", str(home)] + list(args)
        return subprocess.run(command, capture_output=True, text=True, timeout=120)

    def test_status(self):
        result = self.run_cli("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("knowledge_count", payload)

    def test_missing_input_file_fails_loudly(self):
        """输入文件不存在时必须非零退出，不能静默成功。"""
        result = self.run_cli("compute", "--input", str(PROJECT / "does-not-exist.json"))
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip())

    def test_report_requires_existing_run(self):
        result = self.run_cli("report", "--run-id", "missing", "--output", str(temp_home() / "r.html"))
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_port_validation(self):
        result = self.run_cli("serve", "--port", "70000")
        self.assertEqual(result.returncode, 1)
        self.assertIn("validation_error", result.stderr)

    def test_compute_on_fixture_snapshot(self):
        home = temp_home()
        snapshot = make_snapshot([candidate("sh000300")], {"sh000300": history_for("sh000300")})
        snapshot_path = home / "snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        output = home / "facts.json"
        result = self.run_cli("compute", "--input", str(snapshot_path), "--output", str(output), home=home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output.is_file())
        facts = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(facts["asof"], ANCHOR)
        self.assertEqual(facts["schema_version"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
