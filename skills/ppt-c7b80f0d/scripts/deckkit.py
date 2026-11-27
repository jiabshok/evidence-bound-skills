#!/usr/bin/env python3
"""deckkit - evidence-bound academic slides in a supplied PowerPoint template.

  deckkit.py brief                      read case, template and starting deck; index sources; save a first honest result.json
  deckkit.py show P001-P010 | find WORD | table FILE [a-b]
  deckkit.py build                      deck.json -> presentation.pptx + PDF + previews + evidence map + result.json
  deckkit.py adapt                      move every slide of the starting deck into the target template (text, tables, charts, pictures, notes)
  deckkit.py edit                       edits.json applied to the starting deck (or a previous output); untouched slides stay identical
  deckkit.py slide N                    list shapes, text and ids of slide N of the current output (or starting deck)
  deckkit.py review [a-b]               every claim next to the sentence it cites, notes, and the requirement list
  deckkit.py check                      re-run all checks on the current presentation.pptx and refresh result.json
  deckkit.py verify                     confirm delivered files match result.json
  deckkit.py selftest                   run the bundled synthetic example in a temporary folder
"""
import argparse
import copy
import csv
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import kit_sources as ks  # noqa: E402
from kit_sources import INPUT, WORK, OUT, jload, jsave, say, rel, walk_inputs, read_table, table_path, resolve_src, best_quote, write_result, check, trace_numbers, contract, case_id  # noqa: E402

VERSION = "1.24.0"
PPTX = os.path.join(OUT, "presentation.pptx")


def need_pptx():
    try:
        import dk_pptx
        return dk_pptx
    except ImportError as exc:
        sys.exit("python-pptx/lxml unavailable (%s). Try: python3 -m pip install python-pptx lxml pillow" % exc)


def sha(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def inv(p):
    return {"path": p, "bytes": os.path.getsize(p), "sha256": sha(p)} if os.path.exists(p) else None


def find_file(words, ext=".pptx"):
    c = [p for p in walk_inputs() if p.lower().endswith(ext)]
    for w in words:
        for p in c:
            if w in os.path.basename(p).lower():
                return p
    return None


def template_file():
    return find_file(["target-template", "target_template", "template"]) or None


def starting_file():
    p = find_file(["starting", "start-deck", "source-deck", "original", "existing"])
    return p


def workorder():
    for p in ks.workorders():
        try:
            return jload(p)
        except Exception:
            pass
    return {}


def wo_find(keys, obj=None, depth=0):
    """First value in the work order whose key matches one of `keys` (normalised)."""
    obj = workorder() if obj is None else obj
    if depth > 6:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if re.sub(r"[^a-z]", "", str(k).lower()) in keys:
                return v
        for v in obj.values():
            r = wo_find(keys, v, depth + 1)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = wo_find(keys, v, depth + 1)
            if r is not None:
                return r
    return None


def requested_slides():
    v = wo_find({"slidecount", "totalslides", "totalslidecount", "slides", "numslides", "slidetotal", "exactslidecount", "numberofslides", "requestedslidecount", "finalslidecount", "pagecount", "exacttotalslides"})
    if isinstance(v, dict):
        for k in ("exact", "total", "target", "count", "max"):
            if isinstance(v.get(k), int):
                return v[k]
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str) and re.match(r"^\d+$", v.strip()):
        return int(v)
    return None


def requested_minutes():
    v = wo_find({"minutes", "durationminutes", "timeminutes", "talkminutes", "duration", "timelimitminutes", "timemin", "speakingminutes", "totalminutes", "presentationminutes", "time"})
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"\d+(?:\.\d+)?", v)
        return float(m.group(0)) if m else None
    return None


# --- brief ----------------------------------------------------------------------
def deck_digest(path, cap=5200):
    dk = need_pptx()
    prs = dk.Presentation(path)
    out, used = [], 0
    for n, s in enumerate(prs.slides, 1):
        lines = ["-- slide %d [layout %s]%s" % (n, s.slide_layout.name, " notes:%d chars" % len(dk.notes_text(s)) if s.has_notes_slide else "")]
        for sh in s.shapes:
            kind = "ph%d" % sh.placeholder_format.idx if sh.is_placeholder else str(sh.shape_type).split(".")[-1].split(" ")[0].lower()
            txt = " / ".join(t for _, t in dk.shape_texts(sh))
            extra = ""
            if getattr(sh, "has_chart", False) and sh.has_chart:
                v = dk.chart_values(sh)
                extra = " CHART %s" % json.dumps(v, ensure_ascii=False)[:220]
            if getattr(sh, "has_table", False) and sh.has_table:
                extra = " TABLE %dx%d" % (len(sh.table.rows), len(sh.table.columns))
            lines.append("   #%d %s '%s'%s: %s" % (sh.shape_id, kind, sh.name[:22], extra, txt[:230]))
        t = "\n".join(lines)
        used += len(t)
        if used > cap:
            out.append("... slides %d-%d: use `slide N`" % (n, len(prs.slides)))
            break
        out.append(t)
    return "\n".join(out)


def cmd_brief(a):
    ks.cmd_brief(a)
    dk = need_pptx()
    t = template_file()
    if t:
        prs = dk.Presentation(t)
        th = dk.theme_fonts(prs)
        say("\n# TEMPLATE %s: %.2f x %.2f in, %d sample slide(s) (removed automatically), fonts %s/%s" % (
            rel(t), prs.slide_width / 914400, prs.slide_height / 914400, len(prs.slides), th["major"], th["minor"]))
        for k in ("title", "content", "two", "section", "picture", "titleonly"):
            say("   kind %-9s -> layout '%s'" % (k, dk.choose_layout(prs, k).name))
        say("   all layouts: " + "; ".join(l.name for l in prs.slide_layouts))
    s = starting_file()
    if s:
        say("\n# STARTING DECK", rel(s), "(slides, shape ids, text)")
        say(deck_digest(s))
    say("\nRequested slide count: %s | minutes: %s | mode: %s" % (requested_slides(), requested_minutes(), wo_find({"mode", "requestedmode", "taskmode"})))


def cmd_slide(a):
    dk = need_pptx()
    p = PPTX if os.path.exists(PPTX) and not a.start else (starting_file() or template_file())
    prs = dk.Presentation(p)
    s = prs.slides[a.n - 1]
    say("file", p, "slide", a.n, "layout", s.slide_layout.name)
    for sh in s.shapes:
        say(" #%d '%s' %s pos=(%.2f,%.2f) size=(%.2f,%.2f) in" % (sh.shape_id, sh.name, "placeholder idx %d" % sh.placeholder_format.idx if sh.is_placeholder else str(sh.shape_type),
            (sh.left or 0) / 914400, (sh.top or 0) / 914400, (sh.width or 0) / 914400, (sh.height or 0) / 914400))
        for w, t in dk.shape_texts(sh):
            say("     %s: %s" % (w, t))
        if getattr(sh, "has_chart", False) and sh.has_chart:
            say("     chart:", json.dumps(dk.chart_values(sh), ensure_ascii=False)[:900])
    say(" notes:", dk.notes_text(s))


# --- build ------------------------------------------------------------------------
KIND_ALIAS = {"cover": "title", "divider": "section", "agenda": "content", "bullets": "content", "text": "content", "figure": "content", "image": "content",
              "table": "content", "chart": "content", "flow": "content", "stats": "content", "two_column": "two", "two-column": "two", "comparison": "compare",
              "backup": "content", "qa": "content", "q&a": "content", "appendix": "content", "closing": "content", "conclusion": "content", "limitations": "content",
              "references": "content", "method": "content", "results": "content", "summary": "content"}


def src_label(src):
    """Short on-slide citation from a slide's source list."""
    recs = resolve_src(src, [], "")
    labs = []
    for r in recs:
        lab = r.get("label") or ""
        if not lab:
            lab = os.path.basename(r["file"]) + ("" if r["locator"] in ("whole table", "whole file") else " " + r["locator"])
        lab = re.sub(r"~\d+$", "", lab)
        lab = lab.split(" > ")[-1].strip()
        if len(lab) > 46:
            lab = lab[:46].rsplit(" ", 1)[0] + "..."
        if lab and lab not in labs:
            labs.append(lab)
    tot, keep = 0, []
    for x in labs:
        if keep and tot + len(x) > 118:
            break
        keep.append(x)
        tot += len(x) + 2
    return "; ".join(keep) + ("; +%d in source map" % (len(labs) - len(keep)) if len(labs) > len(keep) else "")


def validate_deck(d):
    err, warn = [], []
    if not isinstance(d, dict) or not isinstance(d.get("slides"), list) or not d["slides"]:
        return ["deck.json needs a non-empty 'slides' list"], warn
    for n, s in enumerate(d["slides"], 1):
        if not isinstance(s, dict):
            err.append("slide %d is not an object" % n)
            continue
        s["kind"] = str(s.get("kind") or ("title" if n == 1 else "content")).lower()
        s["role"] = s.get("role") or s["kind"]
        s["kind"] = KIND_ALIAS.get(s["kind"], s["kind"])
        if s["kind"] not in ("title", "section", "content", "two", "compare", "picture", "titleonly"):
            warn.append("slide %d: kind '%s' unknown, using content" % (n, s["kind"]))
            s["kind"] = "content"
        if not s.get("title"):
            err.append("slide %d has no title" % n)
        for key in ("chart", "table", "image", "flow", "stats"):
            if key in s and not s[key]:
                s.pop(key)
        if isinstance(s.get("flow"), dict):
            s["flow"] = s["flow"].get("steps") or s["flow"].get("items") or []
        if isinstance(s.get("image"), str):
            s["image"] = {"path": s["image"]}
        if s.get("table") and isinstance(s["table"], list):
            s["table"] = {"header": s["table"][0], "rows": s["table"][1:]}
        if s.get("image"):
            try:
                s["image"]["path"] = table_path(s["image"]["path"])
            except ValueError:
                err.append("slide %d: image not found: %s" % (n, s["image"].get("path")))
    for n, s in enumerate(d["slides"], 1):
        if not isinstance(s, dict):
            continue
        for k in ("title", "takeaway", "cite", "subtitle"):
            if isinstance(s.get(k), str):
                s[k] = ks.public_refs(s[k])
        for k in ("bullets", "flow", "stats"):
            v = s.get(k)
            if isinstance(v, list):
                s[k] = [ks.public_refs(x) if isinstance(x, str) else {**x, **{q: ks.public_refs(x[q]) for q in ("text", "label") if isinstance(x.get(q), str)}} if isinstance(x, dict) else x for x in v]
        for k in ("table", "chart", "image"):
            if isinstance(s.get(k), dict):
                for q in ("caption", "note"):
                    if isinstance(s[k].get(q), str):
                        s[k][q] = ks.public_refs(s[k][q])
        for t in [s.get("title"), s.get("takeaway")] + [x if isinstance(x, str) else x.get("text", "") for x in (s.get("bullets") or [])]:
            for m in ks.lint_text(str(t or "")):
                warn.append("WORDING slide %d: %s" % (n, m))
    q = requested_slides()
    if q and q != len(d["slides"]):
        warn.append("work order asks for %d slides; spec has %d" % (q, len(d["slides"])))
    return err, warn


def visual_of(s):
    for k in ("chart", "table", "image", "flow", "stats"):
        if s.get(k):
            return k
    return None


