#!/usr/bin/env python3
"""Thin command-line entry for the P03 local application."""
import argparse
import json
import sys
from pathlib import Path

from trade_assistant.config import Settings
from trade_assistant.util import AppError, dumps, write_json


def main():
    parser = argparse.ArgumentParser(description="P03 trade 交易辅助系统")
    parser.add_argument("--home", help="本地配置与数据目录，默认项目 .local/")
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect", help="获取真实免费行情快照")
    collect.add_argument("--output", help="将快照写入指定 JSON 文件")
    calculate = sub.add_parser("compute", help="由已有真实快照计算指标与全市场事实")
    calculate.add_argument("--input", required=True)
    calculate.add_argument("--output")
    sub.add_parser("status", help="查看本地档案和运行状态")
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
        elif args.command == "compute":
            from trade_assistant.facts import compute
            result = compute(json.loads(Path(args.input).read_text(encoding="utf-8")))
            if args.output:
                write_json(args.output, result)
                print(dumps({"snapshot_id": result["snapshot_id"], "asof": result["asof"],
                             "candidates": len(result["candidates"]), "market": result["market"], "output": args.output}, True))
            else:
                print(dumps(result, True))
        elif args.command == "status":
            from trade_assistant.store import Store
            from trade_assistant.knowledge import Knowledge
            store = Store(settings.home)
            knowledge = Knowledge(store)
            knowledge.seed()
            print(dumps({"home": str(settings.home), "knowledge_count": len(knowledge.list()), "runs": store.list_runs()}, True))
    except AppError as exc:
        print(dumps({"error": exc.as_dict()}, True), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
