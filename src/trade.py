#!/usr/bin/env python3
"""Thin command-line entry for the P03 local application."""
import argparse
import sys

from trade_assistant.config import Settings
from trade_assistant.util import AppError, dumps, write_json


def main():
    parser = argparse.ArgumentParser(description="P03 trade 交易辅助系统")
    parser.add_argument("--home", help="本地配置与数据目录，默认项目 .local/")
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect", help="获取真实免费行情快照")
    collect.add_argument("--output", help="将快照写入指定 JSON 文件")
    args = parser.parse_args()
    try:
        settings = Settings(args.home)
        if args.command == "collect":
            from trade_assistant.collector import Collector
            result = Collector(settings, lambda stage, detail: print(stage + "：" + detail, file=sys.stderr, flush=True)).collect()
            if args.output:
                write_json(args.output, result)
                print(dumps({"snapshot_id": result["id"], "asof": result["asof"], "candidates": len(result["candidates"]),
                             "histories": len(result["histories"]), "output": args.output, "coverage": result["coverage"]}, True))
            else:
                print(dumps(result, True))
    except AppError as exc:
        print(dumps({"error": exc.as_dict()}, True), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