def render_slide(prs, s, n, deck, dk, fonts, log):
    vis = visual_of(s)
    bul = dk.norm_items(s.get("bullets"))
    kind = s["kind"]
    if kind in ("content",) and vis and not bul:
        want = "titleonly"
    elif kind == "content" and vis and bul:
        want = "two" if vis != "stats" else "content"
    else:
        want = kind
    if kind in ("two", "compare") and not s.get("left") and not s.get("right"):
        want = "two" if vis and bul else "content"
    layout = dk.choose_layout(prs, want, s.get("layout"))
    slide = prs.slides.add_slide(layout)
    bad_layout = s.get("layout") is not None and layout.name.lower() != str(s["layout"]).lower() and not isinstance(s.get("layout"), int)
    W, H = prs.slide_width, prs.slide_height
    info = {"n": n, "layout": layout.name, "problems": [], "font_changes": []}
    if bad_layout:
        info["problems"].append("layout '%s' does not exist; used '%s'. Available: %s" % (s["layout"], layout.name, "; ".join(l.name for l in prs.slide_layouts)))
    fam_t, fam_b = fonts["major"], fonts["minor"]
    title = sub = None
    bodies, nontext = [], []
    for sh in list(slide.placeholders):
        t = dk.ph_type(sh)
        if t in dk.TITLE_T and title is None:
            title = sh
        elif t == dk.PP_PLACEHOLDER.SUBTITLE:
            sub = sh
        elif t in dk.FOOT_T:
            pass
        elif t in (dk.PP_PLACEHOLDER.PICTURE, dk.PP_PLACEHOLDER.CHART, dk.PP_PLACEHOLDER.TABLE, dk.PP_PLACEHOLDER.MEDIA_CLIP, dk.PP_PLACEHOLDER.ORG_CHART, dk.PP_PLACEHOLDER.BITMAP):
            # a picture/chart/table placeholder cannot show text (bullets put there do not render); it only shapes the region, visuals are own shapes
            nontext.append(sh)
        else:
            bodies.append(sh)
    bodies.sort(key=lambda b: (-(b.width or 0) * (b.height or 0)))
    if title is not None:
        r = dk.fit_title(title, s["title"], layout, fam_t, prs, raw=bool(s.get("raw")))
        if abs(r["size"] - r["inherited"]) > .4:
            info["font_changes"].append("title %.0f->%.0f pt" % (r["inherited"], r["size"]))
        if not r["fits"]:
            info["problems"].append("title too long (%d lines at %.0f pt); shorten it" % (r["lines"], r["size"]))
    else:
        dk.add_textbox(slide, (W * .05, H * .04, W * .9, H * .12), [s["title"]], 28, bold=True, name="Title text")
        info["problems"].append("layout has no title placeholder")
    footer = deck.get("footer")
    if not (s.get("kind") == "title" and cover_exempt()):
        dk.add_footers(slide, layout, footer, deck.get("date"))
    foots = [sh for sh in slide.placeholders if dk.ph_type(sh) in dk.FOOT_T]
    foot_top = min([sh.top for sh in foots if sh.top] or [int(H * .94)])
    for sh in layout.placeholders:
        if dk.ph_type(sh) in dk.FOOT_T and sh.top:
            foot_top = min(foot_top, sh.top)
    if foot_top < H * .8:
        foot_top = int(H * .93)

    def put_body(sh, items, floor=14.0):
        base = [dk.inherited_size(layout, sh.placeholder_format.idx, dk.ph_type(sh), lv, 20 - 2 * lv) for lv in range(3)]
        base0 = list(base)
        if vis and base[0] > 22:
            base = [min(b, 22 - 2 * k) for k, b in enumerate(base)]
        sizes, ok = dk.fit_items(items, base, sh.width / 12700 - 14, sh.height / 12700 - 8, fam_b, floor)
        base = base0
        dk.fill_items(sh.text_frame, items, sizes, base)
        room = sh.height / 12700 - dk.box_text_height(items, sizes, sh.width / 12700 - 14, fam_b)
        if ok and len(items) > 1 and room > 40:
            gap = min(16.0, room * .5 / len(items))
            for q in sh.text_frame.paragraphs:
                q.space_after = dk.Pt(round(gap))
        if abs(sizes[0] - base[0]) > .4:
            info["font_changes"].append("body %.0f->%.0f pt" % (base[0], sizes[0]))
        if not ok:
            info["problems"].append("body text does not fit at %.0f pt; cut words or move content to notes" % sizes[0])

    if kind in ("title", "section"):
        target = sub or (bodies[0] if bodies else None)
        lines = [x for x in (s.get("subtitle"), s.get("presenter"), s.get("date")) if x]
        lines = dk.norm_items(lines) or bul
        if target is not None and lines:
            put_body(target, lines, 12.0)
            if target in bodies:
                bodies.remove(target)
        elif target is None and lines:
            dk.add_textbox(slide, (W * .08, H * .62, W * .84, H * .16), lines, 18, name="Subtitle text")
        left_over = bodies + nontext + ([sub] if sub is not None and target is not sub else [])
        if target is not None and not lines:
            left_over.append(target)
        for sh in left_over:
            if sh._element.getparent() is not None:
                sh._element.getparent().remove(sh._element)
    else:
        src_h = int(max(H * .042, 12 * 1.25 * 12700 + 60000))
        src_items = s.get("cite_items")
        src_all = s.get("cite") or src_label(s.get("src"))
        if src_items:
            src_all = " ".join(i["text"] for i in src_items)
            nl = sum(dk.wrap_count(i["text"], 12, W * .88 / 12700, False, fam_b) for i in src_items)
            src_h = int((nl * 12 * 1.25 + 8) * 12700)
        bottom = foot_top - (src_h + int(H * .008) if src_all else int(H * .01))
        title_bottom = (title.top + title.height) if title is not None and title.top is not None else int(H * .17)
        region_all = [b for b in bodies + nontext if (b.width or 0) > W * .2 and (b.height or 0) > H * .12]
        x0 = min([b.left for b in region_all] or [int(W * .06)])
        x1 = max([b.left + b.width for b in region_all] or [int(W * .94)])
        y0 = min([b.top for b in region_all] or [title_bottom + int(H * .02)])
        y0 = max(y0, title_bottom)
        y1 = min(bottom, max([b.top + b.height for b in region_all] or [bottom]))
        region_body = [b for b in region_all if not any(b is q for q in nontext)]
        for q in nontext:
            if q._element.getparent() is not None:
                q._element.getparent().remove(q._element)
        if not region_all or y1 < y0 + H * .4:
            y1 = bottom
        take = s.get("takeaway")
        tk_box = None
        if take:
            th = int(H * .085)
            lines_tk = dk.wrap_count(dk.plain(take), 18, (x1 - x0) / 12700 - 24, True, fam_b)
            if lines_tk > 1:
                th = int(H * .085 + (lines_tk - 1) * 18 * 1.2 * 12700)
            tk_box = (x0, y1 - th, x1 - x0, th)
            y1 = y1 - th - int(H * .018)

        def visual(box):
            if vis == "chart":
                gf, ci = dk.add_chart(slide, box, s["chart"], read_table, fonts, "Chart %d" % n)
                info["chart"] = ci
                info["problems"] += ["chart: " + w for w in ci["warnings"]]
                cap = s["chart"].get("note") or s["chart"].get("err_note")
                if cap:
                    info["chart_note"] = cap
            elif vis == "table":
                t = s["table"]
                if t.get("data") and not t.get("rows"):
                    cols, rows = read_table(t["data"])
                    use = t.get("columns") or cols
                    sel = [r for r in rows if all(str(r.get(c, "")) in [str(v) for v in (vs if isinstance(vs, list) else [vs])] for c, vs in (t.get("where") or {}).items())]
                    t["header"], t["rows"] = t.get("header") or use, [[r[c] for c in use] for r in sel][:t.get("max_rows", 14)]
                gf, ti = dk.add_table(slide, box, t.get("header"), t["rows"], fam_b, t.get("highlight"), "Table %d" % n)
                info["table"] = ti
                if not ti["fits"]:
                    info["problems"].append("table does not fit at %.0f pt (%dx%d): drop columns/rows or split" % (ti["font_pt"], ti["rows"], ti["cols"]))
            elif vis == "image":
                pic, pi = dk.fit_picture(slide, s["image"]["path"], box, "Figure %d" % n, s["image"].get("alt") or s["image"].get("caption", ""))
                info["image"] = pi
                if pi["effective_dpi"] < 110:
                    info["problems"].append("image only %d dpi at this size" % pi["effective_dpi"])
            elif vis == "flow":
                fi = dk.add_flow(slide, box, s["flow"], fam_b)
                if not fi["fits"]:
                    info["problems"].append("flow step text does not fit; shorten steps")
            elif vis == "stats":
                si = dk.add_stats(slide, box, s["stats"], fam_b)
                if not si["fits"]:
                    info["problems"].append("key-number text does not fit; shorten labels")

        cap_text = None
        if vis == "image":
            cap_text = s["image"].get("caption")
        elif vis in ("chart", "table"):
            cap_text = s[vis].get("caption") or s[vis].get("note")

        def capped(box):
            if cap_text:
                x, y, w, h = box
                nl = dk.wrap_count(dk.plain(cap_text), 12, w / 12700 - 10, False, fam_b)
                ch = int((nl * 12 * 1.25 + 8) * 12700)
                ch = min(ch, int(h * .3))
                visual((x, y, w, h - ch - 40000))
                dk.add_textbox(slide, (x, y + h - ch, w, ch), [cap_text], 12, name="Caption %d" % n)
            else:
                visual(box)
        if kind in ("two", "compare") and (s.get("left") or s.get("right")):
            cols = sorted(region_body, key=lambda b: b.left)
            small = [b for b in bodies if b not in region_body]
            pair = [b for b in cols if b.height > H * .2][:2]
            if len(pair) < 2:  # template offers no two-column layout: make the second column ourselves
                sides = []
                for side in ("left", "right"):
                    v = s.get(side) or {}
                    if isinstance(v, list):
                        v = {"bullets": v}
                    it = dk.norm_items(v.get("bullets") or v.get("items"))
                    if v.get("heading") or v.get("title"):
                        it = [{"text": v.get("heading") or v.get("title"), "level": 0, "bold": True, "src": None, "runs": None}] + [dict(i, level=min(1, i["level"] + 1)) for i in it]
                    sides.append(it)
                gapx = int(W * .03)
                half = (x1 - x0 - gapx) // 2
                for n_, it in enumerate(sides):
                    bx = (x0 + n_ * (half + gapx), y0, half, y1 - y0)
                    if n_ == 0 and pair and it:
                        set_box(pair[0], *bx)
                        put_body(pair[0], it)
                    elif it:
                        dk.add_textbox(slide, bx, it, 18, name="Column %d" % (n_ + 1))
                for b in bodies:
                    if not (pair and sides[0] and b is pair[0]) and b._element.getparent() is not None:
                        b._element.getparent().remove(b._element)
                bodies, pair = [], []
                info["problems"].append("layout has no second text placeholder; right column is a text box")
            for side, sh in zip(("left", "right"), pair):
                v = s.get(side) or {}
                if isinstance(v, list):
                    v = {"bullets": v}
                items = dk.norm_items(v.get("bullets") or v.get("items"))
                head = v.get("heading") or v.get("title")
                heads = sorted([b for b in small if abs(b.left - sh.left) < W * .1], key=lambda b: b.top)
                if head and heads:
                    put_body(heads[0], [{"text": head, "level": 0, "bold": True}], 14)
                    bodies.remove(heads[0])
                elif head:
                    items = [{"text": head, "level": 0, "bold": True, "src": None}] + [dict(i, level=min(1, i["level"] + 1)) for i in items]
                if sh.top + sh.height > y1:
                    set_box(sh, sh.left, sh.top, sh.width, y1 - sh.top)
                if items:
                    put_body(sh, items)
                    bodies.remove(sh)
            for b in bodies:
                if b._element.getparent() is not None and not any(b._element is q._element for q in pair if q.has_text_frame and q.text_frame.text.strip()):
                    b._element.getparent().remove(b._element)
            bodies = []
        elif vis and bul:
            two = sorted([b for b in region_all if b.height > H * .25], key=lambda b: b.left)
            side = s.get("visual_side", "right")
            if side == "right" and vis == "table" and max([len(s["table"].get("header") or [])] + [len(r) for r in s["table"].get("rows") or [[]]]) > 5:
                side = "bottom"
            if side == "bottom":
                tb = region_body[0] if region_body else None
                base = [min(20, dk.inherited_size(layout, tb.placeholder_format.idx, dk.ph_type(tb), lv, 20 - 2 * lv)) for lv in range(3)] if tb is not None else [18, 16, 14]
                need = dk.box_text_height(bul, [18, 16, 15], (x1 - x0) / 12700 - 14, fam_b) + 12
                th = int(min(max(need * 12700, H * .08), (y1 - y0) * .42))
                if tb is not None:
                    set_box(tb, x0, y0, x1 - x0, th)
                    put_body(tb, bul)
                else:
                    dk.add_textbox(slide, (x0, y0, x1 - x0, th), bul, 16, name="Body text")
                capped((x0, y0 + th + int(H * .012), x1 - x0, y1 - y0 - th - int(H * .012)))
                keep = [tb]
            elif len(two) >= 2 and two[1].left > two[0].left + two[0].width * .5:
                tb, vb = (two[0], two[1]) if s.get("visual_side", "right") == "right" else (two[1], two[0])
                if any(tb is q for q in nontext):   # geometry from the layout, text only into a text placeholder
                    tb, vb = vb, tb
                if any(tb is q for q in nontext):
                    tb = None
                gapx = int(W * .02)
                share = float(s.get("visual_share") or (.62 if vis == "image" else .56 if vis in ("chart", "table") else .5))   # a figure needs the larger share to stay readable
                if vis == "flow":
                    share = .5
                tw = int((x1 - x0 - gapx) * (1 - share))
                vw = x1 - x0 - gapx - tw
                if s.get("visual_side", "right") == "right":
                    tbox, vbox = (x0, y0, tw, y1 - y0), (x0 + tw + gapx, y0, vw, y1 - y0)
                else:
                    tbox, vbox = (x0 + vw + gapx, y0, tw, y1 - y0), (x0, y0, vw, y1 - y0)
                if tb is not None:
                    set_box(tb, *tbox)
                    put_body(tb, bul)
                else:
                    dk.add_textbox(slide, tbox, bul, 18, name="Body text")
                capped(vbox)
                keep = [tb]
            else:
                tb = region_body[0] if region_body else None
                vh = int((y1 - y0) * (.34 if vis == "stats" else .56))
                vbox = (x0, y0, x1 - x0, vh)
                if vis == "flow":
                    vbox = (x0, y0, x1 - x0, int((y1 - y0) * .36))
                    vh = vbox[3]
                if vis != "stats" and vis != "flow":
                    tw = int((x1 - x0) * (.38 if vis == "image" else .42))
                    vbox = (x0 + tw + int(W * .02), y0, x1 - x0 - tw - int(W * .02), y1 - y0)
                    tbox = (x0, y0, tw, y1 - y0)
                else:
                    tbox = (x0, y0 + vh + int(H * .02), x1 - x0, y1 - y0 - vh - int(H * .02))
                if tb is not None:
                    set_box(tb, *tbox)
                    put_body(tb, bul)
                else:
                    dk.add_textbox(slide, tbox, bul, 18, name="Body text")
                capped(vbox)
                keep = [tb]
            for b in bodies:
                if b not in keep:
                    b._element.getparent().remove(b._element)
        elif vis:
            for b in bodies:
                b._element.getparent().remove(b._element)
            capped((x0, y0, x1 - x0, y1 - y0))
        else:
            if region_body and bul:
                tb = region_body[0]
                if tb.top + tb.height > y1 or tb.top < y0:
                    top_ = max(tb.top, y0)
                    if y1 - top_ < H * .1:   # a low caption-style body under a takeaway: use the whole content region
                        set_box(tb, x0, y0, x1 - x0, y1 - y0)
                    else:
                        set_box(tb, tb.left, top_, tb.width, y1 - top_)
                put_body(tb, bul)
                for b in bodies:
                    if b is not tb:
                        b._element.getparent().remove(b._element)
            else:
                for b in bodies:
                    b._element.getparent().remove(b._element)
                if bul:
                    dk.add_textbox(slide, (x0, y0, x1 - x0, y1 - y0), bul, 18, name="Body text")
        if tk_box:
            tb = dk.add_textbox(slide, tk_box, [take], 18, bold=True, anchor=dk.MSO_ANCHOR.MIDDLE, name="Takeaway", color=dk.MSO_THEME_COLOR.ACCENT_1)
            tb.fill.solid()
            tb.fill.fore_color.theme_color = dk.MSO_THEME_COLOR.ACCENT_1
            tb.fill.fore_color.brightness = 0.9
        if src_all:
            dk.add_textbox(slide, (x0, foot_top - src_h - int(H * .004), x1 - x0, src_h), src_items if src_items else ["Source: " + src_all if not str(src_all).lower().startswith(("source", "来源")) else src_all], 12,
                           color=dk.MSO_THEME_COLOR.TEXT_1, name="Source line", anchor=dk.MSO_ANCHOR.MIDDLE)
    if s.get("notes"):
        dk.set_notes(slide, str(s["notes"]) if not isinstance(s["notes"], list) else "\n".join(map(str, s["notes"])))
    else:
        info["problems"].append("no speaker notes")
    log.append(info)
    return slide


