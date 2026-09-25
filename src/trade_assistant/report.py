from html import escape

from .util import now


def num(value, digits=2):
    return "—" if value is None else ("%.*f" % (digits, value))


def price_svg(technical):
    bars = technical.get("bars", [])[-90:]
    if len(bars) < 2:
        return '<p class="muted">历史数据不足，未绘制价格走势。</p>'
    values = [x["close"] for x in bars]
    low, high = min(values), max(values)
    span = high - low or 1
    points = " ".join("%.1f,%.1f" % (35 + i * 570 / (len(values) - 1), 150 - (v - low) / span * 120) for i, v in enumerate(values))
    return '<svg viewBox="0 0 640 180" role="img" aria-label="日线收盘走势"><path d="M35 20V150H610" fill="none" stroke="#d9e4de"/><polyline points="' + points + '" fill="none" stroke="#236b56" stroke-width="2.3"/><text x="35" y="173" fill="#586b67" font-size="11">' + escape(bars[0]["date"]) + '</text><text x="510" y="173" fill="#586b67" font-size="11">' + escape(bars[-1]["date"]) + '</text></svg>'


def render(run):
    facts = run.get("facts") or {}
    ai = (run.get("analysis") or {}).get("result") or {}
    market = facts.get("market") or {}
    summary = (ai.get("market") or {}).get("summary", "本轮尚无有效AI解读，以下为程序已取得的事实。")
    opinions = {x["asset_id"]: x for x in ai.get("candidates", [])}
    sections = []
    for item in facts.get("candidates", []):
        opinion = opinions.get(item["asset_id"], {})
        tech = item.get("technical") or {}
        latest = tech.get("latest") or {}
        body = '<h3>' + escape(item["name"]) + '</h3><p>' + escape(opinion.get("reason", "未取得该候选的AI解读")) + '</p>'
        body += '<p class="muted">状态：' + escape({"candidate": "可关注方向", "observe": "观察", "wait": "等待"}.get(opinion.get("stance"), "未分析")) + ' · 技术数据：' + escape(str(tech.get("asof", "缺失"))) + '</p>'
        body += price_svg(tech)
        body += '<p class="muted">CCI ' + num(latest.get("cci")) + ' · DIF ' + num(latest.get("dif")) + ' · DEA ' + num(latest.get("dea")) + '</p>'
        against = opinion.get("against", []) + opinion.get("missing", [])
        if against:
            body += '<ul>' + ''.join('<li>' + escape(x) + '</li>' for x in against) + '</ul>'
        sections.append('<details><summary>' + escape(item["name"]) + ' · ' + escape({"candidate": "关注", "observe": "观察", "wait": "等待"}.get(opinion.get("stance"), "缺解读")) + '</summary>' + body + '</details>')
    gaps = ''.join('<li>' + escape(x.get("group", "")) + '：' + escape(x.get("detail", "")) + '</li>' for x in facts.get("coverage", []) if x.get("status") != "ok")
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>trade · 分析快照</title><style>
    *{box-sizing:border-box}body{margin:0;background:#f5f7f5;color:#183438;font:16px/1.8 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{max-width:1000px;margin:auto;padding:32px 24px}h1{font-size:30px}h2{font-size:21px}h3{font-size:18px}p{white-space:pre-wrap}.muted{color:#596e70;font-size:13px}.card,details{background:white;border:1px solid #dce5df;border-radius:14px;padding:20px;margin:15px 0}summary{cursor:pointer;font-weight:650}.stats{display:flex;flex-wrap:wrap;gap:30px}.stats b{display:block;font-size:24px}.up{color:#b44d3c}.down{color:#1b7b5b}svg{display:block;width:100%;max-height:200px}li{margin:6px 0}.tag{font-size:12px;color:#17664d}a{color:#17664d}footer{font-size:12px;color:#647572;margin-top:25px}@media print{details{break-inside:avoid}}
    </style></head><body><main><div class="tag">P03 / TRADE · 真实来源数据快照 · 人工交易</div><h1>''' + escape((ai.get("market") or {}).get("state", "程序事实与数据缺口")) + '''</h1><p class="muted">源数据截至 ''' + escape(str(facts.get("asof", "未知"))) + ' · 本轮生成 ' + escape(str(run.get("finished_at") or run.get("created_at"))) + ' · 导出 ' + escape(now()) + '''</p><section class="card"><p>''' + escape(summary) + '''</p></section><section class="card stats"><div>上涨<b class="up">''' + num(market.get("advancing"), 0) + '''</b></div><div>下跌<b class="down">''' + num(market.get("declining"), 0) + '''</b></div><div>统计范围<b>''' + num(market.get("eligible_count"), 0) + '''</b></div><div>来源目录完整<b>''' + ("是" if market.get("directory_complete") else "否") + '''</b></div></section><h2>候选与依据</h2>''' + ''.join(sections) + '''<details><summary>数据缺口与口径</summary><ul>''' + gaps + '''</ul><p class="muted">''' + escape(market.get("limit_definition", "")) + '''</p></details><footer>轮次 ''' + escape(run["id"]) + '''。本文件是已生成结果的离线快照；按钮触发、计划确认和回填需使用正在运行的本地系统。数据日期、可得范围与AI生成状态均保留。</footer></main></body></html>'''
