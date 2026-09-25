import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .codex_bridge import CodexBridge, RESOURCES, redact, validate_shape
from .credentials import Credentials
from .util import AppError, digest, dumps, new_id, now, write_json


class AIRouter:
    def __init__(self, settings, cancelled):
        self.settings, self.cancelled = settings, cancelled
        self.codex = CodexBridge(settings)
        self.credentials = Credentials(settings.home)
        self.process = None

    def availability(self):
        cfg = self.settings.load()["ai"]
        return {**self.codex.availability(), "provider": cfg["provider"], "deepseek": {**cfg["deepseek"], **self.credentials.status()}}

    def cancel(self):
        self.codex.cancel()
        p = self.process
        if p and p.poll() is None:
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
                else:
                    os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise AppError("cancelled", "本轮已停止，未继续后备调用", status=409)

    def call(self, purpose, payload, validator=None):
        cfg = self.settings.load()["ai"]
        self.check_cancelled()
        if not cfg["enabled"]:
            raise AppError("ai_disabled", "AI解读已关闭，保留程序事实", status=503)
        providers = [cfg["provider"]]
        if providers[0] == "codex" and cfg["deepseek"]["enabled"]:
            providers.append("deepseek")
        failures = []
        for provider in providers:
            self.check_cancelled()
            try:
                reply = self.codex.call(purpose, payload) if provider == "codex" else self.deepseek(purpose, payload)
                self.check_cancelled()
                if validator:
                    validator(reply["result"])
                reply["trace"].update(provider=provider, fallback_used=bool(failures), attempts=failures)
                write_json(Path(reply["trace"]["record"]) / "trace.json", reply["trace"])
                return reply
            except AppError as exc:
                self.check_cancelled()
                failures.append({"provider": provider, **exc.as_dict()})
        raise AppError("ai_unavailable", "AI解读未完成，程序数据和图表已保留", {"attempts": failures}, 503)

    def deepseek(self, purpose, payload):
        cfg = self.settings.load()["ai"]["deepseek"]
        if not cfg["enabled"] or not self.credentials.key():
            raise AppError("deepseek_unconfigured", "DeepSeek未启用或未配置API Key", status=503)
        schema = json.loads((RESOURCES / "schemas" / (purpose + ".json")).read_text(encoding="utf-8"))
        prompt = (RESOURCES / "prompts" / (purpose + ".txt")).read_text(encoding="utf-8")
        prompt += "\n你是当前配置的DeepSeek分析模块。只返回符合下面JSON Schema的JSON对象：\n" + dumps(schema)
        record = self.settings.home / "ai" / new_id()
        record.mkdir(parents=True)
        write_json(record / "input.json", payload)
        trace = {"record_id": record.name, "record": str(record), "created_at": now(), "purpose": purpose,
                 "provider": "deepseek", "model": cfg["model"], "input_hash": digest(payload), "status": "running"}
        write_json(record / "trace.json", trace)
        key = self.credentials.key()
        body = {"model": cfg["model"], "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": dumps(payload)}],
                "response_format": {"type": "json_object"}, "stream": False, "max_tokens": 16000}
        kwargs = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True,
                  "encoding": "utf-8", "errors": "replace"}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        start = time.monotonic()
        try:
            self.check_cancelled()
            self.process = subprocess.Popen([sys.executable, str(RESOURCES / "deepseek_worker.py")], **kwargs)
            raw, stderr = self.process.communicate(dumps({"url": cfg["base_url"].rstrip("/") + "/chat/completions", "key": key, "body": body, "timeout": cfg["timeout"]}), timeout=cfg["timeout"])
            self.check_cancelled()
            raw, stderr = redact(raw.replace(key, "[已隐藏凭据]")), redact(stderr.replace(key, "[已隐藏凭据]"))
            (record / "stdout.jsonl").write_text(raw, encoding="utf-8")
            (record / "stderr.log").write_text(stderr, encoding="utf-8")
            answer = json.loads(raw)
            if answer.get("error"):
                err = answer["error"]
                raise AppError(err["code"], err["message"], status=503)
            response = answer["response"]
            choice = response["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise AppError("deepseek_incomplete", "DeepSeek输出未完整结束", status=503)
            result = json.loads(choice["message"]["content"])
            validate_shape(result, schema)
            dumps(result)
            write_json(record / "result.json", result)
            trace.update(status="completed", model=response.get("model", cfg["model"]), usage=response.get("usage"), output_hash=digest(result))
            return {"result": result, "trace": trace}
        except subprocess.TimeoutExpired:
            self.cancel()
            try:
                self.process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.communicate()
            trace["status"] = "timeout"
            raise AppError("deepseek_timeout", "DeepSeek调用超时", {"record_id": record.name}, 503)
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            trace["status"] = "failed"
            raise AppError("deepseek_invalid", "DeepSeek响应无法解析", {"record_id": record.name, "type": type(exc).__name__}, 503)
        except AppError as exc:
            trace.update(status="failed", error=exc.as_dict())
            raise
        finally:
            trace.update(finished_at=now(), seconds=round(time.monotonic() - start, 2))
            write_json(record / "trace.json", trace)
            self.process = None