def set_box(sh, x, y, w, h):
    from pptx.util import Emu
    sh.left, sh.top, sh.width, sh.height = [Emu(int(v)) for v in (x, y, w, h)]


def load_json(p):
    try:
        return jload(p)
    except FileNotFoundError:
        sys.exit("file not found: " + p)
    except json.JSONDecodeError as exc:
        ln = open(p, encoding="utf-8").read().splitlines()
        sys.exit("%s is not valid JSON at line %d col %d: %s\n> %s" % (p, exc.lineno, exc.colno, exc.msg, ln[exc.lineno - 1][:200] if exc.lineno <= len(ln) else ""))


def cmd_build(a):
    dk = need_pptx()
    t0 = time.time()
    d = load_json(a.spec or os.path.join(WORK, "deck.json"))
    if not a.spec:
        for f in sorted(glob.glob(os.path.join(WORK, "slides_*.json"))):
            q = load_json(f)
            d["slides"] = list(d.get("slides") or []) + (q if isinstance(q, list) else q.get("slides", [q]))
    err, warn = validate_deck(d)
    if err:
        say("SPEC ERRORS (nothing overwritten):")
        for e in err[:20]:
            say(" -", e)
        sys.exit(2)
    tpl = template_file() or starting_file()
    prs = dk.Presentation(tpl) if tpl else dk.Presentation()
    before = dk.master_hashes(prs)
    while len(prs.slides):
        dk.delete_slide(prs, 0)
    fonts = dk.theme_fonts(prs)
    log = []
    for n, s in enumerate(d["slides"], 1):
        try:
            render_slide(prs, s, n, d, dk, fonts, log)
        except ValueError as exc:
            sys.exit("CANNOT BUILD slide %d (nothing overwritten): %s" % (n, exc))
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            sys.exit("CANNOT BUILD slide %d (nothing overwritten): malformed or missing key %s in its chart/table/image/stats/flow/left/right block; compare with the examples in SKILL.md" % (n, exc))
    prs.core_properties.title = dk.plain(d.get("title", d["slides"][0]["title"]))
    prs.core_properties.author = d.get("presenter", "") or "deckkit"
    os.makedirs(OUT, exist_ok=True)
    prs.save(PPTX)
    dedupe(PPTX)
    jsave(os.path.join(OUT, "deck_spec.json"), d)
    jsave(os.path.join(WORK, "build_log.json"), log)
    finish(d, warn, log, mode="build", master_before=before, tpl=tpl, t0=t0)


def dedupe(path):
    """Rewrite the package once so that parts orphaned by slide deletion disappear."""
    import dk_pptx as dk
    prs = dk.Presentation(path)
    prs.save(path)


# --- adapt --------------------------------------------------------------------------
def cmd_adapt(a):
    """Generic, loss-audited migration of the starting deck into the target template."""
    dk = need_pptx()
    t0 = time.time()
    sp, tp = starting_file(), template_file()
    if not sp or not tp:
        sys.exit("adapt needs both a starting deck and a target template")
    over = {}
    op = a.overrides or os.path.join(WORK, "overrides.json")
    if os.path.exists(op):
        over = {int(k): v for k, v in load_json(op).items() if str(k).isdigit()}
        glob_over = load_json(op)
    else:
        glob_over = {}
    src = dk.Presentation(sp)
    prs = dk.Presentation(tp)
    before = dk.master_hashes(prs)
    while len(prs.slides):
        dk.delete_slide(prs, 0)
    fonts = dk.theme_fonts(prs)
    log, spec = [], {"slides": [], "title": "", "footer": glob_over.get("footer"), "audience": glob_over.get("audience"), "goal": glob_over.get("goal"), "storyline": glob_over.get("storyline"), "qa": glob_over.get("qa", []), "unresolved": glob_over.get("unresolved", []), "decisions": glob_over.get("decisions", []), "omitted": glob_over.get("omitted", [])}
    for n, s in enumerate(src.slides, 1):
        o = over.get(n, {})
        title, bodies, tables, charts, pics, groups, loose = None, [], [], [], [], [], []
        cand_loose = [sh for sh in s.shapes if not sh.is_placeholder and sh.shape_type not in (6, 13, 17, 19, 3) and not hasattr(sh, "image") and not getattr(sh, "has_table", False) and not getattr(sh, "has_chart", False)]
        conns = [sh for sh in cand_loose if sh._element.tag.endswith("cxnSp")]
        if conns or len([sh for sh in cand_loose if sh.has_text_frame and sh.text_frame.text.strip()]) >= 3:
            loose = cand_loose

        def visit(shapes):
            nonlocal title
            for sh in shapes:
                if sh.shape_type == 6:
                    groups.append(sh)
                    continue
                if any(sh._element is q._element for q in loose):
                    continue
                if sh.is_placeholder and dk.ph_type(sh) in dk.FOOT_T:
                    continue
                if getattr(sh, "has_table", False) and sh.has_table:
                    tables.append(sh)
                elif getattr(sh, "has_chart", False) and sh.has_chart:
                    charts.append(sh)
                elif hasattr(sh, "image"):
                    pics.append(sh)
                elif getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip():
                    if title is None and sh.is_placeholder and dk.ph_type(sh) in dk.TITLE_T:
                        title = sh
                    else:
                        bodies.append(sh)
        visit(s.shapes)
        if title is None and bodies:
            cand = sorted(bodies, key=lambda b: ((b.top or 0), -(b.height or 0)))
            def big(b):
                z = [r.font.size.pt for p in b.text_frame.paragraphs for r in p.runs if r.font.size]
                return max(z or [0])
            top = sorted([b for b in cand if (b.top or 0) < src.slide_height * .3 and len(b.text_frame.text) < 160], key=lambda b: (-big(b), b.top or 0))
            title = top[0] if top else cand[0]
            bodies.remove(title)
        bodies.sort(key=lambda b: (round((b.left or 0) / (src.slide_width * .4)), b.top or 0))
        items = []
        small = []
        for b in bodies:
            zs = [r.font.size.pt for p in b.text_frame.paragraphs for r in p.runs if r.font.size]
            txt = b.text_frame.text.strip()
            bottom = (b.top or 0) > src.slide_height * .86
            if len(txt) < 220 and (re.match(r"(?i)^\W*(sources?|refs?|references?|doi|来源|参考|数据来源|adapted from)\b", txt) or re.match(r"(?i)^\W*(https?://|doi\.org|10\.\d{4,})", txt)):
                for p in b.text_frame.paragraphs:
                    t = "".join(r.text for r in p.runs).strip() or p.text.strip()
                    if t:
                        small.append({"text": t, "level": 0, "runs": dk.source_runs(p) or [(t, None, None, None, None, None)]})
                continue
            for p in b.text_frame.paragraphs:
                t = "".join(r.text for r in p.runs).strip() or p.text.strip()
                if t:
                    items.append({"text": t, "level": p.level, "runs": dk.source_runs(p) or [(t, None, None, None, None, None)]})
        is_title = n == 1 and not tables and not charts and not pics and len(items) <= 4
        sl = {"kind": "title" if is_title else "content", "title": title.text_frame.text.strip().replace("\v", " ").replace("\n", " ") if title is not None else "(untitled in source deck)",
              "notes": dk.notes_text(s), "cite_items": small or None, "raw": True, "from_slide": n}
        if is_title:
            sl["bullets"] = items
        else:
            sl["bullets"] = items
        sl.update({k: v for k, v in o.items() if k not in ("drop",)})
        sl["bullets"] = dk.norm_items(sl.get("bullets"))
        media = [("table", t) for t in tables] + [("chart", c) for c in charts] + [("pic", p) for p in pics] + [("group", g) for g in groups] + ([("loose", loose)] if loose else [])
        want = "title" if sl["kind"] == "title" else ("two" if media and sl["bullets"] else ("titleonly" if media else sl["kind"]))
        tmp = {k: v for k, v in sl.items() if k not in ("bullets",)}
        tmp["kind"] = "title" if want == "title" else "content"
        tmp["bullets"] = sl["bullets"]
        if o.get("title"):
            tmp["raw"] = sl["raw"] = False
        if media and sl["bullets"]:
            ncol = max([len(t.table.columns) for t in tables] or [0])
            wide_pic = any(q.width and q.height and q.width / q.height > 1.6 for q in pics)
            chars = sum(len(i["text"]) for i in sl["bullets"])
            tmp["visual_side"] = o.get("visual_side") or ("bottom" if ncol > 5 or (wide_pic and chars < 330) else "right")
        if media:
            # reserve the visual region through a placeholder-free render
            tmp["flow"] = ["x"]
        slide = render_slide(prs, tmp, n, spec, dk, fonts, log)
        info = log[-1]
        if media:
            box = None
            for sh in list(slide.shapes):
                if sh.name.startswith("Step "):
                    pass
            boxes = [sh for sh in slide.shapes if sh.name.startswith("Step ")]
            info["problems"] = [p for p in info["problems"] if "flow" not in p]
            vb = region_of(slide, prs, dk, boxes)
            for sh in boxes:
                sh._element.getparent().remove(sh._element)
            place_media(slide, media, vb, dk, fonts, info, n)
        if dk.is_hidden(s) and not o.get("unhide"):
            slide._element.set("show", "0")
        sl["layout_used"] = slide.slide_layout.name
        sl["media"] = [m[0] for m in media]
        spec["slides"].append(sl)
        if not spec["title"]:
            spec["title"] = sl["title"]
    os.makedirs(OUT, exist_ok=True)
    prs.save(PPTX)
    dedupe(PPTX)
    jsave(os.path.join(OUT, "deck_spec.json"), spec)
    finish(spec, [], log, mode="adapt", master_before=before, tpl=tp, start=sp, t0=t0)


def region_of(slide, prs, dk, boxes):
    W, H = prs.slide_width, prs.slide_height
    L = slide.slide_layout
    title = next((s for s in slide.placeholders if dk.ph_type(s) in dk.TITLE_T), None)
    top = int((title.top + title.height) if title is not None and title.top is not None else H * .18) + int(H * .015)
    bodies = [s for s in slide.placeholders if dk.ph_type(s) not in dk.TITLE_T | dk.FOOT_T and s.has_text_frame and s.text_frame.text.strip()]
    bodies += [s for s in slide.shapes if not s.is_placeholder and s.name == "Body text" and s.has_text_frame and s.text_frame.text.strip()]
    foot = min([s.top for s in L.placeholders if dk.ph_type(s) in dk.FOOT_T and s.top and s.top > H * .7] or [int(H * .93)])
    srcl = [s for s in slide.shapes if s.name == "Source line"]
    bottom = min([foot] + [s.top for s in srcl]) - int(H * .01)
    if bodies and boxes:
        x0 = min(b.left for b in boxes)
        x1 = max(b.left + b.width for b in boxes)
        bx = bodies[0]
        if bx.top + bx.height <= min(b.top for b in boxes) + 20000:   # visual sits under the text
            y0 = bx.top + bx.height + int(H * .012)
            return (bx.left, y0, bx.width, bottom - y0)
        if bx.top > top + H * .2:   # text sits under the visual
            y0 = min(b.top for b in boxes)
            return (x0, y0, x1 - x0, bx.top - y0 - int(H * .01))
        return (x0, max(top, bx.top), x1 - x0, bottom - max(top, bx.top))
    xs = [s for s in L.placeholders if dk.ph_type(s) in dk.BODY_T and s.width and s.width > W * .3]
    x0 = min([s.left for s in xs] or [title.left if title is not None and title.left else int(W * .06)])
    x1 = max([s.left + s.width for s in xs] or [int(W) - x0])
    return (x0, top, x1 - x0, bottom - top)


