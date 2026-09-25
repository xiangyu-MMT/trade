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
    analyze = sub.add_parser("analyze", help="用已确认档案与已有事实调用 Codex")
    analyze.add_argument("--input", required=True)
    analyze.add_argument("--output")
    run = sub.add_parser("run", help="执行并保存完整分析轮次")
    run.add_argument("--snapshot", help="使用已保存真实快照，保留原始数据日期")
    run.add_argument("--no-ai", action="store_true", help="仅生成程序事实，并明确标记AI未执行")
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
        elif args.command in ("run", "analyze"):
            from trade_assistant.engine import Engine
            engine = Engine(settings)
            if args.command == "analyze":
                result = engine.analyze(json.loads(Path(args.input).read_text(encoding="utf-8")))
                if args.output:
                    write_json(args.output, result)
                    print(dumps({"coverage": result["coverage"], "trace": result["trace"], "output": args.output}, True))
                else:
                    print(dumps(result, True))
            else:
                snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8")) if args.snapshot else None
                result = engine.run(lambda stage, detail: print(stage + "：" + detail, file=sys.stderr, flush=True), snapshot, args.no_ai)
                print(dumps({k: result[k] for k in ("id", "status", "created_at", "finished_at", "error", "metadata")}, True))
    except AppError as exc:
        print(dumps({"error": exc.as_dict()}, True), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
