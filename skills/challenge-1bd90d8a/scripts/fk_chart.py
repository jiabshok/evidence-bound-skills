"""Vector charts from tabular data with one addressable element per datum.

Every mark carries data-src (file#row), data-x / data-y as written in the source
table, so the drawing can be inverted back to numbers (`read_back`) and compared
with the table without trusting the drawing code's own bookkeeping.
"""
import csv
import io
import json
import math
import re
from collections import OrderedDict
from html import escape

from kit_table import load_table, num  # noqa: F401
import fk_text
from fk_text import svg_text, tspans, width, wrap, strip_markup

# Okabe-Ito, ordered so that neighbouring entries differ in luminance as well as hue
PALETTE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#5B5B5B", "#B8A900"]
MARKS = ["circle", "square", "triangle", "diamond", "cross", "circle", "square", "triangle"]
DASH = ["", "7 4", "2 3", "9 3 2 3", "1 2", "12 4", "4 2", "6 2 1 2"]
HATCHES = [None, "diag", "dots", "cross", "horiz", "vert", "diag2", None]
INK, GRID = "#1b1f24", "#dfe3e8"


def nice_ticks(lo, hi, n=5):
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / max(1, n)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            step = m * mag
            break
    t = math.floor(lo / step) * step
    out = []
    while t <= hi + step * 0.501:
        out.append(round(t, 12))
        t += step
    return out, step


def fmt(v, step=None):
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 1e5 or a < 1e-3:
        e = int(math.floor(math.log10(a)))
        m = v / 10 ** e
        ms = ("%.2f" % m).rstrip("0").rstrip(".")
        return ("10^{%d}" % e) if ms == "1" else "%s×10^{%d}" % (ms, e)
    dec = 0
    if step:
        dec = max(0, -int(math.floor(math.log10(step) + 1e-9)))
        if abs(step * 10 ** dec - round(step * 10 ** dec)) > 1e-6:
            dec += 1
    s = "%.*f" % (dec, v) if step else "%g" % v
    return s.replace("-", "−")


class Axis:
    def __init__(self, lo, hi, p0, p1, log=False):
        self.lo, self.hi, self.p0, self.p1, self.log = lo, hi, p0, p1, log

    def f(self, v):
        return math.log10(v) if self.log else v

    def to(self, v):
        a, b = self.f(self.lo), self.f(self.hi)
        return self.p0 + (self.f(v) - a) / (b - a) * (self.p1 - self.p0)

    def inv(self, p):
        a, b = self.f(self.lo), self.f(self.hi)
        u = a + (p - self.p0) / (self.p1 - self.p0) * (b - a)
        return 10 ** u if self.log else u

    def ticks(self, n=5):
        if self.log:
            k0, k1 = math.ceil(math.log10(self.lo) - 1e-9), math.floor(math.log10(self.hi) + 1e-9)
            t = [10.0 ** k for k in range(k0, k1 + 1)]
            if len(t) < 3:
                t = [x for x in (m * 10.0 ** k for k in range(k0 - 1, k1 + 2) for m in (1, 2, 5))
                     if self.lo * 0.999 <= x <= self.hi * 1.001]
            return t, None
        t, s = nice_ticks(self.lo, self.hi, n)
        return [x for x in t if self.lo - 1e-9 * abs(s) <= x <= self.hi + 1e-9 * abs(s)], s


def _mark(shape, x, y, r, fill, attrs):
    st = 'fill="%s" stroke="#ffffff" stroke-width="0.8"' % fill
    if shape == "square":
        return '<rect x="%.3f" y="%.3f" width="%.2f" height="%.2f" %s %s/>' % (x - r, y - r, 2 * r, 2 * r, st, attrs)
    if shape == "triangle":
        p = "%.3f,%.3f %.3f,%.3f %.3f,%.3f" % (x, y - r * 1.2, x + r * 1.1, y + r * 0.9, x - r * 1.1, y + r * 0.9)
        return '<polygon points="%s" %s %s/>' % (p, st, attrs)
    if shape == "diamond":
        p = "%.3f,%.3f %.3f,%.3f %.3f,%.3f %.3f,%.3f" % (x, y - r * 1.3, x + r * 1.3, y, x, y + r * 1.3, x - r * 1.3, y)
        return '<polygon points="%s" %s %s/>' % (p, st, attrs)
    if shape == "cross":
        return '<path d="M%.3f %.3fL%.3f %.3fM%.3f %.3fL%.3f %.3f" stroke="%s" stroke-width="2" fill="none" %s/>' % (
            x - r, y - r, x + r, y + r, x - r, y + r, x + r, y - r, fill, attrs)
    return '<circle cx="%.3f" cy="%.3f" r="%.2f" %s %s/>' % (x, y, r, st, attrs)


FUNCS = {"log10": math.log10, "log2": math.log2, "ln": math.log, "sqrt": math.sqrt, "abs": abs, "exp": math.exp}


def evaluate(expr, row):
    """Arithmetic on columns of one row: names or [column name]; + - * / ** ( ) and log10 log2 ln sqrt abs exp."""
    import ast
    names = {}

    def sub(m):
        k = "c%d_" % len(names)
        names[k] = m.group(1)
        return k
    tree = ast.parse(re.sub(r"\[([^\]]+)\]", sub, expr), mode="eval")

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            if a is None or b is None:
                return None
            t = type(n.op)
            if t is ast.Div:
                return a / b if b != 0 else None
            return {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b, ast.Pow: lambda: a ** b}[t]()
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return None if v is None else (-v if isinstance(n.op, ast.USub) else v)
        if isinstance(n, ast.Constant):
            return float(n.value)
        if isinstance(n, ast.Name):
            col = names.get(n.id, n.id)
            if col not in row:
                raise ValueError("derive: column '%s' not found" % col)
            return num(row[col])
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS and len(n.args) == 1:
            v = ev(n.args[0])
            try:
                return None if v is None else FUNCS[n.func.id](v)
            except ValueError:
                return None
        raise ValueError("derive: unsupported expression " + expr)
    return ev(tree)


