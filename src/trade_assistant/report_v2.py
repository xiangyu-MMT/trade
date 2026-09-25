from html import escape

from .charts import candles, turnover, fmt
from .presentation import select
from .util import now

STYLE = '''
*{box-sizing:border-box}body{margin:0;background:#f5f7f2;color:#234136;font:15px/1.8 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{max-width:1150px;padding:30px 24px;margin:auto}h1{font-size:29px}h2{font-size:21px;margin:26px 0 14px}h3{font-size:16px;margin:0}.card{padding:20px;border:1px solid #dce5da;background:white;border-radius:13px;min-width:0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.three{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.title{display:flex;justify-content:space-between;gap:12px}.title span{font-size:12px;color:#678266}.muted{font-size:12px;color:#6f8271}svg{display:block;width:100%;height:auto}.insight{padding:9px 12px;background:#eff5ea;border-left:3px solid #91b194;font-size:13px}p{font-size:14px;white-space:pre-wrap}details{margin-top:14px;font-size:13px}summary{cursor:pointer}li{margin:7px 0}.stats{display:flex;gap:35px;flex-wrap:wrap;padding:22px 0}.stats b{font-size:25px;display:block}.volume{max-width:800px}.warn{color:#927246}.ma{color:#869985;font-size:11px}footer{font-size:12px;color:#72866f;margin-top:28px;border-top:1px solid #dce5da;padding-top:17px}@media(max-width:760px){.grid,.three{grid-template-columns:1fr}main{padding:20px 15px}}@media print{.card{break-inside:avoid}}
'''


def render(run):
    facts = run.get("facts") or {}
    reply = run.get("analysis") or {}
    ai, trace = reply.get("result") or {}, reply.get("trace") or {}
    market = facts.get("market") or {}
    selection = select(facts, reply)
    by_id = {x["asset_id"]: x for x in facts.get("candidates", [])}
    opinions = {x["asset_id"]: x for x in ai.get("candidates", [])}
    labels = {"candidate": "可关注", "observe": "观察", "wait": "等待"}

    def card(ident):
        item, op = by_id[ident], opinions.get(ident, {})
        v = item.get("volume_price") or {}
        reasons = op.get("against", []) + op.get("missing", []) + v.get("missing", [])
        return ('<article class="card"><div class="title"><h3>' + escape(item["name"]) + '</h3><span>'
                + labels.get(op.get("stance"), "量价参考") + '</span></div>' + candles(item["technical"])
                + '<p class="insight">' + escape(op.get("volume_price_reading") or v.get("summary") or "量价资料不足")
                + '</p><p>' + escape(op.get("strength_reason") or op.get("reason") or "未获AI综合判断")
                + '</p><details><summary>依据、反证与缺口</summary><ul>'
                + ''.join('<li>' + escape(x) + '</li>' for x in reasons)
                + '</ul><p class="muted">量价比较截至 ' + escape(v.get("asof") or "未知") + '</p></details></article>')

    m = ai.get("market") or {}
    blocks = [("市场点评", m.get("commentary") or m.get("summary") or "尚无AI点评，保留程序事实。"),
              ("盘面结构", m.get("structure") or "本轮未生成结构解读。"),
              ("市场模式", m.get("mode_summary") or m.get("state") or "模式依据待补充。")]
    mv = facts.get("market_volume") or {}
    exact, ref = mv.get("exact", {}), mv.get("reference", {})
    use_exact = len(exact.get("rows", [])) >= 5 or not ref.get("rows")
    vol = exact if use_exact else ref
    scope = "沪深非ST实际完整收盘记录" if use_exact else "沪深A股含ST参考 · 与严格过滤统计分开"
    parts = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>trade · 量价分析报告</title><style>', STYLE,
             '</style></head><body><main><p class="muted">P03 / TRADE · 量价优先 · 人工交易</p><h1>', escape(m.get("state") or "程序量价事实"),
             '</h1><p class="muted">数据截至 ', escape(str(facts.get("asof", "未知"))), ' · 生成 ', escape(str(run.get("finished_at") or run.get("created_at"))),
             ' · ', escape(trace.get("provider", "未调用AI")), ' / ', escape(trace.get("model", "型号未报告")), ' · 后备调用' if trace.get("fallback_used") else '', '</p>']
    if run.get("error"):
        parts.extend(['<p class="warn">', escape(run["error"]["message"]), '</p>'])
    parts.append('<div class="three">')
    for title, text in blocks:
        parts.extend(['<article class="card"><h3>', title, '</h3><p>', escape(text), '</p></article>'])
    parts.extend(['</div><div class="stats"><div>上涨 / 下跌<b>', str(market.get("advancing", "—")), ' / ', str(market.get("declining", "—")),
                  '</b></div><div>沪深非ST成交额<b>', fmt(market.get("amount")), '</b></div><div>可排序候选<b>', str(selection["eligible_count"]),
                  ' / ', str(selection["analyzed_count"]), '</b></div></div><section class="card volume"><h3>全市场量能</h3><p class="muted">',
                  escape(scope), '</p>', turnover(vol.get("rows", [])), '<p class="insight">', escape(vol.get("summary", "量能历史不足")),
                  '</p><p class="muted">严格非ST历史积累 ', str(len(exact.get("rows", []))),
                  ' 日；不同范围序列不拼接。盘中累计量不直接与完整日相除。</p></section><h2>候选重点 · 最强三项</h2><p class="muted">',
                  escape(selection["label"]), '。相对强弱不表示已经适合交易。</p><div class="three">',
                  ''.join(card(ident) for ident in selection["overall_top3"]), '</div><p class="ma">K线 · MA5 / MA20 / MA60 / MA120 淡色参考 · 下方为同时间轴成交量</p>'])
    for group in selection["groups"]:
        if group["asset_ids"]:
            parts.extend(['<h2>', escape(group["title"]), '</h2><div class="grid">', ''.join(card(ident) for ident in group["asset_ids"]), '</div>'])
    parts.extend(['<p class="muted">成交额前十已分析 ', str(selection["dynamic_analyzed"]),
                  ' 项，常规展示综合前三；固定关注与宽基保留，同对象去重。</p><details><summary>完整限制与覆盖记录</summary><ul>'])
    for x in facts.get("coverage", []):
        if x.get("status") != "ok":
            parts.extend(['<li>', escape(x.get("group", "") + "：" + x.get("detail", "")), '</li>'])
    parts.extend('<li>' + escape(x) + '</li>' for x in ai.get("limitations", []))
    attempts = ((run.get("error") or {}).get("details") or {}).get("attempts", []) or trace.get("attempts", [])
    parts.extend('<li>AI调用：' + escape(x.get("provider", "") + " · " + x.get("message", "")) + '</li>' for x in attempts)
    parts.extend(['</ul></details><footer>轮次 ', escape(run["id"]), ' · 导出 ', escape(now()),
                  '。离线快照；确认计划、回填、删除与恢复需要正在运行的本地应用。</footer></main></body></html>'])
    return ''.join(parts)
