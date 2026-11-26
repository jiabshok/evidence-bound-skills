"""Work-flow commands: start (drafts the spec from the work order), fromtable (result table -> relations), prune, set."""
import json
import os
import re

import kit_sources as ks
from kit_sources import WORK, OUT, jload, jsave, say


def _walk(o, path=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _walk(v, path + (str(k),))
    elif isinstance(o, list):
        yield path, o
        for x in o:
            if isinstance(x, (dict, list)):
                yield from _walk(x, path)
    else:
        yield path, o


def _num(v):
    m = re.search(r"-?\d+(?:\.\d+)?", str(v))
    return float(m.group(0)) if m else None


def order_facts():
    """Canvas, groups and direction that the work order fixes."""
    cv, groups, gkey, text = {}, [], "", ""
    objs = []
    for p in ks.workorders():
        try:
            objs.append(jload(p))
        except Exception:
            text += open(p, errors="replace").read()
    objs.append(ks.get_case())
    for o in objs:
        for path, v in _walk(o):
            k = path[-1].lower() if path else ""
            full = ".".join(path).lower()
            if "contract" in full:
                continue
            if isinstance(v, list):
                if re.search(r"(size|canvas|page)[\w]*_?mm$|^size_mm$", k) and len(v) == 2 and all(_num(x) for x in v):
                    cv["size_mm"] = [_num(x) for x in v]
                elif re.search(r"(size|canvas)[\w]*_?px$", k) and len(v) == 2 and all(_num(x) for x in v):
                    cv["size_px"] = [int(_num(x)) for x in v]
                elif not groups and len(v) >= 2 and all(isinstance(x, str) and len(x) < 60 for x in v) and re.search(r"compartment|group|layer|subsystem|column|stage|lane|level|tier", k):
                    groups, gkey = v, full
            elif v is not None:
                for a, b in (("width_mm", "width_mm"), ("height_mm", "height_mm"), ("width_px", "width_px"), ("height_px", "height_px")):
                    if k == a and _num(v):
                        cv[b] = _num(v)
                if re.search(r"min_?font|minimum_font|font.*min", k) and _num(v):
                    cv["min_font_pt"] = _num(v)
                elif re.search(r"(min_)?dpi$", k) and _num(v):
                    cv["dpi"] = _num(v)
                elif k in ("size_mm", "canvas_mm") and isinstance(v, str):
                    q = re.findall(r"\d+(?:\.\d+)?", v)
                    if len(q) == 2:
                        cv["size_mm"] = [float(x) for x in q]
    if "width_px" in cv and "height_px" in cv:
        cv["size_px"] = [int(cv.pop("width_px")), int(cv.pop("height_px"))]
    if "width_mm" in cv and "height_mm" in cv:
        cv["size_mm"] = [cv.pop("width_mm"), cv.pop("height_mm")]
    return cv, groups, gkey


def slug(t):
    t = re.sub(r"\^\S+|\(.*?\)", " ", t)
    w = re.findall(r"[A-Za-z0-9一-鿿]+", t)
    return "".join(x[:1].upper() + x[1:] for x in w)[:26] or "N"


def draft(kind):
    cv, groups, gkey = order_facts()
    order = " ".join(ks.must_lines()).lower()
    ps = ks.get_index()["passages"]
    title = next((q for q in ps if "title" in str(q.get("label", "")).lower() or str(q["loc"]).lower().endswith("title")), ps[0] if ps else None)
    ed = " ".join(ln for ln in ks.must_lines() if re.search(r"(?i)^\s*(edit|revision)", ln)).lower()
    if ("size_mm" in cv or "size_px" in cv) and re.search(r"inset|as text|add (a |one |an )?(\w+ )?(note|legend|panel|text|table|caption|box|line|inset)", ed):
        cv["reserve"] = .18
    spec = {"title": (title["text"][:140] if title else "Figure"), "title_src": title["id"] if title else None, "canvas": cv or {"width_mm": 180}, "caption": "", "footnotes": [], "panels": []}
    gl = lambda names: "".join("%s | %s | %s | workorder\n" % (slug(g), g[:1].upper() + g[1:], "membrane" if re.search(r"membrane", g, re.I) and kind == "pathway" else "-") for g in names)
    lr = re.search(r"left[\s_-]*to[\s_-]*right", gkey + " " + order)
    files = {}
    if kind == "abstract":
        spec["theme"] = "abstract"
        spec["subtitle"] = ""
        spec["panels"] = [{"id": "Q", "type": "text", "title": "1 Question"}, {"id": "M", "type": "text", "title": "2 Design"}, {"id": "R", "type": "text", "title": "3 Key result"}, {"id": "C", "type": "text", "title": "4 Conclusion and limits"}]
    elif kind == "apparatus":
        spec["panels"] = [{"id": "A", "type": "diagram", "title": "Apparatus"}, {"id": "B", "type": "diagram", "title": "Technical route"}]
        spec["layout"] = [["A"], ["B"]]
        if re.search(r"time axis|by day|schedule|timeline|sampling day|which days", order):
            spec["panels"].append({"id": "T", "type": "timeline", "title": "Schedule", "unit": "day"})
            spec["layout"].append(["T"])
        spec["footnotes"] = [{"text": "Schematic, not to scale.", "src": "workorder"}]
    else:
        p = {"id": "A", "type": "diagram", "title": ""}
        p["direction"] = "LR" if lr else ("TB" if kind == "pathway" else "auto")
        spec["panels"] = [p]
        if groups:
            files["A.groups"] = gl(groups)
        spec["footnotes"] = [{"text": "Schematic, not to scale.", "src": "workorder"}]
    return spec, files


def tables():
    """Result tables in the material: label -> [(passage id, cells)] and data files."""
    out = {}
    for q in ks.get_index()["passages"]:
        lab = str(q.get("label") or "")
        if re.match(r"(?i)(supp\w*\s+)?table\s*\w+", lab) and q["text"].count("|") >= 1:
            out.setdefault(lab, []).append((q["id"], [c.strip() for c in re.split(r"\s*\|\s*", q["text"])]))
    return {k: v for k, v in out.items() if len(v) >= 3}


def table_hint():
    t = tables()
    rows = ["'%s' (%d rows): %s" % (k, len(v) - 1, " | ".join(v[0][1])[:150]) for k, v in t.items()]
    rows += ["'%s' (%d rows): %s" % (x["file"], x["rows"], " | ".join(map(str, x["columns"]))[:150]) for x in ks.get_index()["tables"][:6]]
    return rows[:8]


HEAD = {"to": r"response|outcome|target|dependent|effect on|^to$", "from": r"predictor|source|factor|independent|regulator|^from$|explanatory", "value": r"estimate|coef|beta|\bstd|weight|effect size|^r$|rho|value", "p": r"^p\b|p.?val|signif|^p$"}


COMMON = set("""the this these those figure table supplementary data results discussion introduction materials methods however therefore although although moreover furthermore addition contrast western blot antibody antibodies cells cell line lines protein proteins gene genes treatment treated control controls experiment experiments analysis study studies DNA RNA mRNA PCR FRET SDS PAGE EDTA ANOVA USA UK SEM SD CI NA""".split())


def lexicon(limit=14):
    """Entity names that the order uses (must-show items, edit request) and the paper repeats."""
    order = " ".join(ks.walk_items()[0] + ks.edit_requests())
    body = " ".join(q["text"] for q in ks.get_index()["passages"])
    cand = {}
    for m in re.finditer(r"(?<![\w-])(?:[A-Z][a-z]{3,}|[A-Za-z]{0,3}[A-Z][A-Za-z]*\d[\w-]*|[A-Z]{2,}[\w-]*)(?![\w-])", order):
        w = m.group(0).strip("-")
        if w.lower() in {x.lower() for x in COMMON} or len(w) < 3 or re.match(r"^[A-Z]{2,4}-?[A-Z]?\d{1,2}$", w) and w not in body:
            continue
        n = len(re.findall(r"(?<![\w])" + re.escape(w) + r"(?![\w])", body))
        if re.fullmatch(r"[A-Z][a-z]+", w) and len(re.findall(r"(?<=[a-z,;] )" + re.escape(w) + r"(?![\w])", body)) < 3:
            continue  # an ordinary capitalised word
        if n >= 3:
            cand[w] = n
    return [w for w, _ in sorted(cand.items(), key=lambda t: -t[1])][:limit]


def starter(kind, spec):
    """A minimal honest draft, so that a complete delivery exists from the first minute; replaced as soon as the author writes lines."""
    ps = ks.get_index()["passages"]
    if kind == "pathway":
        rows = []
        for w in lexicon(8):
            b = ks.rank_passages(w, 1)
            rows.append("%s | %s | protein | - | %s" % (slug(w), w, b[0][0]["id"] if b else "workorder"))
        return {"A.starter": "\n".join(rows) + "\n"} if len(rows) >= 2 else {}
    if kind == "apparatus":
        cnt = {}
        for q in ps:
            for m in re.finditer(r"(?i)\b((?:[a-z]+[- ]){0,2}(?:tank|reactor|pump|sump|column|chamber|furnace|condenser|cyclone|detector|camera|laser|valve|cylinder|heater|mixer|electrode|vessel|pipe|trap|filter|sensor))s?\b", q["text"]):
                w = re.sub(r"(?i)^(?:(?:the|a|an|of|in|to|and|each|two|one|with|from|into|was|were|is|are)\s+)+", "", m.group(1).lower()).strip()
                cnt.setdefault(w, []).append(q["id"])
        rows = ["%s | %s | equipment | - | %s" % (slug(w), w[:1].upper() + w[1:], i[0]) for w, i in sorted(cnt.items(), key=lambda t: -len(t[1]))[:6] if len(i) > 1]
        return {"A.starter": "\n".join(rows) + "\n"} if len(rows) >= 2 else {}
    if kind == "schematic":
        gs = order_facts()[1]
        return {"A.starter": "".join("%sNode | %s | concept | %s | workorder\n" % (slug(g), g[:1].upper() + g[1:], slug(g)) for g in gs)} if len(gs) >= 2 else {}
    if kind == "abstract":
        ab = [q for q in ps if "abstract" in str(q.get("label") or q["loc"]).lower()]
        last = re.split(r"(?<=[.!?])\s+", ab[-1]["text"])[-1] if ab else ""
        return {"Q.starter": "- | %s | %s\n" % (spec["title"].replace("|", "/"), spec.get("title_src") or "workorder"), "C.starter": "- | %s | %s\n" % (last[:220].replace("|", "/"), ab[-1]["id"])} if last else {}
    return {}


def cmd_start(a):
    """Compact brief + drafted spec + first work item; small enough not to be truncated."""
    import contextlib
    import io
    kind = {"pathway": "pathway", "mechanism": "pathway", "apparatus": "apparatus", "route": "apparatus", "abstract": "abstract", "schematic": "schematic"}.get(a.kind, "schematic")
    with contextlib.redirect_stdout(io.StringIO()):
        ks.cmd_brief(a)
    spec, files = draft(kind)
    sp = os.path.join(WORK, "spec.json")
    if not os.path.exists(sp):
        jsave(sp, spec)
        try:
            files.update(starter(kind, spec))
        except Exception:
            pass
        for k, v in files.items():
            with open(os.path.join(WORK, k), "w", encoding="utf-8") as f:
                f.write(v)
        jsave(os.path.join(WORK, ".kind"), {"kind": kind})
        if any(k.endswith(".starter") for k in files):
            import subprocess
            import sys
            try:
                subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "figkit.py"), "build"], capture_output=True, text=True, timeout=60, env=dict(os.environ, KIT_STARTER="1"))
            except Exception:
                pass
    idx = ks.get_index()
    say("CASE %s | %d passages indexed from %s" % (ks.case_id(), len(idx["passages"]), ", ".join(sorted({q["file"] for q in idx["passages"]}))[:200]))
    say("DRAFT written by the engine: /app/work/spec.json = canvas %s, panels %s%s" % (json.dumps(spec["canvas"]), ", ".join("%s (%s)" % (p["id"], p["type"]) for p in spec["panels"]),
        "; A.groups = " + "; ".join(l.split(" | ")[0] for l in files["A.groups"].strip().split("\n")) if files.get("A.groups") else ""))
    t = table_hint()
    if t:
        say("TABLES: " + "\n        ".join(t))
    if idx["svgs"]:
        say("SUPPLIED SVG:", idx["svgs"], "-> use svgtree, then edit")
    if os.path.exists(os.path.join(OUT, "figure.svg")):
        say("A STARTER draft (names only, status partial) is already delivered; it disappears with your first lines.")
    say("Do not open or grep the material files: every item below brings its passages; runs that read the paper first ran out of time. Title, caption, notes come at the end (`set title \"...\"`, `set caption \"...\"`).\n")
    a.item = None
    ks.cmd_next(a)