def prepare(panel, cols, rows):
    """Apply where -> derive -> reduce. Returns (cols, rows); '_src' holds contributing source rows."""
    if not (panel.get("derive") or panel.get("reduce")):
        return cols, rows
    out = []
    for k, r in select(rows, panel.get("where")):
        r = dict(r, _src=str(k))
        for name, ex in (panel.get("derive") or {}).items():
            v = evaluate(ex, r)
            r[name] = "" if v is None else repr(float("%.12g" % v))
        out.append(r)
    cols = list(cols) + [c for c in (panel.get("derive") or {}) if c not in cols]
    rd = panel.get("reduce")
    if rd:
        yk, fn = rd.get("y") or panel.get("y"), rd.get("fn", "mean")
        groups = OrderedDict()
        for r in out:
            groups.setdefault(tuple(r.get(c, "") for c in rd["by"]), []).append(r)
        red = []
        for key, rs in groups.items():
            v = [num(r[yk]) for r in rs if num(r[yk]) is not None]
            if not v:
                continue
            sv = sorted(v)
            m = len(sv)
            val = {"max": max(v), "min": min(v), "sum": sum(v), "mean": sum(v) / m, "count": m, "first": v[0], "last": v[-1],
                   "median": sv[m // 2] if m % 2 else (sv[m // 2 - 1] + sv[m // 2]) / 2}.get(fn)
            if val is None:
                raise ValueError("reduce fn '%s' unknown (max min mean median sum count first last)" % fn)
            base = dict(rs[0])
            base[yk] = repr(float("%.12g" % val))
            base["_src"] = ",".join(r["_src"] for r in rs)
            red.append(base)
        out = red
    return cols, out


def halo(x, y, text, size, anchor, fill):
    w, h = width(text, size) + 6, size * 1.2
    x0 = x - w + 3 if anchor == "end" else x - 3 if anchor == "start" else x - w / 2
    return '<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#ffffff" fill-opacity="0.82"/>%s' % (x0, y - h / 2, w, h, svg_text(x, y, [text], size, anchor, fill=fill))


def log_floor(v):
    k = math.floor(math.log10(v) + 1e-12)
    for m in (5, 2, 1):
        if m * 10.0 ** k <= v * (1 + 1e-9):
            return m * 10.0 ** k


def log_ceil(v):
    k = math.floor(math.log10(v) - 1e-12)
    for m in (1, 2, 5, 10):
        if m * 10.0 ** k >= v * (1 - 1e-9):
            return m * 10.0 ** k


def select(rows, where):
    """where: {"col": value | [values]}; returns [(row_index_1based, row)]"""
    out = []
    for k, r in enumerate(rows, 1):
        ok = True
        for c, v in (where or {}).items():
            vals = [str(x) for x in (v if isinstance(v, list) else [v])]
            if str(r.get(c, "")) not in vals:
                ok = False
        if ok:
            out.append((k, r))
    return out


def _uniq(seq):
    return list(OrderedDict((s, 1) for s in seq))


STATS = {"mean_sd": "mean +/- SD (n-1)", "mean_sem": "mean +/- SEM (SD/sqrt(n), n-1)", "mean_ci95": "mean +/- 95% CI (t distribution)", "median_iqr": "median with Q1-Q3 (linear interpolation)", "mean": "mean", "median": "median",
         "geomean_sd": "geometric mean x/÷ geometric SD (log10, n-1)"}
T975 = [0, 12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]


def summary(v, stat):
    n = len(v)
    s = sorted(v)

    def q(p):
        k = (n - 1) * p
        f = int(math.floor(k))
        return s[f] + (s[min(f + 1, n - 1)] - s[f]) * (k - f)
    if stat.startswith("median"):
        return q(.5), (q(.25) if stat == "median_iqr" else None), (q(.75) if stat == "median_iqr" else None)
    if stat == "geomean_sd":
        lg = [math.log10(x) for x in v]
        m = sum(lg) / n
        sd = math.sqrt(sum((x - m) ** 2 for x in lg) / (n - 1)) if n > 1 else None
        return 10 ** m, (10 ** (m - sd) if sd is not None else None), (10 ** (m + sd) if sd is not None else None)
    m = sum(v) / n
    if n < 2 or stat == "mean":
        return m, None, None
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (n - 1))
    e = {"mean_sd": sd, "mean_sem": sd / math.sqrt(n), "mean_ci95": sd / math.sqrt(n) * (T975[n - 1] if n - 1 < len(T975) else 1.96)}.get(stat)
    if e is None:
        raise ValueError("stat '%s' unknown; use %s" % (stat, " ".join(STATS)))
    return m, m - e, m + e


def summarise(raw, stat, panel):
    """Replicate summaries. Default cells: same x and group; with stat_by the cell is stat_by + group and x becomes the cell mean."""
    by = panel.get("stat_by")
    by = [by] if isinstance(by, str) else by
    cells = OrderedDict()
    for d in raw:
        key = (tuple(d["r"].get(c, "") for c in by) if by else d["x"], d["g"])
        cells.setdefault(key, []).append(d)
    out = []
    for (x, g), ds in cells.items():
        m, lo, hi = summary([d["y"] for d in ds], stat)
        rec = {"row": ds[0]["row"], "rows": [d["row"] for d in ds], "r": ds[0]["r"], "y": m, "lo": lo, "hi": hi, "g": g, "x": ds[0]["x"], "n": len(ds), "order": len(out)}
        if by:
            xs = [num(d["x"]) for d in ds]
            if any(v is None for v in xs):
                raise ValueError("stat_by needs a numeric x column")
            xm, xl, xh = summary(xs, stat)
            rec.update(x=repr(float("%.12g" % xm)), xlo=xl, xhi=xh, cell="|".join(x))
        out.append(rec)
    return out


def draw_chart(panel, X, Y, W, H, read, fs=15, pid="chart"):
    """Draw one chart; returns (svg, info). `read(file)` gives (cols, rows)."""
    kind = panel.get("chart", panel.get("kind", "bar"))
    fs = max(fs, fk_text.FLOOR[0] * 1.02) if panel.get("_tight") else max(fs, fk_text.FLOOR[0] / 0.82)
    fname = panel["data"]
    cols, rows = prepare(panel, *read(fname))
    sel = select(rows, panel.get("where"))
    xk, yk, gk = panel.get("x"), panel.get("y"), panel.get("group")
    need = [c for c in (xk, yk, gk, panel.get("xerr"), panel.get("xlo"), panel.get("xhi"), panel.get("err"), panel.get("lo"), panel.get("hi"), panel.get("value")) if c]
    missing = [c for c in need if c not in cols]
    if missing:
        raise ValueError("%s: column(s) %s not in %s; columns are %s" % (pid, missing, fname, cols))
    if not sel:
        raise ValueError("%s: filter %s matches no rows of %s" % (pid, panel.get("where"), fname))
    info = {"panel": pid, "file": fname, "kind": kind, "rows_total": len(rows), "rows_selected": len(sel),
            "mapping": {k: panel[k] for k in ("x", "y", "group", "err", "lo", "hi", "value", "err_meaning", "n", "stat", "stat_by",
                                              "where", "xscale", "yscale") if panel.get(k)},
            "marks": 0, "missing_rows": []}
    s = ['<g id="%s-chart" data-role="chart" data-file="%s">' % (pid, escape(fname))]
    labels = panel.get("labels", {})
    order = panel.get("order") or None
    gorder = panel.get("group_order") or None
    groups = _uniq([r[gk] for _, r in sel]) if gk else [None]
    if gorder:
        groups = [g for g in gorder if g in groups] + [g for g in groups if g not in gorder]
    colors = {g: (panel.get("colors", {}).get(str(g)) or (panel.get("color") if len(groups) == 1 else None) or PALETTE[i % len(PALETTE)]) for i, g in enumerate(groups)}
    marks = {g: MARKS[i % len(MARKS)] for i, g in enumerate(groups)}
    info["groups"] = [g for g in groups if g is not None]
    same = gk is not None and gk == xk and kind in ("bar", "dot", "box")  # colour follows the category, no dodging
    nd = 1 if same else len(groups)

    if kind == "heatmap":
        return _heatmap(panel, X, Y, W, H, sel, fs, pid, info, s, labels)

    # legend first (top strip)
    leg_h = 0
    if gk and panel.get("legend", True) and not same:
        lx, ly, rowh = X + 4, Y + 10, fs * 1.35
        s.append('<g id="%s-legend" data-role="legend">' % pid)
        for i, g in enumerate(groups):
            lab = labels.get(str(g), str(g))
            w = width(lab, fs * 0.9) + 38
            if lx + w > X + W and lx > X + 4:
                lx, ly = X + 4, ly + rowh
            if kind in ("bar", "stacked", "box"):
                s.append('<rect x="%.2f" y="%.2f" width="16" height="11" fill="%s" stroke="%s" stroke-width="0.8"/>' % (
                    lx, ly - 5.5, colors[g], INK))
                s.append(_hatch(HATCHES[i % 8], lx, ly - 5.5, 16, 11))
            else:
                if kind == "line":
                    s.append('<path d="M%.2f %.2fH%.2f" stroke="%s" stroke-width="2" stroke-dasharray="%s"/>' % (
                        lx, ly, lx + 22, colors[g], DASH[i % 8]))
                s.append(_mark(marks[g], lx + 11, ly, 4.2, colors[g], ""))
            s.append(svg_text(lx + 27, ly, [lab], fs * 0.9, "start"))
            lx += w
        s.append("</g>")
        leg_h = ly - Y + rowh * 0.7
    xt, yt = panel.get("xlabel", xk or ""), panel.get("ylabel", yk or "")
    top, bottom = Y + leg_h + (8 if panel.get("_tight") else 14), Y + H - fs * (1.7 if panel.get("_tight") and not xt else 3.0)
    # values
    cat = kind in ("bar", "stacked", "box", "dot", "forest") or (kind == "line" and any(num(r[xk]) is None for _, r in sel))
    ylog, xlog = panel.get("yscale") == "log", panel.get("xscale") == "log"

    def yv(r):
        return num(r[yk])

    data = []
    for k, r in sel:
        v = yv(r)
        if v is None:
            info["missing_rows"].append(k)
            continue
        e0 = e1 = None
        if panel.get("err"):
            d = num(r[panel["err"]])
            if d is not None:
                e0, e1 = v - d, v + d
        elif panel.get("lo") and panel.get("hi"):
            e0, e1 = num(r[panel["lo"]]), num(r[panel["hi"]])
        data.append({"row": k, "r": r, "y": v, "lo": e0, "hi": e1, "g": r[gk] if gk else None, "x": r[xk] if xk else ""})
    if not data:
        raise ValueError("%s: no numeric values in column %s" % (pid, yk))
    stat = panel.get("stat")
    raw = []
    if stat and kind not in ("line", "bar", "dot", "forest"):
        info.setdefault("warnings", []).append("stat is not applied to %s charts; use line, bar, dot or forest" % kind)
    if panel.get("stat_by") and kind != "line":
        raise ValueError("%s: stat_by works with chart \"line\" only" % pid)
    if stat and kind in ("line", "bar", "dot", "forest"):
        raw = data
        data = summarise(raw, stat, panel)
        info["statistic"] = STATS.get(stat, stat) + "; computed by the engine from the listed rows"
    info["values"] = [[";".join(map(str, d["rows"])) if d.get("rows") else d["row"], d["g"] if gk else "", d["x"], d["y"], "" if d["lo"] is None else d["lo"], "" if d["hi"] is None else d["hi"], d.get("n", ""), stat or "as supplied"] for d in data] + \
                     [[d["row"], d["g"] if gk else "", d["x"], d["y"], "", "", 1, "individual observation"] for d in raw]
    if kind == "forest":
        return _forest(panel, X, Y + leg_h, W, H - leg_h, data, fs, pid, info, s, labels, colors, marks, xt, yt)
    vals = [d["y"] for d in data + raw] + [d["lo"] for d in data if d["lo"] is not None] + [d["hi"] for d in data if d["hi"] is not None]
    if kind == "stacked":
        sums = {}
        for d in data:
            sums[d["x"]] = sums.get(d["x"], 0) + d["y"]
        vals += list(sums.values())
    lo, hi = min(vals), max(vals)
    if panel.get("ylim"):
        lo, hi = map(float, panel["ylim"])
    elif ylog:
        pos = [v for v in vals if v > 0]
        if any(d["lo"] is not None and d["lo"] <= 0 for d in data):
            info.setdefault("warnings", []).append("an error bar reaches zero or below and is cut at the lower edge of the log axis; state this in the note or use geomean_sd / median_iqr")
        if any(d["y"] <= 0 for d in data + raw):
            raise ValueError("%s: log axis requested but non-positive values present" % pid)
        lo, hi = log_floor(min(pos)), log_ceil(max(pos))
        if lo == hi:
            hi = lo * 10
    else:
        if kind in ("bar", "stacked"):
            lo, hi = min(0, lo), max(0, hi)
        elif lo > 0 and lo < 0.35 * hi:
            lo = 0
        t, st = nice_ticks(lo, hi)
        lo, hi = (t[0] if t[0] <= lo else lo), t[-1] if t[-1] >= hi else t[-1] + st
        if kind in ("bar", "stacked") and min(vals) >= 0:
            lo = 0
    yax = Axis(lo, hi, bottom, top, ylog)
    tk, st = yax.ticks()
    while len(tk) > 3 and abs(yax.to(tk[1]) - yax.to(tk[0])) < fs * 1.02:  # low plot: fewer tick labels
        tk = tk[::2]
    logfmt = ylog and (max(tk) >= 1e5 or min(tk) < 1e-3) and all(abs(math.log10(t) - round(math.log10(t))) < 1e-9 for t in tk)
    yfmt = (lambda t: "10^{%d}" % round(math.log10(t))) if logfmt else (lambda t: fmt(t, st))
    tw = max(width(yfmt(t), fs * 0.88) for t in tk)
    ylines = wrap(yt, fs, max(60, bottom - top + fs * .6)) if yt else []
    if len(ylines) > 2 or (yt and panel.get("ytop")):  # short panel: put the axis title horizontally above the axis
        tl = wrap(yt, fs, W - 14)
        s.append(svg_text(X + 4, top - 2 + (len(tl) - 1) * fs * .6, tl, fs, "start"))
        top += fs * 1.25 * len(tl)
        yax.p1 = top
        ylines = []
    if bottom - top < fs * 4.2:
        raise ValueError("panel %s: no room left for the chart (plot height %.0f units): shorten its note and title (note at most 2 lines), leave xlabel \"\" or move values to a text item" % (pid, max(0, bottom - top)))
    left = X + tw + (fs * 1.35 if ylines else 4) + 18 + max(0, len(ylines) - 1) * fs * 1.18
    right = X + W - 12
    # x axis
    if cat:
        cats = _uniq([d["x"] for d in data])
        if order:
            cats = [c for c in order if c in cats] + [c for c in cats if c not in order]
        slot = (right - left) / len(cats)
        clabels = [wrap(labels.get(str(c), str(c)), fs * 0.88, max(34, slot - 6)) for c in cats]
        rotate = max(width(l, fs * 0.88) for ls in clabels for l in ls) > slot - 2 and len(cats) > 4
        if rotate:
            longest = max(width(labels.get(str(c), str(c)), fs * 0.85) for c in cats)
            bottom -= min(130, longest * 0.71) - fs * 0.6
        else:
            bottom -= (max(len(l) for l in clabels) - 1) * fs * 1.05
        yax.p0 = bottom
    else:
        xs = [num(d["x"]) for d in data]
        if any(v is None for v in xs):
            bad = [d["row"] for d in data if num(d["x"]) is None]
            raise ValueError("%s: non-numeric x in rows %s" % (pid, bad[:6]))
        xl, xh = min(xs), max(xs)
        if panel.get("stat_by"):
            xx = [v for d in data for v in (d.get("xlo"), d.get("xhi")) if v is not None] + [num(d["x"]) for d in raw]
            xl, xh = min([xl] + xx), max([xh] + xx)
        if panel.get("xerr"):
            xe = [(num(d["x"]), num(d["r"].get(panel["xerr"])) or 0) for d in data]
            xl, xh = min(a - b for a, b in xe), max(a + b for a, b in xe)
        for o in panel.get("overlays") or []:
            if o.get("data") and o.get("x"):
                _, orows = prepare(o, *read(o["data"]))
                ov = [num(r.get(o["x"], "")) for _, r in select(orows, o.get("where"))]
                ov = [v for v in ov if v is not None]
                if ov:
                    xl, xh = min([xl] + ov), max([xh] + ov)
        if panel.get("xlim"):
            xl, xh = map(float, panel["xlim"])
        elif xlog:
            if xl <= 0:
                raise ValueError("%s: log x axis with non-positive values" % pid)
            xl, xh = log_floor(xl), log_ceil(xh)
            if xl == xh:
                xh = xl * 10
        else:
            t, sx = nice_ticks(xl, xh)
            pad = (xh - xl) * 0.04 or 1
            xl, xh = xl - pad, xh + pad
        xax = Axis(xl, xh, left, right, xlog)
    # frame
    s.append('<g id="%s-axes" data-role="axes" data-y0="%.6g" data-y1="%.6g" data-yp0="%.4f" data-yp1="%.4f" data-ylog="%d">' % (
        pid, yax.lo, yax.hi, yax.p0, yax.p1, int(ylog)))
    for t in tk:
        y = yax.to(t)
        s.append('<path d="M%.2f %.2fH%.2f" stroke="%s" stroke-width="0.8"/>' % (left, y, right, GRID))
        s.append(svg_text(left - 7, y, [yfmt(t)], fs * 0.88, "end"))
    s.append('<path d="M%.2f %.2fV%.2fH%.2f" fill="none" stroke="%s" stroke-width="1.3"/>' % (left, top, bottom, right, INK))
    if not ylog and yax.lo < 0 < yax.hi:
        s.append('<path d="M%.2f %.2fH%.2f" stroke="%s" stroke-width="1.1"/>' % (left, yax.to(0), right, INK))
    if cat:
        for c, ls, i in zip(cats, clabels, range(len(cats))):
            cx = left + slot * (i + .5)
            if rotate:
                s.append('<text x="%.2f" y="%.2f" font-size="%.2f" text-anchor="end" fill="%s" transform="rotate(-45 %.2f %.2f)">%s</text>' % (
                    cx + 4, bottom + fs * 0.9, fs * 0.85, INK, cx + 4, bottom + fs * 0.9, tspans(labels.get(str(c), str(c)), fs * .85)))
            else:
                s.append(svg_text(cx, bottom + fs * 0.9 + (len(ls) - 1) * fs * 0.53, ls, fs * 0.88))
    else:
        xt_, sx = xax.ticks()
        for t in xt_:
            x = xax.to(t)
            s.append('<path d="M%.2f %.2fv5" stroke="%s" stroke-width="1.1"/>' % (x, bottom, INK))
            s.append(svg_text(x, bottom + fs * 0.95, [fmt(t, sx)], fs * 0.88))
    s.append(svg_text((left + right) / 2, Y + H - fs * 0.8, [xt], fs))
    yx = X + fs * 0.75 + max(0, len(ylines) - 1) * fs * .6
    s.append('<g transform="rotate(-90 %.2f %.2f)">%s</g>' % (yx, (top + bottom) / 2, svg_text(yx, (top + bottom) / 2, ylines or [""], fs, line_h=1.18)))
    s.append("</g>")
    s.append('<g id="%s-data" data-role="data">' % pid)

    def attrs(d, part):
        return 'id="%s-%s-r%d" data-src="%s#%d" data-rows="%s" data-stat="%s"%s data-x="%s" data-y="%r" data-group="%s"' % (
            pid, part, d["row"], escape(fname), d["row"], ",".join(map(str, d.get("rows") or [d["row"]])), (stat or "") if d.get("rows") else "", ' data-xstat="1"' if d.get("xlo") is not None or panel.get("stat_by") and d.get("rows") else "", escape(str(d["x"])), d["y"], escape(str(d["g"])) if gk else "")

    def errbar(d, cx):
        if d["lo"] is None or d["hi"] is None:
            return ""
        a, b = yax.to(max(d["lo"], yax.lo if ylog else d["lo"])), yax.to(d["hi"])
        return '<path id="%s-err-r%d" data-role="error" data-lo="%r" data-hi="%r" d="M%.3f %.3fV%.3fM%.2f %.3fh8M%.2f %.3fh8" stroke="%s" stroke-width="1.3" fill="none"/>' % (
            pid, d["row"], d["lo"], d["hi"], cx, a, b, cx - 4, a, cx - 4, b, INK)

    def xerrbar(d, x, y):
        if cat:
            return ""
        a = b = None
        if d.get("xlo") is not None:
            a, b = d["xlo"], d["xhi"]
        elif panel.get("xerr"):
            e = num(d["r"].get(panel["xerr"]))
            v = num(d["x"])
            if e is not None:
                a, b = v - e, v + e
        elif panel.get("xlo") and panel.get("xhi"):
            a, b = num(d["r"].get(panel["xlo"])), num(d["r"].get(panel["xhi"]))
        if a is None or b is None:
            return ""
        p0, p1 = xax.to(max(a, xax.lo) if xlog else a), xax.to(b)
        return '<path id="%s-xerr-r%d" data-role="x-error" data-lo="%r" data-hi="%r" d="M%.3f %.3fH%.3fM%.3f %.2fv8M%.3f %.2fv8" stroke="%s" stroke-width="1.3" fill="none"/>' % (
            pid, d["row"], a, b, p0, y, p1, p0, y - 4, p1, y - 4, INK)

    if kind == "bar":
        bw = min(slot * 0.78 / nd, 56)
        for d in data:
            i, j = cats.index(d["x"]), groups.index(d["g"])
            cx = left + slot * (i + .5) + (0 if same else (j - (len(groups) - 1) / 2) * bw)
            y0, y1 = yax.to(max(0, lo) if not ylog else lo), yax.to(d["y"])
            s.append('<rect x="%.3f" y="%.4f" width="%.3f" height="%.4f" fill="%s" stroke="%s" stroke-width="0.8" data-mark="bar" %s/>' % (
                cx - bw * .46, min(y0, y1), bw * .92, abs(y0 - y1), colors[d["g"]], INK, attrs(d, "bar")))
            if len(groups) > 1:
                s.append(_hatch(HATCHES[j % 8], cx - bw * .46, min(y0, y1), bw * .92, abs(y0 - y1)))
            s.append(errbar(d, cx))
            if raw and panel.get("points", True):
                for t, o in enumerate([o for o in raw if o["g"] == d["g"] and o["x"] == d["x"]]):
                    s.append('<circle id="%s-raw-r%d" data-mark="rawpoint" data-src="%s#%d" data-y="%r" cx="%.3f" cy="%.4f" r="2.8" fill="#ffffff" stroke="%s" stroke-width="1.1"/>' % (
                        pid, o["row"], escape(fname), o["row"], o["y"], cx + ((t * .618) % 1 - .5) * bw * .5, yax.to(o["y"]), INK))
            if panel.get("value_labels") and len(data) <= 24:
                ytop = min(y1, y0, yax.to(d["hi"]) if d["hi"] is not None else 1e9)
                vl_ = [str(d["r"][yk]).replace("-", "−")]
                if panel.get("err") and panel.get("_tight") and len(data) <= 6:
                    er_ = "± " + str(d["r"][panel["err"]])
                    vl_ = [vl_[0] + " " + er_] if width(vl_[0] + " " + er_, fs * .82, True) < slot * .96 else [vl_[0], er_]
                s.append(svg_text(cx, ytop - fs * (0.6 if len(vl_) == 1 else 1.1), vl_, fs * 0.82, bold=bool(panel.get("_tight"))))
            info["marks"] += 1
    elif kind == "stacked":
        acc = {}
        for d in sorted(data, key=lambda d: groups.index(d["g"])):
            i = cats.index(d["x"])
            base = acc.get(d["x"], 0)
            acc[d["x"]] = base + d["y"]
            bw = min(slot * .7, 70)
            cx = left + slot * (i + .5)
            y0, y1 = yax.to(base), yax.to(base + d["y"])
            s.append('<rect x="%.3f" y="%.4f" width="%.3f" height="%.4f" fill="%s" stroke="%s" stroke-width="0.8" data-mark="stack" %s/>' % (
                cx - bw / 2, min(y0, y1), bw, abs(y0 - y1), colors[d["g"]], INK, attrs(d, "stack")))
            s.append(_hatch(HATCHES[groups.index(d["g"]) % 8], cx - bw / 2, min(y0, y1), bw, abs(y0 - y1)))
            info["marks"] += 1
    elif kind == "box":
        def q(a, p):
            a = sorted(a)
            k = (len(a) - 1) * p
            f = math.floor(k)
            c = min(f + 1, len(a) - 1)
            return a[f] + (a[c] - a[f]) * (k - f)
        bw = min(slot * 0.7 / nd, 60)
        info["box_definition"] = "box: Q1-Q3 (linear interpolation); line: median; whiskers: most extreme point within 1.5 IQR; every observation drawn"
        for i, c in enumerate(cats):
            for j, g in enumerate(groups):
                pts = [d for d in data if d["x"] == c and d["g"] == g]
                if not pts:
                    continue
                ys = [d["y"] for d in pts]
                q1, m, q3 = q(ys, .25), q(ys, .5), q(ys, .75)
                iqr = q3 - q1
                wl = min(v for v in ys if v >= q1 - 1.5 * iqr)
                wh = max(v for v in ys if v <= q3 + 1.5 * iqr)
                cx = left + slot * (i + .5) + (0 if same else (j - (len(groups) - 1) / 2) * bw)
                s.append('<g data-mark="box" data-panel="' + pid + '" data-x="' + escape(str(c)).replace("%", "%%") + '" data-group="' + escape(str(g) if gk else "").replace("%", "%%") + '" data-n="%d" data-median="%r" data-q1="%r" data-q3="%r"><path d="M%.2f %.3fV%.3fM%.2f %.3fV%.3f" stroke="%s" stroke-width="1.2"/><rect x="%.2f" y="%.3f" width="%.2f" height="%.3f" fill="%s" fill-opacity="0.45" stroke="%s" stroke-width="1.2"/><path d="M%.2f %.3fh%.2f" stroke="%s" stroke-width="2.2"/></g>' % (
                    len(pts), m, q1, q3, cx, yax.to(wh), yax.to(q3), cx, yax.to(q1), yax.to(wl), INK, cx - bw * .4,
                    yax.to(q3), bw * .8, yax.to(q1) - yax.to(q3), colors[g], INK, cx - bw * .4, yax.to(m), bw * .8, INK))
                for t, d in enumerate(sorted(pts, key=lambda d: d["row"])):
                    off = ((t * 0.618) % 1 - .5) * bw * .5
                    s.append(_mark(marks[g], cx + off, yax.to(d["y"]), 3, colors[g], 'data-mark="point" data-cy="%.4f" ' % yax.to(d["y"]) + attrs(d, "pt")))
                    info["marks"] += 1
    else:
        for j, g in enumerate(groups):
            pts = [d for d in data if d["g"] == g]
            for t, d in enumerate([d for d in raw if d["g"] == g] if panel.get("points", True) else []):
                cxr = (left + slot * (cats.index(d["x"]) + .5) + (0 if kind != "dot" or same else (j - (len(groups) - 1) / 2) * min(14, slot * .6 / max(1, len(groups)))) + ((t * .618) % 1 - .5) * 7) if cat else xax.to(num(d["x"]))
                s.append('<circle id="%s-raw-r%d" data-mark="rawpoint" data-src="%s#%d" data-y="%r" cx="%.3f" cy="%.4f" r="2.9" fill="#ffffff" fill-opacity="0.35" stroke="%s" stroke-width="1.1"/>' % (
                    pid, d["row"], escape(fname), d["row"], d["y"], cxr, yax.to(d["y"]), colors[g]))

            def xp(d):
                if cat:
                    off = 0 if kind != "dot" or same else (j - (len(groups) - 1) / 2) * min(14, slot * .6 / max(1, len(groups)))
                    return left + slot * (cats.index(d["x"]) + .5) + off
                return xax.to(num(d["x"]))
            if kind == "line":
                pts = sorted(pts, key=xp) if not panel.get("stat_by") else sorted(pts, key=lambda d: d.get("order", 0))
                if len({d["x"] for d in pts}) < len(pts) and not panel.get("allow_repeat_x") and not panel.get("stat_by"):
                    info.setdefault("warnings", []).append(
                        "series %s has repeated x values; line joins them in row order - set group/where or aggregate" % g)
                s.append('<path id="%s-line-%d" data-role="series" d="%s" fill="none" stroke="%s" stroke-width="2" stroke-dasharray="%s"/>' % (
                    pid, j, "M" + "L".join("%.3f %.3f" % (xp(d), yax.to(d["y"])) for d in pts), colors[g], DASH[j % 8]))
            r = 4.6 if len(data) < 80 else (3.4 if len(data) < 300 else 2.4)
            for d in pts:
                s.append(errbar(d, xp(d)))
                y = yax.to(d["y"])
                s.append(xerrbar(d, xp(d), y))
                s.append(_mark(marks[g], xp(d), y, r, colors[g], 'data-mark="point" data-cy="%.4f" data-cx="%.4f" ' % (y, xp(d)) + attrs(d, "pt")))
                info["marks"] += 1
    s.append("</g>")
    info["overlays"] = []
    for k, o in enumerate(panel.get("overlays") or []):
        lid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(o.get("layer") or "%s-overlay-%d" % (pid, k + 1)))
        col = o.get("color") or INK
        dsh = {"solid": "", "dashed": "8 5", "dotted": "2 4"}.get(o.get("dash", "solid"), "")
        ok = o.get("type") or o.get("chart") or "line"
        s.append('<g id="%s" data-role="overlay" data-layer="%s" data-kind="%s">' % (lid, lid, ok))
        cnt = 0
        if ok in ("hline", "vline"):
            v = num(o.get("value", o.get("y", o.get("x"))))
            if ok == "hline":
                s.append('<path id="%s-line" d="M%.2f %.3fH%.2f" stroke="%s" stroke-width="1.4" stroke-dasharray="%s" fill="none"/>' % (lid, left, yax.to(v), right, col, dsh))
                if o.get("label"):
                    s.append(halo(right - 4, yax.to(v) - fs * .6, str(o["label"]), fs * .82, "end", col))
            elif not cat:
                s.append('<path id="%s-line" d="M%.3f %.2fV%.2f" stroke="%s" stroke-width="1.4" stroke-dasharray="%s" fill="none"/>' % (lid, xax.to(v), top, bottom, col, dsh))
                if o.get("label"):
                    s.append(halo(xax.to(v) + 4, top + fs * .7, str(o["label"]), fs * .82, "start", col))
            cnt = 1
        elif ok == "abline" and not cat:
            a_, b_ = num(o["intercept"]), num(o["slope"])
            x0, x1 = (float(q) for q in (o.get("xrange") or [xax.lo, xax.hi]))
            x0, x1 = max(x0, xax.lo), min(x1, xax.hi)
            log_xy = o.get("space") in ("log10", "log")

            def yy(x):
                return 10 ** (a_ + b_ * math.log10(x)) if log_xy else a_ + b_ * x
            pts = []
            for t in range(61):
                x = 10 ** (math.log10(x0) + (math.log10(x1) - math.log10(x0)) * t / 60) if xlog else x0 + (x1 - x0) * t / 60
                y = yy(x)
                if (not ylog or y > 0) and yax.lo <= y <= yax.hi:
                    pts.append("%.2f %.3f" % (xax.to(x), yax.to(y)))
            if pts:
                s.append('<path id="%s-line" data-intercept="%r" data-slope="%r" data-space="%s" d="M%s" stroke="%s" stroke-width="1.8" stroke-dasharray="%s" fill="none"/>' % (lid, a_, b_, "log10" if log_xy else "linear", "L".join(pts), col, dsh))
                if o.get("label"):
                    qx, qy = (float(q) for q in pts[-1].split())
                    s.append(halo(qx - 4, max(top + 8, qy - fs * .7), str(o["label"]), fs * .82, "end", col))
            cnt = 1
        else:
            osel = select(rows, o.get("where")) if not o.get("data") else select(prepare(o, *read(o["data"]))[1], o.get("where"))
            ox, oy_ = o.get("x", xk), o.get("y", yk)
            pts = []
            for rk, r in osel:
                v, xv = num(r.get(oy_, "")), (r.get(ox, "") if cat else num(r.get(ox, "")))
                if v is None or xv is None or (cat and xv not in cats) or (ylog and v <= 0):
                    continue
                pts.append((left + slot * (cats.index(xv) + .5) if cat else xax.to(xv), yax.to(v), rk, v))
            if ok == "line":
                pts.sort()
                if pts:
                    s.append('<path id="%s-line" d="M%s" stroke="%s" stroke-width="1.8" stroke-dasharray="%s" fill="none"/>' % (lid, "L".join("%.3f %.3f" % q[:2] for q in pts), col, dsh))
            for qx, qy, rk, v in pts:
                if ok == "ring":
                    s.append('<circle id="%s-r%d" data-src="%s#%d" data-y="%r" cx="%.3f" cy="%.4f" r="8" fill="none" stroke="%s" stroke-width="1.8"/>' % (lid, rk, escape(o.get("data", fname)), rk, v, qx, qy, col))
                elif ok == "points":
                    s.append('<circle id="%s-r%d" data-src="%s#%d" data-y="%r" cx="%.3f" cy="%.4f" r="2.6" fill="%s" fill-opacity="0.5"/>' % (lid, rk, escape(o.get("data", fname)), rk, v, qx, qy, col))
                if o.get("label_col"):
                    s.append(svg_text(qx + 10, qy - 8, [str([r for k2, r in osel if k2 == rk][0].get(o["label_col"], ""))], fs * .78, "start", fill=col))
            if o.get("label") and pts and ok == "line":
                s.append(halo(pts[-1][0], max(top + 8, pts[-1][1] - fs * .8), str(o["label"]), fs * .82, "end", col))
            cnt = len(pts)
        s.append("</g>")
        info["overlays"].append({"layer": lid, "kind": ok, "marks": cnt, "label": o.get("label"), "src": o.get("src") or o.get("data")})
    s.append('<g id="%s-annotations" data-role="annotations">' % pid)
    if not cat:
        s.insert(1, '<g id="%s-xmap" data-x0="%.6g" data-x1="%.6g" data-xp0="%.4f" data-xp1="%.4f" data-xlog="%d"/>' % (
            pid, xax.lo, xax.hi, xax.p0, xax.p1, int(xlog)))
    for k, a in enumerate(panel.get("annotations", [])):
        if a.get("y") is not None and num(a["y"]) is not None:
            y = yax.to(num(a["y"]))
            s.append('<path id="%s-ref-%d" d="M%.2f %.2fH%.2f" stroke="#444" stroke-width="1.1" stroke-dasharray="5 4"/>' % (pid, k, left, y, right))
            s.append(svg_text(right - 4, y - fs * .6, [str(a.get("text", ""))], fs * .82, "end"))
    s.append("</g></g>")
    info["axes"] = {"y": [yax.lo, yax.hi, "log" if ylog else "linear"]}
    return "\n".join(x for x in s if x), info


