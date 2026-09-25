import copy
import json
import re
import threading
from pathlib import Path

from .util import AppError, PROJECT, write_json

DEFAULT = Path(__file__).parent / "defaults" / "config.json"
SYMBOL = re.compile(r"^(?:sh|sz)\d{6}$")
INDEX_SYMBOL = re.compile(r"^(?:sh|sz|csi)\d{6}$")


def validate(config):
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise AppError("validation_error", "配置 schema_version 必须为 1")
    if config.get("industry_provider") != "ths":
        raise AppError("validation_error", "行业口径必须为同花顺 ths")
    for key in ("fixed_industries", "indices", "stocks", "watch_indices", "etf_observations"):
        if not isinstance(config.get(key), list) or len(config[key]) > 150:
            raise AppError("validation_error", key + " 必须是长度不超过 150 的列表")
    if any(not isinstance(x, str) or not x.strip() for x in config["fixed_industries"]):
        raise AppError("validation_error", "fixed_industries 请填写同花顺名称或行业代码")
    ids = []
    for key in ("indices", "stocks", "watch_indices", "etf_observations"):
        for row in config[key]:
            pattern = INDEX_SYMBOL if key in ("indices", "watch_indices") else SYMBOL
            if not isinstance(row, dict) or not pattern.fullmatch(str(row.get("asset_id", ""))):
                raise AppError("validation_error", key + " 的 asset_id 格式应为 sh000300 或 sz399006")
            if not isinstance(row.get("name"), str) or not row["name"].strip():
                raise AppError("validation_error", key + " 的对象需要名称")
            if key in ("indices", "stocks"):
                ids.append(row["asset_id"])
    if len(ids) != len(set(ids)):
        raise AppError("validation_error", "indices/stocks 中存在重复对象")
    mapping = config.get("execution_mappings")
    if not isinstance(mapping, dict):
        raise AppError("validation_error", "execution_mappings 必须是对象")
    for source, row in mapping.items():
        if not isinstance(source, str) or not isinstance(row, dict) or not SYMBOL.fullmatch(str(row.get("asset_id", ""))):
            raise AppError("validation_error", "交易映射需要来源 ID 及明确的 ETF/个股 asset_id")
        if not isinstance(row.get("name"), str) or not row["name"].strip():
            raise AppError("validation_error", "交易映射需要名称")
    for key, low, high in (("top_n", 0, 90), ("history_bars", 120, 1000),
                           ("refresh_seconds", 3600, 86400)):
        value = config.get(key)
        if type(value) is not int or not low <= value <= high:
            raise AppError("validation_error", "%s 必须为 %s–%s 的整数" % (key, low, high))
    if type(config.get("auto_refresh")) is not bool:
        raise AppError("validation_error", "auto_refresh 必须为布尔值")
    network = config.get("network", {})
    for key, low, high in (("timeout", 3, 30), ("workers", 1, 8), ("budget_seconds", 30, 600)):
        val = network.get(key)
        if type(val) is not int or not low <= val <= high:
            raise AppError("validation_error", "network.%s 超出允许范围" % key)
    ai = config.get("ai", {})
    if type(ai.get("enabled")) is not bool or type(ai.get("timeout")) is not int or not 30 <= ai["timeout"] <= 900:
        raise AppError("validation_error", "ai.enabled/timeout 格式无效")
    if not isinstance(ai.get("command"), str) or not ai["command"].strip():
        raise AppError("validation_error", "ai.command 需要 Codex 可执行文件路径或名称")
    indicators = config.get("indicators", {})
    ma = indicators.get("ma_periods")
    if not isinstance(ma, list) or not ma or any(type(x) is not int or not 2 <= x <= 500 for x in ma):
        raise AppError("validation_error", "均线周期需要 2–500 的整数列表")
    for key in ("macd_fast", "macd_slow", "macd_signal", "cci_period"):
        if type(indicators.get(key)) is not int or not 2 <= indicators[key] <= 500:
            raise AppError("validation_error", "指标参数 " + key + " 无效")
    if indicators["macd_fast"] >= indicators["macd_slow"]:
        raise AppError("validation_error", "MACD 快线周期必须小于慢线周期")
    if not isinstance(config.get("macro_symbols"), list):
        raise AppError("validation_error", "macro_symbols 需要列表")
    for item in config["macro_symbols"]:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k] for k in ("name", "symbol", "unit")):
            raise AppError("validation_error", "宏观观察项需要 name/symbol/unit")
    return copy.deepcopy(config)


class Settings:
    def __init__(self, home=None):
        self.home = Path(home).expanduser().resolve() if home else PROJECT / ".local"
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "config.json"
        self.lock = threading.RLock()
        if not self.path.exists():
            write_json(self.path, json.loads(DEFAULT.read_text(encoding="utf-8")))
        self.load()

    def load(self):
        with self.lock:
            try:
                return validate(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                raise AppError("config_error", "配置无法读取，请检查 " + str(self.path), status=500) from exc

    def save(self, config):
        result = validate(config)
        with self.lock:
            write_json(self.path, result)
        return result