def cmd_set(a):
    p = os.path.join(WORK, "spec.json")
    d = jload(p)
    k, v = a.key, " ".join(a.value)
    if k in ("title", "caption", "subtitle", "title_src", "subtitle_src"):
        d[k] = v
    elif "." in k:  # panel.key
        pid, kk = k.split(".", 1)
        pan = next((q for q in d["panels"] if q["id"] == pid), None)
        if pan is None:
            say("no panel %s" % pid)
            return 2
        pan[kk] = v
        pj = os.path.join(WORK, pid + ".panel.json")
        if os.path.exists(pj):
            q_ = jload(pj)
            q_[kk] = v
            jsave(pj, q_)
    elif k in ("decision", "omitted", "unresolved"):
        f = [x.strip() for x in v.split("|")]
        if k == "decision":
            d.setdefault("decisions", []).append(v)
        elif k == "omitted":
            d.setdefault("omitted", []).append({"item": f[0], "reason": f[1] if len(f) > 1 else ""})
        else:
            d.setdefault("unresolved", []).append({"item": f[0], "state": f[1] if len(f) > 2 else "conflict", "detail": f[2] if len(f) > 2 else (f[1] if len(f) > 1 else f[0]), "src": [x.strip() for x in f[3].split(",")] if len(f) > 3 else []})
    else:
        say("set: title | caption | PANEL.title | PANEL.direction | unresolved \"item | state | detail | P001,P002\" | omitted \"item | reason\" | decision \"...\"")
        return 2
    jsave(p, d)
    say("saved %s" % k)