def _hatch(kind, x, y, w, h):
    """Explicit hatch strokes (no <pattern>) so every renderer and editor shows them."""
    if not kind or w < 3 or h < 3:
        return ""
    d = []
    step = 6
    if kind in ("diag", "cross", "diag2"):
        t = step
        while t < w + h:
            if kind in ("diag", "cross"):
                x0, y0 = (x + t, y) if t <= w else (x + w, y + t - w)
                x1, y1 = (x, y + t) if t <= h else (x + t - h, y + h)
                d.append("M%.2f %.2fL%.2f %.2f" % (x0, y0, x1, y1))
            if kind in ("diag2", "cross"):
                x0, y0 = (x + w - t, y) if t <= w else (x, y + t - w)
                x1, y1 = (x + w, y + t) if t <= h else (x + w - t + h, y + h)
                d.append("M%.2f %.2fL%.2f %.2f" % (x0, y0, x1, y1))
            t += step
    elif kind == "horiz":
        t = step
        while t < h:
            d.append("M%.2f %.2fh%.2f" % (x, y + t, w))
            t += step
    elif kind == "vert":
        t = step
        while t < w:
            d.append("M%.2f %.2fv%.2f" % (x + t, y, h))
            t += step
    elif kind == "dots":
        t = step / 2
        while t < h:
            u = step / 2
            while u < w:
                d.append("M%.2f %.2fh1.4" % (x + u - .7, y + t))
                u += step
            t += step
    return '<path d="%s" stroke="#ffffff" stroke-opacity="0.85" stroke-width="1.1" fill="none"/>' % "".join(d) if d else ""