def place_media(slide, media, box, dk, fonts, info, n):
    x, y, w, h = [int(v) for v in box]
    k = len(media)
    horiz = w > h * 1.3
    for i, (kind, sh) in enumerate(media):
        if k == 1:
            b = (x, y, w, h)
        elif horiz:
            cw = (w - 120000 * (k - 1)) // k
            b = (x + i * (cw + 120000), y, cw, h)
        else:
            ch = (h - 120000 * (k - 1)) // k
            b = (x, y + i * (ch + 120000), w, ch)
        if kind == "table":
            rows = [[c.text for c in r.cells] for r in sh.table.rows]
            gf, ti = dk.add_table(slide, b, rows[0], rows[1:], fonts["minor"], None, sh.name, True)
            info.setdefault("tables", []).append(ti)
            if not ti["fits"]:
                info["problems"].append("table '%s' does not fit at %.0f pt" % (sh.name, ti["font_pt"]))
        elif kind == "chart":
            v = dk.chart_values(sh)
            t = v["type"]
            ty = "line" if "LINE" in t else "pie" if "PIE" in t else "barh" if "BAR_" in t else "stacked" if "STACKED" in t else "bar"
            sp = {"type": ty, "categories": v["categories"], "series": [{"name": a, "values": c} for a, c in v["series"]]}
            try:
                if sh.chart.value_axis.has_title:
                    sp["ylabel"] = sh.chart.value_axis.axis_title.text_frame.text
                if sh.chart.category_axis.has_title:
                    sp["xlabel"] = sh.chart.category_axis.axis_title.text_frame.text
            except Exception:
                pass
            simple = t.split(" ")[0].split(".")[-1] in ("COLUMN_CLUSTERED", "BAR_CLUSTERED", "LINE", "LINE_MARKERS", "PIE", "COLUMN_STACKED") and len(list(sh.chart.plots)) == 1 and not list(sh.chart._chartSpace.iter(dk.qn("c:errBars"))) and not list(sh.chart._chartSpace.iter(dk.qn("c:trendline")))
            if t.split(" ")[0].split(".")[-1] == "COLUMN_STACKED":
                sp["type"] = "stacked"
            if not simple:
                dk.copy_chart(slide, sh, b)
                info["problems"].append("chart '%s' (%s) copied as the original native chart with its workbook; its own formatting is kept" % (sh.name, t))
                continue
            dk.add_chart(slide, b, sp, read_table, fonts, sh.name)
            if sh.chart.has_title:
                gf = slide.shapes[-1]
                gf.chart.has_title = True
                gf.chart.chart_title.text_frame.text = sh.chart.chart_title.text_frame.text
        elif kind == "group":
            try:
                dk.copy_shape(slide, sh, b)
            except ValueError as exc:
                info["problems"].append("group '%s' not copied: %s" % (sh.name, exc))
        elif kind == "loose":
            dk.group_shapes(slide, sh, b)
        else:
            alt = sh._element.find(".//" + dk.qn("p:cNvPr")).get("descr") or ""
            dk.fit_picture(slide, sh.image.blob, b, sh.name, alt)


# --- edit -----------------------------------------------------------------------------
def find_shape(slide, ref):
    ref = str(ref)
    for sh in slide.shapes:
        if ref.lstrip("#") == str(sh.shape_id) or ref == sh.name:
            return sh
    if ref.lower() == "title":
        return slide.shapes.title
    raise ValueError("shape '%s' not on slide; have %s" % (ref, ["#%d %s" % (s.shape_id, s.name) for s in slide.shapes]))


def replace_text(tf, old, new):
    """Replace inside a paragraph while keeping the first affected run's formatting."""
    n = 0
    for p in tf.paragraphs:
        runs = p.runs
        full = "".join(r.text for r in runs)
        if old not in full:
            continue
        done = False
        for r in runs:
            if old in r.text:
                r.text = r.text.replace(old, new)
                done = True
        if not done:
            i = full.index(old)
            j = i + len(old)
            pos = 0
            first = True
            for r in runs:
                a, b = pos, pos + len(r.text)
                pos = b
                if b <= i or a >= j:
                    continue
                keep_l = r.text[:max(0, i - a)]
                keep_r = r.text[max(0, j - a):] if b > j else ""
                r.text = keep_l + (new if first else "") + keep_r
                first = False
        n += 1
    return n


def set_par_text(p, text):
    rs = p.runs
    if rs:
        rs[0].text = text
        for r in rs[1:]:
            r._r.getparent().remove(r._r)
    else:
        p.add_run().text = text


def all_frames(slide):
    def it(shapes):
        for sh in shapes:
            if sh.shape_type == 6:
                yield from it(sh.shapes)
            elif getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    for c in row.cells:
                        yield c.text_frame
            elif getattr(sh, "has_text_frame", False) and sh.has_text_frame:
                yield sh.text_frame
    yield from it(slide.shapes)


def cmd_edit(a):
    dk = need_pptx()
    t0 = time.time()
    d = load_json(a.ops or os.path.join(WORK, "edits.json"))
    ops = d.get("ops") if isinstance(d, dict) else d
    meta = d if isinstance(d, dict) else {}
    base = starting_file() or template_file()
    if meta.get("base"):
        try:
            base = table_path(meta["base"])
        except ValueError:
            say("NOTE: base %r not found; using the supplied starting deck %s" % (meta["base"], os.path.basename(str(base))))
    if meta.get("continue") and os.path.exists(PPTX):
        base = os.path.join(WORK, "edit_base.pptx")
        shutil.copy(PPTX, base)
    if not base:
        sys.exit("no starting deck found")
    prs = dk.Presentation(base)
    before_m = dk.master_hashes(prs)
    orig = list(prs.slides)
    fonts = dk.theme_fonts(prs)
    log, build_log = [], []
    touched = set()
    handle = {n: s for n, s in enumerate(orig, 1)}   # original numbering stays valid for every op
    new_handles = {}

    def index_of(slide):
        return [s.slide_id for s in prs.slides].index(slide.slide_id)

    def get(ref):
        if str(ref) in new_handles:
            return new_handles[str(ref)]
        n = int(ref)
        if n not in handle:
            raise ValueError("slide %s does not exist (1-%d)" % (ref, len(orig)))
        return handle[n]
    for op in ops:
        kind = op.get("op")
        try:
            detail = ""
            if kind in ("replace_text", "replace"):
                targets = [get(op["slide"])] if op.get("slide") not in (None, "all") else list(prs.slides)
                cnt = 0
                for s in targets:
                    frames = [find_shape(s, op["shape"]).text_frame] if op.get("shape") else list(all_frames(s))
                    c = sum(replace_text(tf, str(op["old"]), str(op["new"])) for tf in frames)
                    if c:
                        touched.add(s.slide_id)
                    cnt += c
                    if op.get("notes") and s.has_notes_slide:
                        replace_text(s.notes_slide.notes_text_frame, str(op["old"]), str(op["new"]))
                if not cnt:
                    raise ValueError("text not found: %s" % op["old"])
                detail = "%d paragraph(s)" % cnt
            elif kind == "set_title":
                s = get(op["slide"])
                t = s.shapes.title
                if t is None:
                    raise ValueError("slide has no title placeholder; use set_text with a shape id")
                set_par_text(t.text_frame.paragraphs[0], str(op["text"]))
                for p in t.text_frame.paragraphs[1:]:
                    p._p.getparent().remove(p._p)
                touched.add(s.slide_id)
            elif kind == "set_text":
                s = get(op["slide"])
                sh = find_shape(s, op["shape"])
                tf = sh.text_frame
                if op.get("paragraph") is not None:
                    set_par_text(tf.paragraphs[int(op["paragraph"])], str(op["text"]))
                else:
                    items = dk.norm_items(op.get("items") or [x for x in str(op.get("text", "")).split("\n")])
                    ps = tf.paragraphs
                    proto = copy.deepcopy(ps[0]._p)
                    for p in ps[1:]:
                        p._p.getparent().remove(p._p)
                    for k, it in enumerate(items):
                        if k == 0:
                            p = tf.paragraphs[0]
                        else:
                            el = copy.deepcopy(proto)
                            tf._txBody.append(el)
                            p = tf.paragraphs[-1]
                        set_par_text(p, dk.plain(it["text"]))
                        p.level = it["level"]
                touched.add(s.slide_id)
            elif kind in ("set_notes", "append_notes"):
                s = get(op["slide"])
                old = dk.notes_text(s)
                dk.set_notes(s, str(op["text"]), keep=(old + "\n" if kind == "append_notes" and old else ""))
                touched.add(("notes", s.slide_id))
            elif kind == "set_cell":
                s = get(op["slide"])
                t = find_shape(s, op["shape"]).table if op.get("shape") else next(sh.table for sh in s.shapes if sh.has_table)
                c = t.cell(int(op["row"]), int(op["col"]))
                detail = "was '%s'" % c.text
                set_par_text(c.text_frame.paragraphs[0], str(op["text"]))
                touched.add(s.slide_id)
            elif kind == "set_table":
                s = get(op["slide"])
                sh = find_shape(s, op["shape"]) if op.get("shape") else next(x for x in s.shapes if x.has_table)
                t = sh.table
                rows = op["rows"]
                if len(rows) != len(t.rows) or any(len(r) != len(t.columns) for r in rows):
                    b = (sh.left, sh.top, sh.width, sh.height)
                    name = sh.name
                    sh._element.getparent().remove(sh._element)
                    gf, ti = dk.add_table(s, b, rows[0], rows[1:], fonts["minor"], None, name)
                    detail = "table rebuilt %dx%d" % (ti["rows"], ti["cols"])
                else:
                    for r, row in enumerate(rows):
                        for c, v in enumerate(row):
                            if t.cell(r, c).text != str(v):
                                set_par_text(t.cell(r, c).text_frame.paragraphs[0], str(v))
                touched.add(s.slide_id)
            elif kind == "update_chart":
                s = get(op["slide"])
                sh = find_shape(s, op["shape"]) if op.get("shape") else next(x for x in s.shapes if x.has_chart)
                k, cats, series, warn = dk.chart_series(op.get("chart", op), read_table)
                cd = dk.CategoryChartData()
                cd.categories = cats
                for nme, v, _ in series:
                    cd.add_series(nme, v)
                detail = "was %s" % json.dumps(dk.chart_values(sh), ensure_ascii=False)[:300]
                sh.chart.replace_data(cd)
                try:
                    va = sh.chart.value_axis
                    vals = [x for _, v, _ in series for x in v if x is not None]
                    if ("BAR" in str(sh.chart.chart_type) or "COLUMN" in str(sh.chart.chart_type)) and va.minimum_scale is None and vals and min(vals) >= 0:
                        va.minimum_scale = 0
                        detail += "; value axis set to start at 0 (bars)"
                except Exception:
                    pass
                touched.add(s.slide_id)
                log += [{"op": "note", "result": w} for w in warn]
            elif kind == "delete_slide":
                s = get(op["slide"])
                dk.delete_slide(prs, index_of(s))
            elif kind == "move_slide":
                s = get(op["slide"])
                dk.move_slide(prs, index_of(s), int(op["to"]) - 1)
            elif kind in ("add_slide", "insert_slide"):
                sp = dict(op.get("spec") or op.get("new") or {})
                err, w = validate_deck({"slides": [sp]})
                if err:
                    raise ValueError("; ".join(err))
                s = render_slide(prs, sp, len(prs.slides) + 1, meta, dk, fonts, build_log)
                if op.get("after") is not None:
                    dk.move_slide(prs, len(prs.slides) - 1, 0 if str(op["after"]) == "0" else index_of(get(op["after"])) + 1)
                elif op.get("position"):
                    dk.move_slide(prs, len(prs.slides) - 1, int(op["position"]) - 1)
                if op.get("id"):
                    new_handles[str(op["id"])] = s
                op["_slide_id"] = s.slide_id
                detail = "layout %s" % s.slide_layout.name
            elif kind == "delete_shape":
                s = get(op["slide"])
                sh = find_shape(s, op["shape"])
                sh._element.getparent().remove(sh._element)
                touched.add(s.slide_id)
            elif kind == "move_shape":
                s = get(op["slide"])
                sh = find_shape(s, op["shape"])
                for k in ("left", "top", "width", "height"):
                    if op.get(k) is not None:
                        from pptx.util import Inches
                        setattr(sh, k, Inches(float(op[k])))
                touched.add(s.slide_id)
            elif kind == "replace_image":
                s = get(op["slide"])
                sh = find_shape(s, op["shape"])
                b = (sh.left, sh.top, sh.width, sh.height)
                name = sh.name
                sh._element.getparent().remove(sh._element)
                dk.fit_picture(s, table_path(op["path"]), b, name, op.get("alt", ""))
                touched.add(s.slide_id)
            elif kind == "set_layout":
                raise ValueError("changing layouts in place is not supported; use adapt or rebuild the slide with add_slide + delete_slide")
            else:
                raise ValueError("unknown op '%s'; use replace_text set_title set_text set_notes append_notes set_cell set_table update_chart add_slide delete_slide move_slide delete_shape move_shape replace_image" % kind)
            log.append({"op": {k: v for k, v in op.items() if not k.startswith("_")}, "result": "applied", "detail": detail})
        except (ValueError, KeyError, IndexError, StopIteration, AttributeError, TypeError) as exc:
            log.append({"op": {k: v for k, v in op.items() if not k.startswith("_")}, "result": "failed: %s" % (exc or type(exc).__name__)})
    os.makedirs(OUT, exist_ok=True)
    prs.save(PPTX)
    dedupe(PPTX)
    bad = [x for x in log if str(x["result"]).startswith("failed")]
    say("EDIT %d applied, %d failed" % (sum(x["result"] == "applied" for x in log), len(bad)))
    for x in bad:
        say(" -", x["result"], json.dumps(x["op"], ensure_ascii=False)[:200])
    jsave(os.path.join(OUT, "edit_operations.json"), log)
    finish(meta, [], build_log, mode="edit", master_before=before_m, tpl=base, start=base, t0=t0, edit_log=log)


def cover_exempt():
    """Does the order say the cover carries no footer / number? (the exemption must concern footer or numbering in the same clause)"""
    t = " ".join(ks.must_lines()).lower()
    ex = re.compile(r"(except|exempt|excluding|but not|not on|no footer on|other than|besides|apart from)[^.;|]{0,40}(cover|title slide|first slide|\u5c01\u9762|\u9996\u9875)"
                    r"|(cover|title slide|\u5c01\u9762|\u9996\u9875)[^.;|]{0,40}(no footer|without footer|no number|exempt|excluded|\u9664\u5916|\u4e0d)"
                    r"|\u9664(\u5c01\u9762|\u9996\u9875)")
    for cl in re.split(r"[.;|\n\u3002\uff1b]|(?=case\.)|(?=  )", t):
        if re.search(r"footer|page.?num|slide.?num|number|\u9875\u811a|\u9875\u7801|\u7f16\u53f7|\u9875\u53f7", cl) and ex.search(cl):
            return True
    return False


