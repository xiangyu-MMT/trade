"""Small optional parsers installed inside the project's ignored runtime folder."""
import importlib
import subprocess
import sys

from .util import AppError, PROJECT

TARGET = PROJECT / ".local" / "python-packages"
PARSERS = ("xlrd", "pypdf")


def load(name):
    if name not in PARSERS:
        raise AppError("dependency_error", "未知解析依赖")
    if TARGET.is_dir() and str(TARGET) not in sys.path:
        sys.path.insert(0, str(TARGET))
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise AppError("dependency_missing", "盈利解析依赖未安装，请运行 src/trade.py setup", {"package": name}) from exc


def ensure():
    try:
        for name in PARSERS:
            load(name)
        return
    except AppError:
        pass
    print("正在准备盈利数据解析依赖…", file=sys.stderr, flush=True)
    command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--target", str(TARGET),
               "-r", str(PROJECT / "src" / "requirements.txt")]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AppError("dependency_install", "解析依赖安装未完成，可稍后重试setup", {"reason": str(exc)})
    if result.returncode:
        raise AppError("dependency_install", "解析依赖安装失败，可运行src/trade.py setup重试", {"returncode": result.returncode})
    importlib.invalidate_caches()
    for name in PARSERS:
        load(name)
