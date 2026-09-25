"""P03 测试公用夹具。

只读被测源码，所有数据写入独立临时目录；不触碰项目 .local/、.scratch/。
"""
import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src"
for _path in (str(SRC), str(HERE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from trade_assistant.config import DEFAULT, Settings, validate   # noqa: E402
from trade_assistant.indicators import MA_PERIODS, calculate     # noqa: E402
from trade_assistant.market_time import is_session_day           # noqa: E402
from trade_assistant.util import CN, AppError                    # noqa: E402

# 已由 calendar.json 核实的交易日，作为离线夹具的锚点。
ANCHOR = "2026-09-24"
PARAMS = {"ma_periods": [5, 20], "macd_fast": 12, "macd_slow": 26, "macd_signal": 9, "cci_period": 20}
_TEMP = []


def temp_home(prefix="p03-test-"):
    path = Path(tempfile.mkdtemp(prefix=prefix))
    _TEMP.append(path)
    return path


def cleanup():
    while _TEMP:
        shutil.rmtree(_TEMP.pop(), ignore_errors=True)


def settings(home=None):
    return Settings(home or temp_home())


def default_config():
    return json.loads(Path(DEFAULT).read_text(encoding="utf-8"))


def trading_days(count, end=ANCHOR):
    day = datetime.strptime(end, "%Y-%m-%d").date()
    days = []
    while len(days) < count:
        if is_session_day(day):
            days.append(day.isoformat())
        day -= timedelta(days=1)
    return list(reversed(days))


def make_bars(count=40, start=10.0, drift=0.1, volume=1000.0, volume_drift=10.0, end=ANCHOR):
    bars = []
    for i, day in enumerate(trading_days(count, end)):
        close = start + i * drift
        vol = volume + i * volume_drift
        bars.append({"date": day, "open": round(close - 0.05, 4), "high": round(close + 0.1, 4),
                     "low": round(close - 0.1, 4), "close": round(close, 4),
                     "volume": vol, "amount": round(vol * close, 2)})
    return bars


def make_technical(count=40, **kw):
    history = {"bars": make_bars(count, **kw), "source": "测试夹具", "volume_unit": "股", "adjustment": "不复权"}
    return calculate(history, dict(PARAMS))


def past_day(days=30):
    day = datetime.now(CN).date() - timedelta(days=days)
    return day.isoformat()


def stock(asset_id, close, prior, amount=1000.0, volume=100.0, name=None, asof=ANCHOR):
    return {"asset_id": asset_id, "name": name or asset_id, "close": close, "previous_close": prior,
            "amount": amount, "volume": volume, "asof": asof}


def make_snapshot(candidates, histories, market=None, **extra):
    """最小可计算快照。candidates/histories 由调用方给出。"""
    snapshot = {
        "schema_version": 1, "id": "snapshot-fixture", "created_at": "2026-09-25T12:00:00+08:00",
        "asof": ANCHOR, "industry_provider": "ths", "config_snapshot": default_config(),
        "candidates": candidates, "watch_instruments": [], "quotes": {},
        "histories": histories, "market": market or {"stocks": [], "received": 0, "complete": False,
                                                   "total_reported": None, "asof": ANCHOR, "errors": [], "sources": []},
        "industries": [], "industry_ranking": {"complete": False, "covered": 0, "expected": 0, "top": [], "date": None},
        "coverage": [], "gaps": [], "attempts": [],
    }
    snapshot.update(extra)
    return snapshot


def candidate(asset_id, name=None, kind="index", reasons=None, quote=None, execution_asset=None,
              excluded=False, exclusion_reason=None):
    row = {"asset_id": asset_id, "name": name or asset_id, "kind": kind, "reasons": reasons or ["配置指定"]}
    if quote:
        row["quote"] = quote
    if execution_asset:
        row["execution_asset"] = execution_asset
    if excluded:
        row["excluded"] = True
        row["exclusion_reason"] = exclusion_reason or "测试排除"
    return row


def history_for(asset_id, **kw):
    bars = make_bars(**kw)
    return {"asset_id": asset_id, "bars": bars, "source": "测试夹具", "volume_unit": "股", "adjustment": "不复权"}


def assert_error(test, code, fn, *args, **kw):
    """断言抛出指定 code 的 AppError，并返回异常本身。"""
    try:
        fn(*args, **kw)
    except AppError as exc:
        test.assertEqual(exc.code, code, "期望 %s，实际 %s：%s" % (code, exc.code, exc.message))
        return exc
    test.fail("期望抛出 %s，但未抛出" % code)


def reject(test, mutate, code="validation_error"):
    """对默认配置施加变更后应被拒绝。"""
    config = default_config()
    mutate(config)
    assert_error(test, code, validate, config)