def heat_colour(v, lo, hi):
    div = lo < 0 < hi
    if div:
        m = max(-lo, hi)
        lo, hi = -m, m
    t = (v - lo) / (hi - lo) if hi > lo else .5
    stops = [(33, 102, 172), (247, 247, 247), (178, 24, 43)] if div else [(247, 251, 255), (107, 174, 214), (8, 48, 107)]
    a, b, u = (stops[0], stops[1], t * 2) if t < .5 else (stops[1], stops[2], t * 2 - 1)
    return tuple(int(round(a[k] + (b[k] - a[k]) * u)) for k in range(3))


def _heatmap(panel, X, Y, W, H, sel, fs, pid, info, s, labels):
    xk, yk, vk = panel["x"], panel["y"], panel.get("value") or panel.get("v")
    if not vk:
        raise ValueError("%s: heatmap needs x, y and value columns" % pid)
    xs, ys = _uniq([r[xk] for _, r in sel]), _uniq([r[yk] for _, r in sel])
    if panel.get("order"):
        xs = [c for c in panel["order"] if c in xs] + [c for c in xs if c not in panel["order"]]
    vals = [num(r[vk]) for _, r in sel]
    good = [v for v in vals if v is not None]
    lo, hi = min(good), max(good)
    div = lo < 0 < hi
    if div:
        m = max(-lo, hi)
        lo, hi = -m, m
    ll = max(width(labels.get(y, y), fs * .88) for y in ys)
    left, top = X + ll + 14, Y + 12
    bw, bottom = 82, Y + H - fs * 3.6
    cw, ch = (X + W - bw - left) / len(xs), (bottom - top) / len(ys)
    s.append('<g id="%s-data" data-role="data" data-lo="%r" data-hi="%r">' % (pid, lo, hi))

    def color(v):
        return heat_colour(v, min(good), max(good))
    for (k, r), v in zip(sel, vals):
        i, j = xs.index(r[xk]), ys.index(r[yk])
        x, y = left + i * cw, top + j * ch
        if v is None:
            info["missing_rows"].append(k)
            s.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="#ffffff" stroke="#999" stroke-dasharray="3 2"/>' % (x, y, cw, ch))
            s.append(svg_text(x + cw / 2, y + ch / 2, ["n/a"], fs * .75, fill="#666"))
            continue
        c = color(v)
        s.append('<rect id="%s-cell-r%d" data-mark="cell" data-src="%s#%d" data-x="%s" data-group="%s" data-y="%r" x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="rgb(%d,%d,%d)" stroke="#fff"/>' % (
            pid, k, escape(panel["data"]), k, escape(r[xk]), escape(r[yk]), v, x, y, cw, ch, *c))
        if cw > 34 and ch > 18:
            dark = .299 * c[0] + .587 * c[1] + .114 * c[2] < 140
            s.append(svg_text(x + cw / 2, y + ch / 2, [str(r[vk]).replace("-", "−")], min(fs * .85, ch * .5), fill="#fff" if dark else INK))
        info["marks"] += 1
    s.append("</g>")
    for j, y in enumerate(ys):
        s.append(svg_text(left - 7, top + (j + .5) * ch, [labels.get(y, y)], fs * .88, "end"))
    for i, x in enumerate(xs):
        s.append(svg_text(left + (i + .5) * cw, bottom + fs * .9, wrap(labels.get(x, x), fs * .85, cw)[:2], fs * .85))
    bx = X + W - bw + 16
    for k in range(40):
        v = hi - (hi - lo) * (k + .5) / 40
        c = color(v)
        s.append('<rect x="%.2f" y="%.2f" width="14" height="%.2f" fill="rgb(%d,%d,%d)"/>' % (bx, top + (bottom - top) * k / 40, (bottom - top) / 40 + .4, *c))
    for v in (hi, (hi + lo) / 2, lo):
        s.append(svg_text(bx + 19, top + (hi - v) / (hi - lo or 1) * (bottom - top), [fmt(v, (hi - lo) / 50 or None)], fs * .8, "start"))
    s.append(svg_text((left + X + W - bw) / 2, Y + H - fs * .8, [panel.get("xlabel", xk)], fs))
    s.append(svg_text(bx, Y + H - fs * .8, [panel.get("ylabel", vk)], fs * .85, "middle"))
    s.append("</g>")
    return "\n".join(x for x in s if x), info


