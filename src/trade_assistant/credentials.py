"""Local credentials; deliberately absent from config snapshots and archives."""
import json
import os

from .util import AppError


class Credentials:
    def __init__(self, home):
        self.path = home / "credentials.json"

    def key(self):
        try:
            key = json.loads(self.path.read_text(encoding="utf-8")).get("deepseek_api_key", "")
        except FileNotFoundError:
            key = ""
        except (OSError, ValueError):
            raise AppError("credentials_error", "本机AI凭据文件无法读取", status=503)
        return key or os.environ.get("DEEPSEEK_API_KEY", "")

    def status(self):
        return {"key_configured": bool(self.key()), "environment_key": bool(os.environ.get("DEEPSEEK_API_KEY"))}

    def save(self, key):
        if not isinstance(key, str) or len(key) > 4096 or any(c in key for c in "\r\n\x00"):
            raise AppError("validation_error", "API Key格式无效")
        if self.path.is_symlink():
            raise AppError("credentials_error", "凭据路径不能为链接")
        descriptor = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"deepseek_api_key": key.strip()}, stream)
        os.chmod(str(self.path), 0o600)
        return self.status()
