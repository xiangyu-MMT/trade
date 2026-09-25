import base64
import gzip
import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .util import AppError, jsonp, now, write_json


class HttpClient:
    def __init__(self, home, timeout=10, budget_seconds=240):
        self.cache = Path(home) / "cache"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.deadline = time.monotonic() + budget_seconds
        self.attempts = []
        self.lock = threading.Lock()
        self.gate = threading.BoundedSemaphore(4)
        self.next_request = 0.0

    def log(self, row):
        with self.lock:
            self.attempts.append(row)

    def get(self, url, params=None, encoding="utf-8", ttl=0, referer=None, stale=False):
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, safe=",:!")
        key = hashlib.sha256(url.encode()).hexdigest()
        cache_path = self.cache / (key + ".json")
        cached = None
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if ttl and time.time() - cached["saved_epoch"] < ttl:
                result = self._cached(cached, encoding, False)
                self.log({"source": url, "status": "cache", "fetched_at": cached["fetched_at"]})
                return result
        except (OSError, ValueError, KeyError):
            cached = None
        last = None
        for retry in range(2):
            remaining = self.deadline - time.monotonic()
            if remaining < 0.5:
                last = "本轮取数时间预算已用尽"
                break
            with self.lock:
                delay = max(0, self.next_request - time.monotonic())
                self.next_request = max(time.monotonic(), self.next_request) + 0.07
            if delay:
                time.sleep(delay)
            started = time.monotonic()
            headers = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"}
            if referer:
                headers["Referer"] = referer
            try:
                request = urllib.request.Request(url, headers=headers)
                with self.gate:
                    with urllib.request.urlopen(request, timeout=min(self.timeout, remaining)) as response:
                        body = response.read(12 * 1024 * 1024 + 1)
                        if len(body) > 12 * 1024 * 1024:
                            raise ValueError("单次响应超过 12MB")
                        if response.headers.get("Content-Encoding") == "gzip":
                            body = gzip.decompress(body)
                fetched = now()
                record = {"body": base64.b64encode(body).decode("ascii"), "source": url,
                          "fetched_at": fetched, "saved_epoch": time.time()}
                write_json(cache_path, record)
                self.log({"source": url, "status": "ok", "fetched_at": fetched,
                          "bytes": len(body), "seconds": round(time.monotonic() - started, 3)})
                return {"text": body.decode(encoding, "replace"), "source": url,
                        "fetched_at": fetched, "cache_stale": False}
            except (urllib.error.URLError, OSError, ValueError) as exc:
                last = str(exc)
                self.log({"source": url, "status": "failed", "fetched_at": now(),
                          "error": last, "seconds": round(time.monotonic() - started, 3)})
                if isinstance(exc, urllib.error.HTTPError) and 400 <= exc.code < 500:
                    break
                if retry == 0:
                    time.sleep(0.2)
        if stale and cached:
            self.log({"source": url, "status": "stale_cache", "error": last,
                      "fetched_at": cached["fetched_at"]})
            return self._cached(cached, encoding, True)
        raise AppError("source_unavailable", "数据源暂不可用", {"source": url, "reason": last}, 503)

    @staticmethod
    def _cached(record, encoding, stale):
        return {"text": base64.b64decode(record["body"]).decode(encoding, "replace"),
                "source": record["source"], "fetched_at": record["fetched_at"], "cache_stale": stale}

    def data(self, url, **kwargs):
        response = self.get(url, **kwargs)
        response["data"] = jsonp(response.pop("text"))
        return response
