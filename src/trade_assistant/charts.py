"""Small self-contained SVG charts, shared by page and report."""
from html import escape

from .indicators import sma

PALETTE = {5: "#b5ac86", 20: "#94b4cd", 60: "#b39fc3", 120: "#9fbfac"}
UP, DOWN = "#bf6356", "#388674"


def fmt(value):
    if value is None:
        return "—"
    if abs(value) >= 1e12:
        return "%.2f万亿" % (value / 1e12)
    if abs(value) >= 1e8:
        return "%.2f亿" % (value / 1e8)
    if abs(value) >= 1e4:
        return "%.1f万" % (value / 1e4)
    return "%.2f" % value


def candles(technical, period="daily", count=65):
    source = technical.get("weekly" if period == "weekly" else "bars", [])
    if len(source) < 2:
        return '<p class="muted small">暂无足够的真实K线资料</p>'
    closes = [b["close"] for b in source]
    mas = {p: sma(closes, p) for p in PALETTE}
    bars = source[-count:]
    offset = len(source) - len(bars)
    values = [v for b in bars for v in (b["high"], b["low"])]
    values += [x for series in mas.values() for x in series[offset:] if x is not None]
    lo, hi = min(values), max(values)
    span = hi - lo or hi * .01 or 1
    lo, hi = lo - span * .06, hi + span * .06
    step = 560 / len(bars)
    x = lambda i: 56 + step * (i + .5)
    y = lambda v: 170 - (v - lo) / (hi - lo) * 145
    vmax = max((b.get("volume") or 0 for b in bars), default=1) or 1
    shapes = []
    for t in (0, .5, 1):
        v = lo + (hi - lo) * t
        shapes.append('<path d="M52 %.1fH620" stroke="#e6ede7"/><text x="47" y="%.1f" text-anchor="end" fill="#7b8b80" font-size="10">%s</text>' % (y(v), y(v) + 3, fmt(v)))
    for p, series in mas.items():
        points = " ".join("%.1f,%.1f" % (x(i), y(v)) for i, v in enumerate(series[offset:]) if v is not None)
        if points:
            shapes.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="1.2" opacity=".75"/>' % (points, PALETTE[p]))
    width = max(2, min(8, step * .6))
    for i, b in enumerate(bars):
        color = UP if b["close"] >= b["open"] else DOWN
        tooltip = "%s 开%s 高%s 低%s 收%s 量%s" % (b["date"], fmt(b["open"]), fmt(b["high"]), fmt(b["low"]), fmt(b["close"]), fmt(b.get("volume")))
        shapes.append('<g><title>%s</title><path d="M%.1f %.1fV%.1f" stroke="%s"/><rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s"/>' % (escape(tooltip), x(i), y(b["high"]), y(b["low"]), color, x(i) - width / 2, min(y(b["open"]), y(b["close"])), width, max(1, abs(y(b["open"]) - y(b["close"]))), color))
        if b.get("volume") is not None and b["volume"] >= 0:
            height = b["volume"] / vmax * 45
            shapes.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" opacity=".55"/>' % (x(i) - width / 2, 238 - height, width, height, color))
        shapes.append('</g>')
    shapes.append('<path d="M52 181H620M52 239H620" stroke="#dce6de"/><text x="5" y="199" fill="#7b8b80" font-size="10">成交量</text>')
    shapes.append('<text x="53" y="259" fill="#7b8b80" font-size="10">%s</text><text x="546" y="259" fill="#7b8b80" font-size="10">%s</text>' % (escape(bars[0]["date"]), escape(bars[-1]["date"])))
    return '<svg viewBox="0 0 640 270" role="img" aria-label="%sK线、均线与成交量">%s</svg>' % ("周" if period == "weekly" else "日", "".join(shapes))


def turnover(rows):
    rows = [x for x in rows if x.get("amount") is not None][-30:]
    if not rows:
        return '<p class="muted small">暂无可用全市场成交额历史，无法比较放量或缩量。</p>'
    max_value = max(x["amount"] for x in rows) or 1
    step = 550 / max(len(rows), 6)
    shapes = ['<path d="M55 150H615" stroke="#dce6de"/>']
    for i, item in enumerate(rows):
        value = item["amount"]
        color = "#6a9f8c" if i < len(rows) - 1 else "#285f4c"
        shapes.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" fill="%s"><title>%s：%s元</title></rect>' % (55 + i * step, 150 - value / max_value * 120, max(3, step * .65), value / max_value * 120, color, escape(item["date"]), fmt(value)))
    shapes.append('<text x="5" y="20" fill="#667e70" font-size="11">%s元</text><text x="55" y="172" fill="#667e70" font-size="11">%s → %s</text>' % (fmt(max_value), escape(rows[0]["date"]), escape(rows[-1]["date"])))
    return '<svg viewBox="0 0 640 182" role="img" aria-label="完整交易日成交额历史">' + ''.join(shapes) + '</svg>'
