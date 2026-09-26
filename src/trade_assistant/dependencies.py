"""Small optional parsers installed inside the project's ignored runtime folder."""
import importlib
import subprocess
import sys
import shutil
from pathlib import Path

from .util import AppError, PROJECT

TARGET = PROJECT / ".local" / "python-packages"
PARSERS = ("xlrd", "pypdf", "curl_cffi")
PARQUET_RUNTIME = PROJECT / ".local" / "parquet-runtime"


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
    installed = True
    try:
        for name in PARSERS:
            load(name)
    except AppError:
        installed = False
    if installed:
        ensure_parquet()
        return
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
    ensure_parquet()


def node_command():
    node = shutil.which("node")
    if not node:
        raise AppError("dependency_missing", "全市场历史解析需要Node22，请安装后运行setup")
    version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10)
    if not version.stdout.strip().startswith("v22."):
        raise AppError("node_version", "本项目全市场历史解析使用Node22.x")
    return node


def ensure_parquet():
    node = node_command()
    manifest = (PROJECT / "src" / "parquet-package.json").read_text(encoding="utf-8")
    target = PARQUET_RUNTIME / "package.json"
    if target.is_file() and target.read_text(encoding="utf-8") == manifest and all((PARQUET_RUNTIME / "node_modules" / name / "package.json").is_file() for name in ("hyparquet", "hyparquet-compressors")):
        return
    npm = shutil.which("npm")
    if not npm:
        raise AppError("dependency_missing", "未找到npm，请安装Node22后运行setup")
    candidates = [Path(npm).resolve(), Path(node).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"]
    entry = next((p for p in candidates if p.is_file() and p.suffix == ".js"), None)
    if not entry:
        raise AppError("dependency_missing", "未找到npm-cli.js，请使用标准Node22安装")
    PARQUET_RUNTIME.mkdir(parents=True, exist_ok=True)
    target.write_text(manifest, encoding="utf-8")
    print("正在准备全市场历史解析组件…", file=sys.stderr, flush=True)
    result = subprocess.run([node, str(entry), "install", "--prefix", str(PARQUET_RUNTIME), "--ignore-scripts", "--no-audit", "--no-fund", "--registry=https://registry.npmmirror.com"], capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise AppError("dependency_install", "全市场历史解析组件未安装完成，请重试setup", {"returncode": result.returncode})