def natives_of(dk, slide):
    """What the delivered slide really shows, object by object."""
    out = []

    def walk(shapes):
        for sh in shapes:
            if sh.shape_type == 6:
                out.append({"type": "group", "name": sh.name, "editable_objects": len(list(sh.shapes))})
                walk(sh.shapes)
            elif getattr(sh, "has_chart", False) and sh.has_chart:
                ch = sh.chart
                try:
                    ser = {str(s_.name): len(list(s_.values)) for pl in ch.plots for s_ in pl.series}
                except Exception:
                    ser = {}
                out.append({"type": "native chart", "name": sh.name, "chart_type": str(ch.chart_type), "series_points": ser})
            elif getattr(sh, "has_table", False) and sh.has_table:
                t = sh.table
                out.append({"type": "native table", "name": sh.name, "rows": len(t.rows), "columns": len(t.columns), "header": [c.text for c in t.rows[0].cells][:8]})
            elif sh.shape_type == 13 or (sh.is_placeholder and getattr(sh, "image", None) is not None if hasattr(sh, "image") else False):
                d = sh._element.xpath(".//p:cNvPr/@descr")
                out.append({"type": "picture", "name": sh.name, "alt_text": d[0] if d else None})
    try:
        walk(slide.shapes)
    except Exception:
        pass
    return out


# --- checks and result --------------------------------------------------------------------
def render_pdf():
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    pdf = os.path.join(OUT, "presentation.pdf")
    if not exe:
        return None, "no LibreOffice"
    if os.path.exists(pdf):
        os.remove(pdf)
    prof = tempfile.mkdtemp(prefix="lo_")
    try:
        r = subprocess.run([exe, "-env:UserInstallation=file://" + prof, "--headless", "--convert-to", "pdf", "--outdir", OUT, PPTX], capture_output=True, text=True, timeout=170)
    except subprocess.TimeoutExpired:
        return None, "LibreOffice timed out"
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    ver = ""
    try:
        ver = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        pass
    return (pdf if os.path.exists(pdf) else None), ver or r.stderr[-200:]


