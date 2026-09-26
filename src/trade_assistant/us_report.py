"""US charts shared with the application and a self-contained historical report."""
from html import escape

from .charts import candles, curves, fmt
from .presentation import select


def chart_data(facts):
    plots = {"breadth": curves(facts.get("breadth", {}).get("rows", []), [("advancing", "上涨", "#bd6555"), ("declining", "下跌", "#368775")], "家")}
    for item in facts.get("macro", []):
        # A mixture of vintages/samples/forecast types is not a single curve.
        rows = item.get("rows", [])
        groups = {(x.get("sample"), x.get("value_type"), x.get("unit"), x.get("definition")) for x in rows}
        if len(groups) > 1 and item["symbol"] in ("US_DEFAULT_RATE", "SP500_EPS", "SP500_NET_MARGIN", "SP500_EPS_YOY"):
            plots[item["symbol"]] = '<p class="small muted">存在不同样本/实际或预测记录，请按明细核对，不混连为同口径曲线。</p>'
        else:
            latest = {}
            for row in sorted(rows, key=lambda x: (x["date"], str(x.get("published_at") or ""))):
                latest[row["date"]] = row
            plots[item["symbol"]] = curves([latest[d] for d in sorted(latest)][-120:], [("value", item["name"], "#547fa2")], item.get("unit", ""))
    return plots


def render(run):
    from .report_v2 import STYLE
    f = run["facts"]
    ai = (run.get("analysis") or {}).get("result") or {}
    market = ai.get("market") or {}
    plots = chart_data(f)
    opinions = {x["asset_id"]: x for x in ai.get("candidates", [])}
    def chart_card(item, paired=False):
        op = opinions.get(item["asset_id"], {})
        tech = item.get("technical") or {}
        premium = item.get("premium") or {}
        text = op.get("volume_price_reading") or (item.get("volume_price") or {}).get("summary") or "量价资料不足"
        out = '<article class="card"><h3>%s</h3><p class="muted">%s · %s</p>%s<p class="insight">%s</p>' % (escape(item["name"]), escape(item["asset_id"]), escape(str(tech.get("asof") or "待取得")), candles(tech), escape(text))
        if paired:
            out += '<p>%s %s%%</p><p class="muted">市场价时点 %s · 净值日 %s；非实时IOPV溢价</p>' % (escape(premium.get("label", "溢价资料不足")), fmt(premium.get("value")), escape(str(premium.get("price_asof") or "未知")), escape(str(premium.get("basis_date") or "未知")))
        if item.get("identity") and item.get("kind") == "industry":
            out += '<p class="muted">美国观察代理：%s</p>' % escape(item["identity"])
        out += '<details><summary>周线与来源</summary>%s<p class="muted">%s</p></details></article>' % (candles(tech, "weekly"), escape(str(tech.get("source") or "缺少来源")))
        return out
    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>trade · 美股观察</title><style>', STYLE,
             '</style><body><main><p class="muted">P03 / US · 人工交易</p><h1>美股观察</h1><p class="muted">美国行情日 ', escape(str(f.get("asof") or "未知")), ' · 生成 ', escape(run.get("finished_at") or run["created_at"]), '</p><div class="three">']
    for title, key in (("市场点评", "commentary"), ("盘面结构", "structure"), ("市场模式", "mode_summary")):
        parts += ['<article class="card"><h3>', title, '</h3><p>', escape(market.get(key) or "未取得AI解读，保留程序事实。"), '</p></article>']
    parts += ['</div><h2>三大指数与固定境内ETF</h2><div class="three">']
    for item in f["candidates"]:
        if item["kind"] != "index":
            continue
        pair = f.get("paired_etfs", {}).get(item["asset_id"])
        parts += ['<section>', chart_card(item), chart_card(pair, True) if pair else '<p class="muted">配对/ETF资料未完整；未自动强配。</p>', '</section>']
    parts += ['</div><h2>NYSE＋NASDAQ与纽约金</h2><div class="grid"><article class="card"><h3>上涨 / 下跌家数</h3>', plots["breadth"], '<p class="muted">', escape(f.get("breadth", {}).get("definition", "未取得")), '</p></article>']
    parts += [chart_card(x) for x in f.get("watch_indices", [])]
    parts += ['</div><h2>短中长期基本面</h2><div class="grid">']
    for item in f.get("macro", []):
        if item["symbol"] in ("WALCL", "WDTGAL", "RRPONTSYD", "GDPC1"):
            continue
        parts += ['<article class="card"><h3>', escape(item["name"]), '</h3><p class="muted">', escape(str(item.get("asof") or "待取得") + " · " + item.get("unit", "")), '</p>', plots.get(item["symbol"], ""), '<details><summary>定义与来源</summary><p>', escape(item.get("definition", "")), '</p><p class="muted">', escape(item.get("source", "")), '</p></details></article>']
    selection = select(f, run.get("analysis"))
    parts += ['</div><h2>候选重点 · 前三</h2><p class="muted">', escape(selection["label"]), '</p><div class="three">']
    by_id = {x["asset_id"]: x for x in f["candidates"]}
    parts += [chart_card(by_id[aid]) for aid in selection["overall_top3"]]
    parts += ['</div><h2>选定美国行业</h2><div class="grid">']
    parts += [chart_card(x) for x in f["candidates"] if x["kind"] == "industry"]
    parts += ['</div><details><summary>覆盖与局限</summary><ul>']
    parts += ['<li>%s：%s</li>' % (escape(x["group"]), escape(x["detail"])) for x in f.get("coverage", []) if x["status"] != "ok"]
    parts += ['</ul></details><footer>历史轮次 ', escape(run["id"]), ' · 固定保存当时的行情、配对与来源。图表默认MA20日。</footer></main></body></html>']
    return ''.join(parts)
