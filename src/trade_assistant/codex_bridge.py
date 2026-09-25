import json
import os
import re
import signal
import shutil
import subprocess
import time
from pathlib import Path

from .util import AppError, digest, dumps, new_id, now, write_json

RESOURCES = Path(__file__).parent


def validate_shape(value, schema, path="response"):
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind]
    checks = {"object": lambda x: isinstance(x, dict), "array": lambda x: isinstance(x, list),
              "string": lambda x: isinstance(x, str), "number": lambda x: type(x) in (int, float),
              "integer": lambda x: type(x) is int, "boolean": lambda x: type(x) is bool,
              "null": lambda x: x is None}
    if not any(checks.get(k, lambda x: True)(value) for k in kinds):
        raise AppError("invalid_ai_output", path + " 的类型不符合约定", status=503)
    if "enum" in schema and value not in schema["enum"]:
        raise AppError("invalid_ai_output", path + " 的值不在允许集合中", status=503)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if any(key not in value for key in schema.get("required", [])):
            raise AppError("invalid_ai_output", path + " 缺少必要字段", status=503)
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise AppError("invalid_ai_output", path + " 含额外字段", status=503)
        for key in set(value) & set(properties):
            validate_shape(value[key], properties[key], path + "." + key)
    elif isinstance(value, list):
        if len(value) > 1000:
            raise AppError("invalid_ai_output", path + " 数组过长", status=503)
        for i, item in enumerate(value):
            validate_shape(item, schema.get("items", {}), "%s[%s]" % (path, i))
    elif isinstance(value, str) and len(value) > 30000:
        raise AppError("invalid_ai_output", path + " 文本过长", status=503)


def redact(text):
    return re.sub(r"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,})", "[已隐藏凭据]", text)


class CodexBridge:
    def __init__(self, settings):
        self.settings = settings
        self.process = None

    @staticmethod
    def command_prefix(command):
        resolved = shutil.which(command) or command
        if os.name == "nt" and str(resolved).lower().endswith((".cmd", ".bat")):
            entry = Path(resolved).parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            node = shutil.which("node")
            if not entry.is_file() or not node:
                raise AppError("codex_path", "Windows请配置实际Codex可执行文件，或使用标准npm安装的Codex与Node22", status=503)
            version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
            if not version.startswith("v22."):
                raise AppError("node_version", "本项目要求Node22.x，当前为" + version, status=503)
            return [node, str(entry)]
        return [resolved]

    def cancel(self):
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            pass

    def availability(self):
        config = self.settings.load()["ai"]
        try:
            result = subprocess.run(self.command_prefix(config["command"]) + ["login", "status"], capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=15)
            message = (result.stdout + result.stderr).lower()
            kind = "ChatGPT" if "chatgpt" in message else "API-key" if "api key" in message else "unknown"
            return {"available": result.returncode == 0 and kind == "ChatGPT", "auth_kind": kind,
                    "enabled": config["enabled"]}
        except (OSError, subprocess.TimeoutExpired, AppError):
            return {"available": False, "auth_kind": "not-found", "enabled": config["enabled"]}

    def call(self, purpose, payload):
        if purpose not in ("analysis", "plan", "review"):
            raise AppError("validation_error", "不支持的推导类型")
        cfg = self.settings.load()["ai"]
        if not cfg["enabled"]:
            raise AppError("ai_disabled", "当前配置已关闭 Codex 推导", status=503)
        auth = self.availability()
        if not auth["available"]:
            raise AppError("codex_auth", "请在当前电脑用 ChatGPT 会员登录 Codex；本系统不自动切换到付费 API", auth, 503)
        schema_path = RESOURCES / "schemas" / (purpose + ".json")
        template_path = RESOURCES / "prompts" / (purpose + ".txt")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        run_dir = self.settings.home / "ai" / new_id()
        run_dir.mkdir(parents=True, exist_ok=False)
        input_path, output_path = run_dir / "input.json", run_dir / "result.json"
        write_json(input_path, payload)
        prompt = template_path.read_text(encoding="utf-8") + "\n\n以下是本次输入资料JSON：\n" + dumps(payload)
        if len(prompt.encode("utf-8")) > 400000:
            raise AppError("ai_input_size", "本轮推导资料过大，请减少候选或归档正文后重试")
        command = self.command_prefix(cfg["command"]) + ["exec", "--ignore-user-config", "--sandbox", "read-only",
                   "--skip-git-repo-check", "--ephemeral", "--json", "--color", "never",
                   "--output-schema", str(schema_path), "--output-last-message", str(output_path),
                   "-c", "project_doc_max_bytes=0", "-c", 'web_search="disabled"']
        for feature in ("shell_tool", "apps", "plugins", "browser_use", "computer_use", "multi_agent",
                        "skill_search", "hooks", "image_generation", "view_image", "sleep_tool", "code_mode_host"):
            command.extend(["--disable", feature])
        command.append("-")
        env = dict(os.environ)
        for key in ("OPENAI_API_KEY", "CODEX_API_KEY"):
            env.pop(key, None)
        start = time.monotonic()
        kwargs = {"cwd": str(run_dir), "env": env, "stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
                  "stderr": subprocess.PIPE, "text": True, "encoding": "utf-8", "errors": "replace"}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        process = None
        try:
            process = subprocess.Popen(command, **kwargs)
            self.process = process
            stdout, stderr = process.communicate(prompt, timeout=cfg["timeout"])
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            else:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            (run_dir / "stdout.jsonl").write_text(redact(stdout), encoding="utf-8")
            (run_dir / "stderr.log").write_text(redact(stderr), encoding="utf-8")
            raise AppError("codex_timeout", "Codex 推导超时，本轮资料已保留", {"record": str(run_dir)}, 503)
        except OSError as exc:
            raise AppError("codex_start", "无法启动 Codex", {"reason": str(exc)}, 503) from exc
        finally:
            self.process = None
        (run_dir / "stdout.jsonl").write_text(redact(stdout), encoding="utf-8")
        (run_dir / "stderr.log").write_text(redact(stderr), encoding="utf-8")
        trace = {"purpose": purpose, "created_at": now(), "seconds": round(time.monotonic() - start, 2),
                 "record_id": run_dir.name,
                 "input_hash": digest(payload), "exit_code": process.returncode, "record": str(run_dir),
                 "auth_kind": auth["auth_kind"], "schema": schema_path.name}
        write_json(run_dir / "trace.json", trace)
        if process.returncode != 0 or not output_path.exists():
            raise AppError("codex_failed", "Codex 未完成本轮推导", {**trace, "diagnostic": redact(stderr)[-1500:]}, 503)
        try:
            result = json.loads(output_path.read_text(encoding="utf-8"))
            validate_shape(result, schema)
            dumps(result)
        except (ValueError, TypeError) as exc:
            raise AppError("invalid_ai_output", "Codex 返回内容无法解析", trace, 503) from exc
        trace["output_hash"] = digest(result)
        write_json(run_dir / "trace.json", trace)
        return {"result": result, "trace": trace}
