"""Case reading, source indexing, citation resolution and result.json writing.

Shared by the figure and slide kits. Standard library only; pdftotext is used for PDF input.
"""
import csv
import glob
import json
import math
import os
import re
import subprocess
import sys
import time

import kit_table

INPUT = os.environ.get("KIT_INPUT", "/input")
WORK = os.environ.get("KIT_WORK", "/app/work")
OUT = os.environ.get("KIT_OUTPUT", "/app/output")
CONTRACT = ["case_id", "status", "editable_source", "export_artifact", "content_map", "compliance_checks", "exceptions"]
TEXT_EXT = (".md", ".txt", ".xml", ".nxml", ".html", ".htm", ".tex", ".rst")
TABLE_EXT = (".csv", ".tsv")


def jload(p):
    with open(p, encoding="utf-8-sig") as f:
        return json.load(f)


def jsave(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def say(*a):
    print(*a)


def walk_inputs():
    out = []
    for root, dirs, files in os.walk(INPUT):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in sorted(files):
            out.append(os.path.join(root, f))
    return sorted(out)


def rel(p):
    return os.path.relpath(p, INPUT)


def clean(t):
    return re.sub(r"\s+", " ", t).strip()


# --- indexing ------------------------------------------------------------------
def scalar(x):
    return x is None or isinstance(x, (str, int, float, bool))


def json_strings(obj, ptr=""):
    """Yield (pointer, text, keep) - keep marks table rows that must be indexed however short they are."""
    if isinstance(obj, dict):
        vals = list(obj.values())
        rowlike = len(vals) >= 2 and all(scalar(v) for v in vals) and max(len(str(v)) for v in vals) <= 90 and re.search(r"/\d+$", ptr)
        if rowlike:
            yield ptr, "; ".join("%s = %s" % (k, v) for k, v in obj.items() if v is not None), True
            return
        for k, v in obj.items():
            yield from json_strings(v, ptr + "/" + str(k))
    elif isinstance(obj, list):
        if obj and all(scalar(x) for x in obj) and sum(len(str(x)) for x in obj) < 700:
            yield ptr, " | ".join("" if x is None else str(x) for x in obj), len(obj) > 1
        else:
            for i, v in enumerate(obj):
                yield from json_strings(v, "%s/%d" % (ptr, i))
    elif isinstance(obj, (str, int, float)) and not isinstance(obj, bool):
        yield ptr, str(obj), False


HEAD_KEYS = ("table_id", "figure_id", "fig_id", "table_label", "figure_label", "section_path", "heading", "section", "section_title", "title", "label", "name", "figure", "table", "caption_label", "id", "para_id", "paragraph_id", "locator", "page", "kind", "type")


def ptr_label(root, ptr):
    """Human-readable locator for a JSON pointer, built from sibling keys on the way down."""
    parts, cur, labs, cur0 = [x for x in ptr.split("/") if x], root, [], None
    for k, x in enumerate(parts):
        if isinstance(cur, dict):
            for h in HEAD_KEYS:
                v = cur.get(h)
                if h != x and isinstance(v, (str, int)) and 0 < len(str(v)) < 70 and str(v) not in labs:
                    if k or h not in ("title", "name", "id", "kind", "type", "label"):
                        labs.append(("p. %s" % v) if h == "page" else str(v))
                        if h in ("heading", "section", "section_title", "title", "label", "name", "figure", "table"):
                            if h not in ("id",):
                                pass
                            break
            cur0 = cur
            cur = cur.get(x)
        elif isinstance(cur, list):
            cur = cur[int(x)] if x.isdigit() and int(x) < len(cur) else None
        if cur is None:
            break
    GENERIC = {"paragraph", "text", "table", "figure_caption", "caption", "heading", "blocks", "rows", "p", "para", "body", "section", "list_item", "figure"}
    labs = [x for x in labs if str(x).lower() not in GENERIC]
    if isinstance(cur0, dict) and isinstance(cur0.get("locator"), (str, int)):
        return str(cur0["locator"])
    labs = [x.split(" > ")[-1] if " > " in x else x for x in labs]
    if not labs and parts:
        key = [x for x in parts if not x.isdigit()]
        labs = [key[-1].replace("_", " ")] if key else []
    para = [int(x) + 1 for x in parts if x.isdigit()]
    out = ", ".join(labs[-2:])
    if not out and para:
        out = "passage"
    if para and len(parts) > 1 and "\u00b6" not in out:
        unit = "row" if any("row" in x.lower() for x in parts) else "para"
        out += (", " if out else "") + "%s %d" % (unit, para[-1])
    return out


def natural_label(text, fallback):
    m = re.match(r"\s*((?:Supplementary\s+)?(?:Fig(?:ure|\.)?|Table|Box|Scheme|Eq(?:uation|\.)?)\s*\.?\s*[A-Z]?\d+[A-Za-z]?)", text)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else fallback


def split_long(text, limit=1400):
    text = text.strip()
    if len(text) <= limit:
        return [text]
    parts = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) == 1:
        parts = re.split(r"(?<=[.!?。！？])\s+", text)
    out, cur = [], ""
    for p in parts:
        if cur and len(cur) + len(p) > limit:
            out.append(cur)
            cur = p
        else:
            cur = (cur + "\n" + p) if cur else p
    if cur:
        out.append(cur)
    return out


def index_sources():
    passages, tables, svgs, others = [], [], [], []

    def add(f, loc, text, label=""):
        for k, part in enumerate(split_long(text)):
            t = clean(part)
            if len(t) >= 2:
                passages.append({"id": "", "file": f, "loc": loc + ("" if k == 0 else "~%d" % (k + 1)), "label": natural_label(t, label or loc), "text": t})
    for p in walk_inputs():
        f, ext = rel(p), os.path.splitext(p)[1].lower()
        try:
            if ext in TABLE_EXT:
                cols, rows = kit_table.load_table(p)
                tables.append({"file": f, "columns": cols, "rows": len(rows)})
            elif ext == ".xlsx":
                for name, raw in kit_table.xlsx_sheets(p).items():
                    bl = kit_table.sheet_blocks(raw)
                    for k, (title, cols, rows) in enumerate(bl, 1):
                        tables.append({"file": f + "!" + name + ("@%d" % k if len(bl) > 1 else ""), "columns": cols, "rows": len(rows), "title": title})
            elif ext == ".json":
                d = jload(p)
                recs = None
                if isinstance(d, list) and d and isinstance(d[0], dict) and all(not isinstance(v, (dict, list)) for v in d[0].values()):
                    recs = d
                if recs:
                    tables.append({"file": f, "columns": list(recs[0]), "rows": len(recs)})
                if f not in ("case.json",) and "workorder" not in f.lower():
                    for ptr, s, keep in json_strings(d):
                        if len(s) >= 25 or keep:
                            add(f, ptr, s, ptr_label(d, ptr))
            elif ext == ".svg":
                svgs.append(f)
            elif ext in TEXT_EXT:
                raw = open(p, encoding="utf-8", errors="replace").read()
                if ext in (".xml", ".nxml", ".html", ".htm"):
                    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
                    body = re.sub(r"(?i)</?(p|title|sec|caption|table-wrap|fig|tr|h\d|li|div|abstract)[^>]*>", "\n\n", raw)
                    raw = re.sub(r"<[^>]+>", " ", body)
                    raw = __import__("html").unescape(raw)
                    raw = "\n\n".join(x for x in (clean(q) for q in re.split(r"\n\s*\n", raw)) if len(x) > 20)
                if f in ("task.md",):
                    continue
                for k, part in enumerate(re.split(r"\n\s*\n", raw), 1):
                    if clean(part):
                        add(f, "para %d" % k, part)
            elif ext == ".pdf":
                txt = subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True, timeout=90).stdout
                for pg, body in enumerate(txt.split("\f"), 1):
                    for k, part in enumerate(re.split(r"\n\s*\n", body), 1):
                        if len(clean(part)) > 30:
                            add(f, "page %d, block %d" % (pg, k), part, "p. %d" % pg)
                others.append(f)
            else:
                others.append(f)
        except Exception as exc:
            others.append("%s (unreadable: %s)" % (f, exc))
    for k, q in enumerate(passages, 1):
        q["id"] = "P%03d" % k
    idx = {"passages": passages, "tables": tables, "svgs": svgs, "others": others}
    jsave(os.path.join(WORK, "index.json"), idx)
    return idx


def get_index():
    p = os.path.join(WORK, "index.json")
    return jload(p) if os.path.exists(p) else index_sources()


def get_case():
    for p in (os.path.join(INPUT, "case.json"),):
        if os.path.exists(p):
            try:
                return jload(p)
            except Exception:
                pass
    return {}


def case_id():
    c = get_case()
    return c.get("case_id") or c.get("id") or "UNKNOWN"


def contract():
    c = get_case().get("output_contract")
    if isinstance(c, dict):
        c = c.get("required") or c.get("fields") or list(c)
    if isinstance(c, list) and c:
        return [str(x) for x in c]
    return CONTRACT


def table_path(name):
    if "!" in name and ".xlsx" in name.lower():
        base, _, sheet = name.partition("!")
        return table_path(base) + "!" + sheet
    for base in (INPUT, os.path.join(INPUT, "artifacts"), WORK, OUT):
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    hits = [p for p in walk_inputs() if os.path.basename(p) == os.path.basename(name)]
    if hits:
        return hits[0]
    raise ValueError("data file not found: " + name)


def read_table(name):
    return kit_table.load_table(table_path(name))


def workorders():
    return [p for p in walk_inputs() if "workorder" in os.path.basename(p).lower()]


def trim(obj, n):
    s = json.dumps(obj, ensure_ascii=False, indent=1)
    return s if len(s) <= n else s[:n] + "\n... [%d more characters: read the file directly]" % (len(s) - n)


def elapsed():
    p = os.path.join(WORK, ".start")
    return (time.time() - os.path.getmtime(p)) / 60 if os.path.exists(p) else 0.0


