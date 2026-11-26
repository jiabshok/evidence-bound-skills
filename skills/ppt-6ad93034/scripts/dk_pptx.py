"""Template-true PPTX building blocks on top of python-pptx."""
import copy
import hashlib
import io
import os
import re
import subprocess
from functools import lru_cache

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData, XyChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE, PP_PLACEHOLDER
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

from kit_table import num

from pptx.opc.packuri import PackURI
from pptx.parts.presentation import PresentationPart


def _unique_slide_name(self):
    """python-pptx numbers new slides by count, which collides after deletions; pick a free part name."""
    used = {str(r.target_part.partname) for r in self.rels.values() if not r.is_external}
    n = 1
    while "/ppt/slides/slide%d.xml" % n in used:
        n += 1
    return PackURI("/ppt/slides/slide%d.xml" % n)


PresentationPart._next_slide_partname = property(_unique_slide_name)

EMU_PT = 12700
TITLE_T = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE, PP_PLACEHOLDER.VERTICAL_TITLE}
FOOT_T = {PP_PLACEHOLDER.DATE, PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.SLIDE_NUMBER}
BODY_T = {PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT, PP_PLACEHOLDER.VERTICAL_BODY, PP_PLACEHOLDER.VERTICAL_OBJECT}


# --- text metrics ------------------------------------------------------------
def is_cjk(ch):
    o = ord(ch)
    return 0x2E80 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF


@lru_cache(None)
def _font(family, bold):
    try:
        from PIL import ImageFont
        f = subprocess.run(["fc-match", "-f", "%{file}", (family or "sans") + (":bold" if bold else "")],
                           capture_output=True, text=True, timeout=10).stdout
        return ImageFont.truetype(f, 100) if f and os.path.exists(f) else None
    except Exception:
        return None


@lru_cache(20000)
def text_w(text, pt, bold=False, family="Arial"):
    latin = "".join(c for c in text if not is_cjk(c))
    cjk = len(text) - len(latin)
    f = _font(family, bold)
    w = f.getlength(latin) / 100.0 if f is not None else len(latin) * (0.56 if bold else 0.52)
    return (w + cjk) * pt


def wrap_count(text, pt, width_pt, bold=False, family="Arial"):
    n = 0
    for para in re.split(r"[\n\v]", text):
        toks = re.findall(r"\s+|[⺀-鿿＀-￯]|[^\s⺀-鿿＀-￯]+", para)
        cur, lines = 0.0, 1
        for t in toks:
            w = text_w(t, pt, bold, family)
            if cur and cur + w > width_pt and not t.isspace():
                lines += 1
                cur = 0.0
            while w > width_pt:
                lines += 1
                w -= width_pt
            cur += w
        n += lines
    return max(1, n)


# --- template inspection -------------------------------------------------------
def ph_type(sh):
    return sh.placeholder_format.type


def layout_info(layout):
    phs = []
    for sh in layout.placeholders:
        phs.append({"idx": sh.placeholder_format.idx, "type": ph_type(sh), "name": sh.name,
                    "box": (sh.left or 0, sh.top or 0, sh.width or 0, sh.height or 0)})
    t = [p for p in phs if p["type"] in TITLE_T]
    b = [p for p in phs if p["type"] in BODY_T]
    sub = [p for p in phs if p["type"] == PP_PLACEHOLDER.SUBTITLE]
    pic = [p for p in phs if p["type"] == PP_PLACEHOLDER.PICTURE]
    obj = [p for p in phs if p["type"] in (PP_PLACEHOLDER.TABLE, PP_PLACEHOLDER.CHART, PP_PLACEHOLDER.ORG_CHART, PP_PLACEHOLDER.MEDIA_CLIP)]
    return {"name": layout.name, "title": t, "body": b, "sub": sub, "pic": pic, "obj": obj,
            "foot": [p for p in phs if p["type"] in FOOT_T]}


def area(p):
    return p["box"][2] * p["box"][3]


