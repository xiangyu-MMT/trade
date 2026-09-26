import json
from pathlib import Path

from .store import reference
from .util import AppError, require_text
from .markets import market, scope

LAYERS = {"logic", "technical", "mode"}


class Knowledge:
    def __init__(self, store):
        self.store = store

    def seed(self):
        path = Path(__file__).parent / "defaults" / "knowledge.json"
        items = json.loads(path.read_text(encoding="utf-8"))
        for item in items:
            try:
                self.store.get_object(item["id"])
            except AppError as exc:
                if exc.status != 404:
                    raise
                self.store.create(item["kind"], item["payload"], item["id"],
                                  status="confirmed", actor="翔宇（需求原话归档）")
        current = self.store.get_object("technical-system")
        old_periods = "5日、20日、60日、120日"
        if current["revision"] == 1 and current["status"] == "confirmed" and old_periods in current["payload"].get("body", ""):
            payload = dict(current["payload"])
            payload["body"] = payload["body"].replace(old_periods, "5日、20日")
            payload["source"] += "；翔宇2026-09-25本轮明确原话：均线只要5日均线和20日均线（REQ-004 R1）"
            updated = self.store.revise(current["id"], payload, current["revision"])
            self.store.confirm(updated["id"], updated["revision"], "翔宇（本轮明确原话归档）")
        us_items = json.loads((path.parent / "us_knowledge.json").read_text(encoding="utf-8"))
        for item in us_items:
            try:
                self.store.get_object(item["id"])
            except AppError as exc:
                if exc.status != 404:
                    raise
                status = item.get("status", "draft")
                self.store.create(item["kind"], item["payload"], item["id"], status=status,
                                  actor="翔宇（REQ-005原话归档）" if status == "confirmed" else None)

    @staticmethod
    def validate(payload):
        if not isinstance(payload, dict):
            raise AppError("validation_error", "知识内容需要对象")
        result = dict(payload)
        result["market_scope"] = scope(payload)
        result["analysis_market"] = market(payload.get("analysis_market", result["market_scope"][0]))
        result["title"] = require_text(payload.get("title"), "标题", 150)
        result["body"] = require_text(payload.get("body"), "定义/内容", 20000)
        layers = payload.get("layers")
        if not isinstance(layers, list) or not layers or not set(layers).issubset(LAYERS):
            raise AppError("validation_error", "layers 需包含 logic、technical、mode 中的一项或多项")
        result["source"] = require_text(payload.get("source", "用户录入"), "来源", 2000)
        if payload.get("usage", "general") not in ("general", "risk"):
            raise AppError("validation_error", "知识用途应为 general 或 risk")
        if "evidence" in payload and (not isinstance(payload["evidence"], list) or any(not isinstance(x, str) for x in payload["evidence"])):
            raise AppError("validation_error", "证据需为文本列表")
        return result

    def create(self, kind, payload):
        if kind not in LAYERS:
            raise AppError("validation_error", "知识种类应为 logic、technical 或 mode")
        return self.store.create(kind, self.validate(payload))

    def revise(self, ident, payload, revision):
        old = self.store.get_object(ident)
        if old["kind"] not in LAYERS:
            raise AppError("validation_error", "该对象不是知识条目")
        return self.store.revise(ident, self.validate(payload), revision)

    def confirm(self, ident, revision, actor):
        if self.store.get_object(ident, revision)["kind"] not in LAYERS:
            raise AppError("validation_error", "该对象不是知识条目")
        return self.store.confirm(ident, revision, actor)

    def list(self, confirmed=False, analysis_market=None):
        return [x for x in self.store.list_objects(confirmed=confirmed, analysis_market=analysis_market) if x["kind"] in LAYERS]

    def context(self, analysis_market="CN"):
        return [{"ref": reference(x), "kind": x["kind"], **x["payload"]} for x in self.list(True, market(analysis_market))]
