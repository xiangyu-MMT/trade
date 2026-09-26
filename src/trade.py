#!/usr/bin/env python3
"""Thin command-line entry for the P03 local application."""
import argparse
import json
import sys
from pathlib import Path

from trade_assistant.config import Settings
from trade_assistant.util import AppError, InstanceLock, dumps, write_json


def main():
    parser = argparse.ArgumentParser(description="P03 trade 交易辅助系统")
    parser.add_argument("--home", help="本地配置与数据目录，默认项目 .local/")
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("collect", help="获取真实免费行情快照")
    collect.add_argument("--output", help="将快照写入指定 JSON 文件")
    collect.add_argument("--market", choices=("CN", "US"), default=None)
    calculate = sub.add_parser("compute", help="由已有真实快照计算指标与全市场事实")
    calculate.add_argument("--input", required=True)
    calculate.add_argument("--output")
    sub.add_parser("status", help="查看本地档案和运行状态")
    sub.add_parser("setup", help="在项目本地目录安装盈利解析依赖")
    analyze = sub.add_parser("analyze", help="用已确认档案与已有事实调用 Codex")
    analyze.add_argument("--input", required=True)
    analyze.add_argument("--output")
    run = sub.add_parser("run", help="执行并保存完整分析轮次")
    run.add_argument("--snapshot", help="使用已保存真实快照，保留原始数据日期")
    run.add_argument("--no-ai", action="store_true", help="仅生成程序事实，并明确标记AI未执行")
    run.add_argument("--market", choices=("CN", "US"), default=None)
    serve = sub.add_parser("serve", help="启动本地HTML交互系统")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-browser", action="store_true")
    export = sub.add_parser("report", help="导出指定分析轮次的自包含HTML")
    export.add_argument("--run-id", required=True)
    export.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        settings = Settings(args.home)
        if args.command in ("setup", "serve") or (args.command in ("collect", "run") and not getattr(args, "snapshot", None) and (args.market or settings.load()["active_market"]) == "US"):
            from trade_assistant.dependencies import ensure
            ensure()
        if args.command == "setup":
            print(dumps({"ready": True, "parsers": ["xlrd", "pypdf", "curl_cffi"], "parquet": "Node22 + hyparquet"}))
            return 0
        if args.command == "collect":
            from trade_assistant.collector import Collector
            if (args.market or settings.load()["active_market"]) == "US":
                from trade_assistant.us_collector import USCollector as Collector
            with InstanceLock(settings.home):
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
                with InstanceLock(settings.home):
                    result = engine.run(lambda stage, detail: print(stage + "：" + detail, file=sys.stderr, flush=True), snapshot, args.no_ai, market=args.market)
                print(dumps({k: result[k] for k in ("id", "status", "created_at", "finished_at", "error", "metadata")}, True))
        elif args.command == "serve":
            from trade_assistant.server import serve
            if not 0 <= args.port <= 65535:
                raise AppError("validation_error", "端口必须为0–65535")
            with InstanceLock(settings.home):
                serve(settings, args.port, not args.no_browser)
        elif args.command == "report":
            from trade_assistant.store import Store
            from trade_assistant.report import render
            run = Store(settings.home).get_run(args.run_id)
            if not run.get("facts"):
                raise AppError("no_report", "该轮没有可导出的报告")
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render(run), encoding="utf-8")
            print(dumps({"output": str(path), "run_id": run["id"]}))
    except AppError as exc:
        print(dumps({"error": exc.as_dict()}, True), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