def choose_layout(prs, kind, wanted=None):
    layouts = list(prs.slide_layouts)
    if wanted is not None:
        for l in layouts:
            if l.name.lower() == str(wanted).lower():
                return l
        if isinstance(wanted, int) and 0 <= wanted < len(layouts):
            return layouts[wanted]
    W, H = prs.slide_width, prs.slide_height
    best = None
    for k, l in enumerate(layouts):
        i = layout_info(l)
        n = l.name.lower()
        big = [b for b in i["body"] if area(b) > 0.10 * W * H]
        wide = [b for b in big if b["box"][2] > 0.55 * W]
        s = 0.0
        center = any(t["type"] == PP_PLACEHOLDER.CENTER_TITLE for t in i["title"])
        secname = any(x in n for x in ("section", "divider", "transition", "chapter", "节", "过渡", "分隔"))
        if kind == "title":
            s = 10 * bool(i["sub"]) + 8 * center + 3 * any(x in n for x in ("title slide", "cover", "封面", "标题幻灯片")) - 6 * bool(wide) - 4 * secname - len(i["pic"])
        elif kind == "section":
            s = 12 * secname + 3 * center - 5 * len(big) + (2 if i["title"] else -20)
        elif kind in ("two", "compare"):
            s = 12 * (len(big) == 2) + 4 * (len(i["body"]) in (2, 4)) - 8 * (len(big) < 2) + (2 if i["title"] else -20) - 4 * center - 5 * secname
            if kind == "compare":
                s += 4 * (len(i["body"]) == 4)
        elif kind == "titleonly":
            s = 10 * (bool(i["title"]) and not i["body"] and not i["sub"] and not i["pic"] and not i["obj"]) - 3 * len(i["body"]) - 4 * center - 5 * secname - 4 * len(i["pic"])
        elif kind == "picture":
            s = 10 * bool(i["pic"]) + 2 * bool(i["body"]) + (2 if i["title"] else -20)
        elif kind == "closing":
            s = 8 * any(x in n for x in ("closing", "thank", "end", "结束", "致谢")) + 3 * bool(wide) + (2 if i["title"] else -20) - 3 * len(i["pic"]) - 4 * secname
        else:
            s = 10 * (len(big) == 1 and bool(wide)) + 4 * any(x in n for x in ("title and content", "content", "内容")) - 4 * len(i["pic"]) - 5 * secname - 6 * center - 5 * (len(big) != 1) + (2 if i["title"] else -20)
            s -= 3 * any(x in n for x in ("two", "comparison", "vertical", "两栏", "caption"))
        s -= k * 0.01
        if best is None or s > best[0]:
            best = (s, l)
    return best[1]


def theme_fonts(prs):
    out = {"major": "Arial", "minor": "Arial"}
    try:
        part = prs.slide_master.part
        for rel in part.rels.values():
            if rel.reltype.endswith("/theme"):
                root = etree.fromstring(rel.target_part.blob)
                ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
                for k in ("major", "minor"):
                    e = root.find(".//a:%sFont/a:latin" % k, ns)
                    if e is not None and e.get("typeface"):
                        out[k] = e.get("typeface")
                out["colors"] = {}
                cs = root.find(".//a:clrScheme", ns)
                for c in cs:
                    v = c[0]
                    out["colors"][etree.QName(c).localname] = v.get("val") if etree.QName(v).localname == "srgbClr" else v.get("lastClr", "")
    except Exception:
        pass
    return out


def inherited_size(layout, idx, ptype, level=0, default=18.0):
    """Font size (pt) a placeholder paragraph would inherit: layout lstStyle -> master lstStyle -> master txStyles."""
    tag = "lvl%dpPr" % (level + 1)

    def look(el):
        if el is None:
            return None
        ls = el.find(".//" + qn("a:lstStyle"))
        if ls is not None:
            lv = ls.find(qn("a:" + tag))
            if lv is not None:
                d = lv.find(qn("a:defRPr"))
                if d is not None and d.get("sz"):
                    return int(d.get("sz")) / 100.0
        return None
    try:
        for sh in layout.placeholders:
            if sh.placeholder_format.idx == idx:
                v = look(sh._element)
                if v:
                    return v
        master = layout.slide_master
        want = "title" if ptype in TITLE_T else "body"
        for sh in master.placeholders:
            t = ph_type(sh)
            if (want == "title" and t in TITLE_T) or (want == "body" and t in BODY_T):
                v = look(sh._element)
                if v:
                    return v
        st = master._element.find(qn("p:txStyles"))
        if st is not None:
            e = st.find(qn("p:titleStyle" if want == "title" else "p:bodyStyle"))
            lv = e.find(qn("a:" + tag)) if e is not None else None
            d = lv.find(qn("a:defRPr")) if lv is not None else None
            if d is not None and d.get("sz"):
                return int(d.get("sz")) / 100.0
    except Exception:
        pass
    return default


def delete_slide(prs, index):
    lst = prs.slides._sldIdLst
    el = lst[index]
    prs.part.drop_rel(el.rId)
    lst.remove(el)


def move_slide(prs, old, new):
    lst = prs.slides._sldIdLst
    el = lst[old]
    lst.remove(el)
    lst.insert(new, el)


def add_footers(slide, layout, footer_text=None, date_text=None):
    """python-pptx does not instantiate footer placeholders; clone them from the layout."""
    have = {ph_type(s) for s in slide.placeholders}
    for sh in layout.placeholders:
        t = ph_type(sh)
        if t not in FOOT_T or t in have:
            continue
        if t == PP_PLACEHOLDER.DATE and not date_text:
            continue
        el = copy.deepcopy(sh._element)
        slide.shapes._spTree.append(el)
        ids = [int(x.get("id")) for x in slide.shapes._spTree.iter(qn("p:cNvPr"))]
        el.find(".//" + qn("p:cNvPr")).set("id", str(max(ids) + 1))
        sp = el.find(qn("p:spPr"))
        if sp is not None:
            for c in list(sp):
                sp.remove(c)
        if t == PP_PLACEHOLDER.FOOTER and footer_text:
            tx = el.find(qn("p:txBody"))
            for p in tx.findall(qn("a:p"))[1:]:
                tx.remove(p)
            p = tx.find(qn("a:p"))
            for c in list(p):
                if etree.QName(c).localname in ("r", "fld", "br"):
                    p.remove(c)
            r = etree.SubElement(p, qn("a:r"))
            rp = etree.SubElement(r, qn("a:rPr"))
            rp.set("lang", "en-US")
            etree.SubElement(rp, qn("a:latin")).set("typeface", "+mn-lt")
            etree.SubElement(r, qn("a:t")).text = footer_text
            end = p.find(qn("a:endParaRPr"))
            if end is not None:
                p.remove(end)
                p.append(end)


