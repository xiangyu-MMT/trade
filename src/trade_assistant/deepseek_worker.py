"""Bounded network child. Secrets enter stdin only and are never echoed."""
import json
import sys
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    try:
        value = json.load(sys.stdin)
        request = urllib.request.Request(value["url"], data=json.dumps(value["body"], ensure_ascii=False).encode(),
                    headers={"Authorization": "Bearer " + value["key"], "Content-Type": "application/json"}, method="POST")
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=value["timeout"]) as response:
            data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError("response too large")
        result = json.loads(data.decode("utf-8"))
        print(json.dumps({"response": result}, ensure_ascii=False))
    except urllib.error.HTTPError as exc:
        print(json.dumps({"error": {"code": "deepseek_http", "message": "DeepSeek HTTP " + str(exc.code), "http_status": exc.code}}))
    except Exception as exc:
        print(json.dumps({"error": {"code": "deepseek_network", "message": "DeepSeek连接或响应不可用：" + type(exc).__name__}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
