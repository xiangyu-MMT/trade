import hashlib
import json
import math
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

CN = timezone(timedelta(hours=8))
PROJECT = Path(__file__).resolve().parents[2]


class AppError(Exception):
    def __init__(self, code, message, details=None, status=400):
        super().__init__(message)
        self.code, self.message, self.details, self.status = code, message, details, status

    def as_dict(self):
        return {"code": self.code, "message": self.message, "details": self.details}


def now():
    return datetime.now(CN).isoformat(timespec="seconds")


def new_id():
    return uuid.uuid4().hex


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(str(value).replace(",", "").replace("%", "").strip())
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def cn_number(value, multiplier=1):
    text = str(value).strip().replace(",", "")
    for unit, scale in (("亿", 1e8), ("万", 1e4)):
        if unit in text:
            n = number(text.split(unit)[0])
            return n * scale if n is not None else None
    n = number(text)
    return n * multiplier if n is not None else None


def epoch_time(value):
    n = number(value)
    if not n or n <= 0:
        return None
    try:
        return datetime.fromtimestamp(n / 1000 if n > 1e12 else n, CN).isoformat(timespec="seconds")
    except (OverflowError, ValueError, OSError):
        return None


def date_text(value):
    s = str(value or "")
    if re.fullmatch(r"\d{8}", s):
        return s[:4] + "-" + s[4:6] + "-" + s[6:]
    if re.match(r"\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    return None


def dumps(value, pretty=False):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      indent=2 if pretty else None, sort_keys=True)


def digest(value):
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement is a normal save; immutable records use new identifiers.
    temp = path.with_name(path.name + ".writing")
    temp.write_text(dumps(value, True) + "\n", encoding="utf-8")
    os.replace(str(temp), str(path))


def jsonp(text):
    positions = [p for p in (text.find("{"), text.find("[")) if p >= 0]
    if not positions:
        raise AppError("source_format", "数据源未返回可识别的 JSON/JSONP", status=503)
    try:
        return json.JSONDecoder().raw_decode(text[min(positions):])[0]
    except ValueError as exc:
        raise AppError("source_format", "数据源 JSON/JSONP 格式变化", status=503) from exc


def require_text(value, field, limit=20000, allow_empty=False):
    if not isinstance(value, str) or len(value) > limit or (not allow_empty and not value.strip()):
        raise AppError("validation_error", "%s 必须是长度不超过 %s 的文本" % (field, limit))
    return value.strip()
