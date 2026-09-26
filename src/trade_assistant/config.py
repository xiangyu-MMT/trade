import copy
import json
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit

from .util import AppError, PROJECT, write_json
from .markets import market

DEFAULT = Path(__file__).parent / "defaults" / "config.json"
SYMBOL = re.compile(r"^(?:sh|sz)\d{6}$")
INDEX_SYMBOL = re.compile(r"^(?:sh|sz|csi)\d{6}$")
STOCK_SYMBOL = re.compile(r"^(?:sh(?:60|68)|sz(?:00|30))\d{4}$")
TRADABLE_SYMBOL = re.compile(r"^(?:sh(?:60|68|50|51|52|56|58)|sz(?:00|30|15|16))\d{4}$")


def validate(config):
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise AppError("validation_error", "配置 schema_version 必须为 1")
    config = copy.deepcopy(config)
    config["active_market"] = market(config.get("active_market", "CN"))
    scheduled = config.setdefault("scheduled_markets", ["CN"])
    if not isinstance(scheduled, list) or not scheduled or any(not isinstance(x, str) for x in scheduled) or len(scheduled) != len(set(scheduled)):
        raise AppError("validation_error", "scheduled_markets需要不重复的市场列表")
    for value in scheduled:
        market(value)
    us_default = json.loads((DEFAULT.parent / "us.json").read_text(encoding="utf-8"))
    us = config.setdefault("us", us_default)
    if not isinstance(us, dict):
        raise AppError("validation_error", "us配置需要对象")
    for key, value in us_default.items():
        us.setdefault(key, copy.deepcopy(value))
    for key in ("indices", "sectors"):
        catalog = {x["asset_id"]: x for x in us_default[key]}
        if not isinstance(us[key], list) or len(us[key]) > len(catalog):
            raise AppError("validation_error", "美股观察范围超出已确认目录")
        seen = set()
        for row in us[key]:
            if not isinstance(row, dict) or row.get("asset_id") not in catalog or row["asset_id"] in seen:
                raise AppError("validation_error", "美股对象身份无效或重复")
            if row.get("symbol") != catalog[row["asset_id"]]["symbol"]:
                raise AppError("validation_error", "美股代表代码需与已核实身份一致")
            seen.add(row["asset_id"])
            row.update(catalog[row["asset_id"]])
    if len(us["indices"]) != 3:
        raise AppError("validation_error", "美股三大指数必须保留")
    tech = us.get("technical")
    if not isinstance(tech, dict):
        raise AppError("validation_error", "us.technical需要对象")
    for key in ("ma_periods", "volume_periods"):
        val = tech.get(key)
        if not isinstance(val, list) or not val or len(val) > 8 or any(type(n) is not int or not 2 <= n <= 250 for n in val) or len(set(val)) != len(val):
            raise AppError("validation_error", "美股技术窗口需为2–250的无重复整数列表")
    if type(tech.get("obv_lookback")) is not int or not 2 <= tech["obv_lookback"] <= 250:
        raise AppError("validation_error", "美股OBV比较窗口须为2–250")
    from .us_observations import validate_observations, validate_breadth
    us["observations"] = validate_observations(us["observations"])
    us["breadth_history"] = validate_breadth(us["breadth_history"])
    defaults = {"provider": "codex", "model": "", "deepseek": {"enabled": False, "base_url": "https://api.deepseek.com", "model": "deepseek-flash", "timeout": 180}}
    ai_config = config.setdefault("ai", {})
    if not isinstance(ai_config, dict):
        raise AppError("validation_error", "ai 必须为对象")
    for key, value in defaults.items():
        ai_config.setdefault(key, copy.deepcopy(value))
    def reject_secrets(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower().endswith("api_key") or str(key).lower() in {"access_token", "refresh_token", "password", "authorization", "cookie", "secret"}:
                    raise AppError("validation_error", "请勿将凭据写入配置或导出文件")
                reject_secrets(child)
        elif isinstance(value, list):
            for child in value:
                reject_secrets(child)
    reject_secrets(config)
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
            if key == "stocks" and not STOCK_SYMBOL.fullmatch(row["asset_id"]):
                raise AppError("validation_error", "stocks 只填写沪深A股代码；指数请放入 indices，不能作为可交易个股")
            if key in ("indices", "stocks"):
                ids.append(row["asset_id"])
    if len(ids) != len(set(ids)):
        raise AppError("validation_error", "indices/stocks 中存在重复对象")
    mapping = config.get("execution_mappings")
    if not isinstance(mapping, dict):
        raise AppError("validation_error", "execution_mappings 必须是对象")
    for source, row in mapping.items():
        if not isinstance(source, str) or not isinstance(row, dict) or not TRADABLE_SYMBOL.fullmatch(str(row.get("asset_id", ""))):
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
    if ai.get("provider") not in ("codex", "deepseek") or not isinstance(ai.get("model"), str) or len(ai["model"]) > 150:
        raise AppError("validation_error", "AI提供方或模型配置无效")
    ds = ai.get("deepseek")
    if not isinstance(ds, dict) or type(ds.get("enabled")) is not bool:
        raise AppError("validation_error", "DeepSeek 配置需要 enabled")
    url = urlsplit(str(ds.get("base_url", "")))
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise AppError("validation_error", "DeepSeek服务地址需为不含凭据/查询参数的HTTPS地址")
    if not isinstance(ds.get("model"), str) or not ds["model"].strip() or len(ds["model"]) > 150:
        raise AppError("validation_error", "请填写DeepSeek模型名称")
    if type(ds.get("timeout")) is not int or not 30 <= ds["timeout"] <= 900:
        raise AppError("validation_error", "DeepSeek超时须为30–900秒")
    indicators = config.get("indicators", {})
    ma = indicators.get("ma_periods")
    if not isinstance(ma, list) or not ma or any(type(x) is not int or not 2 <= x <= 500 for x in ma):
        raise AppError("validation_error", "均线周期需要 2–500 的整数列表")
    if set(ma) not in ({5, 20}, {5, 20, 60, 120}):
        raise AppError("validation_error", "当前均线仅使用5日、20日，请填写 [5,20]")
    indicators["ma_periods"] = [5, 20]
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
        if not re.fullmatch(r"[A-Za-z0-9^=._-]{1,40}", item["symbol"]):
            raise AppError("validation_error", "宏观 symbol 含不支持的字符")
    if type(config.get("max_import_bytes", 104857600)) is not int or not 1048576 <= config.get("max_import_bytes", 104857600) <= 536870912:
        raise AppError("validation_error", "导入上限应为1MB–512MB的字节数")
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
