import threading
import time
from datetime import datetime, timedelta

from .util import AppError, CN, now


class Runner:
    def __init__(self, settings, store, cancel, prepare=None):
        self.settings, self.store, self.cancel_callback = settings, store, cancel
        self.prepare = prepare or (lambda: None)
        self.operation_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.active, self.last_job = None, None
        # Wall time includes device sleep; overdue refresh runs once after wake.
        self.next_due = time.time() + settings.load()["refresh_seconds"]
        self.scheduled_handler = None
        self.timer_thread = None
        self.worker = None

    def start_scheduler(self, handler):
        self.scheduled_handler = handler
        self.timer_thread = threading.Thread(target=self._schedule, name="p03-scheduler", daemon=True)
        self.timer_thread.start()

    def _schedule(self):
        while not self.stop_event.wait(1):
            try:
                cfg = self.settings.load()
                if not cfg["auto_refresh"]:
                    self.next_due = None
                    continue
                if self.next_due is None:
                    self.next_due = time.time() + cfg["refresh_seconds"]
                if time.time() >= self.next_due and not self.operation_lock.locked():
                    self.start("analysis", self.scheduled_handler)
            except AppError:
                self.next_due = time.time() + 60

    def start(self, kind, handler):
        if self.stop_event.is_set():
            raise AppError("stopping", "服务正在退出", status=503)
        if not self.operation_lock.acquire(False):
            raise AppError("busy", "已有任务运行中，请等本轮完成或停止后再触发", self.status()["active"], 409)
        try:
            self.prepare()
            ident = self.store.create_job(kind)
        except Exception:
            self.operation_lock.release()
            raise
        with self.state_lock:
            self.active = {"id": ident, "kind": kind, "stage": "准备", "detail": "", "created_at": now()}
        def work():
            try:
                result = handler()
                self.store.finish_job(ident, result=result)
            except Exception as exc:
                error = exc.as_dict() if isinstance(exc, AppError) else {"code": "operation_failed", "message": str(exc)}
                self.store.finish_job(ident, error=error)
            finally:
                with self.state_lock:
                    self.last_job, self.active = ident, None
                if kind == "analysis":
                    try:
                        interval = self.settings.load()["refresh_seconds"]
                    except AppError:
                        interval = 3600
                    self.next_due = time.time() + interval
                self.operation_lock.release()
        self.worker = threading.Thread(target=work, name="p03-" + kind, daemon=True)
        self.worker.start()
        return {"job_id": ident, "kind": kind}

    def progress(self, stage, detail=""):
        with self.state_lock:
            if self.active:
                self.active.update(stage=stage, detail=detail)

    def status(self):
        with self.state_lock:
            active = dict(self.active) if self.active else None
            last = self.last_job
        config_error = None
        try:
            cfg = self.settings.load()
        except AppError as exc:
            cfg = {"auto_refresh": False, "refresh_seconds": 3600}
            config_error = exc.as_dict()
        upcoming = None
        if cfg["auto_refresh"] and self.next_due:
            upcoming = (datetime.now(CN) + timedelta(seconds=max(0, self.next_due - time.time()))).isoformat(timespec="seconds")
        return {"active": active, "last_job_id": last, "next_refresh": upcoming,
                "auto_refresh": cfg["auto_refresh"], "scheduled_markets": cfg.get("scheduled_markets", ["CN"]), "refresh_seconds": cfg["refresh_seconds"], "config_error": config_error}

    def stop(self):
        self.stop_event.set()
        self.cancel_callback()
        if self.worker:
            self.worker.join(timeout=5)