def _pval(t):
    t = str(t).replace("−", "-").replace("–", "-")
    m = re.search(r"([<>≤≥]?)\s*=?\s*(\d*\.?\d+(?:[eE][-+]?\d+)?)", t)
    if not m:
        return None
    v = float(m.group(2))
    return 1.0 if m.group(1) in (">", "≥") and v >= .5 else (v * .999 if m.group(1) in ("<", "≤") else v)


def _val(t):
    t = str(t).replace("−", "-").replace("–", "-")
    m = re.fullmatch(r"\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\D{0,4}\s*", t)
    return float(m.group(1)) if m else None


def _where(expr):
    m = re.fullmatch(r"\s*p\s*(<=|>=|<|>)\s*([\d.]+)\s*", expr or "")
    if not m:
        return None
    lim = float(m.group(2))
    return {"<": lambda p: p < lim, "<=": lambda p: p <= lim, ">": lambda p: p > lim, ">=": lambda p: p >= lim}[m.group(1)]


def cmd_fromtable(a):
    """Turn the rows of a result table into relation lines with value, p, sign and row-level source."""
    ts = tables()
    key = next((k for k in ts if k.lower() == a.table.lower()), None) or next((k for k in ts if a.table.lower() in k.lower()), None)
    if key:
        head, rows = ts[key][0][1], ts[key][1:]
        if not any(re.search(HEAD["to"], c, re.I) or re.search(HEAD["p"], c, re.I) for c in head):
            for j, (_, c) in enumerate(ts[key][:4]):
                if sum(bool(re.search(v, x, re.I)) for v in HEAD.values() for x in c) >= 2:
                    head, rows = c, ts[key][j + 1:]
                    break
    else:
        try:
            cols, rr = ks.read_table(a.table)
        except Exception:
            say("no table '%s'. Available: %s" % (a.table, "; ".join(table_hint())))
            return 2
        head, rows = [str(c) for c in cols], [("%s#%d" % (a.table, n), [str(r[c]) for c in cols]) for n, r in enumerate(rr, 1)]
        key = a.table
    ci = {}
    for k, pat in HEAD.items():
        want = getattr(a, k if k != "from" else "from_", None)
        if want:
            ci[k] = int(want) - 1 if str(want).isdigit() else next((j for j, c in enumerate(head) if want.lower() in c.lower()), None)
        else:
            ci[k] = next((j for j, c in enumerate(head) if re.search(pat, c.strip(), re.I) and j not in ci.values()), None)
    if ci.get("from") is None or ci.get("to") is None:
        say("columns: %s -> give --from N --to N (and --value N --p N), counted from 1" % " | ".join("%d %s" % (j + 1, c) for j, c in enumerate(head)))
        return 2
    keep, dash = _where(a.where), _where(a.dash)
    nodes, edges, skipped, notest = {}, [], 0, []

    def node(t, src, response):
        parts = [x.strip() for x in t.split(" / ")]
        lab = re.sub(r"\^\S+|\s*\((?:Y/N|PC\d|log|sqrt)[^)]*\)", "", parts[0]).strip()
        k = slug(lab)
        n = nodes.setdefault(k, {"label": lab, "src": src, "note": "-"})
        extra = [x for x in parts[1:] if re.search(r"(?i)R\^?2|R²|n\s*=", x) and not re.search(r"(?i)conditional", x)]
        if response and extra and n["note"] == "-":
            n["note"], n["src"] = re.sub(r"R\^2", "R^{2}", extra[0]).replace(": ", " = "), src
        return k
    resp = {}  # every response row carries its fit, also when none of its paths passes
    for src, c in rows:
        parts = [x.strip() for x in c[ci["to"]].split(" / ")] if len(c) > ci["to"] else [""]
        extra = [x for x in parts[1:] if re.search(r"(?i)R\^?2|R\u00b2|n\s*=", x) and not re.search(r"(?i)conditional", x)]
        if extra:
            resp.setdefault(slug(re.sub(r"\^\S+|\s*\((?:Y/N|PC\d|log|sqrt)[^)]*\)", "", parts[0])), (re.sub(r"R\^2", "R^{2}", extra[0]).replace(": ", " = "), src))
    for src, c in rows:
        c = c + [""] * (len(head) - len(c))
        pv = _pval(c[ci["p"]]) if ci.get("p") is not None else None
        pair = re.split(r"\s*~~\s*", c[ci["to"]])
        if len(pair) == 2:
            nums = [x for x in c if _val(x) is not None]
            v, f, t, ty = (nums[0] if nums else ""), pair[1], pair[0], "association"
        else:
            f, t, ty, v = c[ci["from"]], c[ci["to"]], a.type, (c[ci["value"]] if ci.get("value") is not None else "")
        if not f or not t:
            continue
        if pv is None and ci.get("p") is not None:
            notest.append((src, f, t))
            continue
        if keep and pv is not None and not keep(pv):
            skipped += 1
            continue
        val = _val(v)
        fk, tk = node(f, src, False), node(t, src, True)
        lab = ("%s" % v.strip()).replace("–", "−").replace("-", "−") if val is not None else "estimate not reported"
        if val is not None and val > 0 and not lab.startswith("+"):
            lab = "+" + lab
        line = "%s | %s | %s | %s | stated | %s | %s; p %s" % (fk, tk, ty, lab, src, key, c[ci["p"]] if ci.get("p") is not None else "")
        if val is not None:
            line += " | value=%g" % val
        if pv is not None:
            line += " | p=%g" % pv
        if dash and pv is not None and dash(pv):
            line += " | dash=dashed"
        edges.append(line)
    for k, n in nodes.items():
        if n["note"] == "-" and k in resp:
            n["note"], n["src"] = resp[k]
    if not edges:
        say("no row passes %s" % a.where)
        return 2
    P = a.panel
    nf, ef = os.path.join(WORK, P + ".nodes"), os.path.join(WORK, P + ".edges")
    known = {ln.split("|")[0].strip() for ln in open(nf, encoding="utf-8")} if os.path.exists(nf) else set()
    with open(nf, "a", encoding="utf-8") as f:
        for k, n in nodes.items():
            if k not in known:
                f.write("%s | %s | %s | - | %s | %s | stated\n" % (k, n["label"], a.kind, n["src"], n["note"]))
    with open(ef, "a", encoding="utf-8") as f:
        f.write("\n".join(edges) + "\n")
    opts = {"panel": {"edge_width": {"field": "value", "label": "|%s|" % (head[ci["value"]].lower() if ci.get("value") is not None else "value")}}}
    if a.dash:
        m = re.search(r"([\d.]+)", a.dash).group(1)
        lim = re.search(r"([\d.]+)", a.where or "1").group(1)
        opts["legend_extra"] = [{"text": "p < %s (solid)" % m}, {"text": "%s ≤ p < %s (dashed)" % (m, lim), "dash": "dashed"}]
    jsave(os.path.join(WORK, P + ".opts.json"), opts)
    say("%d relations written from %s (%d rows not passing %s; %d rows without a test result); %d nodes." % (len(edges), key, skipped, a.where or "-", len(notest), len(nodes)))
    if notest:
        say("ROWS WITHOUT RESULT (state them in a footnote, e.g. left out of the submodel): " + "; ".join("%s %s -> %s" % (s, re.sub(r"\^\S+", "", f), t.split(" / ")[0]) for s, f, t in notest)[:900])
    gf = os.path.join(WORK, P + ".groups")
    say("ASSIGN GROUPS NOW - write %s.place, one line per node `id | group`: ids %s%s" % (P, ", ".join(nodes), "; groups " + ", ".join(l.split("|")[0].strip() for l in open(gf, encoding="utf-8") if "|" in l) if os.path.exists(gf) else ""))
    say("then `build && next`.")