def _forest(panel, X, Y, W, H, data, fs, pid, info, s, labels, colors, marks, xt, yt):
    cats = _uniq([d["x"] for d in data])
    ll = max(width(labels.get(str(c), str(c)), fs * .92) for c in cats)
    left, right, top, bottom = X + min(ll, W * .4) + 14, X + W - 18, Y + 8, Y + H - fs * 3
    vals = [v for d in data for v in (d["y"], d["lo"], d["hi"]) if v is not None]
    log = panel.get("xscale") == "log" or panel.get("yscale") == "log"
    lo, hi = min(vals), max(vals)
    ref = panel.get("ref")
    if ref is not None:
        lo, hi = min(lo, float(ref)), max(hi, float(ref))
    if log:
        lo, hi = lo / 1.15, hi * 1.15
    else:
        p = (hi - lo) * .06 or 1
        lo, hi = lo - p, hi + p
    ax = Axis(lo, hi, left, right, log)
    s.append('<g id="%s-xmap" data-x0="%.6g" data-x1="%.6g" data-xp0="%.4f" data-xp1="%.4f" data-xlog="%d" data-valueaxis="x"/>' % (pid, lo, hi, left, right, int(log)))
    tk, st = ax.ticks(6)
    for t in tk:
        s.append('<path d="M%.2f %.2fV%.2f" stroke="%s" stroke-width=".8"/>' % (ax.to(t), top, bottom, GRID))
        s.append(svg_text(ax.to(t), bottom + fs, [fmt(t, st)], fs * .88))
    if ref is not None:
        s.append('<path id="%s-ref" d="M%.2f %.2fV%.2f" stroke="#444" stroke-dasharray="5 4"/>' % (pid, ax.to(float(ref)), top, bottom))
    s.append('<path d="M%.2f %.2fH%.2f" stroke="%s" stroke-width="1.3"/>' % (left, bottom, right, INK))
    rh = (bottom - top) / len(cats)
    s.append('<g id="%s-data" data-role="data">' % pid)
    gl = list(colors)
    for i, c in enumerate(cats):
        y0 = top + (i + .5) * rh
        s.append(svg_text(left - 8, y0, wrap(labels.get(str(c), str(c)), fs * .92, left - X - 14), fs * .92, "end"))
        pts = [d for d in data if d["x"] == c]
        for j, d in enumerate(pts):
            y = y0 + (j - (len(pts) - 1) / 2) * min(14, rh * .7 / max(1, len(pts)))
            if d["lo"] is not None and d["hi"] is not None:
                s.append('<path id="%s-err-r%d" data-role="error" data-lo="%r" data-hi="%r" d="M%.3f %.3fH%.3f" stroke="%s" stroke-width="1.6"/>' % (
                    pid, d["row"], d["lo"], d["hi"], ax.to(d["lo"]), y, ax.to(d["hi"]), INK))
            x = ax.to(d["y"])
            s.append(_mark(marks[d["g"]], x, y, 5, colors[d["g"]], 'data-mark="hpoint" data-cx="%.4f" id="%s-pt-r%d" data-src="%s#%d" data-x="%s" data-y="%r" data-group="%s"' % (
                x, pid, d["row"], escape(panel["data"]), d["row"], escape(str(d["x"])), d["y"], escape(str(d["g"])))))
            info["marks"] += 1
    s.append("</g>")
    s.append(svg_text((left + right) / 2, Y + H - fs * .7, [yt], fs))
    s.append("</g>")
    return "\n".join(x for x in s if x), info


