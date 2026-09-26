import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .util import AppError, dumps, new_id, now
from .markets import belongs, market, run_market, scope

KINDS = {"logic", "technical", "mode", "plan", "execution", "review", "pairing"}
STATUSES = {"draft", "confirmed", "recorded", "generated"}
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


def reference(obj):
    return "%s@%s" % (obj["id"], obj["revision"])


def split_reference(value):
    try:
        ident, revision = str(value).rsplit("@", 1)
        revision = int(revision)
        if not IDENTIFIER.fullmatch(ident) or revision < 1:
            raise ValueError()
        return ident, revision
    except (ValueError, TypeError):
        raise AppError("validation_error", "引用格式应为对象ID@版本")


def trace_identifier(trace):
    if re.fullmatch(r"[a-f0-9]{32}", str(trace.get("record_id", ""))):
        return trace["record_id"]
    match = re.search(r"([a-f0-9]{32})[\\/]?$", str(trace.get("record", "")))
    return match.group(1) if match else None


class Store:
    def __init__(self, home):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "trade.sqlite3"
        with self.connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise AppError("database_version", "数据库版本不受当前程序支持", status=500)
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS objects (
                    id TEXT NOT NULL, kind TEXT NOT NULL, revision INTEGER NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
                    confirmed_at TEXT, confirmed_by TEXT, PRIMARY KEY(id, revision)
                );
                CREATE INDEX IF NOT EXISTS objects_kind ON objects(kind, status);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    finished_at TEXT, snapshot TEXT, facts TEXT, analysis TEXT,
                    error TEXT, metadata TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, finished_at TEXT, result TEXT, error TEXT
                );
                CREATE TABLE IF NOT EXISTS object_lifecycle (
                    object_id TEXT PRIMARY KEY, is_deleted INTEGER NOT NULL,
                    updated_at TEXT NOT NULL, actor TEXT NOT NULL
                );
                PRAGMA user_version=2;
            """)

    @contextmanager
    def connection(self, write=False):
        conn = sqlite3.connect(str(self.path), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.commit()
        except Exception:
            if write:
                conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def object_row(row):
        if row is None:
            return None
        item = dict(row)
        item["payload"] = json.loads(item["payload"])
        item["ref"] = reference(item)
        item["is_deleted"] = bool(item.get("is_deleted", False))
        return item

    def get_object(self, ident, revision=None):
        with self.connection() as conn:
            select = "SELECT o.*,COALESCE(l.is_deleted,0) is_deleted FROM objects o LEFT JOIN object_lifecycle l ON o.id=l.object_id "
            if revision is None:
                row = conn.execute(select + "WHERE o.id=? ORDER BY revision DESC LIMIT 1", (ident,)).fetchone()
            else:
                row = conn.execute(select + "WHERE o.id=? AND revision=?", (ident, revision)).fetchone()
        if row is None:
            raise AppError("not_found", "对象或版本不存在", {"id": ident, "revision": revision}, 404)
        return self.object_row(row)

    def get_ref(self, ref):
        return self.get_object(*split_reference(ref))

    def list_objects(self, kind=None, confirmed=False, include_deleted=False, analysis_market=None):
        if kind is not None and kind not in KINDS:
            raise AppError("validation_error", "对象类别无效")
        where, params = [], []
        if kind:
            where.append("kind=?")
            params.append(kind)
        if confirmed:
            where.append("status='confirmed'")
        clause = " WHERE " + " AND ".join(where) if where else ""
        # Keep grouping explicit so a draft does not hide an earlier confirmed revision.
        sql = "SELECT o.*,COALESCE(l.is_deleted,0) is_deleted FROM objects o JOIN (SELECT id, MAX(revision) rev FROM objects" + clause + " GROUP BY id) x ON o.id=x.id AND o.revision=x.rev LEFT JOIN object_lifecycle l ON o.id=l.object_id"
        if not include_deleted:
            sql += " WHERE COALESCE(l.is_deleted,0)=0"
        sql += " ORDER BY o.created_at DESC"
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        objects = [self.object_row(row) for row in rows]
        if analysis_market is not None:
            selected = market(analysis_market)
            objects = [x for x in objects if belongs(x["payload"], selected)]
        return objects

    def record_pairing(self, payload, expected_revision=None):
        if type(expected_revision) is not int and expected_revision is not None:
            raise AppError("validation_error", "配对版本需为整数")
        ident = "pair-" + payload["index_id"].replace(":", "-")
        with self.connection(True) as conn:
            row = conn.execute("SELECT revision FROM objects WHERE id=? ORDER BY revision DESC LIMIT 1", (ident,)).fetchone()
            revision = row[0] if row else 0
            if revision != (expected_revision or 0):
                raise AppError("conflict", "配对已变化，请重新查看并确认", status=409)
            conn.execute("INSERT INTO objects VALUES(?,?,?,?,?,?,?,?)", (ident, "pairing", revision + 1, "recorded", dumps(payload), now(), None, None))
        return self.get_object(ident)

    def versions(self, ident):
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM objects WHERE id=? ORDER BY revision DESC", (ident,)).fetchall()
        return [self.object_row(row) for row in rows]

    @staticmethod
    def require_active(conn, ident):
        row = conn.execute("SELECT is_deleted FROM object_lifecycle WHERE object_id=?", (ident,)).fetchone()
        if row and row[0]:
            raise AppError("object_deleted", "记录已在回收站，请恢复后再操作", status=409)

    def lifecycle(self):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM object_lifecycle ORDER BY updated_at DESC")]

    def recycle(self, ident, deleted, expected_revision, actor):
        if type(expected_revision) is not int or type(deleted) is not bool or not isinstance(actor, str) or not actor.strip() or len(actor) > 100:
            raise AppError("validation_error", "删除/恢复需要对象版本和操作人")
        with self.connection(True) as conn:
            row = conn.execute("SELECT kind,revision FROM objects WHERE id=? ORDER BY revision DESC LIMIT 1", (ident,)).fetchone()
            if not row:
                raise AppError("not_found", "对象不存在", status=404)
            if row["kind"] not in ("plan", "execution"):
                raise AppError("validation_error", "只有计划与执行记录可移入回收站")
            if row["revision"] != expected_revision:
                raise AppError("conflict", "对象已有新版本，请刷新后再操作", status=409)
            old = conn.execute("SELECT is_deleted FROM object_lifecycle WHERE object_id=?", (ident,)).fetchone()
            if not old or bool(old[0]) != deleted:
                conn.execute("INSERT INTO object_lifecycle VALUES(?,?,?,?) ON CONFLICT(object_id) DO UPDATE SET is_deleted=excluded.is_deleted,updated_at=excluded.updated_at,actor=excluded.actor", (ident, int(deleted), now(), actor.strip()))
        return self.get_object(ident)

    def create(self, kind, payload, ident=None, status="draft", actor=None):
        ident = ident or new_id()
        if kind not in KINDS or status not in STATUSES or not IDENTIFIER.fullmatch(ident):
            raise AppError("validation_error", "对象类别、状态或标识无效")
        if not isinstance(payload, dict):
            raise AppError("validation_error", "对象内容必须为 JSON 对象")
        encoded = dumps(payload)
        if status == "confirmed" and (not isinstance(actor, str) or not actor.strip()):
            raise AppError("validation_error", "确认内容需要确认人")
        stamp = now()
        with self.connection(True) as conn:
            if conn.execute("SELECT 1 FROM objects WHERE id=?", (ident,)).fetchone():
                raise AppError("conflict", "对象已经存在", {"id": ident}, 409)
            conn.execute("INSERT INTO objects VALUES (?,?,?,?,?,?,?,?)", (
                ident, kind, 1, status, encoded, stamp,
                stamp if status == "confirmed" else None, actor if status == "confirmed" else None))
        return self.get_object(ident)

    def revise(self, ident, payload, expected_revision):
        if type(expected_revision) is not int or not isinstance(payload, dict):
            raise AppError("validation_error", "修订需要内容及 expected_revision")
        encoded = dumps(payload)
        with self.connection(True) as conn:
            self.require_active(conn, ident)
            old = conn.execute("SELECT * FROM objects WHERE id=? ORDER BY revision DESC LIMIT 1", (ident,)).fetchone()
            if not old:
                raise AppError("not_found", "对象不存在", status=404)
            if old["revision"] != expected_revision:
                raise AppError("conflict", "对象已出现新版本，请刷新后再修改", status=409)
            if old["kind"] not in {"logic", "technical", "mode", "plan"}:
                raise AppError("validation_error", "执行/复盘记录保留原文，请创建补充记录")
            rev = old["revision"] + 1
            conn.execute("INSERT INTO objects VALUES (?,?,?,?,?,?,?,?)", (
                ident, old["kind"], rev, "draft", encoded, now(), None, None))
        return self.get_object(ident, rev)

    def confirm(self, ident, revision, actor):
        if type(revision) is not int or not isinstance(actor, str) or not actor.strip() or len(actor) > 100:
            raise AppError("validation_error", "确认需要版本与确认人")
        with self.connection(True) as conn:
            self.require_active(conn, ident)
            row = conn.execute("SELECT * FROM objects WHERE id=? AND revision=?", (ident, revision)).fetchone()
            if not row:
                raise AppError("not_found", "待确认对象不存在", status=404)
            latest = conn.execute("SELECT MAX(revision) FROM objects WHERE id=?", (ident,)).fetchone()[0]
            if latest != revision:
                raise AppError("conflict", "不能把过期草稿当作当前版本确认", status=409)
            if row["status"] == "confirmed":
                return self.object_row(row)
            if row["status"] != "draft" or row["kind"] not in {"logic", "technical", "mode", "plan"}:
                raise AppError("validation_error", "该对象状态不可确认")
            conn.execute("UPDATE objects SET status='confirmed', confirmed_at=?, confirmed_by=? WHERE id=? AND revision=?",
                         (now(), actor.strip(), ident, revision))
        return self.get_object(ident, revision)

    def create_run(self, ident=None, metadata=None):
        ident = ident or new_id()
        with self.connection(True) as conn:
            conn.execute("INSERT INTO runs(id,status,created_at,metadata) VALUES(?,?,?,?)",
                         (ident, "running", now(), dumps(metadata or {})))
        return ident

    def update_run(self, ident, **values):
        allowed = {"status", "finished_at", "snapshot", "facts", "analysis", "error", "metadata"}
        if not values or not set(values).issubset(allowed):
            raise AppError("validation_error", "轮次字段无效")
        for key in set(values) & {"snapshot", "facts", "analysis", "error", "metadata"}:
            values[key] = dumps(values[key]) if values[key] is not None else None
        with self.connection(True) as conn:
            cur = conn.execute("UPDATE runs SET " + ",".join(k + "=?" for k in values) + " WHERE id=?",
                               list(values.values()) + [ident])
            if not cur.rowcount:
                raise AppError("not_found", "轮次不存在", status=404)

    def get_run(self, ident):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (ident,)).fetchone()
        if row is None:
            raise AppError("not_found", "分析轮次不存在", status=404)
        result = dict(row)
        for key in ("snapshot", "facts", "analysis", "error", "metadata"):
            result[key] = json.loads(result[key]) if result[key] else None
        return result

    def list_runs(self, limit=30, analysis_market=None):
        with self.connection() as conn:
            rows = conn.execute("SELECT id,status,created_at,finished_at,error,metadata FROM runs ORDER BY created_at DESC LIMIT ?", (10000 if analysis_market else limit,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for key in ("error", "metadata"):
                item[key] = json.loads(item[key]) if item[key] else None
            if analysis_market is None or run_market(item) == market(analysis_market):
                result.append(item)
        return result[:limit]

    def us_breadth_history(self):
        result = {}
        with self.connection() as conn:
            for row in conn.execute("SELECT facts FROM runs WHERE facts IS NOT NULL ORDER BY created_at DESC LIMIT 1000"):
                facts = json.loads(row[0])
                if facts.get("analysis_market") != "US":
                    continue
                breadth = facts.get("breadth") or {}
                for point in breadth.get("rows", []):
                    if not point.get("forming"):
                        result.setdefault((point.get("scope_id", breadth.get("scope_id")), point["date"]), point)
        return sorted(result.values(), key=lambda x: x["date"])[-600:]

    def market_history(self):
        from .volume_price import completed_asof
        rows = {}
        with self.connection() as conn:
            for value in conn.execute("SELECT facts FROM runs WHERE facts IS NOT NULL ORDER BY created_at DESC LIMIT 180"):
                market = (json.loads(value[0]) or {}).get("market", {})
                if market.get("amount_scope") == "shsz_a" and market.get("amount_complete") and market.get("counts_complete") and not market.get("undated_prices") and completed_asof(market.get("asof")):
                    date = market["asof"][:10]
                    rows.setdefault(date, {"date": date, "amount": market["amount"], "source": "本地实际完整收盘快照", "scope_id": "shsz_a"})
        return sorted(rows.values(), key=lambda x: x["date"])[-60:]

    def create_job(self, kind):
        ident = new_id()
        with self.connection(True) as conn:
            conn.execute("INSERT INTO jobs(id,kind,status,created_at) VALUES(?,?,?,?)", (ident, kind, "running", now()))
        return ident

    def finish_job(self, ident, result=None, error=None):
        with self.connection(True) as conn:
            conn.execute("UPDATE jobs SET status=?,finished_at=?,result=?,error=? WHERE id=?",
                         ("failed" if error else "completed", now(), dumps(result), dumps(error), ident))

    def get_job(self, ident):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone()
        if not row:
            raise AppError("not_found", "任务状态不存在", status=404)
        item = dict(row)
        for key in ("result", "error"):
            item[key] = json.loads(item[key]) if item[key] else None
        return item

    def mark_interrupted(self):
        error = dumps({"code": "interrupted", "message": "上次运行中服务已退出，保留当时记录"})
        with self.connection(True) as conn:
            for table in ("jobs", "runs"):
                conn.execute("UPDATE " + table + " SET status='interrupted',finished_at=?,error=? WHERE status='running'", (now(), error))

    def export_data(self, config):
        with self.connection() as conn:
            conn.execute("BEGIN")
            objects = [dict(row) for row in conn.execute("SELECT * FROM objects ORDER BY id,revision")]
            runs = [dict(row) for row in conn.execute("SELECT * FROM runs ORDER BY created_at")]
            lifecycle = [dict(row) for row in conn.execute("SELECT * FROM object_lifecycle")]
        record_ids = set()
        for row in objects:
            trace = json.loads(row["payload"]).get("ai_trace") or {}
            if trace_identifier(trace):
                record_ids.add(trace_identifier(trace))
        for row in runs:
            trace = (json.loads(row["analysis"]) if row["analysis"] else {}).get("trace") or {}
            if trace_identifier(trace):
                record_ids.add(trace_identifier(trace))
        records = {}
        ai_root = self.home / "ai"
        if ai_root.is_dir() and not ai_root.is_symlink():
            record_ids.update(p.name for p in ai_root.iterdir()
                              if p.is_dir() and not p.is_symlink() and re.fullmatch(r"[a-f0-9]{32}", p.name))
        names = ("input.json", "result.json", "trace.json", "stdout.jsonl", "stderr.log")
        for ident in record_ids:
            if not re.fullmatch(r"[a-f0-9]{32}", ident):
                continue
            folder = self.home / "ai" / ident
            if folder.is_dir() and not folder.is_symlink():
                records[ident] = {name: (folder / name).read_text(encoding="utf-8") for name in names
                                  if (folder / name).is_file() and not (folder / name).is_symlink()}
        config = dict(config, auto_refresh=False)
        return {"archive_version": 3, "exported_at": now(), "config": config,
                "objects": objects, "runs": runs, "ai_records": records, "lifecycle": lifecycle}

    def import_data(self, archive):
        if not isinstance(archive, dict) or archive.get("archive_version") not in (1, 2, 3):
            raise AppError("validation_error", "迁移文件版本不支持")
        objects, runs = archive.get("objects"), archive.get("runs")
        if not isinstance(objects, list) or not isinstance(runs, list) or len(objects) > 100000 or len(runs) > 10000:
            raise AppError("validation_error", "迁移文件结构或大小不合理")
        obj_columns = ("id", "kind", "revision", "status", "payload", "created_at", "confirmed_at", "confirmed_by")
        run_columns = ("id", "status", "created_at", "finished_at", "snapshot", "facts", "analysis", "error", "metadata")
        staged_objects, staged_runs = {}, {}
        lifecycle = archive.get("lifecycle", [])
        if not isinstance(lifecycle, list) or len(lifecycle) > 100000:
            raise AppError("validation_error", "回收站迁移结构无效")
        seen_lifecycle = set()
        for row in lifecycle:
            if not isinstance(row, dict) or set(row) != {"object_id", "is_deleted", "updated_at", "actor"}:
                raise AppError("validation_error", "回收站字段无效")
            if not IDENTIFIER.fullmatch(str(row["object_id"])) or type(row["is_deleted"]) is not int or row["is_deleted"] not in (0, 1) or not isinstance(row["updated_at"], str) or not isinstance(row["actor"], str) or not row["actor"].strip():
                raise AppError("validation_error", "回收站状态或操作人无效")
            if row["object_id"] in seen_lifecycle:
                raise AppError("validation_error", "回收站对象重复")
            seen_lifecycle.add(row["object_id"])
        ai_records = archive.get("ai_records", {})
        if not isinstance(ai_records, dict) or len(ai_records) > 10000:
            raise AppError("validation_error", "AI归档结构不合理")
        for ident, files in ai_records.items():
            if not re.fullmatch(r"[a-f0-9]{32}", str(ident)) or not isinstance(files, dict):
                raise AppError("validation_error", "AI归档标识无效")
            for name, text in files.items():
                if name not in {"input.json", "result.json", "trace.json", "stdout.jsonl", "stderr.log"} or not isinstance(text, str) or len(text) > 4000000:
                    raise AppError("validation_error", "AI归档文件类型或长度无效")
                folder = self.home / "ai" / ident
                path = folder / name
                if (self.home / "ai").is_symlink() or folder.is_symlink() or path.is_symlink():
                    raise AppError("validation_error", "本地AI归档路径为链接，未执行导入")
                if path.exists() and path.read_text(encoding="utf-8") != text:
                    raise AppError("conflict", "AI原始归档与本地内容冲突，未覆盖", {"id": ident}, 409)
        for row in objects:
            if not isinstance(row, dict) or set(row) != set(obj_columns) or not IDENTIFIER.fullmatch(str(row.get("id", ""))):
                raise AppError("validation_error", "迁移对象结构无效")
            if row["kind"] not in KINDS or row["status"] not in STATUSES or type(row["revision"]) is not int or row["revision"] < 1:
                raise AppError("validation_error", "迁移对象版本或类别无效")
            try:
                payload = json.loads(row["payload"])
                if not isinstance(payload, dict):
                    raise ValueError()
                market(payload.get("analysis_market", "CN"))
                if "market_scope" in payload:
                    scope(payload)
                if "execution_market" in payload and payload["execution_market"] is not None:
                    market(payload["execution_market"])
                if row["kind"] == "pairing":
                    from .config import TRADABLE_SYMBOL
                    if payload.get("analysis_market") != "US" or payload.get("execution_market") != "CN" or payload.get("index_id") not in {"us:DJI", "us:NDX", "us:SPX"} or not TRADABLE_SYMBOL.fullmatch(str(payload.get("asset_id", ""))) or not isinstance(payload.get("selection"), dict):
                        raise AppError("validation_error", "配对迁移缺少已核实身份、市场或筛选依据")
                dumps(payload)
            except (ValueError, TypeError):
                raise AppError("validation_error", "迁移对象内容不是有效 JSON")
            if row["status"] == "confirmed" and (not row["confirmed_by"] or not row["confirmed_at"]):
                raise AppError("validation_error", "已确认对象缺少确认记录")
            key = (row["id"], row["revision"])
            if key in staged_objects:
                raise AppError("validation_error", "迁移文件存在重复对象版本")
            staged_objects[key] = row
        for row in runs:
            if not isinstance(row, dict) or set(row) != set(run_columns) or not IDENTIFIER.fullmatch(str(row.get("id", ""))):
                raise AppError("validation_error", "迁移轮次结构无效")
            for key in ("snapshot", "facts", "analysis", "error", "metadata"):
                if row[key] is not None:
                    try:
                        dumps(json.loads(row[key]))
                    except (TypeError, ValueError):
                        raise AppError("validation_error", "迁移轮次 JSON 无效")
            if row["id"] in staged_runs:
                raise AppError("validation_error", "迁移文件存在重复轮次")
            staged_runs[row["id"]] = row
            meta = json.loads(row["metadata"] or "{}")
            selected = market(meta.get("analysis_market", "CN"))
            for name in ("snapshot", "facts"):
                part = json.loads(row[name] or "{}")
                if part and market(part.get("analysis_market", "CN")) != selected:
                    raise AppError("validation_error", "迁移轮次的快照/事实市场不一致")
        added_objects = added_runs = 0
        with self.connection(True) as conn:
            existing = {(row["id"], row["revision"]): dict(row) for row in conn.execute("SELECT * FROM objects")}
            known_runs = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM runs")}
            known_objects = {**existing, **staged_objects}
            run_ids = set(known_runs) | set(staged_runs)
            object_kinds = {}
            for key, row in known_objects.items():
                previous_kind = object_kinds.setdefault(key[0], row["kind"])
                if previous_kind != row["kind"]:
                    raise AppError("validation_error", "同一对象的版本类别不一致")
            for row in staged_objects.values():
                p = json.loads(row["payload"])
                refs = list(p.get("knowledge_refs") or [])
                refs.extend(p.get("execution_refs") or [])
                refs.extend(p.get("plan_versions") or [])
                for key in ("plan_ref", "origin_ref", "pairing_ref"):
                    if p.get(key):
                        refs.append(p[key])
                for ref in refs:
                    if split_reference(ref) not in known_objects:
                        raise AppError("validation_error", "迁移文件包含缺失对象引用", {"ref": ref})
                if p.get("run_id") and p["run_id"] not in run_ids:
                    raise AppError("validation_error", "迁移文件缺少关联分析轮次")
                selected = market(p.get("analysis_market", "CN"))
                for ref in refs:
                    target = known_objects[split_reference(ref)]
                    target_payload = json.loads(target["payload"])
                    if target["kind"] in ("logic", "technical", "mode"):
                        if selected not in scope(target_payload) and row["kind"] not in ("logic", "technical", "mode"):
                            raise AppError("validation_error", "迁移知识引用不适用于分析市场")
                    elif row["kind"] not in ("logic", "technical", "mode") and not belongs(target_payload, selected):
                        raise AppError("validation_error", "迁移对象引用的市场归属不一致")
                if p.get("run_id"):
                    linked = (staged_runs.get(p["run_id"]) or known_runs[p["run_id"]])
                    if market(json.loads(linked["metadata"] or "{}").get("analysis_market", "CN")) != selected:
                        raise AppError("validation_error", "迁移计划/档案与关联轮次市场不一致")
                key = (row["id"], row["revision"])
                old = existing.get(key)
                if old:
                    if any(old[k] != row[k] for k in ("kind", "status", "payload")):
                        raise AppError("conflict", "本地对象版本与迁移文件冲突，未覆盖", {"ref": "%s@%s" % key}, 409)
                else:
                    conn.execute("INSERT INTO objects VALUES (?,?,?,?,?,?,?,?)", [row[k] for k in obj_columns])
                    added_objects += 1
            for ident, row in staged_runs.items():
                facts = json.loads(row["facts"] or "{}")
                for paired in facts.get("paired_etfs", {}).values():
                    ref = paired.get("pairing_ref")
                    key = split_reference(ref)
                    if key not in known_objects or known_objects[key]["kind"] != "pairing":
                        raise AppError("validation_error", "迁移轮次缺少其引用的固定配对版本")
                    p = json.loads(known_objects[key]["payload"])
                    if p.get("asset_id") != paired.get("asset_id") or p.get("index_id") != paired.get("index_id"):
                        raise AppError("validation_error", "迁移轮次ETF与原配对不一致")
                old = known_runs.get(ident)
                if old:
                    if any(old[k] != row[k] for k in run_columns):
                        raise AppError("conflict", "分析轮次与本地内容冲突，未覆盖", {"id": ident}, 409)
                else:
                    conn.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)", [row[k] for k in run_columns])
                    added_runs += 1
            for row in lifecycle:
                if object_kinds.get(row["object_id"]) not in ("plan", "execution"):
                    raise AppError("validation_error", "回收站引用缺少计划或执行对象")
                old = conn.execute("SELECT * FROM object_lifecycle WHERE object_id=?", (row["object_id"],)).fetchone()
                if old and dict(old) != row:
                    raise AppError("conflict", "对象回收站状态有冲突，未覆盖", {"object_id": row["object_id"]}, 409)
                if not old:
                    conn.execute("INSERT INTO object_lifecycle VALUES(?,?,?,?)", [row[k] for k in ("object_id", "is_deleted", "updated_at", "actor")])
            for ident, files in ai_records.items():
                folder = self.home / "ai" / ident
                folder.mkdir(parents=True, exist_ok=True)
                for name, text in files.items():
                    path = folder / name
                    if not path.exists():
                        path.write_text(text, encoding="utf-8")
        return {"objects_added": added_objects, "runs_added": added_runs, "ai_records": len(ai_records), "lifecycle": len(lifecycle)}