def cmd_prune(a):
    """Remove relations by p (or certainty) for a requested edit and list them as text in a muted inset."""
    P, cond = a.panel, _where(a.where)
    if not cond:
        say("give a condition such as \"p>=0.05\"")
        return 2
    ef = os.path.join(WORK, P + ".edges")
    names = {}
    nf = os.path.join(WORK, P + ".nodes")
    for ln in open(nf, encoding="utf-8") if os.path.exists(nf) else []:
        f = [x.strip() for x in ln.split("|")]
        if len(f) > 1:
            names[f[0]] = f[1]
    gone, out = {}, []
    for ln in open(ef, encoding="utf-8"):
        m = re.search(r"\|\s*p=([\d.eE+-]+)", ln)
        f = [x.strip() for x in ln.split("|")]
        if m and len(f) > 5 and cond(float(m.group(1))):
            gone["%s|%s|%s" % tuple(f[:3])] = f
        else:
            out.append(ln)
    if not gone:
        say("no relation matches %s" % a.where)
        return 2
    with open(ef, "w", encoding="utf-8") as f:
        f.writelines(out)
    with open(os.path.join(WORK, a.inset + ".items"), "w", encoding="utf-8") as f:
        for q in gone.values():
            pv = re.search(r"; p\s*(.+)$", q[6]) if len(q) > 6 else None
            f.write("- | %s → %s: %s%s | %s\n" % (names.get(q[0], q[0]), names.get(q[1], q[1]), q[3], ", p = " + re.sub(r"[*•]+", "", pv.group(1)) if pv else "", q[5]))
    op = os.path.join(WORK, P + ".opts.json")
    if os.path.exists(op) and not any("dash=dashed" in ln for ln in out):
        o = jload(op)
        o["legend_extra"] = [x for x in o.get("legend_extra", []) if not x.get("dash")]
        jsave(op, o)
    sp = os.path.join(WORK, "spec.json")
    d = jload(sp)
    if not any(q["id"] == a.inset for q in d["panels"]):
        d["panels"].append({"id": a.inset, "type": "text", "title": a.title, "muted": True, "columns": 2})
        d["layout"] = (d.get("layout") or [[q["id"]] for q in d["panels"][:-1]]) + [[a.inset]]
    d["edit_scope"] = sorted(set(d.get("edit_scope") or []) | {"%s-edge-%s-%s-%s" % (P, q[0], q[2], q[1]) for q in gone.values()} | {"%s-edges" % P, "%s-edge-labels" % P, "panel-%s" % a.inset, a.inset + "-", "figure-legend", "legend-"})
    d.setdefault("removed_ids", []).extend("%s-edge-%s-%s-%s" % (P, q[0], q[2], q[1]) for q in gone.values())
    jsave(sp, d)
    say("%d relations removed from %s and listed in inset %s; edit_scope set. Update the caption (`set caption`), then `build --revise \"%s\"`." % (len(gone), P, a.inset, a.title))