# --- text ------------------------------------------------------------------------
ITALIC = r"(?<![\w*])\*(?=[^\s*])[^*\n]{1,70}?(?<=[^\s*])\*(?![\w*])"
MARK = re.compile(r"(\*\*[^*]+\*\*|" + ITALIC + r"|_\{[^}]*\}|\^\{[^}]*\})")


UNIT_EXP = re.compile(r"(?:^|(?<=[\s(·/\[]))(m|cm|mm|km|L|mL|kg|g|mg|µg|μg|ng|s|min|h|hr|yr|ha|mol|mmol|kJ|kPa)([-−])([1-4])(?![\w.%-])")


def tidy_markup(t):
    """10^9, L^-1 and 'mg L-1' get proper superscripts."""
    t = re.sub(r"[_^]\{?([\u00b5\u03bc])\}?(?=[A-Za-z])", r"\1", str(t))
    t = re.sub(r"\^([-−+]?\d+)(?![}\d])", r"^{\1}", str(t))
    return UNIT_EXP.sub(lambda m: "%s^{\u2212%s}" % (m.group(1), m.group(3)), t)


def plain(t):
    t = tidy_markup(t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(ITALIC, lambda m: m.group(0)[1:-1], t)
    return re.sub(r"[_^]\{([^}]*)\}", r"\1", t)


def put_runs(p, text, size=None, color=None, bold=None):
    for part in MARK.split(tidy_markup(text)):
        if not part:
            continue
        r = p.add_run()
        if part.startswith("**"):
            r.text, r.font.bold = part[2:-2], True
        elif part.startswith("_{") or part.startswith("^{"):
            r.text = part[2:-1]
            r.font._element.set("baseline", "-25000" if part[0] == "_" else "30000")
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            r.text, r.font.italic = part[1:-1], True
        else:
            r.text = part
        if size:
            r.font.size = Pt(size)
        if bold is not None and not part.startswith("**"):
            r.font.bold = bold
        if color is not None:
            if isinstance(color, str):
                r.font.color.rgb = RGBColor.from_string(color.lstrip("#"))
            else:
                r.font.color.theme_color = color


def norm_items(items):
    out = []
    for it in items or []:
        if isinstance(it, str):
            it = {"text": it}
        elif not isinstance(it, dict):
            it = {"text": str(it)}
        out.append({"text": str(it.get("text", "")), "level": int(it.get("level", 0) or 0), "src": it.get("src"), "bold": it.get("bold"), "runs": it.get("runs")})
        for sub in it.get("sub", []) or []:
            s = sub if isinstance(sub, dict) else {"text": str(sub)}
            out.append({"text": str(s.get("text", "")), "level": 1, "src": s.get("src") or it.get("src"), "bold": None, "runs": None})
    return out


def box_text_height(items, sizes, width_pt, family, spacing=1.2, para_gap=0.28):
    h = 0.0
    for it in items:
        sz = sizes[min(it["level"], len(sizes) - 1)]
        ind = 18 + 16 * it["level"]
        n = wrap_count(plain(it["text"]), sz, max(30, width_pt - ind - 16), bool(it.get("bold")), family)
        h += n * sz * spacing + sz * para_gap
    return h


def fit_items(items, base, width_pt, height_pt, family, floor=14.0):
    """Return (sizes, fits). Sizes start from the inherited template values."""
    sizes = [max(floor, s) for s in base]
    while True:
        h = box_text_height(items, sizes, width_pt, family)
        if h <= height_pt - 8:
            return sizes, True
        if sizes[0] <= floor:
            return sizes, False
        sizes = [max(floor, s - 1) for s in sizes]


def fill_items(tf, items, sizes=None, inherited=None):
    tf.word_wrap = True
    ps = tf.paragraphs
    for k, it in enumerate(items):
        p = ps[0] if k == 0 else tf.add_paragraph()
        if k == 0:
            for r in list(p.runs):
                r._r.getparent().remove(r._r)
        p.level = min(it["level"], 4)
        sz = None
        if sizes:
            lv = min(it["level"], len(sizes) - 1)
            if inherited is None or abs(sizes[lv] - inherited[lv]) > 0.4:
                sz = sizes[lv]
        if it.get("runs"):
            put_source_runs(p, it["runs"], sz)
        else:
            put_runs(p, it["text"], sz, None, it.get("bold"))


def source_runs(p):
    """[(text, bold, italic, underline, baseline, url)] of a paragraph; None when there is nothing special to keep."""
    out = []
    for r in p.runs:
        url = None
        try:
            url = r.hyperlink.address
        except Exception:
            pass
        rp = r._r.find(qn("a:rPr"))
        out.append((r.text, r.font.bold, r.font.italic, r.font.underline, rp.get("baseline") if rp is not None else None, url))
    return out if any(x[1] or x[2] or x[3] or x[4] or x[5] for x in out) else None


def put_source_runs(p, rs, size=None):
    for t, b, i, u, base, url in rs:
        r = p.add_run()
        r.text = t
        if b:
            r.font.bold = True
        if i:
            r.font.italic = True
        if u and not url:
            r.font.underline = True
        if base:
            r._r.get_or_add_rPr().set("baseline", base)
        if size:
            r.font.size = Pt(size)
        if url:
            r.hyperlink.address = url


def fit_title(sh, text, layout, family, prs, floor=20.0, raw=False):
    base = inherited_size(layout, sh.placeholder_format.idx, ph_type(sh), 0, 32.0)
    w, h = sh.width / EMU_PT - 16, sh.height / EMU_PT
    size = base
    while size > floor and wrap_count(plain(text), size, w, False, family) * size * 1.15 > h - 2:
        size -= 1
    tf = sh.text_frame
    for p in tf.paragraphs[1:]:
        p._p.getparent().remove(p._p)
    p = tf.paragraphs[0]
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    put_runs(p, text, size if abs(size - base) > 0.4 else None)
    lines = wrap_count(plain(text), size, w, False, family)
    return {"size": size, "inherited": base, "fits": lines * size * 1.15 <= h + 4, "lines": lines}


def add_textbox(slide, box, items, size, align=None, color=None, bold=None, anchor=None, name=None):
    tb = slide.shapes.add_textbox(*[Emu(int(v)) for v in box])
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Emu(45720)
    tf.margin_top = tf.margin_bottom = Emu(22860)
    if anchor is not None:
        tf.vertical_anchor = anchor
    for k, it in enumerate(norm_items(items)):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        if align is not None:
            p.alignment = align
        if it.get("runs"):
            put_source_runs(p, it["runs"], size)
        else:
            put_runs(p, it["text"], size, color, it.get("bold") if it.get("bold") is not None else bold)
    return tb


# --- native objects -----------------------------------------------------------------
def add_table(slide, box, header, rows, family, highlight=None, name="Table", raw=False):
    nr, nc = len(rows) + (1 if header else 0), max([len(header or [])] + [len(r) for r in rows])
    x, y, w, h = [int(v) for v in box]
    wpt, hpt = w / EMU_PT, h / EMU_PT
    allr = ([header] if header else []) + rows
    plain_ = (lambda t: t) if raw else plain
    cells = [[plain_(str(r[c])) if c < len(r) else "" for c in range(nc)] for r in allr]
    size = 16.0
    while True:
        need = [max(max(text_w(tok, size, True, family) for tok in (cells[r][c].split() or [""])) for r in range(nr)) + 15 for c in range(nc)]
        full = [max(text_w(cells[r][c], size, r == 0, family) for r in range(nr)) + 16 for c in range(nc)]
        tot_full, tot_need = sum(full), sum(need)
        if tot_full <= wpt:
            widths = [f + (wpt - tot_full) / nc for f in full]
        else:
            extra = wpt - tot_need
            weight = [max(0.1, f - n) for f, n in zip(full, need)]
            widths = [n + extra * g / sum(weight) for n, g in zip(need, weight)]
        ok = tot_need <= wpt and min(widths) > 10
        hs = [max(wrap_count(cells[r][c], size, max(10, widths[c] - 15), r == 0, family) for c in range(nc)) * size * 1.2 + 8 for r in range(nr)]
        if ok and sum(hs) <= hpt:
            break
        if size <= 10.0:
            break
        size -= 0.5
    fits = ok and sum(hs) <= hpt
    total = sum(hs)
    gf = slide.shapes.add_table(nr, nc, Emu(x), Emu(y), Emu(w), Emu(int(min(total, hpt) * EMU_PT)))
    gf.name = name
    t = gf.table
    for c in range(nc):
        t.columns[c].width = Emu(int(max(8, widths[c]) / sum(widths) * w))
    for r in range(nr):
        t.rows[r].height = Emu(int(hs[r] * EMU_PT))
        for c in range(nc):
            cell = t.cell(r, c)
            cell.margin_left = cell.margin_right = Emu(64000)
            cell.margin_top = cell.margin_bottom = Emu(30000)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = cell.text_frame.paragraphs[0]
            val = str(allr[r][c]) if c < len(allr[r]) else ""
            (put_runs if not raw else lambda pp, v, sz, c_, b_: put_source_runs(pp, [(v, b_, None, None, None, None)], sz))(p, val, size, None, True if (r == 0 and header) or (highlight is not None and r - (1 if header else 0) in highlight) else None)
            if c > 0 and re.match(r"^[\s<>=~≈−+\-]*\d", plain(val)):
                p.alignment = PP_ALIGN.CENTER
    return gf, {"font_pt": size, "fits": fits, "rows": nr, "cols": nc}


CHARTS = {"bar": XL_CHART_TYPE.COLUMN_CLUSTERED, "column": XL_CHART_TYPE.COLUMN_CLUSTERED, "barh": XL_CHART_TYPE.BAR_CLUSTERED,
          "stacked": XL_CHART_TYPE.COLUMN_STACKED, "line": XL_CHART_TYPE.LINE_MARKERS, "scatter": XL_CHART_TYPE.XY_SCATTER, "pie": XL_CHART_TYPE.PIE}


def chart_series(spec, read):
    """Return (kind, categories, [(name, values, rows)], warnings) from a data file or inline series."""
    kind = spec.get("type", "bar")
    if spec.get("categories") and spec.get("series"):
        ser = spec["series"]
        if isinstance(ser, dict):
            ser = [{"name": k, "values": v} for k, v in ser.items()]
        return kind, [str(c) for c in spec["categories"]], [(str(s.get("name", "")), [num(v) for v in s["values"]], None) for s in ser], []
    cols, rows = read(spec["data"])
    for k in ("x", "y", "group"):
        if spec.get(k) and not isinstance(spec[k], list) and spec[k] not in cols:
            raise ValueError("chart column '%s' not in %s; columns: %s" % (spec[k], spec["data"], cols))
    sel = []
    for k, r in enumerate(rows, 1):
        if all(str(r.get(c, "")) in [str(v) for v in (vs if isinstance(vs, list) else [vs])] for c, vs in (spec.get("where") or {}).items()):
            sel.append((k, r))
    if not sel:
        raise ValueError("chart filter matches no rows of %s" % spec["data"])
    ys = spec["y"] if isinstance(spec["y"], list) else [spec["y"]]
    warn = []
    if kind == "scatter":
        groups = list(dict.fromkeys(r[spec["group"]] for _, r in sel)) if spec.get("group") else [""]
        out = []
        for g in groups:
            pts = [(num(r[spec["x"]]), num(r[ys[0]]), k) for k, r in sel if not spec.get("group") or r[spec["group"]] == g]
            out.append((g or ys[0], [(a, b) for a, b, _ in pts if a is not None and b is not None], [k for a, b, k in pts]))
        return kind, None, out, warn
    cats = list(dict.fromkeys(r[spec["x"]] for _, r in sel))
    out = []
    groups = list(dict.fromkeys(r[spec["group"]] for _, r in sel)) if spec.get("group") else [None]
    for g in groups:
        for y in ys:
            vals, rr = [], []
            for c in cats:
                hit = [(k, r) for k, r in sel if r[spec["x"]] == c and (g is None or r[spec["group"]] == g)]
                if len(hit) > 1:
                    warn.append("%d rows share category '%s' group '%s'; the first is plotted - filter or aggregate explicitly" % (len(hit), c, g))
                vals.append(num(hit[0][1][y]) if hit else None)
                rr.append(hit[0][0] if hit else None)
            out.append((str(g) if g is not None else y, vals, rr))
    return kind, cats, out, warn


def add_chart(slide, box, spec, read, fonts, name="Chart"):
    kind, cats, series, warn = chart_series(spec, read)
    if kind == "scatter":
        cd = XyChartData()
        for n, pts, _ in series:
            s = cd.add_series(n)
            for a, b in pts:
                s.add_data_point(a, b)
    else:
        cd = CategoryChartData()
        cd.categories = cats
        for n, v, _ in series:
            cd.add_series(n, v)
    gf = slide.shapes.add_chart(CHARTS.get(kind, XL_CHART_TYPE.COLUMN_CLUSTERED), *[Emu(int(v)) for v in box], cd)
    gf.name = name
    ch = gf.chart
    cfs = 14 if box[2] > 4.6 * 914400 and box[3] > 2.6 * 914400 else 12
    ch.font.size = Pt(cfs)
    ch.has_title = False
    ch.has_legend = len(series) > 1 or kind == "pie"
    if ch.has_legend:
        ch.legend.position = XL_LEGEND_POSITION.BOTTOM
        ch.legend.include_in_layout = False
        ch.legend.font.size = Pt(cfs)
    if kind != "pie":
        va, ca = ch.value_axis, ch.category_axis
        va.has_major_gridlines = True
        va.major_gridlines.format.line.color.rgb = RGBColor(0xDD, 0xDD, 0xDD)
        va.tick_labels.font.size = ca.tick_labels.font.size = Pt(cfs)
        for ax, lab in ((ca, spec.get("xlabel")), (va, spec.get("ylabel"))):
            if lab:
                ax.has_title = True
                ax.axis_title.text_frame.text = plain(lab)
                for p in ax.axis_title.text_frame.paragraphs:
                    for r in p.runs:
                        r.font.size, r.font.bold = Pt(cfs), False
        if kind in ("bar", "column", "barh", "stacked"):
            vals = [x for _, v, _ in series for x in v if x is not None]
            if vals and min(vals) >= 0:
                va.minimum_scale = 0
            elif vals:
                from pptx.enum.chart import XL_TICK_LABEL_POSITION
                ca.tick_label_position = XL_TICK_LABEL_POSITION.LOW
        if kind in ("bar", "column", "barh") and len(cats) * len(series) <= 10 and spec.get("value_labels", True):
            pl = ch.plots[0]
            pl.has_data_labels = True
            pl.data_labels.font.size = Pt(12)
            pl.data_labels.show_value = True
            fm = "General"
            pl.data_labels.number_format, pl.data_labels.number_format_is_linked = fm, False
            pl.gap_width = 70
        if kind in ("line", "scatter") and spec.get("yscale") == "log" or spec.get("yscale") == "log":
            sc = va._element.find(qn("c:scaling"))
            lb = etree.SubElement(sc, qn("c:logBase"))
            lb.set("val", "10")
            sc.remove(lb)
            sc.insert(0, lb)
    for k, s in enumerate(ch.plots[0].series):
        theme = [MSO_THEME_COLOR.ACCENT_1, MSO_THEME_COLOR.ACCENT_2, MSO_THEME_COLOR.ACCENT_3, MSO_THEME_COLOR.ACCENT_4, MSO_THEME_COLOR.ACCENT_5, MSO_THEME_COLOR.ACCENT_6][k % 6]
        try:
            if kind == "line":
                s.format.line.color.theme_color = theme
                s.format.line.width = Pt(2.25)
                s.smooth = False
            elif kind == "scatter":
                s.format.line.fill.background()
                s.marker.format.fill.solid()
                s.marker.format.fill.fore_color.theme_color = theme
            elif kind != "pie":
                s.format.fill.solid()
                s.format.fill.fore_color.theme_color = theme
        except Exception:
            pass
    return gf, {"kind": kind, "categories": cats, "series": [(n, v) for n, v, _ in series], "warnings": warn, "rows": [r for _, _, r in series]}


def copy_shape(slide, sh, box=None):
    """Copy an editable shape/group from another package, re-creating image and hyperlink relations."""
    el = copy.deepcopy(sh._element)
    src_part = sh.part
    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    for node in el.iter():
        for a in ("embed", "link", "id"):
            rid = node.get(R + a)
            if not rid or rid not in src_part.rels:
                continue
            rel = src_part.rels[rid]
            if rel.is_external:
                node.set(R + a, slide.part.relate_to(rel.target_ref, rel.reltype, is_external=True))
            elif "image" in rel.reltype:
                ip, new = slide.part.get_or_add_image_part(io.BytesIO(rel.target_part.blob))
                node.set(R + a, new)
            else:
                raise ValueError("cannot copy embedded part " + rel.reltype.rsplit("/", 1)[-1])
    tree = slide.shapes._spTree
    top = max([int(x.get("id")) for x in tree.iter(qn("p:cNvPr"))] + [1])
    for n in el.iter(qn("p:cNvPr")):
        top += 1
        n.set("id", str(top))
    tree.append(el)
    if box:
        new = slide.shapes[-1]
        x, y, w, h = box
        k = min(w / new.width, h / new.height, 1.0 if new.width < w and new.height < h else 99)
        nw, nh = int(new.width * k), int(new.height * k)
        new.left, new.top, new.width, new.height = Emu(int(x + (w - nw) / 2)), Emu(int(y + (h - nh) / 2)), Emu(nw), Emu(nh)
    return slide.shapes[-1]


def readable_chart(cs, least=1200):
    """Raise chart text below 12 pt (format only; data, categories and labels stay)."""
    for tag in ("a:defRPr", "a:rPr", "a:endParaRPr"):
        for r in cs.iter(qn(tag)):
            if r.get("sz") and int(r.get("sz")) < least:
                r.set("sz", str(least))
    if cs.find(qn("c:txPr")) is None:  # chart-wide default, inherited by axes and legend without their own size
        tx = etree.fromstring('<c:txPr xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="%d"/></a:pPr><a:endParaRPr lang="en-US"/></a:p></c:txPr>' % least)
        after = [cs.find(qn(t)) for t in ("c:spPr", "c:chart")]
        ref = next((x for x in after if x is not None), None)
        if ref is not None:
            ref.addnext(tx)


def copy_chart(slide, sh, box):
    """Clone a native chart (any type) with its embedded workbook into another presentation."""
    from pptx.opc.packuri import PackURI
    from pptx.parts.chart import ChartPart
    from pptx.parts.embeddedpackage import EmbeddedXlsxPart
    src = sh.chart.part
    pkg = slide.part.package
    part = ChartPart.load(pkg.next_partname("/ppt/charts/chart%d.xml"), src.content_type, pkg, src.blob)
    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    ext = part._element.find(qn("c:externalData"))
    if ext is not None:
        rid = ext.get(R + "id")
        if rid in src.rels and not src.rels[rid].is_external:
            x = EmbeddedXlsxPart.new(src.rels[rid].target_part.blob, pkg)
            ext.set(R + "id", part.relate_to(x, src.rels[rid].reltype))
        else:
            part._element.remove(ext)
    readable_chart(part._element)
    rid = slide.part.relate_to(part, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart")
    el = copy.deepcopy(sh._element)
    for c in el.iter(qn("c:chart")):
        c.set(R + "id", rid)
    tree = slide.shapes._spTree
    top = max([int(x.get("id")) for x in tree.iter(qn("p:cNvPr"))] + [1])
    el.find(".//" + qn("p:cNvPr")).set("id", str(top + 1))
    tree.append(el)
    new = slide.shapes[-1]
    new.left, new.top, new.width, new.height = [Emu(int(v)) for v in box]
    return new


def group_shapes(slide, shapes, box):
    """Wrap loose diagram shapes of a source slide in one group so their relative geometry survives scaling."""
    x0 = min(s.left for s in shapes)
    y0 = min(s.top for s in shapes)
    x1 = max(s.left + s.width for s in shapes)
    y1 = max(s.top + s.height for s in shapes)
    g = slide.shapes.add_group_shape()
    ids = {}
    tree = slide.shapes._spTree
    for s in shapes:
        before = s.shape_id
        new = copy_shape(slide, s)
        ids[before] = new.shape_id
        el = new._element
        tree.remove(el)
        g._element.append(el)
    for el in g._element.iter():
        if el.tag in (qn("a:stCxn"), qn("a:endCxn")) and int(el.get("id")) in ids:
            el.set("id", str(ids[int(el.get("id"))]))
    xf = g._element.grpSpPr.get_or_add_xfrm() if hasattr(g._element.grpSpPr, "get_or_add_xfrm") else None
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    bx, by, bw, bh = box
    k = min(bw / w, bh / h, 1.0)
    gx = g._element.find(qn("p:grpSpPr"))
    for c in list(gx):
        if etree.QName(c).localname == "xfrm":
            gx.remove(c)
    xfrm = etree.SubElement(gx, qn("a:xfrm"))
    gx.remove(xfrm)
    gx.insert(0, xfrm)
    for tag, a, b, c, d in (("a:off", "x", "y", int(bx + (bw - w * k) / 2), int(by + (bh - h * k) / 2)), ("a:ext", "cx", "cy", int(w * k), int(h * k)), ("a:chOff", "x", "y", int(x0), int(y0)), ("a:chExt", "cx", "cy", int(w), int(h))):
        e = etree.SubElement(xfrm, qn(tag))
        e.set(a, str(c))
        e.set(b, str(d))
    g.name = "Diagram (from source slide)"
    return g


def fit_picture(slide, path_or_blob, box, name="Picture", alt=""):
    from PIL import Image
    src = io.BytesIO(path_or_blob) if isinstance(path_or_blob, (bytes, bytearray)) else path_or_blob
    im = Image.open(src)
    iw, ih = im.size
    if not isinstance(src, str):
        src.seek(0)
    x, y, w, h = [int(v) for v in box]
    k = min(w / iw, h / ih)
    pw, phh = int(iw * k), int(ih * k)
    pic = slide.shapes.add_picture(src, Emu(x + (w - pw) // 2), Emu(y + (h - phh) // 2), Emu(pw), Emu(phh))
    pic.name = name
    if alt:
        pic._element.find(".//" + qn("p:cNvPr")).set("descr", alt[:400])
    return pic, {"pixels": [iw, ih], "effective_dpi": round(iw / (pw / 914400.0))}


def add_flow(slide, box, steps, family, vertical=None):
    """Editable process diagram: rounded boxes joined by glued connectors."""
    x, y, w, h = [int(v) for v in box]
    st = norm_items(steps)
    n = len(st)
    if vertical is None:
        vertical = w / max(1, n) < 1500000 or h > w
    gap = 320000
    shapes, info = [], {"fits": True}
    size = 16.0
    if vertical:
        bh = (h - gap * 0.75 * (n - 1)) / n
        boxes = [(x, y + k * (bh + gap * 0.75), w, bh) for k in range(n)]
    else:
        bw = (w - gap * (n - 1)) / n
        bh = min(h, 1750000)
        boxes = [(x + k * (bw + gap), y + (h - bh) / 2, bw, bh) for k in range(n)]
    while size > 12 and any(wrap_count(plain(s["text"]), size, b[2] / EMU_PT - 18, False, family) * size * 1.2 + 10 > b[3] / EMU_PT for s, b in zip(st, boxes)):
        size -= 0.5
    info["fits"] = not any(wrap_count(plain(s["text"]), size, b[2] / EMU_PT - 18, False, family) * size * 1.2 + 6 > b[3] / EMU_PT for s, b in zip(st, boxes))
    info["font_pt"] = size
    for k, (s, b) in enumerate(zip(st, boxes)):
        sp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, *[Emu(int(v)) for v in b])
        sp.adjustments[0] = 0.12
        sp.name = "Step %d" % (k + 1)
        sp.fill.solid()
        sp.fill.fore_color.theme_color = MSO_THEME_COLOR.ACCENT_1
        sp.fill.fore_color.brightness = 0.82
        sp.line.color.theme_color = MSO_THEME_COLOR.ACCENT_1
        sp.line.width = Pt(1.25)
        sp.shadow.inherit = False
        tf = sp.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = Emu(80000)
        tf.margin_top = tf.margin_bottom = Emu(30000)
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        put_runs(p, s["text"], size, MSO_THEME_COLOR.TEXT_1)
        shapes.append(sp)
    for a, b in zip(shapes, shapes[1:]):
        c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, 0, 0, 0, 0)
        c.begin_connect(a, 2 if vertical else 3)
        c.end_connect(b, 0 if vertical else 1)
        c.line.width = Pt(2)
        c.line.color.theme_color = MSO_THEME_COLOR.ACCENT_1
        ln = c.line._get_or_add_ln()
        etree.SubElement(ln, qn("a:tailEnd")).set("type", "triangle")
        c.name = "Flow connector"
    return info


def add_stats(slide, box, stats, family):
    """Row of big-number callouts; each is a live text box."""
    x, y, w, h = [int(v) for v in box]
    n = max(1, len(stats))
    gap = 200000
    vertical = w / n < 1700000
    info = {"fits": True}
    for k, s in enumerate(stats):
        if vertical:
            bh = (h - gap * (n - 1)) / n
            b = (x, y + k * (bh + gap), w, bh)
        else:
            bw = (w - gap * (n - 1)) / n
            bh = min(h, 1750000)
            b = (x + k * (bw + gap), y, bw, bh)
        sp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, *[Emu(int(v)) for v in b])
        sp.name = "Key number %d" % (k + 1)
        sp.fill.solid()
        sp.fill.fore_color.theme_color = MSO_THEME_COLOR.ACCENT_1
        sp.fill.fore_color.brightness = 0.88
        sp.line.fill.background()
        sp.shadow.inherit = False
        tf = sp.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.margin_left = tf.margin_right = Emu(90000)
        tf.margin_top = tf.margin_bottom = Emu(20000)
        wpt, hpt = b[2] / EMU_PT - 16, b[3] / EMU_PT - 6
        big, small = 30.0, 14.0
        val, lab = str(s.get("value", "")), str(s.get("label", s.get("text", "")))

        def need():
            return wrap_count(plain(val), big, wpt, True, family) * big * 1.15 + wrap_count(plain(lab), small, wpt, False, family) * small * 1.2
        while need() > hpt and big > 18:
            big -= 1
        while need() > hpt and small > 12:
            small -= .5
        info["fits"] = info["fits"] and need() <= hpt
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        put_runs(p, val, big, MSO_THEME_COLOR.ACCENT_1, True)
        q = tf.add_paragraph()
        q.alignment = PP_ALIGN.CENTER
        put_runs(q, lab, small, MSO_THEME_COLOR.TEXT_1)
    return info


def part_hash(part):
    return hashlib.sha256(part.blob).hexdigest()


def master_hashes(prs):
    out = {}
    for m in prs.slide_masters:
        out["master:" + m.name if m.name else "master"] = hashlib.sha256(etree.tostring(m._element, method="c14n")).hexdigest()
        for l in m.slide_layouts:
            out["layout:" + l.name] = hashlib.sha256(etree.tostring(l._element, method="c14n")).hexdigest()
        for rel in m.part.rels.values():
            if rel.reltype.endswith("/theme"):
                out["theme"] = hashlib.sha256(rel.target_part.blob).hexdigest()
    return out


def shape_texts(sh):
    """[(where, text)] for text frames, tables, groups and charts."""
    out = []
    if sh.shape_type == 6:  # group
        for s in sh.shapes:
            out += shape_texts(s)
        return out
    if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
        for k, p in enumerate(sh.text_frame.paragraphs):
            t = "".join(r.text for r in p.runs)
            if t.strip():
                out.append(("p%d" % k, t))
    if getattr(sh, "has_table", False) and sh.has_table:
        for r, row in enumerate(sh.table.rows):
            for c, cell in enumerate(row.cells):
                if cell.text.strip():
                    out.append(("r%dc%d" % (r, c), cell.text))
    return out


def chart_values(sh):
    ch = sh.chart
    out = {"type": str(ch.chart_type), "categories": [], "series": []}
    try:
        out["categories"] = [str(c) for c in ch.plots[0].categories]
    except Exception:
        pass
    for s in ch.plots[0].series:
        try:
            out["series"].append([s.name, list(s.values)])
        except Exception:
            pass
        try:
            xv = [float(v.text) for v in s._element.iter(qn("c:v")) if v.getparent().getparent().getparent().getparent().tag == qn("c:xVal")]
            if xv:
                out.setdefault("xy", []).append(xv)
        except Exception:
            pass
    return out


def deep_hash(slide):
    """Slide XML plus the bytes of everything it uses: notes text, charts, embedded workbooks, media."""
    h = hashlib.sha256(etree.tostring(slide._element, method="c14n"))
    h.update(notes_text(slide).encode())
    blobs = []
    for rel in slide.part.rels.values():
        if rel.is_external:
            blobs.append(rel.target_ref)
        elif any(k in rel.reltype for k in ("/image", "/chart", "/media", "/video", "/package", "/oleObject")):
            blobs.append(hashlib.sha256(rel.target_part.blob).hexdigest())
            for r2 in rel.target_part.rels.values():
                if not r2.is_external and "/package" in r2.reltype:
                    blobs.append(hashlib.sha256(r2.target_part.blob).hexdigest())
    for b in sorted(blobs):
        h.update(b.encode())
    return h.hexdigest()


def links(slide):
    out = []
    for sh in slide.shapes:
        for a in sh._element.iter(qn("a:hlinkClick")):
            rid = a.get(qn("r:id"))
            if rid and rid in slide.part.rels and slide.part.rels[rid].is_external:
                out.append(slide.part.rels[rid].target_ref)
    return sorted(out)


def is_hidden(slide):
    return slide._element.get("show") == "0"


def count_groups(slide):
    return sum(1 for s in slide.shapes if s.shape_type == 6)


def slide_hash(slide):
    return hashlib.sha256(etree.tostring(slide._element, method="c14n")).hexdigest()


def notes_text(slide):
    if not slide.has_notes_slide:
        return ""
    tf = slide.notes_slide.notes_text_frame
    return tf.text if tf is not None else ""


def set_notes(slide, text):
    tf = slide.notes_slide.notes_text_frame
    if tf is not None:
        tf.text = text
