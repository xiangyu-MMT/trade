import json
import secrets
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit, parse_qs

from . import __version__
from .config import validate
from .engine import Engine
from .plans import Plans
from .report import render
from .runner import Runner
from .presentation import select
from .charts import candles, dashboard_charts
from .util import AppError, dumps
from .markets import market, run_market

WEB = Path(__file__).parent / "web"


class App:
    def __init__(self, settings):
        self.settings = settings
        config = settings.load()
        config["auto_refresh"] = False
        settings.save(config)
        self.engine = Engine(settings)
        self.store, self.knowledge = self.engine.store, self.engine.knowledge
        self.plans = Plans(self.engine)
        self.store.mark_interrupted()
        self.runner = Runner(settings, self.store, self.engine.cancel, self.engine.cancelled.clear)
        self.token = secrets.token_hex(32)
        self.pairing_previews = {}
        self.runner.start_scheduler(lambda: self.run("timer"))

    def run(self, trigger, selected=None):
        cfg = self.settings.load()
        markets = cfg["scheduled_markets"] if trigger == "timer" else [market(selected or cfg["active_market"])]
        results = []
        for selected in markets:
            if results and self.engine.cancelled.is_set():
                break
            def progress(stage, detail):
                self.runner.progress(("美股" if selected == "US" else "A股") + " · " + stage, detail)
            run = self.engine.run(progress, trigger=trigger, market=selected)
            results.append({"run_id": run["id"], "market": selected, "status": run["status"], "error": run.get("error")})
        return {**results[-1], "runs": results}

    def state(self, selected=None):
        selected = market(selected or self.settings.load()["active_market"])
        runs = self.store.list_runs(analysis_market=selected)
        latest = next((x["id"] for x in runs if x["status"] in ("completed", "partial")), None)
        return {"version": __version__, "analysis_market": selected, "scheduled_markets": self.settings.load()["scheduled_markets"], **self.runner.status(), "runs": runs, "latest_report_id": latest,
                "knowledge": self.knowledge.list(analysis_market=selected), "confirmed_knowledge": self.knowledge.list(True, selected),
                "plans": self.store.list_objects("plan", analysis_market=selected), "confirmed_plans": self.store.list_objects("plan", confirmed=True, analysis_market=selected),
                "executions": self.store.list_objects("execution", analysis_market=selected)[:200],
                "trash": [x for x in self.store.list_objects(include_deleted=True, analysis_market=selected) if x["is_deleted"]],
                "lifecycle": self.store.lifecycle(),
                "reviews": self.store.list_objects("review", analysis_market=selected)[:100], "config_path": str(self.settings.path)}

    def run_view(self, ident):
        run = self.store.get_run(ident)
        result = {k: run[k] for k in ("id", "status", "created_at", "finished_at", "facts", "analysis", "error", "metadata")}
        result["knowledge_used"] = []
        if run.get("facts"):
            result["presentation"] = select(result["facts"], run.get("analysis"))
            result["charts"] = {x["asset_id"]: {p: candles(x["technical"], p) for p in ("daily", "weekly")} for x in result["facts"]["candidates"]}
            result["market_charts"] = dashboard_charts(result["facts"])
        for ref in (run.get("analysis") or {}).get("knowledge_refs", []):
            try:
                result["knowledge_used"].append(self.store.get_ref(ref))
            except AppError:
                result["knowledge_used"].append({"ref": ref, "payload": {"title": "引用条目暂不可读取"}})
        if (result.get("facts") or {}).get("analysis_market") == "US":
            from .us_report import chart_data
            result["market_charts"] = chart_data(result["facts"])
        return result

    def report(self, ident):
        run = self.store.get_run(ident)
        if not run.get("facts"):
            raise AppError("no_report", "该轮没有可导出的事实与报告", status=404)
        return render(run)

    def import_data(self, body):
        if not self.runner.operation_lock.acquire(False):
            raise AppError("busy", "请在分析/计划任务结束后迁移资料", status=409)
        try:
            archive = body.get("archive")
            if not isinstance(archive, dict):
                raise AppError("validation_error", "缺少迁移文件内容")
            incoming = validate(archive.get("config"))
            incoming["auto_refresh"] = False
            original = self.settings.load()
            apply_config = body.get("apply_config", True)
            if type(apply_config) is not bool:
                raise AppError("validation_error", "apply_config 必须是布尔值")
            if apply_config:
                self.settings.save(incoming)
            try:
                result = self.store.import_data(archive)
            except Exception:
                if apply_config:
                    self.settings.save(original)
                raise
            return {**result, "config_applied": apply_config}
        finally:
            self.runner.operation_lock.release()

    def create_proposal(self, body):
        run = self.store.get_run(body.get("run_id"))
        index = body.get("index")
        items = ((run.get("analysis") or {}).get("result") or {}).get("knowledge_proposals", [])
        if type(index) is not int or not 0 <= index < len(items):
            raise AppError("not_found", "分析建议不存在", status=404)
        item = items[index]
        return self.knowledge.create(item["kind"], {"title": item["title"], "body": item["body"],
                                                   "analysis_market": run_market(run), "market_scope": [run_market(run)],
                                                   "layers": [item["kind"]], "source": "AI分析建议，待确认",
                                                   "run_id": run["id"], "evidence": item["evidence_refs"]})


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "P03/0.1"

        def log_message(self, fmt, *args):
            if len(args) > 1 and str(args[1]).startswith(("4", "5")):
                print("HTTP", fmt % args, file=sys.stderr)

        def valid_host(self):
            port = self.server.server_address[1]
            return self.headers.get("Host", "") in {"127.0.0.1:%s" % port, "localhost:%s" % port}

        def authorize(self):
            if not self.valid_host():
                raise AppError("forbidden", "只允许本机地址访问", status=403)
            port = self.server.server_address[1]
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://127.0.0.1:%s" % port, "http://localhost:%s" % port}:
                raise AppError("forbidden", "请求来源不受允许", status=403)
            if not secrets.compare_digest(self.headers.get("X-P03-Token", ""), app.token):
                raise AppError("forbidden", "页面会话已失效，请刷新本地页面", status=403)

        def send(self, content, status=200, mime="application/json; charset=utf-8", filename=None):
            raw = content.encode("utf-8") if isinstance(content, str) else content
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            if filename:
                self.send_header("Content-Disposition", 'attachment; filename="' + filename + '"')
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def json(self, data, status=200):
            self.send(dumps(data), status)

        def body(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise AppError("validation_error", "请求长度无效")
            try:
                maximum = app.settings.load().get("max_import_bytes", 104857600)
            except AppError:
                maximum = 104857600
            if size <= 0 or size > maximum:
                raise AppError("request_size", "请求为空或超过导入大小上限", status=413)
            if "application/json" not in self.headers.get("Content-Type", ""):
                raise AppError("validation_error", "请求需要 application/json", status=415)
            try:
                value = json.loads(self.rfile.read(size).decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise AppError("validation_error", "请求不是有效 UTF-8 JSON")
            if not isinstance(value, dict):
                raise AppError("validation_error", "请求正文需要 JSON 对象")
            return value

        def guarded(self, fn):
            try:
                fn()
            except AppError as exc:
                self.json({"error": exc.as_dict()}, exc.status)
            except (ValueError, TypeError, KeyError) as exc:
                self.json({"error": {"code": "validation_error", "message": "输入结构无效：" + str(exc)}}, 400)
            except (OSError, sqlite3.Error) as exc:
                self.json({"error": {"code": "storage_error", "message": "本地读写失败：" + str(exc)}}, 500)
            except Exception as exc:
                print("P03 request error:", type(exc).__name__, str(exc), file=sys.stderr)
                self.json({"error": {"code": "internal_error", "message": "处理失败，请查看本地服务输出"}}, 500)

        def do_GET(self):
            self.guarded(self.read)

        def read(self):
            if not self.valid_host():
                raise AppError("forbidden", "只允许本机访问", status=403)
            path = unquote(urlsplit(self.path).path)
            query = parse_qs(urlsplit(self.path).query)
            selected = market(query.get("market", ["CN"])[0])
            if path in ("/", "/index.html"):
                text = (WEB / "index.html").read_text(encoding="utf-8").replace("__P03_TOKEN__", app.token)
                self.send(text, mime="text/html; charset=utf-8")
            elif path in ("/app.js", "/us.js", "/style.css"):
                mime = "text/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8"
                self.send((WEB / path[1:]).read_bytes(), mime=mime)
            elif path == "/favicon.ico":
                self.send(b"", 204, mime="image/x-icon")
            elif path == "/api/state":
                self.json(app.state(selected))
            elif path == "/api/status":
                self.json(app.runner.status())
            elif path == "/api/config":
                try:
                    self.json({"config": app.settings.load(), "path": str(app.settings.path)})
                except AppError as exc:
                    self.json({"config": None, "raw": app.settings.path.read_text(encoding="utf-8"), "path": str(app.settings.path), "error": exc.as_dict()})
            elif path == "/api/codex":
                self.json(app.engine.bridge.availability())
            elif path == "/api/ai":
                self.json({"config": app.settings.load()["ai"], **app.engine.bridge.credentials.status()})
            elif path == "/api/runs":
                self.json(app.store.list_runs(analysis_market=selected))
            elif path == "/api/us/pairings":
                self.json({"pairings": app.store.list_objects("pairing", analysis_market="US")})
            elif path.startswith("/api/us/pairings/previews/"):
                ident = path.split("/")[-1]
                if ident not in app.pairing_previews:
                    raise AppError("not_found", "筛选预览已失效，请重新获取", status=404)
                self.json(app.pairing_previews[ident])
            elif path.startswith("/api/runs/"):
                parts = path.split("/")
                if len(parts) == 5 and parts[4] == "report":
                    self.send(app.report(parts[3]), mime="text/html; charset=utf-8")
                elif len(parts) == 4:
                    self.json(app.run_view(parts[3]))
                else:
                    raise AppError("not_found", "接口不存在", status=404)
            elif path.startswith("/api/jobs/"):
                self.json(app.store.get_job(path.split("/")[-1]))
            elif path == "/api/knowledge":
                self.json(app.knowledge.list(analysis_market=selected))
            elif path.startswith("/api/knowledge/") and path.endswith("/versions"):
                self.json(app.store.versions(path.split("/")[-2]))
            elif path == "/api/plans":
                self.json(app.store.list_objects("plan", analysis_market=selected))
            elif path.startswith("/api/plans/") and path.endswith("/versions"):
                self.json(app.store.versions(path.split("/")[-2]))
            elif path == "/api/executions":
                self.json(app.store.list_objects("execution", analysis_market=selected))
            elif path == "/api/trash":
                self.json([x for x in app.store.list_objects(include_deleted=True, analysis_market=selected) if x["is_deleted"]])
            elif path == "/api/export":
                if not app.runner.operation_lock.acquire(False):
                    raise AppError("busy", "请在当前任务结束后导出完整资料", status=409)
                try:
                    data = app.store.export_data(app.settings.load())
                    self.send(dumps(data), filename="p03-trade-archive.json")
                finally:
                    app.runner.operation_lock.release()
            else:
                raise AppError("not_found", "页面或接口不存在", status=404)

        def do_POST(self):
            self.guarded(self.write)

        def do_PUT(self):
            self.guarded(self.write)

        def write(self):
            self.authorize()
            body = self.body()
            path = unquote(urlsplit(self.path).path)
            if path == "/api/run":
                app.settings.load()
                selected = market(body.get("market", app.settings.load()["active_market"]))
                self.json(app.runner.start("analysis", lambda: app.run("manual", selected)), 202)
            elif path == "/api/us/pairings/preview":
                from .http_client import HttpClient
                from .etf_pairing import ETFPairing
                index = body.get("index_id")
                def preview():
                    cfg = app.settings.load()["network"]
                    app.runner.progress("ETF筛选", "核实跟踪标的与同20日成交金额，当前配对保持不变")
                    client = HttpClient(app.settings.home, cfg["timeout"], cfg["budget_seconds"])
                    app.engine.collector = SimpleNamespace(http=client)
                    try:
                        result = ETFPairing(client, app.store).preview(index)
                        if app.engine.cancelled.is_set():
                            raise AppError("cancelled", "筛选已停止，未变更配对", status=409)
                    finally:
                        app.engine.collector = None
                    app.pairing_previews[result["id"]] = result
                    return {"preview_id": result["id"]}
                self.json(app.runner.start("pairing", preview), 202)
            elif path == "/api/us/pairings/bind":
                from .etf_pairing import ETFPairing
                preview = app.pairing_previews.get(body.get("preview_id"))
                if not preview or body.get("confirmed") is not True:
                    raise AppError("validation_error", "绑定需要有效预览与明确确认")
                if (datetime.now(timezone.utc) - datetime.fromisoformat(preview["created_at"])).total_seconds() > 900:
                    raise AppError("preview_expired", "筛选预览超过15分钟，请重新读取后确认", status=409)
                if not app.runner.operation_lock.acquire(False):
                    raise AppError("busy", "请在当前任务结束后变更配对", status=409)
                try:
                    self.json(ETFPairing(None, app.store).bind(preview, body.get("asset_id"), body.get("expected_revision")), 201)
                finally:
                    app.runner.operation_lock.release()
            elif path == "/api/cancel":
                app.engine.cancel()
                self.json({"requested": True})
            elif path == "/api/config":
                if not app.runner.operation_lock.acquire(False):
                    raise AppError("busy", "当前任务仍在运行，请完成后保存配置", status=409)
                try:
                    self.json({"config": app.settings.save(body.get("config", body))})
                finally:
                    app.runner.operation_lock.release()
            elif path == "/api/ai":
                if not app.runner.operation_lock.acquire(False):
                    raise AppError("busy", "请在当前任务结束后保存模型配置", status=409)
                try:
                    config = app.settings.load()
                    config["ai"] = body.get("config")
                    config = validate(config)
                    if body.get("api_key") is not None:
                        app.engine.bridge.credentials.save(body["api_key"])
                    app.settings.save(config)
                    self.json({"config": config["ai"], **app.engine.bridge.credentials.status()})
                finally:
                    app.runner.operation_lock.release()
            elif path == "/api/import":
                self.json(app.import_data(body))
            elif path.startswith("/api/objects/"):
                parts = path.split("/")
                if len(parts) != 5 or parts[-1] not in ("trash", "restore"):
                    raise AppError("not_found", "对象操作不存在", status=404)
                if not app.runner.operation_lock.acquire(False):
                    raise AppError("busy", "请在分析/复盘结束后删除或恢复记录", status=409)
                try:
                    self.json(app.store.recycle(parts[-2], parts[-1] == "trash", body.get("expected_revision"), body.get("actor", "翔宇")))
                finally:
                    app.runner.operation_lock.release()
            elif path == "/api/knowledge":
                self.json(app.knowledge.create(body.get("kind"), body.get("payload")), 201)
            elif path == "/api/knowledge/from-run":
                self.json(app.create_proposal(body), 201)
            elif path == "/api/knowledge/from-review":
                self.json(app.plans.knowledge_from_review(body.get("review_id"), body.get("index")), 201)
            elif path.startswith("/api/knowledge/"):
                parts = path.split("/")
                if len(parts) == 5 and parts[-1] == "revise":
                    self.json(app.knowledge.revise(parts[-2], body.get("payload"), body.get("expected_revision")), 201)
                elif len(parts) == 5 and parts[-1] == "confirm":
                    self.json(app.knowledge.confirm(parts[-2], body.get("revision"), body.get("actor", "翔宇")))
                else:
                    raise AppError("not_found", "知识操作不存在", status=404)
            elif path == "/api/plans/manual":
                self.json(app.plans.manual(body.get("payload", body)), 201)
            elif path == "/api/plans/draft":
                def draft():
                    app.runner.progress("拟定计划", "对照所选候选与用户风险规则")
                    obj = app.plans.draft(body.get("run_id"), body.get("asset_id"))
                    return {"object_id": obj["id"], "ref": obj["ref"]}
                self.json(app.runner.start("plan", draft), 202)
            elif path.startswith("/api/plans/"):
                parts = path.split("/")
                if len(parts) == 5 and parts[-1] == "revise":
                    self.json(app.plans.revise(parts[-2], body.get("payload"), body.get("expected_revision")), 201)
                elif len(parts) == 5 and parts[-1] == "confirm":
                    self.json(app.plans.confirm(parts[-2], body.get("revision"), body.get("actor", "翔宇")))
                else:
                    raise AppError("not_found", "计划操作不存在", status=404)
            elif path == "/api/executions":
                self.json(app.plans.execution(body), 201)
            elif path == "/api/reviews":
                def review():
                    app.runner.progress("复盘", "对照原计划版本与人工回填")
                    obj = app.plans.review(body.get("plan_id"), body.get("revision"))
                    return {"object_id": obj["id"], "ref": obj["ref"]}
                self.json(app.runner.start("review", review), 202)
            else:
                raise AppError("not_found", "操作不存在", status=404)

    return Handler


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(settings, port=8765, browser=True):
    app = App(settings)
    try:
        server = LocalServer(("127.0.0.1", port), handler_for(app))
    except OSError as exc:
        app.runner.stop()
        raise AppError("port_unavailable", "端口不可用，请换一个 --port 或使用已运行的服务", {"reason": str(exc)}, 500)
    url = "http://127.0.0.1:%s" % server.server_address[1]
    print(dumps({"ready": True, "url": url, "home": str(settings.home)}), flush=True)
    if browser:
        import subprocess
        import webbrowser
        if sys.platform == "darwin":
            subprocess.run(["open", "-a", "Google Chrome", url], check=False)
        else:
            webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.runner.stop()
        server.server_close()
