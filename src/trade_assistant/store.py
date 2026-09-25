import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .util import AppError, dumps, new_id, now

KINDS = {"logic", "technical", "mode", "plan", "execution", "review"}
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


class Store:
    def __init__(self, home):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "trade.sqlite3"
        with self.connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
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
                PRAGMA user_version=1;
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
        return item

    def get_object(self, ident, revision=None):
        with self.connection() as conn:
            if revision is None:
                row = conn.execute("SELECT * FROM objects WHERE id=? ORDER BY revision DESC LIMIT 1", (ident,)).fetchone()
            else:
                row = conn.execute("SELECT * FROM objects WHERE id=? AND revision=?", (ident, revision)).fetchone()
        if row is None:
            raise AppError("not_found", "对象或版本不存在", {"id": ident, "revision": revision}, 404)
        return self.object_row(row)

    def get_ref(self, ref):
        return self.get_object(*split_reference(ref))

    def list_objects(self, kind=None, confirmed=False):
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
        sql = "SELECT o.* FROM objects o JOIN (SELECT id, MAX(revision) rev FROM objects" + clause + " GROUP BY id) x ON o.id=x.id AND o.revision=x.rev ORDER BY o.created_at DESC"
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self.object_row(row) for row in rows]

    def versions(self, ident):
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM objects WHERE id=? ORDER BY revision DESC", (ident,)).fetchall()
        return [self.object_row(row) for row in rows]

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

    def list_runs(self, limit=30):
        with self.connection() as conn:
            rows = conn.execute("SELECT id,status,created_at,finished_at,error,metadata FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for key in ("error", "metadata"):
                item[key] = json.loads(item[key]) if item[key] else None
            result.append(item)
        return result

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
        return {"archive_version": 1, "exported_at": now(), "config": config, "objects": objects, "runs": runs}

    def import_data(self, archive):
        if not isinstance(archive, dict) or archive.get("archive_version") != 1:
            raise AppError("validation_error", "迁移文件版本不支持")
        objects, runs = archive.get("objects"), archive.get("runs")
        if not isinstance(objects, list) or not isinstance(runs, list) or len(objects) > 100000 or len(runs) > 10000:
            raise AppError("validation_error", "迁移文件结构或大小不合理")
        obj_columns = ("id", "kind", "revision", "status", "payload", "created_at", "confirmed_at", "confirmed_by")
        run_columns = ("id", "status", "created_at", "finished_at", "snapshot", "facts", "analysis", "error", "metadata")
        staged_objects, staged_runs = {}, {}
        for row in objects:
            if not isinstance(row, dict) or set(row) != set(obj_columns) or not IDENTIFIER.fullmatch(str(row.get("id", ""))):
                raise AppError("validation_error", "迁移对象结构无效")
            if row["kind"] not in KINDS or row["status"] not in STATUSES or type(row["revision"]) is not int or row["revision"] < 1:
                raise AppError("validation_error", "迁移对象版本或类别无效")
            try:
                payload = json.loads(row["payload"])
                if not isinstance(payload, dict):
                    raise ValueError()
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
                for key in ("plan_ref", "origin_ref"):
                    if p.get(key):
                        refs.append(p[key])
                for ref in refs:
                    if split_reference(ref) not in known_objects:
                        raise AppError("validation_error", "迁移文件包含缺失对象引用", {"ref": ref})
                if p.get("run_id") and p["run_id"] not in run_ids:
                    raise AppError("validation_error", "迁移文件缺少关联分析轮次")
                key = (row["id"], row["revision"])
                old = existing.get(key)
                if old:
                    if any(old[k] != row[k] for k in ("kind", "status", "payload")):
                        raise AppError("conflict", "本地对象版本与迁移文件冲突，未覆盖", {"ref": "%s@%s" % key}, 409)
                else:
                    conn.execute("INSERT INTO objects VALUES (?,?,?,?,?,?,?,?)", [row[k] for k in obj_columns])
                    added_objects += 1
            for ident, row in staged_runs.items():
                old = known_runs.get(ident)
                if old:
                    if any(old[k] != row[k] for k in run_columns):
                        raise AppError("conflict", "分析轮次与本地内容冲突，未覆盖", {"id": ident}, 409)
                else:
                    conn.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)", [row[k] for k in run_columns])
                    added_runs += 1
        return {"objects_added": added_objects, "runs_added": added_runs}