def cmd_brief(a):
    os.makedirs(WORK, exist_ok=True)
    if not os.path.exists(os.path.join(WORK, ".start")):
        open(os.path.join(WORK, ".start"), "w").close()
    os.makedirs(OUT, exist_ok=True)
    idx = index_sources()
    say("# CASE", case_id(), "| contract:", ", ".join(contract()))
    case = get_case()
    say(trim({k: v for k, v in case.items() if k not in ("output_contract",)}, 2600))
    for p in walk_inputs():
        if os.path.basename(p) == "task.md":
            t = open(p, encoding="utf-8", errors="replace").read()
            say("\n# task.md\n" + t[:2600] + ("\n...[%d more chars]" % (len(t) - 2600) if len(t) > 2600 else ""))
    for p in workorders():
        say("\n# WORKORDER", rel(p))
        try:
            say(trim(jload(p), 7000))
        except Exception:
            say(open(p, errors="replace").read()[:7000])
    say("\n# FILES")
    for p in walk_inputs():
        say("  %-52s %8d B" % (rel(p), os.path.getsize(p)))
    for t in idx["tables"]:
        say("\n# TABLE %s: %d rows; columns %s" % (t["file"], t["rows"], t["columns"]))
        cols, rows = read_table(t["file"])
        for r in rows[:3]:
            say("   " + " | ".join(str(r[c]) for c in cols)[:260])
    ps = idx["passages"]
    say("\n# PASSAGES: %d (cite by id; read with `show`)" % len(ps))
    cap, used = 5200, 0
    step = 92 if len(ps) <= 60 else (64 if len(ps) <= 110 else 44)
    for q in ps:
        line = "%s [%s] %s" % (q["id"], (q.get("label") or q["loc"])[:34], q["text"][:step])
        used += len(line)
        if used > cap:
            say("... %s is the last passage; use find/show for the rest" % ps[-1]["id"])
            break
        say(line)
    if idx["svgs"]:
        say("\n# SUPPLIED SVG:", idx["svgs"], "-> use svgtree, then edit")
    if not os.path.exists(os.path.join(OUT, "result.json")):
        write_result({"status": "partial", "exceptions": [{"item": "figure", "state": "not yet built", "detail": "written by the brief step so an interrupted run still reports honestly"}]})
    say("\nNEXT: follow the step table of SKILL.md: either spec + `next` (it selects the passages for you), or at most 3 ranges with show. Do not plan the whole product yet.")


def cmd_show(a):
    ps = get_index()["passages"]
    ids = {q["id"]: k for k, q in enumerate(ps)}
    want = []
    for tok in a.ids:
        for t in tok.split(","):
            m = re.match(r"P?(\d+)-P?(\d+)$", t)
            if m:
                want += list(range(int(m.group(1)), int(m.group(2)) + 1))
            elif re.match(r"P?\d+$", t):
                want.append(int(t.lstrip("P")))
    cf, rf = os.path.join(WORK, ".shows"), os.path.join(WORK, ".readchars")
    n = (int(open(cf).read()) if os.path.exists(cf) else 0) + 1
    read = int(open(rf).read()) if os.path.exists(rf) else 0
    open(cf, "w").write(str(n))
    fig = os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "figkit.py"))
    built = os.path.exists(os.path.join(WORK, ".builds"))
    hint = first_step_hint(fig)
    if not built and read > (26000 if fig else 42000):
        say("READING PAUSED (%d characters read, nothing built yet). %s `show` works again after the first build; then read for one named gap at a time." % (read, hint))
        return
    if not built and n >= 2:
        say("NEXT (after this): " + hint + "\n")
    total = 0
    for w in want:
        k = ids.get("P%03d" % w)
        if k is None:
            continue
        q = ps[k]
        total += len(q["text"])
        if total > 14000:
            say("... stopped at 14000 characters; request the rest separately")
            break
        say("%s [%s | %s]\n%s\n" % (q["id"], q.get("label") or q["loc"], q["file"], q["text"]))
    open(rf, "w").write(str(read + total))
    if not built and n >= 2:
        say("NEXT: " + hint)


def walk_items():
    """Work items in order: the case's own must-show lines (never the prohibitions or the delivery list)."""
    items, rules, skip = [], [], False
    for ln in must_lines():
        if ln == "WORK ORDER":
            break
        if ln.startswith("#"):
            skip = bool(re.search(r"(?i)must.?not|not claim|do not|avoid|deliver|hand.?in|stage|disagree|output|contract|forbid|submit|format|file|\u4e0d\u5f97|\u7981\u6b62|\u4ea4\u4ed8|\u63d0\u4ea4", ln))
            neg = bool(re.search(r"(?i)must.?not|not claim|do not|avoid|forbid|\u4e0d\u5f97|\u7981\u6b62", ln))
            continue
        if ln.startswith("  "):
            t = re.sub(r"^\s*(?:\d+[.)]|[-*])\s+", "", ln).strip()
            if not skip:
                items.append(t)
            elif neg:
                rules.append(t)
    c = get_case()
    for k in ("must_show", "requirements", "tasks", "checklist"):
        if isinstance(c.get(k), list):
            items += [str(x) if not isinstance(x, dict) else json.dumps(x, ensure_ascii=False)[:300] for x in c[k]]
    for k in ("must_not", "must_not_claim", "forbidden"):
        if isinstance(c.get(k), list):
            rules += [str(x) for x in c[k]]
    wo = []
    if "WORK ORDER" in must_lines():
        ml = must_lines()
        for ln in ml[ml.index("WORK ORDER") + 1:]:
            t = ln.strip()
            if not re.match(r"(?i)(mode|case|case_id|id|size|canvas|export|output|deliver|edit|language|color|colour|font|min_font|traceab|svg_req|dpi|files?|work_order)", t):
                wo.append(t)
    for t in wo:  # parts the order itself demands
        if re.search(r"(?i)(must_include|must_show|must_contain|required|mandatory)\b", t.split(":")[0]) and ":" in t:
            items.append("work order " + t)
    if len(items) < 3:
        items += [t for t in wo if re.search(r"(?i)must|includ|requir|show|state|entit|element|step|relation|content|node|edge", t)]
    if len(items) < 3:
        items = ["the main entities and where they are", "the main relations, in the order of the text, with direction and sign", "conditions, states, time points and measured outcomes",
                 "what is only proposed, not significant or not reported, and the limits"]
    return items[:14], rules, wo


def rank_passages(text, k=6, cap=5200):
    """Best passages for one work item, cut to the sentences that match."""
    idx = [q for q in get_index()["passages"] if len(q["text"]) > 40]
    terms = {w[:max(4, len(w) - 2)] for w in re.findall(r"[a-z0-9][a-z0-9+-]{2,}|[\u4e00-\u9fff]{2,}", text.lower()) if w not in STOP and w not in GENERIC_REQ}
    if not terms:
        return []
    low = [q["text"].lower() for q in idx]
    df = {t: sum(1 for x in low if t in x) for t in terms}
    idf = {t: math.log((len(idx) + 1.0) / (1 + c)) if c else 0 for t, c in df.items()}
    sc = []
    for q, x in zip(idx, low):
        v = sum(idf[t] * min(2.0, 1 + .3 * (x.count(t) - 1)) for t in terms if t in x)
        if v > 0:
            sc.append((v / (1 + max(0, len(x) - 900) / 2500.0), q))
    sc.sort(key=lambda r: -r[0])
    out, used = [], 0
    for v, q in sc[:k]:
        ss = re.split(r"(?<=[.!?;])\s+", q["text"])
        hit = [any(t in z.lower() and idf[t] > .7 for t in terms) for z in ss]
        keep = [z for j, z in enumerate(ss) if hit[j] or (j and hit[j - 1])] or ss[:3]
        t = " ".join(keep)
        t = t if len(t) <= 1100 else t[:1100] + " ..."
        if used + len(t) > cap:
            break
        used += len(t)
        out.append((q, t))
    return out


HEDGE = re.compile(r"(?i)\b(may|might|could|possib\w+|propos\w+|postulat\w+|hypothes\w+|suggest\w*|likely|thought to|unclear|not known|speculat\w+|correlat\w+|has been shown|have been shown|previously)\b")