def previews(pdf):
    d = os.path.join(OUT, "previews")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    if shutil.which("pdftoppm") and pdf:
        subprocess.run(["pdftoppm", "-r", "60", "-png", pdf, os.path.join(d, "slide")], capture_output=True, timeout=120)
    pngs = sorted(glob.glob(os.path.join(d, "*.png")))
    sheet = None
    try:
        from PIL import Image
        ims = [Image.open(p) for p in pngs]
        if ims:
            cols = 3 if len(ims) > 4 else 2
            tw = 520
            th = int(tw * ims[0].height / ims[0].width)
            rows = (len(ims) + cols - 1) // cols
            im = Image.new("RGB", (cols * (tw + 10) + 10, rows * (th + 10) + 10), (110, 110, 110))
            for k, x in enumerate(ims):
                im.paste(x.convert("RGB").resize((tw, th)), (10 + (k % cols) * (tw + 10), 10 + (k // cols) * (th + 10)))
            sheet = os.path.join(OUT, "contact_sheet.png")
            im.save(sheet)
    except Exception:
        pass
    return pngs, sheet


def hidden_previews(dk, prs, ver):
    """Render hidden slides apart from the show, for inspection only."""
    hid = [k for k, q in enumerate(prs.slides, 1) if dk.is_hidden(q)]
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not hid or not exe or not shutil.which("pdftoppm"):
        return []
    d = tempfile.mkdtemp(prefix="hid_")
    out = []
    try:
        q = dk.Presentation(PPTX)
        for sl in q.slides:
            if "show" in sl._element.attrib:
                del sl._element.attrib["show"]
        tmp = os.path.join(d, "all.pptx")
        q.save(tmp)
        subprocess.run([exe, "-env:UserInstallation=file://" + os.path.join(d, "lo"), "--headless", "--convert-to", "pdf", "--outdir", d, tmp], capture_output=True, timeout=120)
        for n in hid:
            stem = os.path.join(OUT, "previews", "hidden_slide-%02d" % n)
            subprocess.run(["pdftoppm", "-r", "60", "-png", "-f", str(n), "-l", str(n), "-singlefile", os.path.join(d, "all.pdf"), stem], capture_output=True, timeout=60)
            if os.path.exists(stem + ".png"):
                out.append(stem + ".png")
    except Exception:
        pass
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return out


def audit(dk, path):
    """Structural audit of a delivered deck; independent of the build log."""
    prs = dk.Presentation(path)
    W, H = prs.slide_width, prs.slide_height
    fonts = dk.theme_fonts(prs)
    rep = []
    for n, s in enumerate(prs.slides, 1):
        r = {"slide": n, "layout": s.slide_layout.name, "empty_placeholders": [], "out_of_bounds": [], "overlaps": [], "overflow": [], "min_font": None, "title": "", "words": 0,
             "off_theme_fonts": [], "notes_chars": len(dk.notes_text(s)), "native": {"tables": 0, "charts": 0, "pictures": 0}}
        boxes = []
        for sh in s.shapes:
            if getattr(sh, "has_table", False) and sh.has_table:
                r["native"]["tables"] += 1
            elif getattr(sh, "has_chart", False) and sh.has_chart:
                r["native"]["charts"] += 1
            elif hasattr(sh, "image"):
                r["native"]["pictures"] += 1
            ph = sh.is_placeholder
            foot = ph and dk.ph_type(sh) in dk.FOOT_T
            if ph and not foot and getattr(sh, "has_text_frame", False) and sh.has_text_frame and not sh.text_frame.text.strip():
                r["empty_placeholders"].append(sh.name)
            if sh.left is None or sh.width is None:
                continue
            if sh.left < -20000 or sh.top < -20000 or sh.left + sh.width > W + 20000 or sh.top + sh.height > H + 20000:
                r["out_of_bounds"].append(sh.name)
            if getattr(sh, "has_text_frame", False) and sh.has_text_frame and sh.text_frame.text.strip() and not foot:
                t = sh.text_frame.text
                if ph and dk.ph_type(sh) in dk.TITLE_T:
                    r["title"] = t.replace("\v", " ").replace("\n", " ")
                else:
                    r["words"] += len(re.findall(r"[A-Za-z0-9][\w.%-]*|[一-鿿]", t))
                need = 0.0
                fam = fonts["major"] if ph and dk.ph_type(sh) in dk.TITLE_T else fonts["minor"]
                for p in sh.text_frame.paragraphs:
                    sz = [q.font.size.pt for q in p.runs if q.font.size]
                    base = max(sz) if sz else (dk.inherited_size(s.slide_layout, sh.placeholder_format.idx, dk.ph_type(sh), p.level, 18) if ph else 18.0)
                    for q in p.runs:
                        if q.font.name and q.font.name not in (fonts["major"], fonts["minor"]) and not q.font.name.startswith("+"):
                            r["off_theme_fonts"].append(q.font.name)
                        v = q.font.size.pt if q.font.size else base
                        if q.text.strip():
                            r["min_font"] = v if r["min_font"] is None else min(r["min_font"], v)
                    tx = "".join(q.text for q in p.runs)
                    ind = 18 * (p.level + 1) if ph and dk.ph_type(sh) in dk.BODY_T else 0
                    if tx.strip():
                        need += dk.wrap_count(tx, base, max(20, sh.width / 12700 - 14 - ind), False, fam) * base * 1.2
                if need > sh.height / 12700 * 1.10 + 6:
                    r["overflow"].append("%s: needs ~%.0f pt, has %.0f pt" % (sh.name, need, sh.height / 12700))
            if not foot and sh.width > 60000 and sh.height > 60000 and "onnector" not in sh.name and sh.shape_type != 9:
                boxes.append((sh.name, sh.left, sh.top, sh.left + sh.width, sh.top + sh.height, sh))
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                ox, oy = min(a[3], b[3]) - max(a[1], b[1]), min(a[4], b[4]) - max(a[2], b[2])
                if ox > 40000 and oy > 40000:
                    amin = min((a[3] - a[1]) * (a[4] - a[2]), (b[3] - b[1]) * (b[4] - b[2]))
                    if ox * oy > .08 * amin:
                        r["overlaps"].append("%s x %s" % (a[0], b[0]))
        r["off_theme_fonts"] = sorted(set(r["off_theme_fonts"]))
        rep.append(r)
    return rep, prs


def collect_text(dk, prs, skip_footers=True):
    out = []
    for n, s in enumerate(prs.slides, 1):
        for sh in s.shapes:
            if skip_footers and sh.is_placeholder and dk.ph_type(sh) in dk.FOOT_T:
                continue
            for w, t in dk.shape_texts(sh):
                out.append((n, t))
    return out


def preservation(dk, start, edit_log=None, mode="adapt"):
    """What survived from the starting deck: paragraphs, table cells, chart data, images, notes."""
    import hashlib
    A, B = dk.Presentation(start), dk.Presentation(PPTX)
    nm = lambda t: re.sub(r"\s+", " ", t.replace("\v", " ")).strip()
    ta = [(n, nm(t)) for n, t in collect_text(dk, A)]
    blob = {nm(t) for _, t in collect_text(dk, B)}
    joined = " ".join(nm(t) for _, t in collect_text(dk, B))
    lost = [(n, t) for n, t in ta if t not in blob and t not in joined]

    def media(p):
        c, i, nt = [], [], []
        for s in p.slides:
            def rec(shapes):
                for sh in shapes:
                    if sh.shape_type == 6:
                        rec(sh.shapes)
                    elif getattr(sh, "has_chart", False) and sh.has_chart:
                        v = dk.chart_values(sh)
                        c.append(json.dumps([v["type"].replace("LINE_MARKERS", "LINE"), v["categories"], v["series"], v.get("xy")], ensure_ascii=False, default=str))
                    elif hasattr(sh, "image"):
                        i.append(hashlib.sha256(sh.image.blob).hexdigest())
            rec(s.shapes)
            nt.append(nm(dk.notes_text(s)))
        return c, i, nt
    ca, ia, na = media(A)
    cb, ib, nb = media(B)
    hb = {}
    for k, s in enumerate(B.slides, 1):
        hb.setdefault(dk.deep_hash(s), k)
    same = [[n, hb[dk.deep_hash(s)]] for n, s in enumerate(A.slides, 1) if dk.deep_hash(s) in hb]
    def pics(p):
        out = []
        for n, s in enumerate(p.slides, 1):
            def rec(shapes):
                for sh in shapes:
                    if sh.shape_type == 6:
                        rec(sh.shapes)
                    elif hasattr(sh, "image"):
                        cp = (sh.crop_left, sh.crop_right, sh.crop_top, sh.crop_bottom)
                        iw, ih = sh.image.size
                        nat = iw * (1 - cp[0] - cp[1]) / max(1e-9, ih * (1 - cp[2] - cp[3]))
                        out.append({"slide": n, "sha256": hashlib.sha256(sh.image.blob).hexdigest()[:16], "alt": sh._element.find(".//" + dk.qn("p:cNvPr")).get("descr") or "", "distortion": round(abs((sh.width / sh.height) / nat - 1), 4)})
            rec(s.shapes)
        return out

    def tabs(p):
        return [{"slide": n, "cells": [[c.text for c in r.cells] for r in sh.table.rows]} for n, s in enumerate(p.slides, 1) for sh in s.shapes if getattr(sh, "has_table", False) and sh.has_table]

    def chs(p):
        return [{"slide": n, "name": sh.name, **{k: v for k, v in dk.chart_values(sh).items()}} for n, s in enumerate(p.slides, 1) for sh in s.shapes if getattr(sh, "has_chart", False) and sh.has_chart]
    pa, pb = pics(A), pics(B)
    alt_lost = [q for q in pa if q["alt"] and not any(r["sha256"] == q["sha256"] and r["alt"] == q["alt"] for r in pb)]
    stretched = [q for q in pb if q["distortion"] > .02]
    tA, tB = tabs(A), tabs(B)
    tab_lost = [t["slide"] for t in tA if not any(t["cells"] == u["cells"] for u in tB)]
    la, lb = sorted(x for s in A.slides for x in dk.links(s)), sorted(x for s in B.slides for x in dk.links(s))
    lost_links = list(la)
    for x in lb:
        if x in lost_links:
            lost_links.remove(x)
    hid = lambda p: [n for n, s in enumerate(p.slides, 1) if dk.is_hidden(s)]
    grp = lambda p: sum(dk.count_groups(s) for s in p.slides)
    return {"start_slides": len(A.slides), "final_slides": len(B.slides), "text_items_in_start": len(ta), "text_items_not_verbatim_in_final": [{"slide": n, "text": t[:200]} for n, t in lost][:40],
            "charts_in_start": len(ca), "charts_data_identical": sum(1 for x in ca if x in cb), "images_in_start": len(ia), "images_byte_identical": sum(1 for x in ia if x in ib),
            "notes_in_start": sum(1 for x in na if x), "notes_preserved": sum(1 for x in na if x and x in nb),
            "alt_text_lost": alt_lost, "pictures_stretched": stretched, "pictures_before": pa, "pictures_after": pb, "tables_in_start": len(tA), "tables_cell_identical": len(tA) - len(tab_lost), "tables_changed_on_slides": tab_lost,
            "charts_before": chs(A), "charts_after": chs(B), "hyperlinks_in_start": len(la), "hyperlinks_lost": lost_links, "hidden_slides_start": hid(A), "hidden_slides_final": hid(B), "groups_in_start": grp(A), "groups_in_final": grp(B),
            "slides_xml_identical": [{"start": a, "final": b} for a, b in same]}


def protected_slides(n):
    """Slide numbers the work order asks to leave alone."""
    out = set()

    def walk(o, flag):
        if isinstance(o, dict):
            for k, v in o.items():
                kk = re.sub(r"[^a-z]", "", str(k).lower())
                walk(v, any(w in kk for w in ("protect", "unchanged", "untouched", "donotchange", "keepidentical", "frozen", "mustnotchange")))
        elif isinstance(o, list):
            for v in o:
                walk(v, flag)
        elif flag and isinstance(o, int) and not isinstance(o, bool) and 1 <= o <= n:
            out.add(o)
        elif flag and isinstance(o, str):
            for a, b in re.findall(r"\b(\d+)\s*[-\u2013]\s*(\d+)\b", o):
                if int(b) <= n:
                    out.update(range(int(a), int(b) + 1))
            for a in re.findall(r"(?i)slides?\s+(\d+)", o):
                if int(a) <= n:
                    out.add(int(a))
    walk(workorder(), False)
    return sorted(out)


def finish(d, warn, log, mode, master_before, tpl, t0, start=None, edit_log=None):
    dk = need_pptx()
    problems, cmap, untraced, unsourced = [], [], [], []
    rep, prs = audit(dk, PPTX)
    slides = d.get("slides") or []
    # content map
    for n, s in enumerate(slides, 1):
        src = resolve_src(s.get("src"), problems, "slide %d" % n)
        items = []
        texts = []
        for key in ("bullets", "left", "right"):
            v = s.get(key)
            if isinstance(v, dict):
                v = v.get("bullets") or v.get("items")
            for it in dk.norm_items(v):
                isrc = it["src"] or s.get("src")
                r = resolve_src(it["src"], problems, "slide %d" % n) if it["src"] else src
                r = [dict(x) for x in r]
                for x in r:
                    if x.get("text"):
                        x["quote"] = best_quote(it["text"], x.pop("text"))
                items.append({"text": dk.plain(it["text"]), "source": r})
                miss = trace_numbers(dk.plain(it["text"]), isrc) if isrc else ([] if mode != "build" else ks.numbers(dk.plain(it["text"])))
                if miss and mode == "build":
                    untraced.append({"slide": n, "text": dk.plain(it["text"])[:90], "numbers": [m for m in miss if m not in ks.SMALL_INT]})
        for key in ("title", "takeaway"):
            if s.get(key):
                miss = trace_numbers(dk.plain(s[key]), all_src(s))
                if miss and mode == "build":
                    untraced.append({"slide": n, "text": dk.plain(s[key])[:90], "numbers": miss})
        for st in s.get("stats") or []:
            t = "%s %s" % (st.get("value", ""), st.get("label", ""))
            isrc = st.get("src") or s.get("src")
            items.append({"text": dk.plain(t), "source": ks.tidy(resolve_src(isrc, problems, "slide %d" % n), t)})
            miss = trace_numbers(dk.plain(t), isrc) if isrc else ks.numbers(t)
            if miss and mode == "build":
                untraced.append({"slide": n, "text": t[:90], "numbers": miss})
        vis = visual_of(s)
        vobj = None
        if vis:
            v = s[vis]
            vsrc = (v.get("src") if isinstance(v, dict) else None) or s.get("src")
            vobj = {"type": vis, "caption": v.get("caption") if isinstance(v, dict) else None, "source": ks.tidy(resolve_src(vsrc, problems, "slide %d visual" % n), str((v.get("caption") if isinstance(v, dict) else "") or s.get("title", "")))}
            if isinstance(v, dict) and v.get("data"):
                vobj["data_file"] = v["data"]
                vobj["mapping"] = {k: v[k] for k in ("x", "y", "group", "where", "columns") if v.get(k)}
            if vis == "table" and mode == "build" and not v.get("data"):
                cells = " ; ".join(dk.plain(str(c)) for row in v.get("rows", []) for c in row)
                miss = trace_numbers(cells, vsrc) if vsrc else ks.numbers(cells)
                if miss:
                    untraced.append({"slide": n, "text": "table cells", "numbers": miss})
            if vis == "chart" and mode == "build" and v.get("series"):
                vals = " ; ".join(str(x) for sr in (v["series"] if isinstance(v["series"], list) else [{"values": z} for z in v["series"].values()]) for x in sr["values"])
                miss = trace_numbers(vals, vsrc) if vsrc else ks.numbers(vals)
                if miss:
                    untraced.append({"slide": n, "text": "chart values", "numbers": miss})
        if mode == "build" and not src and s.get("kind") not in ("title", "section") and not any(i["source"] for i in items):
            unsourced.append(n)
        src = [dict(x) for x in src]
        for x in src:
            if x.get("text"):
                x["quote"] = best_quote(dk.plain(s["title"]), x.pop("text"))
        cmap.append({"slide": n, "role": s.get("role") or s.get("kind"), "claim": dk.plain(s.get("title", "")), "layout": rep[n - 1]["layout"] if n <= len(rep) else None,
                     "minutes": s.get("minutes"), "from_slide": s.get("from_slide"), "evidence_strength": s.get("evidence") or s.get("evidence_strength"),
                     "source": src, "items": items, "visual": vobj, "takeaway": s.get("takeaway"), "notes_present": bool(s.get("notes"))})
    absent = []
    if mode in ("adapt", "edit"):
        norm_ = lambda t: re.sub(r"\W+", "", t.lower())
        sf_ = start or starting_file()
        origin = []
        try:
            for k_, sl_ in enumerate(dk.Presentation(sf_).slides, 1) if sf_ else []:
                origin.append((k_, {norm_(t_) for sh_ in sl_.shapes for _, t_ in dk.shape_texts(sh_)}))
        except Exception:
            origin = []

        def supported(t_):
            hit_ = [k_ for k_, ts_ in origin if norm_(t_) and norm_(t_) in ts_]
            out_ = []
            if hit_:
                out_.append({"id": "deck", "file": os.path.basename(str(sf_)), "locator": "original slide %s" % hit_[0], "quote": t_[:200], "match": "verbatim in the supplied deck (carried over, not re-derived)"})
            m_ = ks.auto_match(t_)
            if hit_ and not m_:
                out_[0]["paper_support"] = "no passage with the same numbers and terms was found in the supplied sources; kept as the deck author's statement"
            return out_ + m_
        have_map = {c["slide"] for c in cmap if c.get("slide")}
        for n, sl in enumerate(prs.slides, 1):
            items = []
            for sh in sl.shapes:
                if sh.is_placeholder and dk.ph_type(sh) in dk.FOOT_T:
                    continue
                for w_, t_ in dk.shape_texts(sh):
                    miss = ks.numbers_absent(t_)
                    if miss and not w_.startswith("r"):
                        absent.append({"slide": n, "text": t_[:120], "numbers": miss[:6]})
                    if w_.startswith("p") and len(t_) > 18:
                        items.append({"text": t_[:200], "source": supported(t_)})
            row = next((c for c in cmap if c.get("slide") == n and c.get("type") != "edit"), None)
            if row is None:
                row = {"slide": n, "role": "slide", "claim": rep[n - 1]["title"], "layout": rep[n - 1]["layout"], "source": [], "items": [], "visual": None, "notes_present": rep[n - 1]["notes_chars"] > 0}
                cmap.append(row)
            if not any(i.get("source") for i in row.get("items") or []):
                row["items"] = items
            if not row.get("source"):
                row["source"] = supported(rep[n - 1]["title"])
            if not row.get("visual"):
                vis_ = natives_of(dk, sl)
                row["visual"] = vis_[0] if len(vis_) == 1 else (vis_ or None)
        rm_ = requested_minutes()
        if rm_ and slides and not any(x.get("minutes") for x in slides):
            vis_ = [k for k, q in enumerate(prs.slides) if not dk.is_hidden(q)]
            wt = {k: (0.5 if k == 0 else 1 + min(1.0, rep[k]["words"] / 90.0) + .3 * bool(rep[k]["native"]["charts"] + rep[k]["native"]["tables"])) for k in vis_}
            tot_ = sum(wt.values())
            for k, x in enumerate(slides):
                x["minutes"] = round(rm_ * wt[k] / tot_, 1) if k in wt else 0
            for c in cmap:
                if c.get("type") != "edit" and c.get("slide") and c["slide"] <= len(slides):
                    c["minutes"] = slides[c["slide"] - 1].get("minutes")
            warn.append("per-slide minutes were distributed by the engine from the requested total (by text and visuals); adjust if needed")
    if mode == "edit":
        for x in edit_log:
            o = x["op"] if isinstance(x["op"], dict) else {"op": x["op"]}
            cmap.append({"type": "edit", "operation": o.get("op"), "slide": o.get("slide") or o.get("after"), "detail": {k: v for k, v in o.items() if k not in ("op", "src")},
                         "result": x["result"], "source": ks.tidy(resolve_src(o.get("src"), problems, "edit"), str(o.get("new") or o.get("text") or ""))})
    pdf, ver = render_pdf()
    pngs, sheet = previews(pdf)
    pngs += hidden_previews(dk, prs, ver)
    checks = []
    q = requested_slides()
    checks.append(check("slide_count", q is None or q == len(rep), "%d slides%s" % (len(rep), "" if q is None else "; work order asks %d" % q), "slides in saved file"))
    after = dk.master_hashes(prs)
    same = master_before == after
    checks.append(check("template_inheritance", same and all(r["layout"] for r in rep), "master, %d layouts and theme byte-identical (canonical XML) to %s; every slide is bound to one of its layouts: %s" % (
        sum(k.startswith("layout") for k in after), os.path.basename(tpl or "default"), sorted({r["layout"] for r in rep})) if same else "master/layout/theme differs: %s" % [k for k in set(master_before) ^ set(after)] , "canonical-XML SHA-256 of master/layout/theme parts, before vs after"))
    hits = {k: ["slide %d: %s" % (r["slide"], "; ".join(map(str, r[k][:3]))) for r in rep if r[k]] for k in ("empty_placeholders", "out_of_bounds", "overlaps", "overflow", "off_theme_fonts")}
    for k, label in (("empty_placeholders", "no_empty_placeholders"), ("out_of_bounds", "inside_slide_bounds"), ("overlaps", "no_shape_overlap"), ("overflow", "no_text_overflow"), ("off_theme_fonts", "theme_fonts_only")):
        checks.append(check(label, not hits[k], "none found on %d slides" % len(rep) if not hits[k] else " | ".join(hits[k][:6]), "geometry and font metrics of the saved file"))
    mf = min([r["min_font"] for r in rep if r["min_font"]] or [0])
    checks.append(check("minimum_font", mf >= 12 - .01, "smallest slide text %.1f pt (captions and source lines); table cells are sized separately: %s" % (mf, sorted({t["font_pt"] for l in log for t in (l.get("tables") or ([l["table"]] if l.get("table") else []))}) or "no generated tables"), "run-level or inherited size"))
    titles = [r["title"] for r in rep]
    if pdf:
        n_pages = 0
        try:
            out = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True, timeout=30).stdout
            n_pages = int(re.search(r"Pages:\s+(\d+)", out).group(1))
            txt = re.sub(r"\s+", "", subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True, timeout=60).stdout)
            hidden = {k for k, q in enumerate(prs.slides, 1) if dk.is_hidden(q)}
            lost = [t for k, t in enumerate(titles, 1) if t and k not in hidden and not all(re.sub(r"\s+", "", w) in txt for w in t.split())]
            fl = subprocess.run(["pdffonts", pdf], capture_output=True, text=True, timeout=30).stdout.splitlines()[2:]
            fonts_used = sorted({x.split()[0].split("+")[-1] for x in fl if x.split()})
        except Exception as exc:
            lost, fonts_used = [str(exc)], []
        checks.append(check("pdf_export", n_pages in (len(rep), len(rep) - len(hidden)) and not lost, "%d pages for %d slides%s; every visible title present as text; fonts in PDF: %s" % (n_pages, len(rep), " (%d hidden, not exported)" % len(hidden) if hidden else "", fonts_used) if not lost else "titles missing in PDF: %s" % lost[:4], "pdfinfo/pdftotext/pdffonts on the real export (%s)" % ver))
        want = {dk.theme_fonts(prs)["major"], dk.theme_fonts(prs)["minor"]}
        sub = [f for f in want if f and not f.startswith("+") and not any(f.replace(" ", "").lower()[:8] in u.lower() for u in fonts_used)]
        if sub:
            warn.append("theme font(s) %s not installed in this renderer; PDF uses a substitute (PPTX keeps the theme font)" % sub)
    else:
        checks.append(check("pdf_export", False, "not exported: %s" % ver, "LibreOffice"))
    blank = []
    try:
        from PIL import Image
        for k, p in enumerate(pngs, 1):
            im = Image.open(p).convert("L").resize((160, 90))
            if len(set(im.tobytes())) < 4:
                blank.append(k)
    except Exception:
        pass
    checks.append(check("rendered_pages_not_blank", bool(pngs) and not blank, "%d page images inspected; blank: %s" % (len(pngs), blank or "none"), "pixel statistics of rendered pages"))
    nn = [r["slide"] for r in rep if r["notes_chars"] < 20]
    checks.append(check("speaker_notes", not nn, "notes on all %d slides" % len(rep) if not nn else "missing or very short on slides %s" % nn, "notes part text"))
    rm = requested_minutes()
    tot = sum(float(s.get("minutes") or 0) for s in slides)
    if slides and tot:
        checks.append(check("time_plan", not rm or abs(tot - rm) <= .15 * rm + .5, "planned %.1f min%s" % (tot, "" if not rm else " of %.0f" % rm), "sum of per-slide minutes"))
    try:   # decimals the order prescribes ("one decimal for percentages")
        ml_ = " ".join(ks.must_lines()).lower()
        dm_ = re.search(r"\b(one|two|three|1|2|3)\s+decimals?\s+(?:place\s+)?(?:for|in|on)\s+(?:all\s+)?percent", ml_)
        if dm_:
            want_ = {"one": 1, "two": 2, "three": 3}.get(dm_.group(1), None) or int(dm_.group(1))
            bad_, orig_ = [], set()
            PCT_ = r"(?<![\d.])(\d+(?:\.(\d+))?)\s?%"
            if mode in ("edit", "adapt"):   # values carried over from the starting deck keep their form; only new ones are checked
                try:
                    sf_ = start or starting_file()
                    if sf_:
                        orig_ = {m_.group(1) for _, t_ in collect_text(dk, dk.Presentation(sf_)) for m_ in re.finditer(PCT_, t_)}
                except Exception:
                    orig_ = set()
            for n_, t_ in collect_text(dk, prs):
                for m_ in re.finditer(PCT_, t_):
                    if m_.group(1) not in orig_ and len(m_.group(2) or "") != want_:
                        bad_.append("slide %d: %s" % (n_, m_.group(0)))
            if True:
                checks.append(check("number_format", not bad_, "every percentage has %d decimal(s) as the order asks" % want_ if not bad_ else "percentages not at %d decimal(s): %s" % (want_, "; ".join(dict.fromkeys(bad_))[:400]), "percent tokens on all slides vs the order's decimal rule"))
                if bad_:
                    say("ATTENTION number_format: the order asks for %d decimal(s) in percentages; fix %s (or say in an exception why a carried-over value keeps its form)" % (want_, "; ".join(list(dict.fromkeys(bad_))[:6])))
    except Exception:
        pass
    if mode == "build":
        checks.append(check("numbers_traceable", not untraced, "every number on slides occurs in its cited source" if not untraced else "not verbatim in cited source (fix, or state the derivation): %s" % json.dumps(untraced[:8], ensure_ascii=False), "numeric tokens of slide text searched in cited passages/table rows"))
        checks.append(check("source_coverage", not unsourced and not problems, "all %d content slides carry resolvable sources" % sum(1 for s in slides if s.get("kind") not in ("title", "section")) if not unsourced and not problems else "unsourced slides %s; problems %s" % (unsourced, problems[:5]), "source ids looked up in indexed input"))
        cv = chart_check(dk, prs, slides, log)
        if cv:
            checks.append(cv)
    pres = None
    if start:
        pres = preservation(dk, start, edit_log, mode)
        if mode == "adapt":
            ok = not pres["text_items_not_verbatim_in_final"] and pres["charts_data_identical"] == pres["charts_in_start"] and pres["images_byte_identical"] == pres["images_in_start"] and pres["notes_preserved"] == pres["notes_in_start"] and not pres["hyperlinks_lost"] and len(pres["hidden_slides_start"]) == len(pres["hidden_slides_final"]) and pres["groups_in_final"] >= pres["groups_in_start"] and not pres["alt_text_lost"] and not pres["pictures_stretched"] and not pres["tables_changed_on_slides"]
            checks.append(check("content_preservation", ok, "text items lost: %d of %d; chart data identical %d/%d; images byte-identical %d/%d; notes preserved %d/%d; hyperlinks lost %d of %d; hidden slides %s -> %s; editable groups %d -> %d; tables cell-identical %d/%d; alt text lost %d; pictures stretched %d" % (
                len(pres["text_items_not_verbatim_in_final"]), pres["text_items_in_start"], pres["charts_data_identical"], pres["charts_in_start"], pres["images_byte_identical"], pres["images_in_start"], pres["notes_preserved"], pres["notes_in_start"], len(pres["hyperlinks_lost"]), pres["hyperlinks_in_start"], pres["hidden_slides_start"], pres["hidden_slides_final"], pres["groups_in_start"], pres["groups_in_final"], pres["tables_cell_identical"], pres["tables_in_start"], len(pres["alt_text_lost"]), len(pres["pictures_stretched"])), "independent re-read of both PPTX files"))
        else:
            aimed = set()
            glob_rep = False
            for x in edit_log or []:
                o = x["op"] if isinstance(x["op"], dict) else {}
                if o.get("op") in ("add_slide", "insert_slide", "move_slide", "note"):
                    continue
                if str(o.get("slide", "all")) in ("all", "None") and o.get("op") in ("replace_text", "replace"):
                    glob_rep = True
                elif str(o.get("slide", "")).isdigit():
                    aimed.add(int(o["slide"]))
            same = {x["start"] for x in pres["slides_xml_identical"]}
            others = [n for n in range(1, pres["start_slides"] + 1) if n not in aimed]
            broken = [n for n in others if n not in same]
            prot = protected_slides(pres["start_slides"])
            pbad = [n for n in prot if n not in same]
            checks.append(check("untouched_slides_identical", not broken and not pbad, "slides not named in any operation: %s; identical after editing (slide XML, notes, chart data, media): %s%s%s%s" % (
                others, sorted(n for n in others if n in same), "; CHANGED WITHOUT BEING NAMED: %s%s" % (broken, " (global replace_text)" if glob_rep else "") if broken else "",
                "; protected by work order: %s" % prot if prot else "", "; PROTECTED SLIDES CHANGED: %s" % pbad if pbad else ""), "deep hash per slide: canonical XML + notes + chart parts + workbooks + media"))
    exceptions = []
    for x in absent[:20]:
        exceptions.append({"item": "slide %d: number not found anywhere in the supplied material" % x["slide"], "state": "lead to check (deck vs material)", "detail": "%s in '%s'" % (x["numbers"], x["text"])})
    for u in d.get("unresolved") or []:
        u = dict(u) if isinstance(u, dict) else {"item": str(u)}
        u["source"] = ks.tidy(resolve_src(u.pop("src", None), problems, "unresolved"), "%s %s" % (u.get("item", ""), u.get("detail", "")))
        u.setdefault("state", "unresolved")
        exceptions.append(u)
    try:
        exceptions += ks.auto_exceptions(exceptions)
    except Exception:
        pass
    exceptions += ks.unreadable_inputs()
    for c in checks:
        if c["result"] != "pass":
            exceptions.append({"item": c["check"], "state": "check needs attention", "detail": c["detail"][:600]})
    for l in log:
        for p_ in l.get("problems", []):
            exceptions.append({"item": "slide %d layout" % l["n"], "state": "needs attention", "detail": p_})
        for f in l.get("font_changes", []):
            exceptions.append({"item": "slide %d font size" % l["n"], "state": "adjusted to fit", "detail": f})
    for w in warn:
        exceptions.append({"item": "note", "state": "disclosed", "detail": w})
    if edit_log:
        exceptions += [{"item": json.dumps(x["op"], ensure_ascii=False)[:200], "state": x["result"]} for x in edit_log if str(x["result"]).startswith("failed")]
    qa_out = []
    for x in d.get("qa") or []:
        x = dict(x) if isinstance(x, dict) else {"q": str(x)}
        isrc = x.get("src")
        x["source"] = ks.tidy(resolve_src(isrc, problems, "qa"), x.get("q", "") + " " + x.get("a", ""))
        miss = trace_numbers(str(x.get("a", "")), isrc) if isrc else []
        if miss:
            x["numbers_not_in_cited_source"] = miss
        qa_out.append(x)
    changes = {"mode": mode, "starting_point": inv(start) if start else inv(tpl) if tpl else None, "preservation": pres, "operations": edit_log,
               "slide_map": [{"final": c.get("slide"), "from": c.get("from_slide")} for c in cmap if c.get("from_slide")], "rollback": "the supplied input files are never modified"}
    jsave(os.path.join(OUT, "change_record.json"), changes)
    with open(os.path.join(OUT, "claim_source_map.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["slide", "role", "evidence_strength", "claim_or_item", "source_id", "file", "locator", "quote"])
        for c in cmap:
            if c.get("type") == "edit":
                for s in (c["source"] or [{}]):
                    w.writerow([c["slide"], "edit:" + str(c["operation"]), "", json.dumps(c["detail"], ensure_ascii=False)[:300], s.get("id", ""), s.get("file", ""), s.get("locator", ""), s.get("quote", s.get("text", ""))])
                continue
            for s in (c["source"] or [{}]):
                w.writerow([c["slide"], c["role"], c.get("evidence_strength") or "", c["claim"], s.get("id", ""), s.get("file", ""), s.get("locator", ""), s.get("quote", "")])
            for it in c["items"]:
                for s in (it["source"] or [{}]):
                    w.writerow([c["slide"], "item", "", it["text"], s.get("id", ""), s.get("file", ""), s.get("locator", ""), s.get("quote", "")])
    if slides:
        with open(os.path.join(OUT, "speaker_plan.md"), "w", encoding="utf-8") as f:
            f.write("# %s\n\nAudience: %s  \nGoal: %s  \nStoryline: %s  \nPlanned time: %s min\n\n" % (dk.plain(d.get("title", "")), d.get("audience", "-"), d.get("goal", "-"), d.get("storyline", "-"), tot or "-"))
            if d.get("omitted"):
                f.write("## Left out on purpose\n\n" + "".join("- %s: %s\n" % (o.get("item", ""), o.get("reason", "")) if isinstance(o, dict) else "- %s\n" % o for o in d["omitted"]) + "\n")
            for n, s in enumerate(slides, 1):
                f.write("## %d. %s (%s%s)\n\nSources: %s\n\n%s\n\n" % (n, dk.plain(s.get("title", "")), s.get("role", ""), ", %s min" % s["minutes"] if s.get("minutes") else "", s.get("src") or s.get("cite") or "-", dk.notes_plain(s.get("notes", "") if not isinstance(s.get("notes"), list) else "\n".join(map(str, s["notes"])))))
            if d.get("qa"):
                f.write("## Prepared questions\n\n")
                for x in d["qa"]:
                    f.write("- **%s** %s (sources: %s; slide %s)\n" % (x.get("q", ""), x.get("a", ""), x.get("src", "-"), x.get("slide", "-")))
    if pres and mode == "adapt":
        res_pres = {k: v for k, v in pres.items() if k not in ("charts_before", "charts_after", "pictures_before", "pictures_after")}
    blocking = [c for c in checks if c["result"] != "pass" and c["check"] in ("slide_count", "pdf_export", "rendered_pages_not_blank", "content_preservation", "untouched_slides_identical")]
    failed_ops = [x for x in (edit_log or []) if str(x["result"]).startswith("failed")]
    status = "completed" if not blocking and not problems and not failed_ops else "partial"
    os.makedirs(os.path.join(OUT, "rebuild"), exist_ok=True)
    for s in ("deckkit.py", "dk_pptx.py", "kit_sources.py", "kit_table.py"):
        try:
            shutil.copy(os.path.join(HERE, s), os.path.join(OUT, "rebuild", s))
        except OSError:
            pass
    cmd = {"build": "build --spec ../deck_spec.json", "adapt": "adapt", "edit": "edit ../edits.json"}[mode]
    if mode == "edit" and os.path.exists(os.path.join(WORK, "edits.json")):
        shutil.copy(os.path.join(WORK, "edits.json"), os.path.join(OUT, "edits.json"))
    with open(os.path.join(OUT, "rebuild", "rebuild.sh"), "w", encoding="utf-8") as f:
        f.write("""#!/bin/sh
# sh rebuild.sh [INPUT_FOLDER]   rebuilds the delivered deck into ../_rebuilt
cd "$(dirname "$0")" || exit 1
mkdir -p ../_work ../_rebuilt && cp -f ../edits.json ../overrides.json ../_work/ 2>/dev/null
KIT_INPUT="${1:-/input}" KIT_WORK="$PWD/../_work" KIT_OUTPUT="$PWD/../_rebuilt" python3 deckkit.py %s
""" % cmd)
    if mode == "adapt" and os.path.exists(os.path.join(WORK, "overrides.json")):
        shutil.copy(os.path.join(WORK, "overrides.json"), os.path.join(OUT, "overrides.json"))
    res = {"status": status, "editable_source": dict(inv(PPTX) or {}, format="native PPTX: live text, native tables/charts, glued connectors", template=inv(tpl) if tpl else None,
                                                      specification=os.path.join(OUT, "deck_spec.json") if slides else os.path.join(OUT, "edits.json"),
                                                      layouts_used=sorted({r["layout"] for r in rep}), rebuild_command="sh /app/output/rebuild/rebuild.sh /input   (first argument = case input folder; writes ../_rebuilt)"),
           "export_artifact": {"pdf": inv(pdf) if pdf else None, "slide_previews": pngs, "contact_sheet": sheet, "renderer": ver, "theme_fonts": {k: v for k, v in dk.theme_fonts(prs).items() if k != "colors"}},
           "content_map": cmap, "compliance_checks": checks, "exceptions": exceptions, "change_record": changes,
           "narrative": {k: d.get(k) for k in ("title", "audience", "goal", "storyline", "language") if d.get(k)}, "time_plan": [{"slide": n, "minutes": s.get("minutes")} for n, s in enumerate(slides, 1)],
           "qa_preparation": qa_out, "design_decisions": d.get("decisions", []), "omitted_from_source": d.get("omitted", []),
           "slide_audit": rep,
           "provenance": {"engine": "deckkit %s" % VERSION, "inputs": [{"file": rel(p), "sha256": sha(p)} for p in walk_inputs()], "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "build_seconds": round(time.time() - t0, 1)}}
    write_result(res)
    say("%s status=%s  %d slides  %.1fs  renderer=%s" % (mode.upper(), status, len(rep), time.time() - t0, ver))
    tf_ = os.path.join(WORK, ".told")
    try:
        told = jload(tf_)
    except (OSError, ValueError):
        told = {}
    for c in checks:
        if c["result"] != "pass":
            told[c["check"]] = told.get(c["check"], 0) + 1
            if told[c["check"]] > 3:
                say("(already disclosed in exceptions - leave it and go on: %s)" % c["check"])
            else:
                say("ATTENTION %s: %s" % (c["check"], c["detail"][:460]))
    jsave(tf_, told)
    for x in absent[:10]:
        say("LEAD slide %d: %s not found in the material: %s" % (x["slide"], x["numbers"], x["text"][:100]))
    for l in log:
        for p_ in l.get("problems", []):
            say("SLIDE %d: %s" % (l["n"], p_))
    for w in warn[:8]:
        say("NOTE", w)
    for p_ in problems[:8]:
        say("SOURCE", p_)
    cnt_f = os.path.join(WORK, ".builds")
    n_build = (int(open(cnt_f).read()) if os.path.exists(cnt_f) else 0) + 1
    open(cnt_f, "w").write(str(n_build))
    say("build %d, %.1f min since brief. Deliverables and result.json are complete and saved." % (n_build, ks.elapsed()))
    if n_build >= 5 or ks.elapsed() > 7.5:
        say("STOP RULE: remaining items are already disclosed in exceptions. Finish any missing requested item with one more run, then verify and stop.")
    if ks.elapsed() <= 7.5:
      say("NEXT: run review (claims vs cited sentences, requirement list), fix what it shows, then look at the contact sheet once, verify, stop.")
    say("%d/%d checks pass. result.json saved. Look at %s with read_image once." % (sum(c["result"] == "pass" for c in checks), len(checks), sheet))


def all_src(s):
    out = []
    def add(x):
        if x:
            out.extend(x if isinstance(x, list) else [x])
    add(s.get("src"))
    for key in ("bullets", "left", "right", "stats"):
        v = s.get(key)
        if isinstance(v, dict):
            v = v.get("bullets") or v.get("items")
        for it in v or []:
            if isinstance(it, dict):
                add(it.get("src"))
    for key in ("chart", "table", "image"):
        if isinstance(s.get(key), dict):
            add(s[key].get("src"))
            add(s[key].get("data"))
    return out


def chart_check(dk, prs, slides, log):
    """Read native chart caches back from the saved file and compare with the source table."""
    n_ok, bad = 0, []
    sl = list(prs.slides)
    for n, s in enumerate(slides, 1):
        c = s.get("chart")
        if not c or not c.get("data") or c.get("type") == "scatter":
            continue
        cols, rows = read_table(c["data"])
        sh = next((x for x in sl[n - 1].shapes if getattr(x, "has_chart", False) and x.has_chart), None)
        if sh is None:
            bad.append("slide %d: chart missing" % n)
            continue
        v = dk.chart_values(sh)
        ys = c["y"] if isinstance(c["y"], list) else [c["y"]]
        for name, vals in v["series"]:
            for cat, val in zip(v["categories"], vals):
                hit = [r for r in rows if str(r[c["x"]]) == cat and (not c.get("group") or str(r[c["group"]]) == name) and all(str(r.get(k, "")) in [str(q) for q in (w if isinstance(w, list) else [w])] for k, w in (c.get("where") or {}).items())]
                col = name if not c.get("group") and name in ys else ys[0]
                truth = [ks.kit_table.num(r[col]) for r in hit]
                if val is None and (not truth or truth[0] is None):
                    continue
                if truth and truth[0] is not None and val is not None and abs(truth[0] - val) < 1e-9 * max(1, abs(val)):
                    n_ok += 1
                else:
                    bad.append("slide %d %s/%s: chart %s, table %s" % (n, name, cat, val, truth[:2]))
    if not n_ok and not bad:
        return None
    return check("chart_values_read_back", not bad, "%d native chart points equal the source table cells" % n_ok if not bad else "; ".join(bad[:6]), "chart part read back from saved PPTX, compared with input table")


def cmd_check(a):
    d = jload(os.path.join(OUT, "deck_spec.json")) if os.path.exists(os.path.join(OUT, "deck_spec.json")) else {}
    dk = need_pptx()
    tpl = template_file() or starting_file()
    finish(d, [], [], mode="build" if d else "edit", master_before=dk.master_hashes(dk.Presentation(tpl)) if tpl else {}, tpl=tpl, t0=time.time(), start=starting_file() if not d else None, edit_log=None if d else [])


def cmd_review(a):
    """Claims next to the sentences they cite, plus the requirement list: a semantic self-check for the agent."""
    dk = need_pptx()
    r = jload(os.path.join(OUT, "result.json"))
    prs = dk.Presentation(PPTX)
    lo, hi = 1, len(prs.slides)
    if a.range:
        m = re.match(r"(\d+)(?:-(\d+))?$", a.range)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
    say("# CLAIM | cited sentence. Ask for each: same direction and sign? same strength? right group, unit, n? does the title say what the evidence says? If not, fix text or src.")
    used = 0
    for c in r.get("content_map") or []:
        if c.get("type") == "edit" or not c.get("slide") or not lo <= c["slide"] <= hi:
            continue
        say("== slide %s [%s] %s" % (c["slide"], c.get("role"), c.get("claim")))
        for x in (c.get("source") or [])[:4]:
            say("     %s: %s" % (x.get("id"), (x.get("quote") or x.get("locator", ""))[:240]))
        if c.get("takeaway"):
            say("   takeaway: %s" % c["takeaway"])
        for it in c.get("items") or []:
            q = " || ".join("%s: %s" % (x.get("id"), (x.get("quote") or x.get("locator", ""))[:210]) for x in (it.get("source") or [])[:2])
            line = "   - %s\n        %s" % (it["text"][:170], q or "NO SOURCE")
            used += len(line)
            if used < 9500:
                say(line)
        v = c.get("visual")
        if v:
            say("   visual %s %s" % (v.get("type"), v.get("data_file") or v.get("caption") or ""))
    if used >= 9500:
        say("... shortened; use review %d-%d for the rest" % (hi // 2 + 1, hi))
    if hi == len(prs.slides):
        print("\nNOTES (first 160 characters per slide)")
        for n, s in enumerate(prs.slides, 1):
            print("  %d: %s" % (n, dk.notes_text(s)[:160].replace("\n", " ")))
        blob = " ".join(t for _, t in collect_text(dk, prs)) + " " + " ".join(dk.notes_text(q) for q in prs.slides) + " " + json.dumps([r.get(k) for k in ("exceptions", "design_decisions", "omitted_from_source", "qa_preparation", "narrative")], ensure_ascii=False)
        ks.print_must(blob[:400000])


def cmd_verify(a):
    r = jload(os.path.join(OUT, "result.json"))
    bad = [k for k in contract() if k not in r]
    if r.get("case_id") != case_id():
        bad.append("case_id mismatch")

    def files(o):
        if isinstance(o, dict):
            if isinstance(o.get("path"), str) and o.get("sha256") and o["path"].startswith(OUT):
                yield o["path"], o["sha256"]
            for v in o.values():
                yield from files(v)
        elif isinstance(o, list):
            for v in o:
                yield from files(v)
    n = 0
    for f in ("presentation.pptx", "presentation.pdf"):
        if not os.path.exists(os.path.join(OUT, f)):
            bad.append("missing deliverable " + f)
    if not r.get("content_map") or not r.get("compliance_checks"):
        bad.append("content_map/compliance_checks empty: nothing has been built")
    for f, h in files({k: r.get(k) for k in ("editable_source", "export_artifact")}):
        n += 1
        if not os.path.exists(f):
            bad.append("missing " + f)
        elif sha(f) != h:
            bad.append("hash differs (rerun check): " + f)
    att = [c["check"] for c in (r.get("compliance_checks") or []) if c.get("result") != "pass"]
    if att:
        say("OPEN CHECKS (disclosed in exceptions):", att)
    if not bad and ks.elapsed() > 6.5:
        say("DONE at %.1f min: the delivery is complete and checked. FINAL STEP: reply with one short sentence and end. Do not view the image, open result.json, edit_record.json or REPORT.md, list files or run any command again: everything is written and verified, and every extra call only adds time (the run is cut at minute 15)." % ks.elapsed())
    nrev, fresh = ks.review_state()
    if ks.elapsed() < 6.5 and (nrev == 0 or (nrev < 2 and (not fresh or ks.elapsed() < 4.5))):
        say("NOT DONE YET: %s (%.1f of 15 min used)." % ("run review once - claims against quotes, requirements, possibly missing terms" if nrev == 0 else "content changed since the last review: run review again and close the remaining gaps", ks.elapsed()))
    say("VERIFY", ("OK" if r.get("status") == "completed" else "INCOMPLETE (status %s)" % r.get("status")) if not bad else "PROBLEMS: %s" % bad, "| status=%s | %d files hashed | %d map entries | %d checks | %d exceptions" % (
        r.get("status"), n, len(r.get("content_map") or []), len(r.get("compliance_checks") or []), len(r.get("exceptions") or [])))
    return 1 if bad else 0


def cmd_selftest(a):
    ex = next((p for p in (os.path.join(os.path.dirname(HERE), "examples", "synthetic"), os.path.join(HERE, "examples", "synthetic")) if os.path.isdir(p)), "")
    d = tempfile.mkdtemp(prefix="deckkit_")
    shutil.copytree(os.path.join(ex, "input"), d + "/input")
    os.makedirs(d + "/input/artifacts", exist_ok=True)
    dk = need_pptx()
    dk.Presentation().save(d + "/input/artifacts/target-template.pptx")
    env = dict(os.environ, KIT_INPUT=d + "/input", KIT_WORK=d + "/work", KIT_OUTPUT=d + "/out")
    os.makedirs(d + "/work")
    shutil.copy(os.path.join(ex, "deck.json"), d + "/work/deck.json")
    for c in (["brief"], ["build"], ["verify"]):
        r = subprocess.run([sys.executable, os.path.abspath(__file__)] + c, env=env, capture_output=True, text=True)
        say("$", " ".join(c), "exit", r.returncode, "|", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-600:])
        if r.returncode:
            say(r.stderr[-900:])
            return 1
    rb = subprocess.run(["sh", d + "/out/rebuild/rebuild.sh", d + "/input"], capture_output=True, text=True, env=dict(os.environ))
    okr = rb.returncode == 0 and os.path.exists(d + "/out/_rebuilt/presentation.pptx")
    say("  delivered rebuild.sh rebuilds the deck                    %s" % ("ok" if okr else "FAILED " + (rb.stdout + rb.stderr)[-400:]))
    # negative tests: damage the delivered deck and require the audit to notice
    out = d + "/out/presentation.pptx"
    n = [0, 0]

    def probe(name, fn, key):
        prs = dk.Presentation(out)
        fn(prs)
        q = d + "/damaged.pptx"
        prs.save(q)
        rep, _ = audit(dk, q)
        ok = any(r[key] for r in rep)
        n[0] += bool(ok)
        n[1] += 1
        say("  negative test %-46s %s" % (name, "caught" if ok else "MISSED"))

    def overflow(prs):
        tf = next(s for s in prs.slides[2].placeholders if s.placeholder_format.idx != 0 and s.has_text_frame and s.text_frame.text).text_frame
        tf.text = "very long sentence that will not fit " * 40

    def outside(prs):
        s = prs.slides[2].shapes[1]
        s.left, s.top, s.width, s.height = prs.slide_width - 100000, s.top, 3000000, 1000000

    def empty(prs):
        prs.slides.add_slide(dk.choose_layout(prs, "content"))
    probe("text overflow", overflow, "overflow")
    probe("shape outside the slide", outside, "out_of_bounds")
    probe("placeholder left empty", empty, "empty_placeholders")
    spec = jload(d + "/out/deck_spec.json")
    prs = dk.Presentation(out)
    for s in prs.slides:
        for sh in s.shapes:
            if getattr(sh, "has_chart", False) and sh.has_chart:
                for v in sh.chart._chartSpace.iter(dk.qn("c:val")):
                    pt = next(v.iter(dk.qn("c:v")))
                    pt.text = "999"
                    break
    ks.INPUT = d + "/input"
    c = chart_check(dk, prs, spec["slides"], [])
    n[1] += 1
    n[0] += c is not None and c["result"] != "pass"
    say("  negative test %-46s %s" % ("chart value altered", "caught" if c is not None and c["result"] != "pass" else "MISSED"))
    say("negative tests caught %d of %d" % tuple(n))
    say("selftest output (example only, not a formal result):", d + "/out")
    return 0 if n[0] == n[1] else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("brief")
    p = sub.add_parser("show"); p.add_argument("ids", nargs="+")
    p = sub.add_parser("find"); p.add_argument("words", nargs="+")
    p = sub.add_parser("table"); p.add_argument("file"); p.add_argument("rows", nargs="?")
    p = sub.add_parser("build"); p.add_argument("--spec")
    p = sub.add_parser("adapt"); p.add_argument("overrides", nargs="?")
    p = sub.add_parser("edit"); p.add_argument("ops", nargs="?")
    p = sub.add_parser("slide"); p.add_argument("n", type=int); p.add_argument("--start", action="store_true")
    sub.add_parser("check")
    sub.add_parser("audit")
    p = sub.add_parser("review"); p.add_argument("range", nargs="?")
    sub.add_parser("verify")
    sub.add_parser("selftest")
    a = ap.parse_args()
    fn = {"show": ks.cmd_show, "find": ks.cmd_find, "table": ks.cmd_table, "audit": ks.cmd_audit}.get(a.cmd) or globals()["cmd_" + a.cmd]
    try:
        rc = fn(a)
    except Exception as exc:  # never leave the agent with a stack trace to debug
        import traceback
        tb = traceback.extract_tb(exc.__traceback__)[-1]
        say("CANNOT %s: %s: %s (at %s:%s). Undo or simplify the entry you just wrote and run again; do not read or edit the engine." % (
            a.cmd.upper(), type(exc).__name__, str(exc)[:200], os.path.basename(tb.filename), tb.lineno))
        sys.exit(3)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