def centre(el):
    """Visible centre of a mark, taken from the drawn primitive (not from its data attributes)."""
    tag = el.tag.rsplit("}", 1)[-1]
    f = lambda k: float(el.get(k))
    if tag == "circle":
        return f("cx"), f("cy")
    if tag == "rect":
        return f("x") + f("width") / 2, f("y") + f("height") / 2
    if tag == "polygon":
        pts = [tuple(float(v) for v in q.split(",")) for q in el.get("points").split()]
        if len(pts) == 3:  # apex at y-1.2r, base half-width 1.1r
            r = abs(pts[1][0] - pts[0][0]) / 1.1
            return pts[0][0], pts[0][1] + 1.2 * r
        return sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts)
    v = [float(x) for x in re.findall(r"-?\d+\.?\d*", el.get("d") or "")]
    return (v[0] + v[2]) / 2, (v[1] + v[3]) / 2


# --- independent read-back -----------------------------------------------------
def read_back(svg_text_, read, specs):
    """Recover numbers from geometry only and compare with the source table cells."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(svg_text_.encode("utf-8"))
    rep = []
    for pid, sp in specs.items():
        cols, rows = prepare(sp, *read(sp["data"]))
        yk = sp.get("value") if sp.get("chart") == "heatmap" else sp.get("y")
        axes = xmap = None
        marks = []
        for el in root.iter():
            i = el.get("id", "")
            if i == pid + "-axes":
                axes = el
            elif i == pid + "-xmap":
                xmap = el
            elif el.get("data-mark") in ("bar", "point", "hpoint", "cell", "rawpoint", "stack") and i.startswith(pid + "-"):
                marks.append(el)
        worst, checked, bad = 0.0, 0, []
        cells_xy, fills, parts = {}, [], []
        ax = None
        if axes is not None:
            ax = Axis(float(axes.get("data-y0")), float(axes.get("data-y1")), float(axes.get("data-yp0")),
                      float(axes.get("data-yp1")), axes.get("data-ylog") == "1")
        hx = None
        if xmap is not None:
            hx = Axis(float(xmap.get("data-x0")), float(xmap.get("data-x1")), float(xmap.get("data-xp0")),
                      float(xmap.get("data-xp1")), xmap.get("data-xlog") == "1")
        for m in marks:
            row = int(m.get("data-src").rsplit("#", 1)[1])
            truth = num(rows[row - 1][yk])
            if m.get("data-stat"):
                truth = summary([num(rows[int(k) - 1][yk]) for k in m.get("data-rows").split(",")], m.get("data-stat"))[0]
            mk = m.get("data-mark")
            if mk == "cell":
                got = float(m.get("data-y"))
                rng = abs(truth) or 1
                cells_xy.setdefault(("x", m.get("data-x")), set()).add(round(float(m.get("x")), 1))
                cells_xy.setdefault(("y", m.get("data-group")), set()).add(round(float(m.get("y")), 1))
                fills.append((truth, m.get("fill")))
            elif mk == "hpoint":
                got, rng = hx.inv(centre(m)[0]), abs(hx.hi - hx.lo)
            elif mk == "stack":
                y, h = float(m.get("y")), float(m.get("height"))
                got, rng = abs(ax.inv(y) - ax.inv(y + h)), abs(ax.hi - ax.lo)
                truth = abs(truth)
            elif mk in ("point", "rawpoint"):
                got, rng = ax.inv(centre(m)[1]), abs(ax.hi - ax.lo)
            else:
                y, h = float(m.get("y")), float(m.get("height"))
                zero = ax.to(0) if (not ax.log and ax.lo <= 0 <= ax.hi) else ax.to(ax.lo)
                got = ax.inv(y) if abs(y + h - zero) <= abs(y - zero) else ax.inv(y + h)
                rng = abs(ax.hi - ax.lo)
            if mk in ("point", "rawpoint") and hx is not None and sp.get("chart") in ("scatter", "line"):
                tx = num(rows[row - 1].get(sp.get("x"), ""))
                if m.get("data-xstat"):
                    tx = summary([num(rows[int(k) - 1][sp["x"]]) for k in m.get("data-rows").split(",")], m.get("data-stat"))[0]
                gx = hx.inv(centre(m)[0])
                if tx is not None:
                    ex = abs(gx - tx) / (abs(tx) if hx.log and tx else abs(hx.hi - hx.lo))
                    worst = max(worst, ex)
                    if ex > 0.004:
                        bad.append({"row": row, "axis": "x", "table": tx, "read_back": round(gx, 6)})
            lg = (hx is not None and hx.log) if mk == "hpoint" else (ax is not None and ax.log)
            err = abs(got - truth) / (abs(truth) if lg and truth else rng)
            worst = max(worst, err)
            checked += 1
            if err > 0.004:
                bad.append({"row": row, "table": truth, "read_back": round(got, 6)})
        if fills:
            pos = {k: v for k, v in cells_xy.items()}
            if any(len(v) != 1 for v in pos.values()) or len({next(iter(v)) for k, v in pos.items() if k[0] == "x"}) != sum(k[0] == "x" for k in pos) or len({next(iter(v)) for k, v in pos.items() if k[0] == "y"}) != sum(k[0] == "y" for k in pos):
                bad.append({"row": None, "problem": "heatmap cells do not form the expected grid"})
            vals = [t for t, _ in fills]
            lo, hi = min(vals), max(vals)
            for t, f in fills:
                if f != "rgb(%d,%d,%d)" % heat_colour(t, lo, hi):
                    bad.append({"row": None, "problem": "cell colour does not match its value", "table": t})
            parts.append("cell grid and colours")
        boxes = [el for el in root.iter() if el.get("data-mark") == "box" and (el.get("data-panel") == pid)]
        if sp.get("chart") == "box":
            want = {}
            for k, r in select(rows, sp.get("where")):
                v = num(r.get(yk, ""))
                if v is not None:
                    want.setdefault((r.get(sp.get("x")), r.get(sp["group"]) if sp.get("group") else ""), []).append(v)
            if len(boxes) != len(want):
                bad.append({"row": None, "problem": "%d boxes drawn, %d groups in table" % (len(boxes), len(want))})
            for b in boxes:
                v = want.get((b.get("data-x"), b.get("data-group") or ""))
                rc = next((c for c in b if c.tag.endswith("rect")), None)
                if not v or rc is None:
                    bad.append({"row": None, "problem": "box without matching group"})
                    continue
                m_, q1, q3 = summary(v, "median_iqr")
                g3, g1 = ax.inv(float(rc.get("y"))), ax.inv(float(rc.get("y")) + float(rc.get("height")))
                if max(abs(g1 - q1), abs(g3 - q3)) > .006 * abs(ax.hi - ax.lo):
                    bad.append({"row": None, "problem": "box edges", "table": [q1, q3], "read_back": [g1, g3]})
            parts.append("box quartiles")
        for el in root.iter():
            if el.get("data-role") == "error" and el.get("id", "").startswith(pid + "-err-"):
                v = [float(x) for x in re.findall(r"-?\d+\.?\d*", el.get("d"))]
                if hx is not None and ax is None:
                    e0, e1, sp_ = hx.inv(v[0]), hx.inv(v[2]), abs(hx.hi - hx.lo)
                elif ax is not None:
                    e0, e1, sp_ = ax.inv(v[1]), ax.inv(v[2]), abs(ax.hi - ax.lo)
                else:
                    continue
                lo_, hi_ = float(el.get("data-lo")), float(el.get("data-hi"))
                cut = ax is not None and ax.log and lo_ < ax.lo
                if (not cut and abs(e0 - lo_) > .006 * max(sp_, abs(lo_) if sp_ == 0 else sp_)) or abs(e1 - hi_) > .006 * sp_:
                    bad.append({"row": el.get("id"), "problem": "error bar", "table": [lo_, hi_], "read_back": [e0, e1]})
                errs = True
                if "error bars" not in parts:
                    parts.append("error bars")
        sel = select(rows, sp.get("where"))
        expect = [k for k, r in sel if num(r.get(yk, "")) is not None]
        drawn = {int(m.get("data-src").rsplit("#", 1)[1]) for m in marks}
        drawn |= {int(k) for m in marks if m.get("data-rows") for k in m.get("data-rows").split(",")}
        miss = [k for k in expect if k not in drawn]
        rep.append({"panel": pid, "marks_checked": checked, "rows_expected_from_table": len(expect),
                    "rows_not_drawn": miss[:20], "also_verified": parts, "max_relative_error": float("%.2g" % worst), "mismatches": bad[:10],
                    "pass": not bad and not miss and checked > 0})
    return rep