def hedged(ids, cap=5200):
    """Sentences with hedged or cited relations that name at least two entities already drawn."""
    names = {i.lower() for i in ids if len(i) > 2}
    out, used, seen = [], 0, set()
    rows = []
    for q in get_index()["passages"]:
        ss = re.split(r"(?<=[.!?;])\s+", q["text"])
        lab = str(q.get("label") or q["loc"]).lower()
        base = 1.2 if "discuss" in lab else -1.0 if re.search(r"abstract|introd|method|summary", lab) else 0.0
        for j, z in enumerate(ss):
            mech = bool(re.search(r"\[\d+\]", z) and re.search(r"(?i)\b(via|through|leading to|leads to|by (?:reduc|inhibit|activ|increas|suppress)\w+|mediated|results? in|due to)\b", z))
            if not (HEDGE.search(z) or mech) or len(z) > 600 or not re.search(r"(?i)activat|inhibit|regulat|induc|increas|decreas|reduc|phosphoryl|\bbind|mediat|releas|transcri|suppress|feedback|translocat|correlat|promot|block|trigger|caus", z):
                continue
            low, pair = z.lower(), (ss[j - 1] + " " + z if j and len(ss[j - 1]) < 420 else z).lower()
            cnt = lambda t: sum(1 for x in names if re.search(r"(?<![a-z0-9])" + re.escape(x) + r"(?![a-z0-9])", t))
            n1, n2 = cnt(low), cnt(pair)
            if n1 >= 1 and n2 >= 2:
                strong = len(re.findall(r"(?i)\b(possib\w+|propos\w+|postulat\w+|hypothes\w+|correlat\w+|may|via)\b", z))
                rows.append((min(n2, 3) + .4 * n1 + .6 * min(2, strong) + 1.3 * mech + base, q, (ss[j - 1] + " " + z) if n1 < 2 and j and len(ss[j - 1]) < 420 else z))
    rows.sort(key=lambda r: -r[0])
    for v, q, z in rows:
        key = re.sub(r"\W+", "", z.lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        if used + len(z) > cap or len(out) >= 13:
            break
        used += len(z)
        out.append((q, z))
    return out


def item_passages(text, cap=6400):
    """Passages for a whole requirement plus, for each of its parts, the best ones not yet shown."""
    out = rank_passages(text, 5, 3800)
    seen, used = {q["id"] for q, _ in out}, sum(len(t) for _, t in out)
    parts = [x.strip() for x in re.split(r"[,;:]|\band\b|\bthen\b|\bplus\b|->|\u2192|\uff0c|\u3001|\uff1b|\u548c|\u4e0e", text) if x.strip()]
    if len(parts) > 1:
        for x in parts[:6]:
            if len(re.findall(r"[a-z0-9]{3,}|[\u4e00-\u9fff]{2,}", x.lower())) < 2:
                continue
            for q, t in rank_passages(x, 3, 2600)[:2]:
                if q["id"] in seen:
                    continue
                if used + len(t) > cap:
                    return out
                seen.add(q["id"])
                used += len(t)
                out.append((q, t))
    return out


def sites(limit=7):
    """Modification sites the material names (antibody or functional), one line per sentence."""
    rx = re.compile(r"(?i)\b(?:Tyr|Ser|Thr|Lys)[- ]?\d{2,4}\b|\bp[YST]\d{2,4}\b|\bY\d{3,4}\b|\b(?:tyrosine|serine|threonine|lysine)[- ]?\d{2,4}\b")
    out = []
    for q in get_index()["passages"]:
        for z in re.split(r"(?<=[.!?])\s+", q["text"]):
            ms = list(rx.finditer(z))
            if ms:
                i = max(0, ms[0].start() - 60)
                out.append("%s ...%s..." % (q["id"], z[i:min(len(z), max(ms[-1].end() + 30, i + 60), i + 420)]))
                if len(out) >= limit:
                    return out
    return out


def dated(limit=22, cap=3400):
    """Sentences that tie an action or measurement to days, weeks or a frequency."""
    rx = re.compile(r"(?i)\b(?:days?|d|weeks?|months?|hours?)\s?[\u2212\u2013-]?\s?\d+|\b\d+(?:\s?[\u2013-]\s?\d+)?\s?(?:days?|weeks?|months?)\b|\b(daily|weekly|monthly|every (?:day|week|month|\w+ days?)|once a (?:day|week)|twice a (?:day|week))\b")
    out, used, seen = [], 0, set()
    for q in get_index()["passages"]:
        lab = str(q.get("label") or q["loc"])
        if re.search(r"(?i)abstract|introd|discussion|reference", lab):
            continue
        meth = bool(re.search(r"(?i)method|material|procedure|experiment|design|sampl|protocol|analys", lab))
        for z in re.split(r"(?<=[.!?;])\s+", q["text"]):
            if rx.search(z) and (meth or re.search(r"(?i)sampl|measur|collect|analy[sz]|extract|monitor|record", z)):
                k = re.sub(r"\W+", "", z.lower())[:70]
                if k in seen:
                    continue
                seen.add(k)
                t = z.strip()[:210]
                if used + len(t) > cap or len(out) >= limit:
                    return out
                used += len(t)
                out.append("%s %s" % (q["id"], t))
    return out


def edge_gaps():
    """Relations whose evidence record is still incomplete (panel/table locator, reference of a cited relation)."""
    out = []
    for f in sorted(glob.glob(os.path.join(WORK, "*.edges"))):
        for ln in open(f, encoding="utf-8", errors="replace"):
            c = [x.strip() for x in ln.split("|")]
            if len(c) < 4 or ln.startswith("#") or c[3] == "delete":
                continue
            cert = c[4] if len(c) > 4 else ""
            ev = c[6] if len(c) > 6 and "=" not in c[6] else ""
            why = []
            if not re.search(r"(?i)fig|table|movie|suppl|text|\bref|\[\d", ev + " " + c[3]):
                why.append("no figure/table/reference in evidence")
            if cert == "cited" and not re.search(r"(?i)ref|\[\d|et al", c[3] + " " + ev):
                why.append("cited without its reference")
            if cert in ("", "-"):
                why.append("certainty empty")
            if why:
                out.append("%s -> %s (%s): %s" % (c[0], c[1], c[2], "; ".join(why)))
    return out


def edit_requests():
    return [ln.strip() for ln in must_lines() if re.search(r"(?i)^\s*(edit|revision|change)[\w.\[\]]*\.?(text|do|instruction|description|request)?\s*:", ln)]


def have_lines():
    """Ids already declared in the line files."""
    n, e = [], 0
    for f in sorted(glob.glob(os.path.join(WORK, "*.nodes"))):
        for ln in open(f, encoding="utf-8", errors="replace"):
            if "|" in ln and not ln.startswith("#"):
                i = ln.split("|")[0].strip()
                if i not in n:
                    n.append(i)
    for f in glob.glob(os.path.join(WORK, "*.edges")):
        e += sum(1 for ln in open(f, encoding="utf-8", errors="replace") if ln.count("|") >= 2 and not ln.startswith("#"))
    return n, e


def walking():
    p = os.path.join(WORK, ".item")
    return os.path.exists(p) and int(open(p).read().split("/")[0]) <= int(open(p).read().split("/")[1])


def cmd_next(a):
    """Walk through the case requirement by requirement: one item, its passages, one small write."""
    items, rules, wo = walk_items()
    p = os.path.join(WORK, ".item")
    k = int(open(p).read().split("/")[0]) if os.path.exists(p) else 0
    if a.item:
        k = a.item - 1
    edit = edit_requests()
    hedge = os.path.join(WORK, ".hedge")
    if k >= min(3, len(items)) and not os.path.exists(hedge) and elapsed() < 7 and have_lines()[1]:
        open(hedge, "w").close()
        rows = hedged(have_lines()[0])
        if rows:
            say("EXTRA ITEM (%.1f min): relations the authors only propose or take from earlier work, and tests of them, about the entities you already drew. Add the missing ones that belong to this figure's question (certainty proposed or cited; keep every intermediate the sentence names; a correlation is `association`), at most 6 lines, then `build` and `next`:" % elapsed())
            for q, t in rows:
                say("  %s [%s] %s" % (q["id"], q.get("label") or q["loc"], t))
            return
    built = os.path.exists(os.path.join(WORK, ".builds"))
    late = elapsed() > (5.5 if built else 7)
    if late and k < len(items):
        say("%.1f min used: the remaining items are printed together; cover only what is still missing, in one short batch." % elapsed())
        for j in range(k, len(items)):
            say("  ITEM %d: %s" % (j + 1, items[j]))
        k = len(items)
    elif k < len(items):
        n, e = have_lines()
        k0 = k
        pace = elapsed() / max(1, k0)
        batch = [k0]
        while batch[-1] + 1 < len(items) and len(batch) < 3 and (re.search(r"(?i)\blegend\b|\bscale\b|^(?:for )?(?:every|each) (?:edge|arrow|relation)", items[batch[-1]]) or (len(batch) < 2 and k0 >= 2 and pace > .85)):
            batch.append(batch[-1] + 1)
        for k in batch:
          it = items[k]
          say("ITEM %d of %d (%.1f min): %s" % (k + 1, len(items), elapsed(), it))
          if k == 0:
              if rules:
                  say("ALWAYS: " + " | ".join(rules)[:900])
              if wo:
                  say("WORK ORDER: " + " | ".join(wo)[:1500])
          if n and k == k0:
              say("already declared: %s; %d relations" % (", ".join(n)[:700], e))
          if re.search(r"(?i)\blegend\b", it) and len(it) < 90:
              say("(The legend is drawn automatically from the types used: write no legend text; check only that each demanded encoding is used, then run `next`.)")
          if re.search(r"(?i)table|model output|\brows?\b|all (links|paths|edges|variables|relations)|coefficient|estimate|\u8868", it):
              try:
                  import fk_flow
                  th = fk_flow.table_hint()
              except ImportError:
                  th = []
              if th:
                  say("TABLES: " + "; ".join(th))
                  say("Relations that come from table rows: do NOT type them - `fromtable \"Table 2\" --where \"p<0.1\" --dash \"p>=0.05\"` writes nodes, values, signs and row sources (limits from the order); then assign groups in A.place.")
          say("passages for this item:")
          for q, t in item_passages(it, 6400 if len(batch) == 1 else 3600):
              say("  %s [%s] %s" % (q["id"], q.get("label") or q["loc"], t))
          if re.search(r"(?i)phosph|modif|\bsites?\b|acetyl|ubiquit", it + " " + " ".join(rules)):
              sl = sites()
              if sl and k == 0 or sl and re.search(r"(?i)phosph|site", it):
                  say("SITES NAMED in the material (put them in the node note with their status, e.g. antibody site; never claim that none is named):")
                  for x in sl[:7]:
                      say("  " + x[:440])
          if re.search(r"(?i)\b(days?|dates?|schedule|time axis|timeline|sampling|samples|when|frequency|weekly|daily)\b", it):
              dl = dated()
              if dl:
                  say("DATED STATEMENTS in the material (every measurement or action with its days belongs in the schedule; check none is missing):")
                  for x in dl:
                      say("  " + x)
          if re.search(r"(?i)\b(every|each|all)\b.{0,20}(edge|relation|arrow|link|connection)", it):
              eg = edge_gaps()
              if eg:
                  say("RELATIONS WITH AN INCOMPLETE EVIDENCE RECORD (%d): delete and re-append each with certainty and evidence (panel; system; condition; ref for cited):" % len(eg))
                  for x in eg[:14]:
                      say("  " + x)
        open(p, "w").write("%d/%d" % (k + 1, len(items)))
        say("NOW: one command for %s - append at most %d node lines and %d relation lines (or one text/chart/timeline panel), each with its passage id, then `build` and `next` in the same command. "
            "If it is already covered or is only a rule, run `next`. Use `find WORD`/`show Pnnn`/`table FILE` for one named missing fact only. Do not think about later items, layout or the edit: they come one by one."
            % ("THIS item only" if len(batch) == 1 else "these %d items together" % len(batch), 6 + 3 * (len(batch) > 1), 6 + 4 * (len(batch) > 1)))
        return
    if k >= len(items):
        open(p, "w").write("%d/%d" % (len(items) + 1, len(items)))
        say("ALL %d ITEMS VISITED (%.1f min). Now: (1) `audit` once; real conflicts, missing facts and limits: `set unresolved \"item | conflict | both values | P008,P021\"` and, if a reader needs it, a line in notes.items; `set title \"...\"`, `set caption \"...\"`; (2) `build`; (3) `review` and close real gaps; (4) the requested edit with `build --revise`; (5) read_image once; (6) `verify`, stop." % (len(items), elapsed()))
        if wo:
            say("ENCODINGS DEMANDED (check each is used as asked): " + " | ".join(wo)[:900])
        for ln in edit[:4]:
            say("EDIT REQUEST: " + ln[:600])
        long_ = max(edit, key=len) if edit else ""
        if len(long_) > 40:
            say("passages for the edit (use the measured result, its condition and p, with its own passage):")
            for q, t in item_passages(re.sub(r"^[\w.\[\]]+:", "", long_), 3600):
                say("  %s [%s] %s" % (q["id"], q.get("label") or q["loc"], t[:700]))


def first_step_hint(fig):
    if fig:
        return ("Your next response is one short command: write spec.json (title, canvas, panel stubs) and A.groups, then run `next`, which hands you one requirement at a time with its passages "
                "(charts: write the chart panel and run build instead). Do not plan relations, layout, evidence or the edit yet - each gets its own later response. Thinking is limited: 16384 tokens in one response end the run.")
    return ("Your next response is one short command: write the spec file with the top-level keys and the first 3-4 slides (or the first 6 edits) and run build/edit. "
            "Plan the later slides in later responses. Thinking is limited: 16384 tokens in one response end the run.")


def cmd_find(a):
    ps = get_index()["passages"]
    hits = []
    for q in ps:
        t = q["text"].lower()
        n = sum(1 for w in a.words if w.lower() in t)
        if n:
            hits.append((n, q))
    hits.sort(key=lambda h: (-h[0], h[1]["id"]))
    for n, q in hits[:12]:
        t = q["text"]
        pos = min([t.lower().find(w.lower()) for w in a.words if w.lower() in t.lower()])
        say("%s [%s %s] ...%s..." % (q["id"], os.path.basename(q["file"]), q["loc"], t[max(0, pos - 120):pos + 260]))
    say("%d passage(s) match" % len(hits))


def cmd_table(a):
    cols, rows = read_table(a.file)
    lo, hi = 1, min(40, len(rows))
    if a.rows:
        m = re.match(r"(\d+)-(\d+)", a.rows)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
    say("row | " + " | ".join(cols))
    for k in range(lo, min(hi, len(rows)) + 1):
        say("%d | %s" % (k, " | ".join(str(rows[k - 1][c]) for c in cols)))
    say("%d rows in total; numeric summary:" % len(rows))
    for c in cols:
        v = [kit_table.num(r[c]) for r in rows]
        g = [x for x in v if x is not None]
        u = list(dict.fromkeys(r[c] for r in rows))
        if g and len(g) >= len(v) * .6:
            say("  %s: numeric n=%d missing=%d min=%g max=%g" % (c, len(g), len(v) - len(g), min(g), max(g)))
        else:
            say("  %s: %d distinct: %s" % (c, len(u), ", ".join(u[:12])))


HEDGE = re.compile(r"\b(may|might|suggest\w*|possibl\w*|propos\w*|hypothes\w*|likely|presum\w*|appears? to|not shown|unclear|speculat\w*|representative)\b", re.I)
NEGATE = re.compile(r"(not (?:significant\w*|statistically|measured|reported|tested|determined|available|assessed|observed|analy[sz]ed|shown)|no (?:significant|statistical|difference|effect|evidence|correlation)|did not|were not|was not|only one|single (?:site|run|experiment|year|centre|center)|limitation|excluded|missing|unable to|failed to|withdrawn|corrected|erratum|correction)", re.I)


def hard_leads():
    """Conflicts that can be stated without interpretation: malformed numbers, one value with two units, percentages that do not fit their counts."""
    out = []
    body = [q for q in get_index()["passages"] if not re.search(r"(?i)\b(doi|references?|bibliograph|acknowledg|author)", str(q.get("label") or q["loc"]))]
    for q in body:
        for m in re.finditer(r"(?<![\d.vV])(?:\d{2,4}\.\d{2,4}\.\d{1,4}|\d\.\d{3}\.\d{1,3})(?![\d.])", q["text"]):
            ctx = q["text"][max(0, m.start() - 70):m.end() + 40]
            if re.search(r"(?i)version|section|doi|www|http|\d{1,2}\.\d{1,2}\.(19|20)\d\d", q["text"][max(0, m.start() - 12):m.end() + 6]):
                continue
            out.append({"kind": "malformed number", "detail": "'%s' in: ...%s..." % (m.group(0), ctx.strip()), "ids": [q["id"]]})
    fam = {"m": "L", "cm": "L", "mm": "L", "km": "L", "g": "M", "mg": "M", "kg": "M", "ug": "M", "\u00b5g": "M", "\u03bcg": "M", "mL": "V", "L": "V", "ml": "V"}
    seen = {}
    for q in body:
        for m in re.finditer(r"(?<![\w.])([-\u2212\u2013]?\d+(?:\.\d+)?)\s?(cm|mm|km|m|kg|mg|\u00b5g|\u03bcg|ug|g|mL|ml|L)(?![\w^\u00b2\u00b3\-\u2212/]|\s?[\u2212-]\d)", q["text"]):
            v = m.group(1).replace("\u2212", "-").replace("\u2013", "-")
            if v.startswith("-") or "." in v:
                seen.setdefault((v, fam[m.group(2)]), {}).setdefault(m.group(2), []).append(q["id"])
    for (v, f), u in seen.items():
        if len(u) > 1:
            out.append({"kind": "one value, two units", "detail": "; ".join("%s %s in %s" % (v, k, ", ".join(dict.fromkeys(i))[:40]) for k, i in u.items()), "ids": [x[0] for x in u.values()]})
    for q in body:
        for m in re.finditer(r"(\d{1,6})\s*(?:/|of|out of)\s*(\d{1,6})\s*[\(\[,;]?\s*(\d{1,3}(?:\.\d+)?)\s?%", q["text"]):
            x, y, z = float(m.group(1)), float(m.group(2)), float(m.group(3))
            if y and x <= y and abs(100 * x / y - z) > max(1.0, .01 * z):
                out.append({"kind": "percentage does not fit its count", "detail": "'%s' but %g/%g = %.1f%%" % (m.group(0)[:40], x, y, 100 * x / y), "ids": [q["id"]]})
    return out[:10]


def auto_exceptions(have):
    """Source errors the scan is sure about, for result.json, unless the author already recorded them."""
    blob = json.dumps(have, ensure_ascii=False)
    ps = {q["id"]: q for q in get_index()["passages"]}
    out = []
    for x in hard_leads():
        key = re.search(r"'([^']+)'|(-?\d+(?:\.\d+)?) (?:cm|mm|km|m|mg|kg|g|ug|mL|ml|L)\b", x["detail"])
        k = (key.group(1) or key.group(2)) if key else x["detail"][:20]
        if k and (k in blob and len(k) > 4 or x["kind"] in blob):
            continue
        out.append({"item": x["kind"] + " in the source", "state": "conflict in the source; both readings kept, nothing repaired", "detail": x["detail"][:400],
                    "source": [{"id": i, "file": ps[i]["file"], "locator": ps[i]["loc"]} for i in x["ids"] if i in ps], "found_by": "engine consistency scan"})
    for t in p_leads()[:4]:
        m = re.search(r"text p ([\d.]+)", t)
        if m and m.group(1) in blob:
            continue
        out.append({"item": "p-value in table and text differ", "state": "possible conflict found by the engine; compare both passages", "detail": t[:400], "found_by": "engine consistency scan"})
    return out[:8]


def p_leads():
    """Text p-values that differ from the p-value printed for the same row or column in a table (leads)."""
    rows, cols = [], {}
    tab = {}
    for q in get_index()["passages"]:
        if re.match(r"(?i)table", str(q.get("label") or "")):
            tab.setdefault(re.split(r",", str(q["label"]))[0], []).append(q)
    for lab, qs in tab.items():
        cells = [(q["id"], [c.strip() for c in re.split(r"\s*\|\s*", q["text"])]) for q in qs if "|" in q["text"]]
        ptab = any(re.search(r"(?i)p[- ]?values?|anova|signific", q["text"]) for q in qs[:2])
        head = cells[0][1] if cells else []
        pc = [j for j, c in enumerate(head) if re.fullmatch(r"(?i)p([- ]?values?)?\.?", c)]
        for pid, c in cells[1:]:
            for j in pc:
                if j < len(c) and re.search(r"\d", c[j]) and c[0]:
                    rows.append((lab, pid, c[0], c[j]))
    txt = []
    for q in get_index()["passages"]:
        if re.match(r"(?i)table", str(q.get("label") or "")):
            continue
        for z in re.split(r"(?<=[.!?;])\s+", q["text"]):
            ps_ = re.findall(r"(?i)\bp\s*[=<]\s*(0?\.\d+)", z)
            if ps_:
                txt.append((q["id"], z, ps_))
    out = []
    for lab, pid, name, pv in rows:
        w = [x for x in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", name.lower()) if x not in STOP]
        m = re.search(r"0?\.\d+", pv)
        if not w or not m or len(name) > 60:
            continue
        for tid, z, ps_ in txt:
            if name.lower() in z.lower() and len(ps_) == 1 and abs(float(ps_[0]) - float(m.group(0))) > 1e-9 and not pv.startswith("<"):
                out.append("%s row '%s' p %s (%s) vs text p %s (%s): %s" % (lab, name[:40], pv, pid, ps_[0], tid, z[:150]))
    return out[:8]


def cmd_audit(a):
    """Internal-consistency scan of the material: leads to check, not conclusions."""
    ps = get_index()["passages"]
    out = []
    ns = {}
    for q in ps:
        for m in re.finditer(r"(?i)\b([nN])\s*=\s*(\d[\d,]*)", q["text"]):
            ns.setdefault(m.group(2).replace(",", ""), []).append(q["id"])
    if ns:
        out.append("SAMPLE SIZES n = value: passages (check that the n you print belongs to that analysis)")
        for v, ids in sorted(ns.items(), key=lambda t: -len(t[1]))[:18]:
            out.append("  n=%s: %s" % (v, ", ".join(dict.fromkeys(ids))[:90]))
    bad, ratio = [], {}
    for q in ps:
        for m in re.finditer(r"(\d{1,6})\s*(?:/|of|out of)\s*(\d{1,6})\s*[\(\[,;]?\s*(\d{1,3}(?:\.\d+)?)\s?%", q["text"]):
            x, y, z = float(m.group(1)), float(m.group(2)), float(m.group(3))
            if y and x <= y:
                if abs(100 * x / y - z) > max(.6, .006 * z):
                    bad.append("  %s: '%s' but %g/%g = %.2f%%" % (q["id"], m.group(0)[:40], x, y, 100 * x / y))
                ratio.setdefault(z, set()).add((x, y))
    for z, v in ratio.items():
        if len(v) > 1:
            bad.append("  %g%% is given for different counts: %s" % (z, sorted(v)))
    if bad:
        out.append("PERCENTAGES THAT DO NOT MATCH THEIR COUNTS")
        out += bad[:12]
    # the same decimal quantity with opposite sign or a near-duplicate label
    val = {}
    for q in ps:
        for n in numbers(q["text"]):
            if "." in n and len(n.strip("-")) >= 4:
                val.setdefault(n.lstrip("-"), {}).setdefault(n.startswith("-"), []).append(q["id"])
    flips = ["  %s appears as +%s (%s) and -%s (%s)" % (k, k, ",".join(dict.fromkeys(v[False]))[:30], k, ",".join(dict.fromkeys(v[True]))[:30]) for k, v in val.items() if len(v) == 2]
    if flips:
        out.append("SAME NUMBER WITH BOTH SIGNS")
        out += flips[:8]
    dates = {}
    for q in ps:
        for m in re.finditer(r"\b((?:\d{1,2}\s+)?(?:Jan|Feb|Mar|Apr|May|June?|July?|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(?:\d{1,2},?\s+)?(?:19|20)\d\d)", q["text"]):
            dates.setdefault(m.group(1), []).append(q["id"])
    if dates:
        out.append("DATES: " + "; ".join("%s (%s)" % (k, ",".join(dict.fromkeys(v))[:20]) for k, v in list(dates.items())[:16]))

    def snip(rx, title, cap):
        hits = []
        for q in ps:
            for sent in re.split(r"(?<=[.!?])\s+", q["text"]):
                m = rx.search(sent)
                if m and len(sent) > 25:
                    i = max(0, m.start() - 70)
                    hits.append("  %s ...%s..." % (q["id"], sent[i:i + 170]))
                    break
        if hits:
            out.append("%s (%d passages; the first %d)" % (title, len(hits), min(cap, len(hits))))
            out.extend(hits[:cap])
    hl = hard_leads()
    if hl:
        out.insert(0, "LIKELY ERRORS IN THE SOURCE (record each with both readings; never repair silently)\n" + "\n".join("  %s: %s [%s]" % (x["kind"], x["detail"][:200], ", ".join(x["ids"])) for x in hl))
    try:
        pl = p_leads()
    except Exception:
        pl = []
    if pl:
        out.append("P-VALUES: TABLE VERSUS TEXT")
        out += ["  " + x for x in pl]
    snip(NEGATE, "NEGATIVE / MISSING / LIMITING / CORRECTION STATEMENTS", 20)
    snip(HEDGE, "HEDGED OR PROPOSED STATEMENTS", 12)
    for t in get_index()["tables"]:
        try:
            cols, rows = read_table(t["file"])
        except Exception:
            continue
        miss = {c: sum(1 for r in rows if kit_table.num(r[c]) is None and str(r[c]).strip() in ("", "NA", "N/A", "nan", "-", "ND")) for c in cols}
        out.append("TABLE %s: blanks per column %s" % (t["file"], {k: v for k, v in miss.items() if v} or "none"))
    txt = "\n".join(out)
    say(txt[:8500])
    say("These are leads. Open the passages that touch your product, and record each real conflict or gap in `unresolved` (both values, both passages).")


STOP = set("the and for with from that this were was are has have had not but its our their than then also into over under each per all any can may which been being more most less least between among after before during both such these those only other".split())


def auto_match(text, k=1, floor=.5):
    """Passages that carry the same numbers and most of the terms of a carried-over sentence; nothing is returned when support is loose."""
    words = {w for w in re.findall(r"[a-z\u4e00-\u9fff][a-z\u4e00-\u9fff0-9-]{2,}", text.lower()) if w not in STOP}
    nums = {n for n in numbers(text) if n not in SMALL_INT}
    if len(words) + len(nums) < 4:
        return []
    out = []
    for q in get_index()["passages"]:
        low = q["text"].lower()
        have = set(numbers(q["text"]))
        hit = sum(1 for w in words if w in low)
        nh = len(nums & have)
        score = (hit + 2.0 * nh) / (len(words) + 2.0 * len(nums))
        min_hit = 0 if len(nums) >= 3 and nh == len(nums) else 2  # three or more numbers all present: the numbers carry the match
        if score < floor or hit < min_hit or (nums and nh < len(nums)) or (not nums and (hit < 4 or hit < .6 * len(words))):
            continue
        quote = best_quote(text, q["text"])
        qn = set(numbers(quote))
        if nums and not nums <= qn:  # the quote shown must carry every number of the claim
            parts = [quote]
            for z in re.split(r"(?<=[.!?;])\s+", q["text"]):
                if len(parts) >= 3 or nums <= qn:
                    break
                if set(numbers(z)) & (nums - qn) and z not in parts:
                    parts.append(z.strip()[:240])
                    qn |= set(numbers(z))
            quote = " ... ".join(parts)
        if nums and not nums <= set(numbers(quote)):
            continue
        out.append((score, q, quote, nh))
    out.sort(key=lambda t: -t[0])
    return [{"id": q["id"], "file": q["file"], "locator": q["loc"], "label": q.get("label", ""), "quote": quote,
             "match": "candidate support: same numbers %d of %d (all in the quote), term overlap score %.2f; matched by the engine, not checked clause by clause" % (nh, len(nums), sc)} for sc, q, quote, nh in out[:k]]


def numbers_absent(text):
    """Numbers that occur nowhere in the indexed material or tables."""
    global _ALLNUM
    if _ALLNUM is None:
        _ALLNUM = set()
        for q in get_index()["passages"]:
            _ALLNUM.update(n.lstrip("-") for n in numbers(q["text"]))
        for t in get_index()["tables"]:
            try:
                for r in read_table(t["file"])[1]:
                    for v in r.values():
                        _ALLNUM.update(n.lstrip("-") for n in numbers(str(v)))
            except Exception:
                pass
    return [n for n in numbers(text) if n.lstrip("-") not in _ALLNUM and n not in SMALL_INT]


_ALLNUM = None


NULLISH = re.compile(r"(?i)\b(no effect|no difference|no change|did not change|do(?:es)? not change|unchanged|not correlated|uncorrelated|no correlation|no association|equal to|the same as|identical (?:to|in)|had no influence|does not affect|did not affect)\b")
NULLISH2 = re.compile(r"(?i)\b(did not (?:increase|decrease|raise|reduce|lower|alter|differ|improve|worsen)|no (?:inverse |direct )?(?:relationship|link|relation)|not (?:associated|related) (?:with|to))\b")
CAUSAL = re.compile(r"(?i)\b(drives?|drove|driven by|causes?|caused by|leads? to|led to|results? in|due to|because of|proves?|proven|prevents?|determines?|improves?|improved by|is responsible for)\b")


def lint_text(text):
    """Wording that often overstates evidence; a prompt to check, not a verdict."""
    out = []
    m = NULLISH.search(text)
    if m and not re.search(r"(?i)signific|detect|statistic|not reported", text):
        out.append("'%s': absence of significance is not absence of effect - say 'no significant ... detected' (with p) unless the source shows equivalence" % m.group(0))
    m2 = NULLISH2.search(text) if not m else None
    if m2 and not re.search(r"(?i)signific|detect|statistic|not reported|fell|rose|declin|\d+(?:\.\d+)?\s*%", text):
        out.append("'%s': if this sums up a test that was not significant, say 'no significant ... detected' (with p); if the source reports a measured change or no test, keep the source's wording" % m2.group(0))
    m = CAUSAL.search(text)
    if m:
        out.append("'%s': keep only if the source establishes causation for exactly this design; otherwise use raised/lowered with, was associated with, tracked" % m.group(0))
    return out


def public_refs(text):
    """Replace internal passage ids (P012, P012-P015) in viewer-facing text by readable locators."""
    if not re.search(r"\bP\d{3}\b", str(text)):
        return text
    ps = {q["id"]: q for q in get_index()["passages"]}

    def lab(i):
        q = ps.get(i)
        if not q:
            return i
        return re.sub(r"~\d+$", "", (q.get("label") or q["loc"])).split(" > ")[-1]

    def rep(m):
        a, b = m.group(1), m.group(2)
        la = lab(a)
        if b and lab(b) != la:
            base = lambda t: re.sub(r",?\s*(row|para) \d+$", "", t)
            return base(la) if base(la) == base(lab(b)) else "%s to %s" % (la, lab(b))
        return la
    t = re.sub(r"\b(P\d{3})\b(?:\s*[-\u2013]\s*(P\d{3})\b)?", rep, str(text))
    return re.sub(r"\(([^()]+)(?:, \1)+\)", r"(\1)", t)


def must_lines():
    """Numbered/bulleted requirement lines of task.md and the work order, for ticking off."""
    out = []
    for p in (os.path.join(INPUT, "task.md"),):
        if os.path.exists(p):
            for ln in open(p, encoding="utf-8", errors="replace"):
                ln = ln.strip()
                if ln.startswith("#"):
                    out.append(ln)
                elif re.match(r"^(\d+[.)]|[-*])\s+", ln):
                    out.append("  " + ln[:330])
    c = get_case()
    for k in ("task", "instructions", "requirements", "must_show", "must_not"):
        v = c.get(k)
        if v:
            out.append("case.%s: %s" % (k, json.dumps(v, ensure_ascii=False)[:900]))
    wo = []
    for w in workorders():
        try:
            d = jload(w)
        except Exception:
            continue

        def walk(o, path):
            if isinstance(o, dict):
                for k, v in o.items():
                    walk(v, path + [k])
            elif isinstance(o, list):
                if all(scalar(x) for x in o):
                    wo.append("  %s: %s" % (".".join(path), "; ".join(map(str, o))[:420]))
                else:
                    for x in o:
                        walk(x, path)
            else:
                wo.append("  %s: %s" % (".".join(path), str(o)[:420]))
        walk(d, [])
    return out + (["WORK ORDER"] + wo if wo else [])


GENERIC_REQ = set("""figure panel slide slides deck task artifacts input output result results json field fields file files source sources material show shown must each every with from that this exactly least where which when what whether work order deliver deliverable deliverables export record recorded
svg png pdf pptx editable contract following following using used make made drawn draw drawing keep kept include including included listed list state stated stating give given text same other another only also than then them they there their should please needs need required requirement version original final stage stages first second third apply applied request requested edit edits edited change changed changes unchanged page pages number numbers value values name names label labels legend note notes caption title titles minutes audience template layout layouts placeholder placeholders
about above below between into onto over under after before during without within because per via not for the and are was were has have had its""".split())


def coverage(blob, least=.5):
    """Requirement lines whose own terms are largely absent from the delivered text."""
    low = re.sub(r"[\s_\-]+", " ", blob.lower())
    have = set(numbers(blob))
    rows = []
    for ln in must_lines():
        if ln.startswith("#") or ln == "WORK ORDER" or re.match(r"\s*(audience|consistency|keep_unchanged|records|deliverables|native|language)\b", ln):
            continue
        t = re.sub(r"`[^`]*`", " ", ln)
        words = [w for w in dict.fromkeys(re.findall(r"[a-z][a-z0-9]{3,}|[\u4e00-\u9fff]{2,}", re.sub(r"[_\-]", " ", t.lower()))) if w not in GENERIC_REQ and w not in STOP]
        nums = [n for n in numbers(t) if n not in SMALL_INT and len(n) > 1]
        if len(words) + len(nums) < 3:
            continue
        miss = [w for w in words if w[:max(4, len(w) - 2)] not in low] + [n for n in nums if n not in have]
        cov = 1 - len(miss) / float(len(words) + len(nums))
        if cov < least:
            rows.append((cov, ln.strip(), miss))
    rows.sort(key=lambda r: r[0])
    return rows


def table_gaps(text):
    """Rows of a source table that the delivery uses in part: which row labels are not shown."""
    low = re.sub(r"[\s\-\u2010-\u2015_]+", " ", text.lower())
    tabs = {}
    for q in get_index()["passages"]:
        lab = str(q.get("label") or "")
        if re.match(r"(?i)table\s*\w+", lab) and q["text"].count("|") >= 1:
            c = [x.strip() for x in re.split(r"\s*\|\s*", q["text"])]
            if c and re.search(r"[A-Za-z\u4e00-\u9fff]{3}", c[0]) and any(re.search(r"\d", x) for x in c[1:]):
                tabs.setdefault(re.split(r",", lab)[0], []).append((q["id"], c))
    out = []
    for lab, rows in tabs.items():
        if not 4 <= len(rows) <= 40:
            continue
        seen = lambda c: re.sub(r"[\s\-\u2010-\u2015_]+", " ", re.sub(r"\(.*?\)|\^\S+", "", c[0]).lower()).strip() in low
        hit = [r for r in rows if seen(r[1])]
        miss = [r for r in rows if not seen(r[1])]
        if len(hit) >= max(2, .3 * len(rows)) and miss:
            out.append("%s: %d of %d rows shown; not shown: %s" % (lab, len(hit), len(rows), "; ".join("%s %s" % (i, " | ".join(c)[:90]) for i, c in miss[:9])))
    return out[:4]


def missing_facts(text):
    """For each must-show item: printed values in its best-matching sentences that the delivery does not contain."""
    have = set(numbers(text))
    out, used, seen = [], 0, set()
    for it in walk_items()[0][:12]:
        rows = []
        for q, t in rank_passages(it, 4, 4000):
            hits = []
            for z in re.split(r"(?<=[.!?;])\s+", t):
                nn = [x for x in dict.fromkeys(numbers(z)) if x not in have and len(x.strip("-+")) > 1 and (("." in x) or ("%" in z)) and x not in seen]
                if len(nn) >= 1:
                    hits.append((z, nn))
            for z, nn in hits[:2]:
                rows.append((q["id"], z, nn))
                seen.update(nn)
        rows = rows[:3]
        if rows:
            out.append((it, rows))
            used += sum(min(260, len(r[1])) for r in rows)
        if used > 3200:
            break
    return out


def print_must(blob, cap=5200, visible=None):
    t = "\n".join(must_lines())
    say("\n# REQUIREMENTS - tick off one by one; for each name in two words where it is, or fix it")
    say(t[:cap] + ("\n...(read task.md for the rest)" if len(t) > cap else ""))
    rows = coverage(blob + " " + (visible or ""))
    if visible:
        done = {ln for _, ln, _ in rows}
        only = [(c, ln, m) for c, ln, m in coverage(visible, .55) if ln not in done and re.search(r"must.?show|show|label|mark|state|include|depict|draw|indicate", ln, re.I)]
        if only:
            say("\n# NOT VISIBLE ON THE FIGURE - terms exist only in caption/result.json; a reader sees only the figure, so put must-show facts on it (node note, edge label, text item, footnote):")
            for cov, ln, miss in only[:10]:
                say("  - %s\n        not on the figure: %s" % (ln[:170], ", ".join(miss[:9])))
    if rows:
        say("\n# POSSIBLY MISSING - terms of these requirement lines do not occur in what you delivered (check the meaning, not the wording):")
        for cov, ln, miss in rows[:14]:
            say("  [%d%%] %s\n        absent terms: %s" % (round(100 * cov), ln[:170], ", ".join(miss[:9])))
    else:
        say("\n# every requirement line shares most of its terms with the delivered text")
    try:
        tg = table_gaps(visible or blob)
    except Exception:
        tg = []
    if tg:
        say("\n# TABLE ROWS NOT SHOWN (if the order asks for all changed and unchanged results, every row of that group belongs in, with value and p):")
        for x in tg:
            say("  " + x)
    try:
        facts = missing_facts((visible or blob))
    except Exception:
        facts = []
    if facts:
        say("\n# NUMBERS IN THE BEST PASSAGES OF EACH REQUIREMENT that are not in the delivery (add those the requirement asks for, e.g. every mean with its p; ignore the rest):")
        for it, rows_ in facts:
            say("  REQUIREMENT: %s" % it[:150])
            for pid_, t_, nn in rows_:
                say("     %s absent %s <- %s" % (pid_, ", ".join(nn[:10]), t_[:260]))
    cf = os.path.join(WORK, ".reviews")
    n = (int(open(cf).read()) if os.path.exists(cf) else 0) + 1
    open(cf, "w").write(str(n))
    if elapsed() > 5.5:
        say("\nreview %d at %.1f min: little time left. One batch only: correct errors of fact (wrong sign, direction, number, citation), do the requested edit if still missing, verify, stop." % (n, elapsed()))
    else:
        say("\nreview %d at %.1f min (hard limit 15, aim to finish by 10). Fix real gaps now, 4-6 at a time, each batch one short command; do not think all of them through at once. Accuracy and completeness weigh more than speed." % (n, elapsed()))


def review_state():
    """(reviews done, reviewed after the last build?)"""
    cf, bf = os.path.join(WORK, ".reviews"), os.path.join(OUT, "result.json")
    if not os.path.exists(cf):
        return 0, False
    return int(open(cf).read() or 0), os.path.getmtime(cf) >= os.path.getmtime(bf) - 1


# --- sources -------------------------------------------------------------------
def resolve_src(src, problems, where):
    """src entries: P012 | P012-P014 | file.csv | file.csv#3-9 | workorder | task"""
    idx = get_index()
    ps = {q["id"]: q for q in idx["passages"]}
    out = []
    items = src if isinstance(src, list) else ([src] if src else [])
    for s in items:
        quote = None
        if isinstance(s, dict):
            quote = s.get("quote")
            s = s.get("id") or s.get("ref") or s.get("file") or ""
        s = str(s).strip()
        m = re.match(r"^P(\d+)(?:-P?(\d+))?$", s)
        if m:
            a = int(m.group(1))
            b = int(m.group(2) or a)
            if b - a > 8:
                problems.append("%s: source range %s too wide; cite the exact passage" % (where, s))
            for k in range(a, min(b, a + 8) + 1):
                q = ps.get("P%03d" % k)
                if not q:
                    problems.append("%s: passage P%03d does not exist" % (where, k))
                    continue
                rec = {"id": q["id"], "file": q["file"], "locator": q["loc"], "label": q.get("label", "")}
                if quote:
                    if clean(quote).lower() in q["text"].lower():
                        rec["quote"] = clean(quote)
                    else:
                        problems.append("%s: quote not found verbatim in %s: %s" % (where, q["id"], quote[:60]))
                        rec["quote_unverified"] = quote
                else:
                    rec["text"] = q["text"]
                out.append(rec)
        elif s.lower() in ("workorder", "task", "task.md", "case.json"):
            out.append({"id": s, "file": rel(workorders()[0]) if s.lower() == "workorder" and workorders() else s, "locator": "whole file"})
        else:
            f = s.split("#")[0]
            try:
                p = table_path(f)
                out.append({"id": s, "file": rel(p) if p.startswith(INPUT) else f, "locator": ("rows " + s.split("#")[1]) if "#" in s else ("whole table" if re.search(r"(?i)\.(csv|tsv|json|xlsx)", f) else "whole file")})
            except Exception:
                problems.append("%s: unknown source '%s' (use P###, a data file, or workorder)" % (where, s))
    return out


def tidy(src, label=""):
    """Replace full passage text by the best matching sentence before a record is written."""
    for x in src or []:
        if x.get("text"):
            x["quote"] = best_quote(label, x.pop("text"))
    return src


def unreadable_inputs():
    """Input files that gave no text or table: must be disclosed."""
    idx = get_index()
    seen = {q["file"] for q in idx["passages"]} | {t["file"].split("!")[0] for t in idx["tables"]}
    out = []
    for o in idx["others"]:
        name = o.split(" (unreadable")[0]
        if "(unreadable" in o:
            out.append({"item": name, "state": "unreadable input", "detail": o})
        elif name.lower().endswith(".pdf") and name not in seen:
            out.append({"item": name, "state": "unreadable input", "detail": "no text layer could be extracted (scanned, image-only or encrypted); inspect it with pdftoppm/OCR and cite the page, or leave its content out"})
    return out


def core_name(label):
    """The entity behind a label: pHER2 -> HER2, 'ADAM17 mRNA (up)' -> ADAM17."""
    t = re.sub(r"\(.*?\)|[*_{}^]", " ", str(label))
    t = re.sub(r"(?i)\b(mrna|protein|sirna|inhibitor|inhibition|phosphorylation|activity|level|levels|expression|amount|up|down|nuclear|active|signal|tank|step|\d+\s*(L|mL|h|d|days?|min))\b", " ", t)
    toks = [w for w in re.findall(r"[A-Za-z0-9\u4e00-\u9fff/+-]{2,}", t) if w.lower() not in STOP]
    if not toks:
        return ""
    w = max(toks, key=lambda x: (bool(re.search(r"\d|[A-Z]{2}", x)), len(x)))
    return re.sub(r"^p(?=[A-Z0-9])", "", w).lower().rstrip("s")


def mentions(text, name):
    if not name:
        return True
    sq = lambda t: re.sub(r"[\s\-\u2010-\u2015]+", "", t.lower())
    return sq(name) in sq(text) or (len(name) > 5 and sq(name)[:5] in sq(text))


def better_citation(a, b, words, skip=()):
    """The passage sentence that names both ends of a relation, best match on the remaining words."""
    best = (0, None, "")
    for q in get_index()["passages"]:
        if q["id"] in skip or not (mentions(q["text"], a) and mentions(q["text"], b)):
            continue
        lab = str(q.get("label") or q["loc"]).lower()
        bonus = -.6 if re.search(r"abstract|introd", lab) else .3 if "result" in lab or re.match(r"p\d|fig", lab) else 0
        ss = re.split(r"(?<=[.!?;])\s+", q["text"])
        for z in ss:
            if mentions(z, a) and mentions(z, b) and len(z) < 520:
                sc = 2 + bonus + sum(.7 for w in words if w in z.lower())
                if sc > best[0]:
                    best = (sc, q["id"], z)
    return best[1], best[2]


PROPOSAL_ = re.compile(r"(?i)\b(propos\w*|hypothes\w*|postulat\w*|speculat\w*|putative|presumabl\w*|may|might|could(?! not)|possibl\w*|we (?:suggest|think|believe|envisage)|(?:our|a|the) (?:working |proposed )?model (?:in which|where|whereby|that|of))\b")
CORREL_ = re.compile(r"(?i)\b(correlat\w*|associated with|association (?:between|with)|coincid\w* with)\b")
PRIOR_ = re.compile(r"(?i)(\[\d+(?:\s*[,\u2013-]\s*\d+)*\]|\bet al\b|\bpreviously (?:been )?(?:shown|reported|described|demonstrated)|\b(?:has|have) (?:previously )?been (?:shown|reported|described|demonstrated)|\bis known to\b|\bare known to\b)")
OWN_ = re.compile(r"(?i)\b(we (?:show|showed|found|find|demonstrat\w*|observed|detected|confirmed)|here,? we|in this study|our (?:data|results) (?:show|demonstrate))\b")


CLAUSE_ = re.compile(r",\s+(?=(?:in contrast|correlating|consistent|suggesting|indicating|which|whereas|while|although|but|and (?:this|these|that|thus))\b)|;\s+|\s+(?=(?:but|whereas)\b)")


MECH_TYPES_ = ("activation", "inhibition", "binding", "phosphorylation", "modification", "dimerisation", "cleavage", "degradation", "transport", "expression", "conversion", "causal", "signal")


def _hit(z, n):
    return mentions(z, n) or (len(re.sub(r"[\d/]+$", "", n)) >= 3 and mentions(z, re.sub(r"[\d/]+$", "", n)))


def strength_pass(spec):
    """Evidence class from the source wording. A relation drawn as stated whose every cited sentence naming both ends
    only proposes it, only correlates the two, or only reports earlier work is drawn as proposed / association / cited.
    One plain sentence keeps it as stated. Returns the list of changes (also kept in spec['_strength'])."""
    out = []
    for p in spec.get("panels") or []:
        if not isinstance(p, dict):
            continue
        lab = {str(n.get("id")): str(n.get("label") or n.get("id")) for n in p.get("nodes") or [] if isinstance(n, dict)}
        for e in p.get("edges") or []:
            if not isinstance(e, dict) or e.get("evidence_class_locked") or str(e.get("type") or "activation") not in MECH_TYPES_:
                continue
            cert = str(e.get("certainty") or "").strip().lower()
            if cert not in ("", "stated", "observed", "shown", "measured", "this study"):
                continue
            a_, b_ = core_name(lab.get(str(e.get("from")), e.get("from"))), core_name(lab.get(str(e.get("to")), e.get("to")))
            if len(a_) < 2 or len(b_) < 2 or a_ == b_:
                continue
            try:
                src = resolve_src(e.get("src"), [], "strength")
            except Exception:
                continue
            sents = []
            for s_ in src:
                for z in re.split(r"(?<=[.!?;])\s+", str(s_.get("text") or s_.get("quote") or "")):
                    if len(z) < 600 and _hit(z, a_) and _hit(z, b_):
                        parts = [c for c in CLAUSE_.split(z) if c and _hit(c, a_) and _hit(c, b_)]
                        for c in (parts or [z]):
                            sents.append((s_.get("id"), c.strip()))
            if not sents:
                continue
            if any(not PROPOSAL_.search(z) and not CORREL_.search(z) and not (PRIOR_.search(z) and not OWN_.search(z)) for _, z in sents):
                continue
            pid_, z = sents[0]
            if all(PROPOSAL_.search(q) for _, q in sents):
                new, why = "proposed", "proposes it"
            elif all(CORREL_.search(q) or PROPOSAL_.search(q) for _, q in sents):
                new, why = "association", "only correlates the two"
            else:
                new, why = "cited", "reports it from earlier work"
            old = {"type": e.get("type"), "certainty": e.get("certainty")}
            if new == "association":   # the sign the authors give stays; the line shows it is not established
                e["certainty"] = "proposed"
                if "correlat" not in str(e.get("label") or "").lower():
                    e["label"] = (str(e.get("label") or "") + " (correlation)").strip()
            else:
                e["certainty"] = new
            e["evidence_class_locked"] = True
            rec = {"from": e.get("from"), "to": e.get("to"), "panel": p.get("id"), "was": old, "now": {"type": e.get("type"), "certainty": e.get("certainty")},
                   "reason": "every cited sentence naming both ends %s" % why, "source": pid_, "quote": z[:300]}
            spec.setdefault("_strength", []).append(rec)
            out.append("EVIDENCE CLASS %s -> %s drawn %s: the cited sentence %s (%s: %s). If another sentence shows it directly, cite that one instead." % (
                lab.get(str(e.get("from")), e.get("from")), lab.get(str(e.get("to")), e.get("to")), {"association": "dashed with its sign, labelled (correlation)", "proposed": "dashed as proposed", "cited": "grey as cited literature"}[new], why, pid_, z[:160]))
    return out


GENE_ = re.compile(r"\b(?:p-?)?([A-Z][A-Za-z]{0,6}[0-9][A-Za-z0-9/-]{0,6}|[A-Z]{2,}[A-Za-z0-9/-]{0,6})\b")
NOT_GENE_ = {"DNA", "RNA", "MRNA", "SIRNA", "PCR", "QPCR", "ELISA", "FRET", "FLIM", "PBS", "DMSO", "TKI", "HRP", "SD", "SE", "SEM", "CI", "WT", "KO", "MAB", "FIG", "FIGS", "UK", "USA", "ER", "PR", "OD", "UV", "TAPI"}


def chain_gaps(spec, limit=4):
    """Entities a cited sentence names between the two ends of a drawn relation that are not drawn themselves."""
    out = []
    for p in spec.get("panels") or []:
        if not isinstance(p, dict) or not p.get("edges"):
            continue
        labs = " ".join(str(n.get("label") or "") + " " + str(n.get("id") or "") + " " + str(n.get("note") or "") for n in p.get("nodes") or [] if isinstance(n, dict))
        drawn = set()
        for w in re.findall(r"[A-Za-z0-9/-]{2,}", labs):
            for v in (w, re.sub(r"^p(?=[A-Z0-9])", "", w), re.sub(r"[\d/]+$", "", w), re.sub(r"[\d/]+$", "", re.sub(r"^p(?=[A-Z0-9])", "", w))):
                v = re.sub(r"[^a-z0-9]", "", v.lower())
                if len(v) >= 2:
                    drawn.add(v)
        lab = {str(n.get("id")): str(n.get("label") or n.get("id")) for n in p.get("nodes") or [] if isinstance(n, dict)}
        for e in p["edges"]:
            if not isinstance(e, dict) or str(e.get("type") or "activation") not in MECH_TYPES_:
                continue
            a_, b_ = core_name(lab.get(str(e.get("from")), e.get("from"))), core_name(lab.get(str(e.get("to")), e.get("to")))
            if len(a_) < 2 or len(b_) < 2:
                continue
            try:
                src = resolve_src(e.get("src"), [], "chain")
            except Exception:
                continue
            for s_ in src:
                for z in re.split(r"(?<=[.!?;])\s+", str(s_.get("text") or "")):
                    zl = re.sub(r"[\s\-\u2010-\u2015]+", "", z.lower())
                    ia, ib = zl.find(re.sub(r"[\s\-]+", "", a_)), zl.find(re.sub(r"[\s\-]+", "", b_))
                    if ia < 0 or ib < 0 or abs(ia - ib) < 4:
                        continue
                    lo, hi = sorted((ia, ib))
                    mid = []
                    for m in re.finditer(r"\b(?:via|through|by)\s+(?:the\s+)?([A-Z][a-z]{1,5}\d?)\s+(?:inhibition|activation|phosphorylation|signalling|signaling|kinase|binding)\b", z):
                        t = m.group(1)
                        k = t.lower()
                        if lo < zl.find(k) < hi and k not in drawn:
                            mid.append(t)
                    for m in GENE_.finditer(z):
                        t = m.group(1)
                        k = re.sub(r"[^a-z0-9]", "", t.lower())
                        if re.sub(r"[\d/]+$", "", t).lower().replace("-", "") in drawn:
                            continue
                        pos = zl.find(k)
                        if re.match(r"(?i)^(?:[\s,]+(?:and|or)?\s*[A-Za-z0-9-]{2,12}){0,3}\s+(?:cells?|cell lines?|xenografts?|tumou?rs?|mice)\b", z[m.end():]):
                            continue
                        if lo < pos < hi and t.upper() not in NOT_GENE_ and k not in drawn and k.rstrip("s") not in drawn and not re.fullmatch(r"[A-Z]?\d+[A-Za-z]?", t):
                            mid.append(t)
                    if mid:
                        out.append("CHAIN GAP %s -> %s: %s names %s between them (\"%s\"). If it is a step of this relation, draw it (cited steps grey, with the reference)." % (
                            lab.get(str(e.get("from")), e.get("from")), lab.get(str(e.get("to")), e.get("to")), s_.get("id"), ", ".join(dict.fromkeys(mid)), z.strip()[:200]))
                        break
                if len(out) >= limit:
                    return out
    return out


def best_quote(label, rec_text, must=()):
    words = [w for w in re.findall(r"[A-Za-z0-9一-鿿.+-]{2,}", label.lower()) if w not in ("the", "and", "of", "in", "to", "by")]
    best, score = "", -1
    for sent in re.split(r"(?<=[.!?。])\s+", rec_text):
        low = sent.lower()
        sc = sum((3 if re.search(r"\d", w) else 1) for w in words if w in low)
        for name in must:
            toks = [w for w in re.findall(r"[A-Za-z0-9\u4e00-\u9fff-]{2,}", str(name).lower()) if w not in STOP]
            if toks and any(w in low for w in toks):
                sc += 4
        if sc > score:
            best, score = sent, sc
    if len(best) <= 240:
        return best
    # a long sentence: show the 240-character stretch that carries the label's numbers and words, not just its start
    nums_ = [w for w in words if re.search(r"\d", w)]
    top, at = -1, 0
    for st in range(0, len(best) - 200, 30):
        win = best[st:st + 240].lower()
        sc = sum(3 for w in nums_ if re.search(r"(?<![\d.])" + re.escape(w) + r"(?![\d])", win)) + sum(1 for w in words if w in win)
        if sc > top:
            top, at = sc, st
    return ("\u2026" if at else "") + best[at:at + 240] + ("\u2026" if at + 240 < len(best) else "")



NUM = re.compile(r"(?<![A-Za-z0-9_.])(?<![A-Za-z][-\u2010\u2011\u2212])[-\u2212+]?\d[\d,]*(?:\.\d+)?(?:\s?[x\u00d7]\s?10\^?\{?[-\u2212]?\d+\}?)?%?")


def norm_num(t):
    return t.replace("\u2212", "-").replace(",", "").replace("\u00d7", "x").replace(" ", "").replace("{", "").replace("}", "").lstrip("+").rstrip("%")


def numbers(text):
    out = []
    for m in NUM.finditer(re.sub(r"(?<![\dA-Za-z%)])\s*[\u2013\u2014](?=\d)", " -", text).replace("\u2013", " ").replace("\u2014", " ")):
        n = norm_num(m.group(0))
        if n and n not in out:
            out.append(n)
    return out


def source_blob(src):
    """Full text behind src ids, for number tracing."""
    idx = get_index()
    ps = {q["id"]: q["text"] for q in idx["passages"]}
    blob = []
    for s in (src if isinstance(src, list) else [src] if src else []):
        if isinstance(s, dict):
            s = s.get("id") or s.get("ref") or s.get("file") or ""
        m = re.match(r"^P(\d+)(?:-P?(\d+))?$", str(s).strip())
        if m:
            for k in range(int(m.group(1)), min(int(m.group(2) or m.group(1)), int(m.group(1)) + 8) + 1):
                blob.append(ps.get("P%03d" % k, ""))
        else:
            f = str(s).split("#")[0]
            if f.lower() in ("workorder", "task", "task.md", "case.json"):
                for p in (workorders() if f.lower() == "workorder" else [os.path.join(INPUT, "task.md"), os.path.join(INPUT, "case.json")]):
                    if os.path.exists(p):
                        blob.append(open(p, encoding="utf-8", errors="replace").read())
                continue
            try:
                cols, rows = read_table(f)
                m = re.search(r"#(\d+)(?:-(\d+))?", str(s))
                if m:
                    rows = rows[int(m.group(1)) - 1:int(m.group(2) or m.group(1))]
                blob.append(" ".join(cols))
                blob += [" ".join(str(v) for v in r.values()) for r in rows]
            except Exception:
                pass
    return " ".join(blob)


SMALL_INT = {str(k) for k in range(0, 4)}


def trace_numbers(text, src):
    """Numbers in `text` that do not occur in the cited sources (exact after normalisation)."""
    blob = source_blob(src)
    have = set(numbers(blob))
    flt = set()
    for h in have:
        try:
            flt.add(float(h))
        except ValueError:
            pass
    miss = []
    for n in numbers(text):
        if n in have:
            continue
        if n in SMALL_INT and not re.search(r"(?i)\bn\s*=\s*%s\b" % re.escape(n), text):
            continue
        try:
            if float(n) in flt:
                continue
            if -float(n) in flt:
                miss.append(n + " (sign differs from source)")
                continue
        except ValueError:
            pass
        if re.search(r"(?<![\d.])%s(?![\d])" % re.escape(n), norm_num(blob)):
            continue
        miss.append(n)
    return miss


def write_result(d):
    base = {k: None for k in contract()}
    cid = case_id()
    base.update({"case_id": cid})
    base.update(d)
    base["case_id"] = cid
    for k, v in (("editable_source", {}), ("export_artifact", {}), ("content_map", []), ("compliance_checks", []), ("exceptions", [])):
        if base.get(k) is None and (k in contract() or k in CONTRACT):
            base[k] = v
    base.setdefault("status", "partial")
    base["delivery_report"] = os.path.join(OUT, "REPORT.md")
    jsave(os.path.join(OUT, "result.json"), base)
    try:
        write_report(base)
    except Exception as exc:  # the report never blocks the delivery
        base.pop("delivery_report", None)
        jsave(os.path.join(OUT, "result.json"), base)
        say("(report skipped: %s)" % exc)
    return base


def _cell(t, n=160):
    t = re.sub(r"\s+", " ", str(t if t is not None else "")).replace("|", "/")
    return t if len(t) <= n else t[:n - 1] + "\u2026"


def write_report(r):
    """REPORT.md: a reader's summary of result.json - what was delivered, which requirement lines it answers, what was checked, what is open."""
    cm = r.get("content_map") or []
    ck = r.get("compliance_checks") or []
    ex = r.get("exceptions") or []
    L = ["# Delivery report: %s" % (r.get("case_id") or "case"), ""]
    L.append("Status: **%s**. Written by the engine from `result.json` (the full record; this page only summarises it)." % r.get("status"))
    if r.get("title"):
        L.append("Title: %s" % _cell(r.get("title"), 300))
    L += ["", "## Files", "", "| file | what | check |", "|---|---|---|"]
    es = r.get("editable_source") or {}
    if es.get("path"):
        L.append("| `%s` | editable source (%s) | sha256 %s |" % (os.path.basename(str(es["path"])), _cell(es.get("format", ""), 60), str(es.get("sha256", ""))[:12]))
    for k, v in (r.get("export_artifact") or {}).items():
        if isinstance(v, dict) and v.get("path"):
            info = ", ".join("%s %s" % (q, v[q]) for q in ("pixels", "dpi", "pages", "bytes") if v.get(q) is not None)
            L.append("| `%s` | %s | %s |" % (os.path.basename(str(v["path"])), k, _cell(info, 80)))
    if (r.get("edit_record") or r.get("change_record")):
        L.append("| `edit_record.json` / change record | requested edit, element-by-element comparison with the first version | see below |")
    srcd = sum(1 for c in cm if c.get("source"))
    L += ["", "## Traceability", "", "%d mapped elements, %d with a cited source (file, locator and quote in `result.json` -> content_map)." % (len(cm), srcd)]
    unc = [c for c in cm if str(c.get("certainty") or "") not in ("", "stated", "observed")]
    if unc:
        L.append("%d elements are drawn or written as not established (proposed, cited literature, uncertain): %s." % (len(unc), "; ".join(_cell("%s -> %s %s" % (c.get("from", ""), c.get("to", ""), c.get("certainty")) if c.get("from") else "%s %s" % (c.get("label") or c.get("element_id"), c.get("certainty")), 60) for c in unc[:8])))
    L += ["", "## Checks on the delivered files", "", "| check | result | detail | method |", "|---|---|---|---|"]
    for c in ck:
        L.append("| %s | %s | %s | %s |" % (c.get("check"), c.get("result"), _cell(c.get("detail"), 180), _cell(c.get("method"), 80)))
    npass = sum(1 for c in ck if c.get("result") == "pass")
    L.append("")
    L.append("%d of %d checks pass; the others are open and disclosed below." % (npass, len(ck)) if npass < len(ck) else "All %d checks pass." % len(ck))
    rec = r.get("edit_record") or r.get("change_record")
    if isinstance(rec, dict) and rec:
        L += ["", "## Requested edit", "", "- request: %s" % _cell(rec.get("request"), 300)]
        for k in ("changed", "added", "removed"):
            v = rec.get(k)
            if isinstance(v, list):
                L.append("- %s: %d %s" % (k, len(v), _cell(", ".join(str(x.get("id") if isinstance(x, dict) else x) for x in v[:12]), 260)))
        for k in ("unchanged_elements", "page_coordinate_system", "edit_scope", "outside_scope"):
            if rec.get(k) not in (None, [], ""):
                L.append("- %s: %s" % (k.replace("_", " "), _cell(rec.get(k), 260)))
    elif isinstance(rec, list) and rec:
        L += ["", "## Changes", ""] + ["- %s" % _cell(json.dumps(x, ensure_ascii=False), 220) for x in rec[:20]]
    L += ["", "## Exceptions, conflicts and limits (%d)" % len(ex), ""]
    for x in ex[:30]:
        if isinstance(x, dict):
            L.append("- **%s** - %s. %s" % (_cell(x.get("item"), 120), _cell(x.get("state"), 80), _cell(x.get("detail") if not isinstance(x.get("detail"), (dict, list)) else json.dumps(x.get("detail"), ensure_ascii=False), 220)))
        else:
            L.append("- %s" % _cell(x, 240))
    if not ex:
        L.append("None recorded.")
    rr = r.get("run_record") or {}
    pv = r.get("provenance") or {}
    L += ["", "## Reproduce", ""]
    if es.get("rebuild_command"):
        L.append("- rebuild from the delivered specification: `%s`" % es["rebuild_command"])
    L.append("- engine: %s; inputs hashed: %d%s" % (pv.get("engine", ""), len(pv.get("inputs") or []), "; builds in this run: %s, minutes: %s" % (rr.get("builds_so_far"), rr.get("minutes_since_start")) if rr else ""))
    open(os.path.join(OUT, "REPORT.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")


def check(name, ok, detail, method):
    return {"check": name, "result": "pass" if ok else "attention", "detail": detail, "method": method}


