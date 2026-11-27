#!/usr/bin/env python3
"""figkit - source-bound scientific figures from a small JSON spec.

  figkit.py brief                     read the case, index sources, save a first honest result.json
  figkit.py show P001-P010            print indexed passages
  figkit.py find WORD [WORD...]       search indexed passages
  figkit.py review                    every claim next to the sentence it cites, then the requirement list
  figkit.py audit                     internal conflicts, n values, percentages, limits and hedged statements
  figkit.py table FILE [a-b]          print rows of a data table
  figkit.py build                     spec.json -> figure.svg/png/pdf + checks + result.json
  figkit.py build --revise "what/why" same, after editing spec.json; keeps earlier geometry, records the diff
  figkit.py edit FILE.svg ops.json    element-level edit of a supplied SVG, byte-preserving elsewhere
  figkit.py svgtree FILE.svg          list editable elements of an SVG
  figkit.py verify                    re-check delivered files against result.json
  figkit.py selftest                  run the bundled synthetic example in a temporary folder
"""
import argparse
import csv
import difflib
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
import fk_chart  # noqa: E402
import fk_draw   # noqa: E402
import fk_export  # noqa: E402
from fk_flow import cmd_start, cmd_set, cmd_fromtable, cmd_prune  # noqa: E402
from fk_layout import Box  # noqa: E402
from fk_text import strip_markup, width  # noqa: E402


from kit_sources import (INPUT, WORK, OUT, CONTRACT, jload, jsave, say, walk_inputs, rel, clean, get_case, case_id, contract,  # noqa: E402
                         table_path, read_table, workorders, resolve_src, best_quote, tidy, unreadable_inputs, auto_exceptions, print_must, must_lines, core_name, mentions, better_citation, review_state, lint_text, public_refs, write_result, check, trace_numbers,
                         cmd_brief, cmd_show, cmd_find, cmd_table, cmd_audit, cmd_next, walking)

from kit_sources import elapsed as ks_elapsed  # noqa: E402

VERSION = "1.24.0"

# --- spec validation -------------------------------------------------------------
ALIAS_T = {"dimerization": "dimerisation", "dimerises": "dimerisation", "dimerizes": "dimerisation", "heterodimerisation": "dimerisation", "heterodimerization": "dimerisation", "homodimerisation": "dimerisation", "complex_formation": "dimerisation", "dimer": "dimerisation",
           "proteolysis": "cleavage", "proteolytic_release": "cleavage", "shedding": "cleavage", "sheds": "cleavage", "release": "cleavage", "releases": "cleavage", "cleaves": "cleavage", "degrades": "degradation",
           "activates": "activation", "activate": "activation", "promotion": "activation", "promotes": "activation", "stimulation": "activation",
           "inhibits": "inhibition", "inhibit": "inhibition", "repression": "inhibition", "suppression": "inhibition",
           "binds": "binding", "interaction": "binding", "arrow": "flow", "sequence": "flow", "leads_to": "flow", "next": "flow", "step": "flow",
           "translocation": "transport", "secretion": "transport", "transcription": "expression", "reaction": "conversion", "produces": "conversion",
           "phosphorylates": "phosphorylation", "ubiquitination": "modification", "correlation": "association", "associated": "association",
           "information": "data", "electrical": "energy", "heat": "energy", "optical": "energy", "light": "energy", "feedback": "return", "recycle": "return",
           "cause": "causal", "causes": "causal", "supports": "evidence", "part_of": "contains", "input": "dependency", "output": "flow", "water": "liquid", "mechanical": "assembly"}


def validate(spec):
    """Repair harmless variations in place; return (errors, warnings)."""
    err, warn = [], []
    if not isinstance(spec, dict):
        return ["spec.json must be a JSON object"], warn
    if "panels" not in spec and "nodes" in spec:
        spec["panels"] = [{"id": "A", "type": "diagram", **{k: spec.pop(k) for k in ("nodes", "edges", "groups", "direction") if k in spec}}]
    if not isinstance(spec.get("panels"), list) or not spec["panels"]:
        return ["spec needs a non-empty 'panels' list"], warn
    idset = set()
    for i, p in enumerate(spec["panels"]):
        p.setdefault("id", "ABCDEFGHIJKL"[i % 12])
        p["id"] = re.sub(r"[^A-Za-z0-9_]", "_", str(p["id"]))
        if p["id"] in idset:
            err.append("panel id '%s' repeated" % p["id"])
        idset.add(p["id"])
        t = p.get("type") or ("diagram" if "nodes" in p else "chart" if "data" in p else "text")
        if t in ("bar", "line", "scatter", "box", "heatmap", "forest", "stacked", "dot"):
            p["chart"], t = t, "chart"
        if t in ("bullets", "callout", "stats"):
            t = "text"
        if t in ("timeline", "gantt", "schedule"):
            t, p["timeline"] = "text", True
            good = []
            for it in p.get("items") or []:
                try:
                    if it.get("at") is not None:
                        it["at"] = [float(v) for v in (it["at"] if isinstance(it["at"], list) else [it["at"]])]
                        it["at"] = [int(v) if v == int(v) else v for v in it["at"]]
                        it.pop("start", None)
                    else:
                        for q in ("start", "end"):
                            v = float(it[q] if it.get(q) is not None else it["start"])
                            it[q] = int(v) if v == int(v) else v
                    if it.get("start") is not None and it["end"] < it["start"]:
                        raise ValueError
                    good.append(it)
                except (KeyError, TypeError, ValueError, AttributeError):
                    err.append("panel %s: timeline item needs lane, text and numeric start+end (start <= end) or at: %s" % (p["id"], str(it)[:90]))
            p["items"] = good
            if not good:
                err.append("panel %s: timeline has no items" % p["id"])
        if t in ("flow", "pathway", "schematic", "roadmap"):
            t = "diagram"
        p["type"] = t
        pid = p["id"]
        if p.get("title"):  # the panel letter is drawn by the engine
            p["title"] = re.sub(r"^\s*(?:panel\s+%s\b[\s.):\-\u2013\u2014]*|%s[.):]\s+)" % (re.escape(pid), re.escape(pid)), "", str(p["title"]), flags=re.I) or p["title"]
        if t == "diagram":
            nodes = p.get("nodes") or []
            if not nodes:
                err.append("panel %s: diagram has no nodes" % pid)
            nid = set()
            for n in nodes:
                if "id" not in n:
                    err.append("panel %s: node without id: %s" % (pid, str(n)[:60]))
                    n["id"] = "n%d" % len(nid)
                n["id"] = re.sub(r"[^A-Za-z0-9_.-]", "_", str(n["id"]))
                if n["id"] in nid:
                    err.append("panel %s: node id '%s' repeated" % (pid, n["id"]))
                nid.add(n["id"])
                n.setdefault("label", n["id"])
                if n.get("step") is not None:  # the number is drawn by the engine
                    n["label"] = re.sub(r"^\s*(?:step\s*)?%s\s*[.):]\s*" % re.escape(str(n["step"])), "", str(n["label"]), flags=re.I) or n["label"]
                k = str(n.get("kind", "concept")).lower().replace("-", "_").replace(" ", "_")
                if k not in fk_draw.KINDS:
                    warn.append("panel %s node %s: kind '%s' unknown, drawn as concept; kinds: %s" % (pid, n["id"], k, " ".join(fk_draw.KINDS)))
                    k = "concept"
                n["kind"] = k
                if n.get("glyph") and n["glyph"] not in fk_draw.GLYPHS:
                    warn.append("panel %s node %s: glyph '%s' unknown (ignored); available: %s" % (pid, n["id"], n["glyph"], " ".join(fk_draw.GLYPHS)))
                    n.pop("glyph")
            g = p.get("groups") or []
            p["groups"] = [x if isinstance(x, dict) else {"id": str(x), "label": str(x)} for x in g]
            for x in p["groups"]:
                x["id"] = re.sub(r"[^A-Za-z0-9_.-]", "_", str(x.get("id") or x.get("label")))
            gids = {x["id"] for x in p["groups"]}
            for n in nodes:
                if n.get("group"):
                    n["group"] = re.sub(r"[^A-Za-z0-9_.-]", "_", str(n["group"]))
                    if n["group"] not in gids:
                        p["groups"].append({"id": n["group"], "label": n["group"]})
                        gids.add(n["group"])
                        warn.append("panel %s: group '%s' was not declared; added" % (pid, n["group"]))
            for e in p.get("edges") or []:
                e["from"] = re.sub(r"[^A-Za-z0-9_.-]", "_", str(e.get("from", e.get("source", ""))))
                e["to"] = re.sub(r"[^A-Za-z0-9_.-]", "_", str(e.get("to", e.get("target", ""))))
                for end in ("from", "to"):
                    if e[end] not in nid:
                        err.append("panel %s: edge %s->%s refers to undefined node '%s'" % (pid, e["from"], e["to"], e[end]))
                ty = str(e.get("type", "flow")).lower().replace("-", "_").replace(" ", "_")
                ty = ALIAS_T.get(ty, ty)
                if ty not in fk_draw.EDGES:
                    err.append("panel %s: edge type '%s' unknown; types: %s" % (pid, ty, " ".join(fk_draw.EDGES)))
                    ty = "flow"
                e["type"] = ty
            p["edges"] = p.get("edges") or []
            FLOW = ("material", "gas", "liquid", "flow", "energy")
            kinds = {n["id"]: n["kind"] for n in nodes}
            for n in nodes:
                if n["kind"] in ("equipment", "instrument") and p["edges"]:
                    for fam, types in (("material/liquid/gas", ("material", "gas", "liquid", "return", "waste")),):
                        i_ = [e for e in p["edges"] if e["to"] == n["id"] and e["type"] in types]
                        o_ = [e for e in p["edges"] if e["from"] == n["id"] and e["type"] in types]
                        if i_ and not o_:
                            warn.append("panel %s flow continuity: '%s' receives %s but nothing leaves it - follow the source sentence for its outlet (or record it in unresolved)" % (pid, n["label"], fam))
                        elif i_ and any(e["type"] in ("material", "gas", "liquid") for e in i_) and o_ and all(e["type"] == "waste" for e in o_) and len(p["edges"]) > 4:
                            warn.append("panel %s flow continuity: the main stream into '%s' ends in waste only - re-read the sentence: where does the stream go next?" % (pid, n["label"]))
                        elif o_ and not i_ and any(e["type"] == "liquid" for e in o_):
                            warn.append("panel %s flow continuity: '%s' has an outlet but no inlet - check the source" % (pid, n["label"]))
            for n in nodes:
                outs = {}
                for e in p["edges"]:
                    if e["from"] == n["id"] and e["type"] in ("liquid", "gas", "material") and re.search(r"\d", str(e.get("label") or "")):
                        outs.setdefault(re.sub(r"\s+", "", str(e["label"])), set()).add(e["to"])
                for lab_, tos in outs.items():
                    if len(tos) == 2 and len({(next((q for q in nodes if q["id"] == t_), {}) or {}).get("label", t_).rstrip(" 0123456789") for t_ in tos}) == 2:
                        warn.append("panel %s: '%s' sends '%s' to two different units (%s) - is it a split, or one stream through them in sequence? re-read the sentence" % (pid, n["label"], lab_, ", ".join(sorted(tos))))
            st_ = sorted(int(float(n["step"])) for n in nodes if re.fullmatch(r"\d+(\.0)?", str(n.get("step", ""))))
            if len(st_) > 2:
                gap_ = [k for k in range(st_[0], st_[-1]) if k not in st_]
                if gap_:
                    warn.append("panel %s: step numbers %s are missing in the sequence" % (pid, gap_))
            lab_of = {n["id"]: n["label"] for n in nodes}
            steps_ = [n for n in nodes if re.match(r"\d", str(n.get("step", "")))]
            if len(steps_) > 4:
                last_ = max(steps_, key=lambda n: float(re.match(r"\d+(\.\d+)?", str(n["step"])).group(0)))
                ends_ = [n for n in steps_ if n is not last_ and not any(e["from"] == n["id"] for e in p["edges"]) and any(e["to"] == n["id"] for e in p["edges"])]
                if ends_:
                    warn.append("panel %s: route stops at %s - does it continue (e.g. to the common sampling) in the source?" % (pid, ", ".join("'%s. %s'" % (n["step"], n["label"]) for n in ends_[:4])))
            for n in nodes:
                kids = [e["to"] for e in p["edges"] if e["from"] == n["id"]]
                if n["kind"] == "decision" and len(kids) > 1:
                    reach = {k: {e["to"] for e in p["edges"] if e["from"] == k} | {k} for k in kids}
                    shared = [x for x in set.union(*reach.values()) if sum(x in r for r in reach.values()) == len(kids)]
                    if shared:
                        warn.append("panel %s: every branch of '%s' runs into %s - true for the control / untreated branch too? If the source skips it there, let that branch bypass it" % (pid, n["label"], ", ".join(repr(lab_of.get(x, x)) for x in shared[:2])))
            lonely = nid - {e["from"] for e in p["edges"]} - {e["to"] for e in p["edges"]}
            if lonely and p["edges"]:
                warn.append("panel %s: nodes without any relation: %s (intended?)" % (pid, sorted(lonely)))
        elif t == "chart":
            if not p.get("data") and not p.get("inline"):
                err.append("panel %s: chart needs 'data' (file name) or 'inline' {columns, rows} for values printed in the text" % pid)
            inl = p.get("inline") or (p["data"] if isinstance(p.get("data"), dict) else None)
            if inl and inl.get("columns") and inl.get("rows"):
                name = "%s_inline.csv" % p["id"]
                os.makedirs(WORK, exist_ok=True)
                with open(os.path.join(WORK, name), "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(inl["columns"])
                    w.writerows(inl["rows"])
                p["data"] = name
            p["chart"] = p.get("chart") or p.get("kind") or "bar"
            if p["chart"] not in ("bar", "stacked", "line", "scatter", "box", "heatmap", "forest", "dot"):
                err.append("panel %s: chart '%s' unknown; use bar stacked line scatter dot box heatmap forest" % (pid, p["chart"]))
            if (p.get("err") or (p.get("lo") and p.get("hi"))) and not p.get("err_meaning"):
                warn.append("panel %s: error bars drawn without 'err_meaning' (SD, SEM, 95%% CI ... as the source states)" % pid)
            em_ = str(p.get("err_meaning") or "")
            kind_ = re.search(r"(?i)\b(SEM|SE|S\.E\.M?\.?|SD|S\.D\.|standard (?:error|deviation)|(?:95|99) ?% ?(?:CI|confidence)|CI|confidence interval|IQR|range)\b", em_)
            if kind_ and p.get("src") and not p.get("stat"):
                try:
                    txt_ = " ".join(str(q.get("text") or q.get("quote") or "") for q in resolve_src(p.get("src"), [], pid))
                except Exception:
                    txt_ = ""
                k_ = kind_.group(1).upper().replace(".", "")
                pats_ = {"SE": r"\bS\.?E\.?M?\b|standard error", "SEM": r"\bS\.?E\.?M\b|standard error", "SD": r"\bS\.?D\b|standard deviation",
                         "CI": r"\bCI\b|confidence", "IQR": r"\bIQR\b|interquartile", "RANGE": r"\brange\b"}
                pat_ = next((v for kk, v in pats_.items() if k_.startswith(kk) or kk in k_), None) or re.escape(kind_.group(1))
                if txt_ and not re.search(pat_, txt_, re.I):
                    p["err_meaning"] = "reported error (type not stated in the cited text)"
                    for f_ in ("note", "title", "ylabel"):
                        if p.get(f_):
                            p[f_] = re.sub(r"(?i)(±|\+/-|\+-)\s*" + re.escape(kind_.group(1)) + r"\b", r"\1 reported error", str(p[f_]))
                    warn.append("panel %s: err_meaning '%s' is not named in the cited passages %s, so the bars are labelled 'reported error'. If the paper states it (often in a figure legend), cite that passage in src." % (pid, em_, p.get("src")))
            for k in ("xlabel", "ylabel"):
                if not p.get(k) and p["chart"] != "heatmap":
                    warn.append("panel %s: '%s' missing - give quantity and unit" % (pid, k))
            for k_, o_ in enumerate(p.get("overlays") or []):
                if isinstance(o_, dict) and not (o_.get("src") or o_.get("data")):
                    warn.append("panel %s overlay %d (%s%s): no src - give the passage or table id that reports it, or drop it" % (pid, k_ + 1, o_.get("type", "?"), (" '%s'" % o_["label"]) if o_.get("label") else ""))
        else:
            if not p.get("items"):
                err.append("panel %s: text panel needs 'items'" % pid)
    SLASHED_ = re.compile(r"\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?\s*(?:±|\+/-)\s*\d+(?:\.\d+)?\s*/\s*\d")
    for p in spec["panels"]:
        bits = [str(p.get(k) or "") for k in ("note", "title")] + [str(x.get("text", x) if isinstance(x, dict) else x) for x in (p.get("items") or [])]
        bits += [str(n.get(k) or "") for n in (p.get("nodes") or []) if isinstance(n, dict) for k in ("label", "note")]
        ERRK_ = re.compile(r"(?i)(?:±|\+/-)\s*(SEM|SE|SD)\b|mean\s*(?:±|\+/-)\s*(SEM|SE|SD)\b|\b(standard error|standard deviation)\b")
        srcs_ = [x.get("src") for x in (p.get("items") or []) if isinstance(x, dict) and x.get("src")] + ([p.get("src")] if p.get("src") else [])
        for b in bits:
            ek_ = ERRK_.search(b)
            if ek_ and srcs_ and not p.get("stat"):
                try:
                    txt_ = " ".join(str(q.get("text") or q.get("quote") or "") for s_ in srcs_ for q in resolve_src(s_, [], p.get("id")))
                except Exception:
                    txt_ = ""
                k_ = (ek_.group(1) or ek_.group(2) or ek_.group(3) or "").lower()
                pat_ = r"\bS\.?D\b|standard deviation" if k_ in ("sd", "standard deviation") else r"\bS\.?E\.?M?\b|standard error"
                if txt_ and not re.search(pat_, txt_, re.I):
                    warn.append("panel %s: '%s' names the spread as %s, but the cited passages do not say so - write '±' with 'type not stated in the text' or cite the legend/methods passage that names it" % (p.get("id"), b[:80], ek_.group(0)))
                    break
        for b in bits:
            if SLASHED_.search(b):
                warn.append("panel %s: '%s' joins several groups' values with '/': write one value ± spread per group with its group name (\"W0 5.76 ± 0.63\"), and give each p value its comparison" % (p.get("id"), b[:90]))
                break
    return err, warn


# --- geometric checks --------------------------------------------------------------
def geometry(meta):
    res = {"node_overlaps": [], "labels_on_nodes": [], "label_overlaps": [], "edges_through_nodes": [], "unrouted": [], "group_overlaps": [], "crossings": 0}
    for pid, m in meta["panels"].items():
        r = m["res"]
        ns = r["nodes"]
        for i, a in enumerate(ns):
            for b in ns[i + 1:]:
                if a["_box"].overlap(b["_box"]) > 1:
                    res["node_overlaps"].append([pid, a["id"], b["id"]])
        gs = r["groups"]
        for i, a in enumerate(gs):
            for b in gs[i + 1:]:
                if a["box"].overlap(b["box"]) > 60:
                    res["group_overlaps"].append([pid, a["id"], b["id"]])
        labs = [(e, e["label_box"]) for e in r["edges"] if e.get("label_box")]
        for k, (e, b) in enumerate(labs):
            for n in ns:
                if b.overlap(n["_box"]) > 24:
                    res["labels_on_nodes"].append([pid, "%s->%s" % (e["from"], e["to"]), n["id"]])
            for e2, b2 in labs[k + 1:]:
                if b.overlap(b2) > 12:
                    res["label_overlaps"].append([pid, "%s->%s" % (e["from"], e["to"]), "%s->%s" % (e2["from"], e2["to"])])
        segs = []
        for k, e in enumerate(r["edges"]):
            if e.get("unrouted"):
                res["unrouted"].append([pid, e["from"], e["to"]])
            for p, q in zip(e["pts"], e["pts"][1:]):
                segs.append((k, p, q))
                bx = Box(min(p[0], q[0]), min(p[1], q[1]), abs(p[0] - q[0]) + .1, abs(p[1] - q[1]) + .1)
                for n in ns:
                    if n["id"] in (e["from"], e["to"]):
                        continue
                    if bx.hit(n["_box"].pad(-3)):
                        res["edges_through_nodes"].append([pid, "%s->%s" % (e["from"], e["to"]), n["id"]])
        for i, (k, p, q) in enumerate(segs):
            for (k2, p2, q2) in segs[i + 1:]:
                if k == k2:
                    continue
                h1, h2 = abs(p[1] - q[1]) < .5, abs(p2[1] - q2[1]) < .5
                if h1 == h2:
                    continue
                (hp, hq), (vp, vq) = ((p, q), (p2, q2)) if h1 else ((p2, q2), (p, q))
                if min(hp[0], hq[0]) + 1 < vp[0] < max(hp[0], hq[0]) - 1 and min(vp[1], vq[1]) + 1 < hp[1] < max(vp[1], vq[1]) - 1:
                    res["crossings"] += 1
    return res


def lum(c):
    c = c.lstrip("#")
    v = []
    for i in (0, 2, 4):
        x = int(c[i:i + 2], 16) / 255
        v.append(x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4)
    return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]


def svg_facts(svg):
    import xml.etree.ElementTree as ET
    root = ET.fromstring(svg.encode("utf-8"))
    ids, dup, texts, sizes, nodes, edges, raster = set(), [], 0, [], set(), [], 0
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        i = el.get("id")
        if i:
            if i in ids:
                dup.append(i)
            ids.add(i)
        if tag == "text":
            texts += 1
            try:
                sizes.append(float(el.get("font-size", "0")))
            except ValueError:
                pass
        if tag == "tspan" and el.get("font-size") and (el.text or "").strip():
            try:
                sizes.append(float(el.get("font-size")))
            except ValueError:
                pass
        if tag == "image":
            raster += 1
        if el.get("data-role") == "node":
            nodes.add((i.split("-node-")[0], el.get("data-node")))
        if el.get("data-role") == "edge":
            edges.append((i.split("-edge-")[0], el.get("data-from"), el.get("data-type"), el.get("data-to")))
    layers = [el.get("data-layer") for el in root.iter() if el.get("data-layer")]
    return {"ids": ids, "dup": dup, "texts": texts, "sizes": sizes, "nodes": nodes, "edges": edges, "raster": raster,
            "layers": sorted(set(layers))}


TXT = {"groups": ("id", "label", "kind", "src"), "nodes": ("id", "label", "kind", "group", "src", "note", "certainty", "glyph"),
       "edges": ("from", "to", "type", "label", "certainty", "src", "evidence"), "items": ("value", "text", "src", "lane", "start", "end", "at")}


def read_lines(pid, what, problems):
    """Rows of WORK/<panel>.<what>: pipe-separated fields, one item per line, # for comments."""
    p = os.path.join(WORK, "%s.%s" % (pid, what))
    if not os.path.exists(p):
        return None
    out = []
    for n, ln in enumerate(open(p, encoding="utf-8"), 1):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        f = [x.strip() for x in ln.split("|")]
        if f[0].lower() in ("id", "from"):
            continue
        if what == "edges" and len(f) < 3:
            problems.append("%s.edges line %d needs: from | to | type | label | certainty | src" % (pid, n))
            continue
        rec = {}
        for k, v in zip(TXT[what], f):
            if v and v != "-":
                rec[k] = [x.strip() for x in v.replace(";", ",").split(",") if x.strip()] if k == "src" else v
        for extra in f[len(TXT[what]):]:
            if "=" in extra:
                k, v = extra.split("=", 1)
                rec[k.strip()] = v.strip()
        for k in ("rank", "step", "width", "value", "p"):
            if k in rec and not (what == "items" and k == "value"):
                try:
                    rec[k] = float(rec[k]) if "." in str(rec[k]) or k in ("width", "value", "p") else int(rec[k])
                except ValueError:
                    pass
        # last definition of the same id/relation wins; "delete" removes it
        gone = str(rec.get("label", "")).lower() == "delete"
        if what == "items":
            if rec.get("at"):
                rec["at"] = [x.strip() for x in str(rec["at"]).replace(";", ",").split(",") if x.strip()]
            if str(rec.get("text", "")).lower() == "delete":
                out = [o for o in out if o.get("value") != rec.get("value")]
                continue
        elif what != "edges":
            out = [o for o in out if o.get("id") != rec.get("id")]
        elif gone and what == "edges":
            n0 = len(out)
            out = [o for o in out if (o.get("from"), o.get("to")) != (rec.get("from"), rec.get("to")) or ALIAS_T.get(o.get("type"), o.get("type")) != ALIAS_T.get(rec.get("type"), rec.get("type"))]
            if len(out) == n0:
                problems.append("%s.edges line %d: delete matched no relation %s -> %s of type %s" % (pid, n, rec.get("from"), rec.get("to"), rec.get("type")))
        else:
            out = [o for o in out if (o.get("from"), o.get("to"), o.get("type"), o.get("label")) != (rec.get("from"), rec.get("to"), rec.get("type"), rec.get("label"))]
        if not gone:
            out.append(rec)
    return out


def merge_lines(spec):
    problems = []
    spec.setdefault("panels", [])
    spec.pop("_starter", None)
    for f in sorted(glob.glob(os.path.join(WORK, "*.starter"))):  # first-minute draft, only until the author's own lines exist
        pid = os.path.basename(f)[:-8]
        if glob.glob(os.path.join(WORK, "*.nodes")) or glob.glob(os.path.join(WORK, "*.items")) or glob.glob(os.path.join(WORK, "*.panel.json")):
            break
        kind_ = "items" if any(q.get("id") == pid and q.get("type") in ("text", "timeline") for q in spec["panels"]) else "nodes"
        rows = []
        for ln in open(f, encoding="utf-8"):
            c = [x.strip() for x in ln.split("|")]
            if len(c) >= 3:
                rows.append({"value": None, "text": c[1], "src": [c[2]]} if kind_ == "items" else {"id": c[0], "label": c[1], "kind": c[2], "group": c[3] if len(c) > 3 and c[3] != "-" else None, "src": [c[4]] if len(c) > 4 else None})
        for q in spec["panels"]:
            if q.get("id") == pid and rows:
                q[kind_] = [{k: v for k, v in r.items() if v} for r in rows]
                q.setdefault("edges", []) if kind_ == "nodes" else None
                spec["_starter"] = True
    for f in sorted(glob.glob(os.path.join(WORK, "*.panel.json"))):  # one panel per file (charts)
        pid = os.path.basename(f)[:-len(".panel.json")]
        try:
            d = jload(f)
        except ValueError as exc:
            problems.append("%s.panel.json is not valid JSON: %s" % (pid, exc))
            continue
        d["id"] = pid
        k = next((j for j, q in enumerate(spec["panels"]) if q.get("id") == pid), None)
        if k is None:
            base_ = re.sub(r"\d+$|[a-z]$", "", pid)  # R2 goes right after R
            at = next((j for j, q in enumerate(spec["panels"]) if q.get("id") == base_), None) if base_ != pid else None
            spec["panels"].insert(at + 1 if at is not None else len(spec["panels"]), d)
        else:
            old_ = spec["panels"][k]
            spec["panels"][k] = dict({q: old_[q] for q in ("title", "weight") if q in old_}, **d)
    pids = sorted({os.path.basename(f).rsplit(".", 1)[0] for k in TXT for f in glob.glob(os.path.join(WORK, "*." + k))})
    spec.setdefault("panels", [])
    for pid in pids:
        panel = next((q for q in spec["panels"] if q.get("id") == pid), None)
        only_items = not any(os.path.exists(os.path.join(WORK, "%s.%s" % (pid, k))) for k in ("nodes", "edges", "groups"))
        if only_items:  # text, timeline or footnote lines
            rows = read_lines(pid, "items", problems) or []
            if pid.lower() in ("notes", "footnotes"):
                spec["footnotes"] = [f for f in spec.get("footnotes") or [] if not (isinstance(f, dict) and f.get("_line"))] + [{"text": str(r.get("text") or r.get("value") or ""), "src": r.get("src"), "_line": True} for r in rows]
                continue
            if panel is None:
                panel = {"id": pid, "type": "timeline" if any(r.get("lane") for r in rows) else "text"}
                spec["panels"].append(panel)
            panel["items"] = rows
            continue
        if panel is None:
            panel = {"id": pid, "type": "diagram"}
            spec["panels"].insert(0, panel)
        panel["type"] = "diagram"
        for what in ("groups", "nodes", "edges"):
            rows = read_lines(pid, what, problems)
            if rows is not None:
                panel[what] = rows
        cf_ = os.path.join(WORK, pid + ".cite")
        if os.path.exists(cf_):
            for ln in open(cf_, encoding="utf-8"):
                f = [x.strip() for x in ln.split("|")]
                if len(f) >= 3 and not ln.startswith("#"):
                    for e_ in panel.get("edges") or []:
                        if e_.get("from") == f[0] and e_.get("to") == f[1]:
                            e_["src"] = [x.strip() for x in f[2].replace(";", ",").split(",") if x.strip()]
        pl = os.path.join(WORK, pid + ".place")
        if os.path.exists(pl):
            where = {}
            for ln in open(pl, encoding="utf-8"):
                f = [x.strip() for x in ln.split("|")]
                if len(f) >= 2 and not ln.startswith("#"):
                    where[f[0]] = f
            for n_ in panel.get("nodes") or []:
                f = where.get(n_.get("id"))
                if f:
                    n_["group"] = f[1]
                    if len(f) > 2 and f[2] not in ("", "-"):
                        n_["kind"] = f[2]
        op = os.path.join(WORK, pid + ".opts.json")
        if os.path.exists(op):
            o_ = jload(op)
            for k, v in o_.get("panel", {}).items():
                panel.setdefault(k, v)
            have_ = {str(x.get("text")) for x in spec.get("legend_extra") or [] if isinstance(x, dict)}
            spec["legend_extra"] = (spec.get("legend_extra") or []) + [x for x in o_.get("legend_extra", []) if x["text"] not in have_]
    return problems


def canvas_fix(spec):
    """Accept size_mm / size / height keys used by work orders."""
    cv = spec.setdefault("canvas", {})
    px = cv.pop("size_px", None) or ([cv.pop("width_px"), cv.pop("height_px")] if cv.get("width_px") and cv.get("height_px") else None)
    if px:  # exact pixel canvas: physical width follows from pixels and dpi
        cv["dpi"] = float(re.search(r"[0-9.]+", str(cv.get("dpi", 300))).group(0))
        cv["width_mm"], cv["height_mm"] = float(px[0]) / cv["dpi"] * 25.4, float(px[1]) / cv["dpi"] * 25.4
        cv["pixels"] = [int(px[0]), int(px[1])]
    sz = cv.pop("size_mm", None) or cv.pop("size", None)
    if isinstance(sz, (list, tuple)) and len(sz) == 2:
        cv["width_mm"], cv["height_mm"] = float(sz[0]), float(sz[1])
    for k in ("width_mm", "height_mm", "max_height_mm", "max_width_mm", "font_pt", "dpi"):
        if isinstance(cv.get(k), str):
            m = re.search(r"[0-9.]+", cv[k])
            cv[k] = float(m.group(0)) if m else None
        if cv.get(k) is None:
            cv.pop(k, None)
    if not isinstance(cv.get("formats"), list):
        cv["formats"] = []


def fill_ratio(mt):
    """Share of a fixed page height that the content really uses."""
    return 1 - 2 * float(mt.get("shift") or 0) / mt["canvas_units"][1]


def can_wrap(p):
    """Only step-like routes may be folded into rows."""
    n = len(p.get("nodes", []))
    if n < 6:
        return False
    stepped = sum(1 for x in p["nodes"] if x.get("step") is not None or x.get("kind") in ("step", "milestone", "decision"))
    return len(p.get("edges", [])) <= n * 1.35 + 1 and stepped >= .6 * n


def best_render(spec, locked, lock_scale=None):
    """Render as asked; compact the arrangement or use a finer scale when the page would not fit."""
    first = json.loads(json.dumps(spec))
    cv = spec.get("canvas", {})
    if locked:
        svg, reg, meta = fk_draw.render(spec, read_table, locked, lock_scale or 1.0)
        return svg, reg, meta, spec, None
    import fk_layout
    limit = cv.get("height_mm") or cv.get("max_height_mm")
    order_ = " ".join(must_lines()).lower()
    dg_ = [p for p in first["panels"] if p["type"] == "diagram"]
    if len(dg_) == 1 and re.search(r"(group|column|node|stage|panel|layer|arrang|layout|flow)[^.;|]{0,60}left[\s_-]*to[\s_-]*right", order_) and str(dg_[0].get("direction", "")).upper() != "LR":
        dg_[0]["direction"] = "LR"   # demanded by the work order
    ids = [p["id"] for p in first["panels"]]
    dia = [p["id"] for p in first["panels"] if p["type"] == "diagram"]
    rest = [i for i in ids if i not in dia]
    lays = [first.get("layout") or [[i] for i in ids]]
    if len(dia) == 1 and rest and ids[0] == dia[0]:
        lays += [[[dia[0], rest]], [[dia[0]], rest]]
    if len(dia) == 1 and len(rest) >= 2 and ids[0] != dia[0]:
        k = ids.index(dia[0])
        lays += [[ids[:k + 1], ids[k + 1:]]] if ids[k + 1:] else []
        lays += [[[ids[:k + 1], ids[k + 1:]]]] if ids[k + 1:] else []
    if len(ids) == 4:
        a_, b_, c_, d_ = ids
        lays += [[ids[:2], ids[2:]], [[ids[:2], ids[2:]]], [[a_], [b_, c_], [d_]], [[[a_, b_], c_, d_]], [[a_, b_, [c_, d_]]], [[[a_, b_], [c_, d_]]], [[a_], [b_, [c_, d_]]], [[b_ if False else a_, d_], [b_, c_]]]
    if len(dia) == 2:
        lays += [[dia] + ([rest] if rest else []), [[dia[0]], [dia[1]] + rest]]
    if len(ids) in (2, 3):
        lays.append([ids])
    if 3 <= len(ids) <= 6:  # every order-preserving split into 2-3 columns or rows
        n_ = len(ids)
        cuts = [(i,) for i in range(1, n_)] + [(i, j) for i in range(1, n_) for j in range(i + 1, n_)]
        part = lambda c: [ids[a:b] for a, b in zip((0,) + c, c + (n_,))]
        cell = lambda q: q if len(q) > 1 else q[0]
        wide = [[[cell(q) for q in part(c)]] for c in cuts]           # columns, panels stacked inside
        tall = [[list(q) for q in part(c)] for c in cuts]             # rows
        mixed = [[list(ids[:1])] + [[cell(q) for q in [ids[1:k], ids[k:]]]] for k in range(2, n_)]
        lays += [q for pair in zip(wide, tall) for q in pair] + mixed
    uniq = []
    for q in lays:
        if q not in uniq:
            uniq.append(q)
    uniq = uniq[:26]
    target = float(limit) * (1 - float(cv.get("reserve") or 0)) if limit else float(cv.get("width_mm", 180)) * (1.0 if not dia else 1.25)

    def attempt(lay, mode, k, route, squeeze=False):
        s2 = json.loads(json.dumps(first))
        s2["layout"] = lay
        dirs = {}
        bypid = {p["id"]: p for p in s2["panels"]}
        for r_ in lay:
            if isinstance(r_, list) and len(r_) >= 3:  # a column holding only short text needs less width
                for c_ in r_:
                    one = [c_] if not isinstance(c_, list) else c_
                    if len(one) == 1 and bypid[one[0]]["type"] == "text" and not bypid[one[0]].get("weight") and not bypid[one[0]].get("timeline") and not any(isinstance(i_, dict) and str(i_.get("value", "")).lower() == "grid" for i_ in bypid[one[0]].get("items", [])) and sum(len(str(i_.get("text", "")) if isinstance(i_, dict) else str(i_)) for i_ in bypid[one[0]].get("items", [])) < 420:
                        bypid[one[0]]["weight"] = .6 if sum(len(str(i_.get("text", "")) if isinstance(i_, dict) else str(i_)) for i_ in bypid[one[0]].get("items", [])) < 150 else .8
        for p in s2["panels"]:
            if p["type"] == "diagram" and mode != "asis":
                p["direction"] = mode[p["id"]] if isinstance(mode, dict) else mode
                dirs[p["id"]] = p["direction"]
            if p["type"] == "chart" and limit and p.get("height_mm") is None:
                depth = sum(max(len(c) if isinstance(c, list) else 1 for c in (r if isinstance(r, list) else [r])) for r in lay)
                n_rows = max(1, depth)
                p["height_mm"] = max((22.0 if first.get("theme") else 26.0) * k, min(62.0 * k, (target * k - 24) / n_rows * (.6 if first.get("theme") else .74)))
        fk_layout.ROUTE[0] = route
        try:
            sv, rg, mt = fk_draw.render(s2, read_table, None, k, squeeze)
        finally:
            fk_layout.ROUTE[0] = True
        return sv, rg, mt, s2, ({"layout": lay, "direction": dirs} if (lay != uniq[0] or dirs) else None)

    def fits_width(mt):
        return not any(m["res"]["w"] > m["inner"] + 3 for m in mt["panels"].values())
    cands, last = [], None
    wr = {p["id"]: can_wrap(p) for p in first["panels"] if p["type"] == "diagram"}
    fixed = {p["id"]: str(p["direction"]).upper() for p in first["panels"] if p["type"] == "diagram" and str(p.get("direction", "auto")).upper() in ("LR", "TB", "WRAP")}
    if fixed and not re.search(r"left[\s_-]*to[\s_-]*right|top[\s_-]*to[\s_-]*bottom|right[\s_-]*to[\s_-]*left|bottom[\s_-]*to[\s_-]*top|horizontal|vertical|stacked|从左|自左|从上|自上", " ".join(must_lines()).lower()):
        soft, fixed = fixed, {}   # the author's preference, not a requirement: may yield when it would make text much smaller
    else:
        soft = {}
    opts = [[fixed[d]] if d in fixed else ["LR", "TB"] + (["WRAP"] if wr[d] else []) for d in dia]  # a required direction is respected
    modes = ["asis"]
    if len(dia) == 1 and dia[0] not in fixed:
        modes = [{dia[0]: x} for x in opts[0]]   # explicit, so that search and final drawing agree
    elif len(dia) == 2 and len(fixed) < 2:
        modes = [dict(zip(dia, (x, y))) for x in opts[0] for y in opts[1]]
    t0 = time.time()
    for n, lay in enumerate(uniq):
        for mode in modes:
            wrapn = sum(v == "WRAP" for v in (mode.values() if isinstance(mode, dict) else [mode]))
            asis = n == 0 and mode == "asis"
            k = 1.0
            for _ in range(6 if limit else 3):
                try:
                    sv, rg, mt, s2, au = attempt(lay, mode, k, False)
                except ValueError as exc:
                    last = exc
                    break
                h = mt["size_mm"][1]
                over = max(0.0, h - target) / target
                fit = fits_width(mt)
                shrink = k * (1 + over) if cv.get("height_mm") else k
                low = min(svg_facts(sv)["sizes"] or [9e9]) / fk_draw.MM / 25.4 * 72 / shrink
                viol = max(0.0, float(cv.get("min_font_pt") or 5.0) / low - 1)
                off = .3 * sum(1 for d, v in soft.items() if isinstance(mode, dict) and mode.get(d) != v)
                cands.append((1 if not fit else 0, round(viol + off, 2) + (over if not cv.get("height_mm") else 0.0),
                              (.5 if len(dia) == 2 and len(lay) and any(sum(1 for c in r for i in (c if isinstance(c, list) else [c]) if i in dia) == 2 and len(r) > 1 for r in lay) else 0.0) + (shrink - 1) * .5 + over * .3 + (0 if asis else .05) + n * .02 + wrapn * .02 + (0 if asis else abs(h - target * .72) / target * .1), lay, mode, k, over))
                if fit and over <= .003:
                    break
                if time.time() - t0 > (3.5 if walking() else 9) and len(cands) > 2:
                    break
                k2 = k * 1.15 if not fit else max(k + .05, k * (1 + over) ** .7)   # a finer scale that just fills the page
                if k2 > (3.2 if limit else 1.35):
                    break
                k = round(k2, 3)
    if not cands:
        raise last or ValueError("nothing could be laid out")
    cands.sort(key=lambda c: (c[0], round(c[1], 1), c[2]))
    best = None
    t1 = time.time()
    for c in cands[:8]:
        sv, rg, mt, s2, au = attempt(c[3], c[4], c[5], True, squeeze=bool(cv.get("height_mm")))
        g = geometry(mt)
        bad = sum(len(v) for q, v in g.items() if q != "crossings") * 10 + g["crossings"] * .7 + (0 if fits_width(mt) else 120) + 60 * c[1] + (14 * (c[5] * (1 + c[6]) - 1) + 40 * c[6] if cv.get("height_mm") else 14 * (c[5] - 1)) + 12 * c[2] + (max(0.0, .72 - fill_ratio(mt)) * 60 if cv.get("height_mm") else 0) + (0 if not au else 1)
        if best is None or bad < best[0]:
            best = (bad, sv, rg, mt, s2, au)
        if bad < 9 or time.time() - t1 > (2.5 if walking() else 8):
            break
    return best[1:]


def edit_pairs(text):
    """(old, new) variant names in an edit request: 'from the RAS+A variant to show the RAS-A variant', 'replace X with Y'."""
    out = []
    for m in re.finditer(r"(?i)\bfrom (?:the |a )?([^,;.]{1,40}?) (?:variant |version |design |condition )?to (?:show |display )?(?:the |a )?([^,;.]{1,40}?)(?: variant| version| design| condition)?(?=\s+by\b|\s+and\b|[,;.]|$)", text):
        out.append((m.group(1).strip(), m.group(2).strip()))
    if not out:
        for m in re.finditer(r"(?i)\b(?:replace|swap|switch)\s+(?:the\s+)?([^,;.]{1,40}?)\s+(?:with|by|for)\s+(?:the\s+)?([^,;.]{1,40}?)(?=\s+by\b|[,;.]|$)", text):
            out.append((m.group(1).strip(), m.group(2).strip()))
    return [(o, n) for o, n in out if 0 < len(o.split()) <= 4 and 0 < len(n.split()) <= 4 and o.lower() != n.lower()]


COLOR_ = {"blue": "#1F5FA8", "brown": "#7B4A1E", "yellow": "#C9A000", "gold": "#B8860B", "orange": "#D2691E", "red": "#B3261E", "green": "#2E7D32",
          "grey": "#7A7F87", "gray": "#7A7F87", "black": "#1B1F24", "purple": "#6C4AA5", "teal": "#2E8B7A", "olive": "#70773A", "cyan": "#1C8FA8", "pink": "#C2185B"}
FLOWTYPE_ = [(r"measure|data|signal|sensor|analy[sz]er|monitor", ("data", "signal")), (r"control", ("control",)),
             (r"light|energy|heat|power|electric|illumin", ("energy",)), (r"\bair\b|gas|aeration|co2|oxygen", ("gas",)),
             (r"solid|discharge|waste|sludge|drain|effluent|exhaust", ("waste",)), (r"water|liquid|medium|flow|stream", ("liquid",))]


def order_encoding(spec):
    """Line encodings the work order prescribes (e.g. 'water': 'solid blue with arrowheads') override the engine's default edge styles.
    Returns (applied, missing): applied = [(order key, edge types, style)], missing = encoded categories with no drawn line."""
    import kit_sources as ks_
    enc = {}
    for w in ks_.workorders():
        try:
            d = jload(w)
        except Exception:
            continue

        def walk(o):
            if isinstance(o, dict):
                vals = [v for v in o.values() if isinstance(v, str)]
                if len(vals) >= 2 and sum(bool(re.search(r"(?i)\b(%s)\b" % "|".join(COLOR_), v)) or bool(re.search(r"(?i)dash|dott|solid", v)) for v in vals) >= 2:
                    for k, v in o.items():
                        if isinstance(v, str) and len(v) < 90:
                            enc[str(k)] = v
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(d)
    if not enc:
        return [], []
    used = {str(e.get("type")) for p in spec.get("panels", []) for e in (p.get("edges") or []) if isinstance(e, dict)}
    applied, missing = [], []
    for k, v in enc.items():
        types = next((t for rx, t in FLOWTYPE_ if re.search("(?i)" + rx, k)), None)
        if not types:
            continue
        col = next((COLOR_[c] for c in re.findall(r"(?i)[a-z]+", v.lower()) if c in COLOR_), None)
        dash = "8 4" if re.search(r"(?i)dash", v) else "2 3" if re.search(r"(?i)dott", v) else "" if re.search(r"(?i)solid", v) else None
        for t in types:
            if t not in fk_draw.EDGES:
                continue
            c0, d0, h0, w0, l0 = fk_draw.EDGES[t]
            w1 = 1.4 if re.search(r"(?i)thin", v) else w0
            fk_draw.EDGES[t] = (col or c0, d0 if dash is None else dash, h0, w1, k[:1].upper() + k[1:])
        applied.append((k, types, v))
        if not used & set(types):
            missing.append((k, v))
    return applied, missing


def cmd_build(a):
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    sp = a.spec or os.path.join(WORK, "spec.json")
    has_lines = not a.spec and bool(glob.glob(os.path.join(WORK, "*.nodes")))
    if not os.path.exists(sp) and not has_lines:
        sys.exit("spec not found: " + sp)
    try:
        spec = jload(sp) if os.path.exists(sp) else {"title": "", "panels": []}
    except json.JSONDecodeError as exc:
        txt = open(sp, encoding="utf-8").read().splitlines()
        sys.exit("spec.json is not valid JSON at line %d col %d: %s\n> %s" % (exc.lineno, exc.colno, exc.msg, txt[exc.lineno - 1][:200] if exc.lineno <= len(txt) else ""))
    if not a.spec:
        for f in sorted(glob.glob(os.path.join(WORK, "panel_*.json"))):
            try:
                q = jload(f)
            except json.JSONDecodeError as exc:
                sys.exit("%s is not valid JSON at line %d: %s" % (f, exc.lineno, exc.msg))
            q = q if isinstance(q, list) else q.get("panels", [q])
            spec.setdefault("panels", [])
            for x in q:
                spec["panels"] = [y for y in spec["panels"] if y.get("id") != x.get("id")] + [x]
        rec_ = os.path.join(OUT, "edit_record.json")
        if not a.revise and not a.restart and os.path.exists(rec_) and os.path.exists(os.path.join(OUT, "figure_before_edit.svg")):
            a.revise = jload(rec_).get("request") or "requested edit (continued)"
            say("NOTE the edit has begun: this build continues it as `build --revise` (the frozen first version stays). Use `build --restart` only to redo the first version and then the edit.")
        lp = merge_lines(spec)
    else:
        lp = []

    def empty_(p):
        t_ = str(p.get("type") or "")
        if t_ in ("diagram", "flow", "pathway", "schematic", "roadmap") or (not t_ and "nodes" in p):
            return not p.get("nodes")
        if t_ in ("text", "bullets", "callout", "stats", "timeline", "gantt", "schedule"):
            return not p.get("items")
        return False
    pend_ = [p.get("id") for p in spec.get("panels") or [] if isinstance(p, dict) and empty_(p)]
    if pend_ and len(pend_) < len(spec["panels"]):
        spec["panels"] = [p for p in spec["panels"] if p.get("id") not in pend_]
    if spec.get("theme") == "abstract" and not a.revise and not a.spec:  # the engine arranges an abstract; hand-set widths made columns unreadable
        spec.pop("layout", None)
        for p_ in spec["panels"]:
            p_.pop("weight", None)
            p_.pop("height_mm", None)

    def flat_(q):
        return [y for x in q for y in (flat_(x) if isinstance(x, list) else [x])]
    if spec.get("layout") and sorted(map(str, flat_(spec["layout"]))) != sorted(str(p.get("id")) for p in spec.get("panels") or []):
        spec.pop("layout")   # the list of panels changed: let the engine arrange them
    err, warn = validate(spec)
    err = lp + err
    try:
        enc_applied, enc_missing = order_encoding(spec)
        if enc_applied:
            spec.setdefault("_order_encoding", [{"order_key": k, "edge_types": list(t), "style": v} for k, t, v in enc_applied])
        for k_, v_ in enc_missing:
            warn.append("ORDER ENCODING: the work order defines '%s' lines (%s) but no such line is drawn - find the source sentence (e.g. lighting, aeration, heating, sampling to analyser) and draw it, or record why not in unresolved" % (k_, v_))
    except Exception as exc_:
        warn.append("order encoding not applied: %s" % str(exc_)[:120])
    try:
        import fk_flow
        want_ = fk_flow.order_facts()[1]
        got_ = " ".join(str(g.get("label", "")) + " " + str(g.get("id", "")) for p in spec.get("panels", []) for g in p.get("groups", []) or [] if any(n.get("group") == g.get("id") for n in p.get("nodes", []))).lower()
        lost_ = [g for g in want_ if re.sub(r"\W+", "", g.lower())[:8] not in re.sub(r"\W+", "", got_)]
        if lost_ and want_ and not spec.get("_starter") and len(lost_) < len(want_):
            warn.append("the order demands group(s) %s but nothing is drawn in them: which element or proposed step does the source place there?" % ", ".join(lost_))
    except Exception:
        pass
    if err:
        say("SPEC ERRORS (nothing overwritten):")
        for e in err[:25]:
            say(" -", e)
        sys.exit(2)
    for p in spec["panels"]:
        for k in ("title", "note"):
            if p.get(k):
                p[k] = public_refs(p[k])
        for it in p.get("items", []) or []:
            if isinstance(it, dict) and it.get("text"):
                it["text"] = public_refs(it["text"])
    for k in ("title", "caption"):
        if spec.get(k):
            spec[k] = public_refs(spec[k])
    seen_, keep_ = set(), []
    for f in spec.get("footnotes") or []:  # the same note once
        k_ = re.sub(r"\W+", "", str(f.get("text", "") if isinstance(f, dict) else f).lower())
        if k_ and k_ not in seen_:
            seen_.add(k_)
            keep_.append(f)
    spec["footnotes"] = keep_
    spec["footnotes"] = [dict(f, text=public_refs(f.get("text", ""))) if isinstance(f, dict) else public_refs(f) for f in spec.get("footnotes") or []]
    lints = []
    for where, t in [("title", spec.get("title", "")), ("caption", spec.get("caption", ""))] + [("panel %s title" % p["id"], p.get("title", "")) for p in spec["panels"]] + [("panel %s item" % p["id"], it.get("text", "") if isinstance(it, dict) else str(it)) for p in spec["panels"] for it in p.get("items", []) or []]:
        for m in lint_text(strip_markup(str(t))):
            lints.append("%s: %s" % (where, m))
    for t_ in [str(f.get("text", "") if isinstance(f, dict) else f) for f in spec.get("footnotes") or []] + [str(spec.get("caption") or "")]:
        for z_ in re.split(r"(?<=[.;])\s+", t_):
            if re.search(r"(?i)^(?:no|none)\b[^.;]{0,70}\b(?:is|are|was|were)\s+(?:named|reported|stated|given|mentioned|described|specified)\b", z_.strip()):
                warn.append("ABSENCE CLAIM '%s' - confirm it with `find` before keeping it" % z_.strip()[:90])
    warn += ["WORDING " + x for x in lints[:5]]
    if not a.revise and not a.spec:
        for old_, new_ in edit_pairs(" ".join(ln for ln in must_lines() if re.search(r"(?i)edit|revis|convert|replace", ln))):
            if old_.lower() in strip_markup(str(spec.get("title") or "")).lower():
                warn.append("EDIT PLAN: the requested edit turns '%s' into '%s', and an edit may only touch the named objects. Keep '%s' out of the title now (a variant-neutral title), name the variant on the objects the edit changes or in the caption." % (old_, new_, old_))
            break
    if True:  # deterministic: v1, the edit and a rebuild give the same classes for unchanged relations
        try:
            from kit_sources import strength_pass, chain_gaps
            v1s_ = os.path.join(OUT, "figure_before_edit_spec.json")
            if a.revise and os.path.exists(v1s_):   # relations drawn in v1 keep the class they had there
                old_e = {(str(p_.get("id")), str(e_.get("from")), str(e_.get("to"))): e_ for p_ in jload(v1s_).get("panels") or [] for e_ in p_.get("edges") or [] if isinstance(e_, dict)}
                for p_ in spec["panels"]:
                    for e_ in p_.get("edges") or []:
                        o_ = old_e.get((str(p_.get("id")), str(e_.get("from")), str(e_.get("to")))) if isinstance(e_, dict) else None
                        if o_ is not None and not e_.get("evidence_class_locked"):
                            if o_.get("evidence_class_locked"):
                                e_["type"], e_["certainty"] = o_.get("type"), o_.get("certainty")
                                if "(correlation)" in str(o_.get("label") or "") and "(correlation)" not in str(e_.get("label") or ""):
                                    e_["label"] = o_.get("label")
                            e_["evidence_class_locked"] = True
                spec["_strength"] = [x for x in (jload(v1s_).get("_strength") or [])]
            warn += strength_pass(spec)
            if not a.revise and not a.spec:
                warn += chain_gaps(spec)
        except Exception as exc:  # the check never blocks a delivery
            warn.append("evidence-class check skipped: %s" % exc)
    if not a.spec:
        try:   # a size or type minimum the work order states is not the agent's to change
            import fk_flow
            req_cv = fk_flow.order_facts()[0]
            cv_ = spec.setdefault("canvas", {})
            want_ = {"size_px": req_cv.get("size_px"), "size_mm": req_cv.get("size_mm") if not req_cv.get("size_px") else None, "min_font_pt": req_cv.get("min_font_pt")}
            have_ = json.loads(json.dumps(cv_))
            canvas_fix({"canvas": have_})
            for k_, v_ in want_.items():
                if not v_:
                    continue
                if k_ == "min_font_pt":
                    if float(cv_.get("min_font_pt") or 0) < float(v_):
                        cv_["min_font_pt"] = v_
                    continue
                got_ = have_.get("pixels") if k_ == "size_px" else [have_.get("width_mm"), have_.get("height_mm")]
                if not got_ or any(g is None or abs(float(g) - float(w)) > (1 if k_ == "size_px" else .6) for g, w in zip(got_, v_)):
                    for q_ in ("size_px", "size_mm", "size", "width_mm", "height_mm", "width_px", "height_px", "pixels"):
                        cv_.pop(q_, None)
                    cv_[k_] = list(v_)
                    warn.append("canvas set back to the work order's %s %s (the spec had %s): the size is a requirement, not a layout choice; shorten text instead" % (k_.replace("_", " "), v_, got_))
        except Exception as exc:
            warn.append("work-order canvas check skipped: %s" % exc)
    canvas_fix(spec)
    plain = json.loads(json.dumps(spec))
    prev_svg = os.path.join(OUT, "figure.svg")
    layout_file = os.path.join(WORK, "layout.json")
    locked, lock_scale = None, None
    if re.search(r"shown (here|in this)|demonstrated|this study|this work", " ".join(must_lines()).lower()):
        spec["_shown"] = True
    if re.search(r"propos[^.;|]{0,40}dotted|dotted[^.;|]{0,40}propos", " ".join(must_lines()).lower()):
        fk_draw.PDASH[0] = "2 4"
    v1 = os.path.join(OUT, "figure_before_edit.svg")
    v1_layout = os.path.join(WORK, "layout_before_edit.json")
    if a.revise and os.path.exists(prev_svg):
        if not os.path.exists(v1):  # freeze the first version once; every retry is compared with it
            for e in (".svg", ".png", ".pdf", "_300dpi.png"):
                if os.path.exists(os.path.join(OUT, "figure" + e)):
                    shutil.copy(os.path.join(OUT, "figure" + e), os.path.join(OUT, "figure_before_edit" + e))
            if os.path.exists(layout_file):
                shutil.copy(layout_file, v1_layout)
            if os.path.exists(os.path.join(OUT, "figure_spec.json")):
                shutil.copy(os.path.join(OUT, "figure_spec.json"), os.path.join(OUT, "figure_before_edit_spec.json"))
        if os.path.exists(v1_layout):
            locked = jload(v1_layout)
            lock_scale = locked.pop("_scale", 1.0)
            v1spec = os.path.join(OUT, "figure_before_edit_spec.json")
            if os.path.exists(v1spec):
                old = jload(v1spec)
                spec["layout"] = old.get("layout") or spec.get("layout")
                spec["canvas"] = old.get("canvas") or spec.get("canvas")
                od = {p["id"]: p for p in old["panels"]}
                for p in spec["panels"]:
                    if p["id"] in od:
                        if p.get("edge_width") and not p["edge_width"].get("max") and (od[p["id"]].get("edge_width") or {}).get("max"):
                            p["edge_width"]["max"] = od[p["id"]]["edge_width"]["max"]
                        for q in ("direction", "height_mm", "weight", "group_axis"):
                            if q in od[p["id"]]:
                                p[q] = od[p["id"]][q]
                plain = json.loads(json.dumps(spec))
    elif not a.revise:
        for f in glob.glob(os.path.join(OUT, "figure_before_edit*")) + [os.path.join(OUT, "edit_record.json"), v1_layout]:
            if os.path.exists(f):
                os.remove(f)
    try:
        svg, reg, meta, spec, auto = best_render(spec, locked, lock_scale)
        req_ = (spec.get("canvas") or {}).get("min_font_pt")
        for _ in range(2 if (req_ and not locked) else 0):   # a stated minimum is met at final size, after the page squeeze
            mp_ = min(svg_facts(svg)["sizes"] or [9e9]) / fk_draw.MM / meta["scale"] / 25.4 * 72
            if mp_ >= float(req_) - .05:
                break
            cvb_ = spec.setdefault("canvas", {})
            cvb_["_floor_boost"] = round(float(cvb_.get("_floor_boost") or 1) * float(req_) / mp_ * 1.02, 3)
            plain.setdefault("canvas", {})["_floor_boost"] = cvb_["_floor_boost"]
            svg, reg, meta, spec, auto = best_render(spec, None)
    except ValueError as exc:
        sys.exit("CANNOT DRAW (nothing overwritten): %s" % exc)
    used = {p["id"]: p for p in spec["panels"]}
    plain["layout"] = spec.get("layout") or plain.get("layout")
    for p in plain["panels"]:
        for q in ("direction", "height_mm", "weight"):
            if used.get(p["id"], {}).get(q) is not None:
                p[q] = used[p["id"]][q]
    for p in plain["panels"]:
        ew = p.get("edge_width")
        if ew and not ew.get("max"):
            vals = [abs(fk_draw._num(e.get(ew.get("field", "value"))) or 0) for e in p.get("edges", [])]
            if vals and max(vals) > 0:
                ew["max"] = max(vals)
    if auto:
        say("layout chosen by the engine: %s %s" % (json.dumps(auto["layout"]), auto["direction"] or ""))
    facts = svg_facts(svg)
    with open(prev_svg, "w", encoding="utf-8") as f:
        f.write(svg)
    jsave(layout_file, dict(meta["layout"], _shift=meta.get("shift"), _view=meta["view"], _scale=meta["layout_scale"], _frames=meta.get("frames", {}), _multi=meta["multi"], _plan=plain.get("layout")))
    jsave(os.path.join(OUT, "figure_spec.json"), plain)
    w_mm, h_mm = meta["size_mm"]
    cv = spec.get("canvas", {})
    dpi = float(cv.get("dpi", 300))
    exp = fk_export.export(prev_svg, os.path.join(OUT, "figure"), w_mm, h_mm, dpi, cv.get("formats", []))
    png, pdf = os.path.join(OUT, "figure.png"), os.path.join(OUT, "figure.pdf")

    # content map with resolved sources
    problems, cmap, unsourced = [], [], []
    names0 = {(r["panel"], r["element_id"].split("-node-")[-1]): r["label"] for r in reg if r["type"] == "entity"}
    weak = []
    for r in reg:
        src = resolve_src(r.get("src"), problems, r["element_id"])
        if r["type"] == "relation" and src and all(s.get("text") for s in src):
            na, nb = core_name(names0.get((r.get("panel"), r.get("from")), r.get("from"))), core_name(names0.get((r.get("panel"), r.get("to")), r.get("to")))
            blob_ = " ".join(s["text"] for s in src)
            lost = [x for x in (na, nb) if not mentions(blob_, x)]
            if lost and len(na) > 1 and len(nb) > 1:
                wd = [w[:5] for w in re.findall(r"[a-z]{4,}", (str(r.get("label") or "") + " " + str(r.get("relation") or "")).lower())]
                pid_, sent = better_citation(na, nb, wd, {s["id"] for s in src})
                weak.append((r, lost, pid_, sent))
                r["citation_support"] = "cited passage does not name: " + ", ".join(lost)
        for s in src:
            if s.get("text"):
                ends = [names0.get((r.get("panel"), r.get(q)), r.get(q)) for q in ("from", "to") if r.get(q)]
                s["quote"] = best_quote(" ".join([r.get("label", ""), r.get("note", "") or ""] + ends + [str(r.get("evidence") or "")]), s.pop("text"), ends or ([r.get("label")] if r["type"] == "entity" else ()))
        item = {k: v for k, v in r.items() if k not in ("src",) and v not in ("", None)}
        item["source"] = src
        if not src and r["type"] in ("entity", "relation", "chart", "text"):
            unsourced.append(r["element_id"])
            item["source_status"] = "no source cited in spec"
        cmap.append(item)

    # independent checks on the delivered files
    checks = []
    want_n = {(p["id"], n["id"]) for p in spec["panels"] if p["type"] == "diagram" for n in p["nodes"]}
    want_e = sorted((p["id"], e["from"], e["type"], e["to"]) for p in spec["panels"] if p["type"] == "diagram" for e in p["edges"])
    ok_rel = want_n == facts["nodes"] and want_e == sorted(facts["edges"])
    if want_n:
        checks.append(check("entities_and_relations_round_trip", ok_rel,
                            "%d entities and %d directed relations re-parsed from figure.svg equal the specification" % (len(facts["nodes"]), len(facts["edges"]))
                            if ok_rel else "differences: nodes %s; edges %s" % (sorted(want_n ^ facts["nodes"])[:6], [e for e in want_e if e not in facts["edges"]][:6]),
                            "XML parse of delivered SVG, set comparison"))
    charts = {p["id"]: p for p in spec["panels"] if p["type"] == "chart"}
    rb = fk_chart.read_back(svg, read_table, charts) if charts else []
    for r in rb:
        checks.append(check("data_read_back_panel_%s" % r["panel"], r["pass"],
                            "%d marks inverted from geometry through the axis calibration and compared with %d source rows; max relative error %.2g%s" % (
                                r["marks_checked"], r["rows_expected_from_table"], r["max_relative_error"],
                                "" if r["pass"] else "; not drawn rows %s; mismatches %s" % (r["rows_not_drawn"], r["mismatches"][:3])),
                            "geometry -> value inversion, independent of drawing code"))
    for info in meta["charts"]:
        if info["missing_rows"]:
            warn.append("panel %s: rows %s hold no numeric value and are not drawn" % (info["panel"], info["missing_rows"][:12]))
        warn += ["panel %s: %s" % (info["panel"], x) for x in info.get("warnings", [])]
    geo = geometry(meta)
    geo["wider_than_panel"] = [[pid, "%.0f units" % m["res"]["w"]] for pid, m in meta["panels"].items() if m["res"]["w"] > m["inner"] + 3]
    bad = {k: v for k, v in geo.items() if k != "crossings" and v}
    checks.append(check("layout_collisions", not bad, "no node overlap, no connector through an unrelated node, no label collision; %d perpendicular crossings" % geo["crossings"] if not bad else json.dumps(bad, ensure_ascii=False)[:600],
                        "box/segment intersection on final geometry"))
    minpt = min(facts["sizes"] or [0]) / fk_draw.MM / meta["scale"] / 25.4 * 72
    checks.append(check("minimum_type_size", minpt >= float(cv.get("min_font_pt") or 5.0) - .05, "smallest live text %.2f pt at final width %.0f mm; required %s pt%s" % (minpt, w_mm, cv.get("min_font_pt") or "5 (default)", "; sub/superscripts (0.72 of their line, never below the minimum) are included in this measurement" if "_{" in json.dumps(plain) or "^{" in json.dumps(plain) else ""), "SVG font sizes at physical scale"))
    checks.append(check("editable_vector_structure", not facts["dup"] and facts["raster"] == 0,
                        "%d live text objects, %d unique ids, %d raster images; layers: %s" % (facts["texts"], len(facts["ids"]), facts["raster"], ", ".join(facts["layers"])), "XML parse"))
    pi, di = fk_export.inspect_png(png), fk_export.inspect_pdf(pdf, [strip_markup(r["label"]) for r in reg if r["type"] in ("entity", "panel-title", "title")])
    need_px = int(w_mm / 25.4 * dpi)
    checks.append(check("png_export", bool(pi.get("pixels")) and abs(pi["pixels"][0] - need_px) <= 4 and not pi.get("blank") and (not pi.get("touches_edge") or spec.get("theme") == "abstract"),
                        "%s" % pi, "decoded pixels: size, dpi, blank and edge-clipping tests"))
    checks.append(check("pdf_export", str(di.get("pages", "")) == "1" and not di.get("labels_not_found_as_text") and not di.get("fonts_not_embedded"), "%s" % di, "pdfinfo / pdffonts / pdftotext on delivered PDF"))
    gray = fk_export.inspect_gray(png)
    ng = max([len(q["groups"]) for q in meta["charts"]] or [0])
    group_cols = [fk_chart.PALETTE[q % len(fk_chart.PALETTE)] for q in range(ng)]
    checks.append(check("not_colour_only", ng <= len(fk_chart.PALETTE), "relation types differ by head/dash, chart groups by marker, dash or hatch as well as colour; grayscale preview saved" +
                        ("; group luminances %s" % ["%.2f" % lum(c) for c in group_cols] if group_cols else ""), "encoding redundancy + grayscale render"))
    max_w = cv.get("max_width_mm") or cv.get("width_mm", 180)
    max_h = cv.get("height_mm") or cv.get("max_height_mm")
    checks.append(check("physical_size", w_mm <= float(max_w) + .01 and (abs(h_mm - float(cv["height_mm"])) < .2 if cv.get("height_mm") else h_mm <= float(max_h or max(240, w_mm * 1.25)) + .01), "%.1f x %.1f mm%s" % (w_mm, h_mm, " (required %s x %s mm)" % (cv.get("width_mm"), cv["height_mm"]) if cv.get("height_mm") else " (limit height %s mm)" % max_h if max_h else ""), "SVG width/height"))
    checks.append(check("source_coverage", not unsourced and not problems,
                        "%d of %d scientific elements carry a resolved source" % (
                            sum(1 for c in cmap if c["type"] in ("entity", "relation", "chart", "text") and c["source"]),
                            sum(1 for c in cmap if c["type"] in ("entity", "relation", "chart", "text"))) +
                        ("; unsourced: %s" % unsourced[:10] if unsourced else "") + ("; problems: %s" % problems[:5] if problems else ""), "every src id looked up in the indexed input; quotes matched verbatim"))

    untraced = []
    for r in reg:
        if r["type"] in ("entity", "relation", "text", "note", "panel-title", "title"):
            t = " ".join(str(r.get(k, "")) for k in ("label", "note"))
            if r["type"] in ("panel-title", "title"):
                t = re.sub(r"^\s*(?:[A-Z]\s+)?\d{1,2}[.)]?\s+", "", t)
            elif r["type"] == "entity":
                t = re.sub(r"^\s*\d{1,2}[.)]\s+", "", t)
            srcs = r.get("src") or [x for x in [q.get("src") for q in reg if q.get("panel") == r.get("panel")] if x][:40]
            flat = []
            for x in (srcs if isinstance(srcs, list) else [srcs]):
                flat += x if isinstance(x, list) else [x]
            miss = trace_numbers(t, flat + ([] if r.get("src") else ["workorder"]))
            if miss:
                untraced.append({"element": r["element_id"], "numbers": miss})
    for p in spec["panels"]:
        if p["type"] == "chart":
            try:
                tp = table_path(p["data"])
            except ValueError:
                continue
            if not os.path.abspath(tp).startswith(os.path.abspath(INPUT)):
                cols_, rows_ = read_table(p["data"])
                cells = " ; ".join(str(v) for r in rows_ for v in r.values())
                miss = trace_numbers(cells, [x for x in (p.get("src") if isinstance(p.get("src"), list) else [p.get("src")]) if x and x != p["data"]])
                if miss:
                    untraced.append({"element": p["id"] + "-chart (typed data)", "numbers": miss[:12]})
    if untraced:   # the record must not call a number stated when its cited text does not contain it
        bad_ = {u["element"]: u["numbers"] for u in untraced}
        for c_ in cmap:
            if c_.get("element_id") in bad_:
                c_["number_check"] = "not found in the cited text: %s" % ", ".join(map(str, bad_[c_["element_id"]][:6]))
                if str(c_.get("certainty") or "stated") in ("stated", "observed"):
                    c_["certainty"] = "derived or unverified (number not in the cited text)"
    checks.append(check("numbers_traceable", not untraced, "every number printed on the figure occurs in its cited source" if not untraced else
                        "not found verbatim in the cited source (verify, or cite the right source / mark as derived): %s" % json.dumps(untraced[:8], ensure_ascii=False), "numeric tokens searched in the cited passages/rows"))
    # edit record
    record = None
    if a.revise and os.path.exists(os.path.join(OUT, "figure_before_edit.svg")):
        record = svg_diff(os.path.join(OUT, "figure_before_edit.svg"), prev_svg, a.revise)
        jsave(os.path.join(OUT, "edit_record.json"), record)
        did = len(record["changed"]) + len(record["added"]) + len(record["removed"])
        allow = [str(x) for x in (spec.get("edit_scope") or [])]
        BOXES = ("-edges", "-nodes", "-groups", "-edge-labels", "-chart", "-data", "-axes", "-text", "-legend")
        is_container = lambda i: i.startswith(("panel-", "figure-content", "figure-legend", "layer-")) and not i.endswith(("-title", "-note")) or i.endswith(BOXES)

        def within(i, pats):
            pats = [x.rstrip("-") for x in pats]
            return any(i == x or i.startswith(x + "-") or i.startswith("panel-" + x) or (len(x) > 2 and x in i) for x in pats)
        outside = [c["id"] for c in record["changed"] if allow and not within(c["id"], allow) and not (is_container(c["id"]) and not c["id"].endswith(("-chart", "-data", "-axes")))]
        outside += [x for x in record["removed"] if allow and not within(x, allow) and not is_container(x)]
        outside = [x for x in outside if not x.startswith(("legend", "footnote", "background"))]
        prot = [str(x) for x in (spec.get("edit_protect") or [])]
        hit = [c["id"] for c in record["changed"] if within(c["id"], prot)] + [x for x in record["removed"] if within(x, prot)]
        moved = locked is not None and locked.get("_view") and [round(v, 2) for v in locked["_view"]] != [round(v, 2) for v in meta["view"]]
        if moved and meta["view"][2] and abs(locked["_view"][2] / meta["view"][2] - 1) <= .05:   # element markup identical, page view within 5 %: disclosed, not a failure
            record["page_rescale_within_5_percent"] = round(locked["_view"][2] / meta["view"][2], 3)
            moved = False
        record["page_coordinate_system"] = ("page view rescaled uniformly by %.3f (within 5 %%) to hold the addition; markup and coordinates of untouched elements are unchanged" % record["page_rescale_within_5_percent"]) if record.get("page_rescale_within_5_percent") else "identical viewBox and content offset" if not moved else "the fixed page could not hold the addition, so the whole page is scaled uniformly by %.3f; markup of untouched elements is unchanged" % (locked["_view"][2] / meta["view"][2])
        record["edit_scope"], record["outside_scope"], record["protected_touched"] = allow, outside, hit
        jsave(os.path.join(OUT, "edit_record.json"), record)
        checks.append(check("source_preserving_edit", did > 0 and not outside and not hit and not moved,
                            "requested: %s; changed %d %s, added %d %s, removed %d %s; byte-identical %d elements%s%s%s" % (
                                a.revise, len(record["changed"]), [c["id"] for c in record["changed"]][:30], len(record["added"]), record["added"][:20], len(record["removed"]), record["removed"][:20], record["unchanged_elements"],
                                ("; " + record["page_coordinate_system"] if moved or record.get("page_rescale_within_5_percent") else "") + ("; OUTSIDE edit_scope: %s" % outside[:8] if outside else ""), "; PROTECTED objects touched: %s" % hit[:8] if hit else "",
                                "" if allow or prot else "; no edit_scope/edit_protect was declared, so the full list of changed ids above is the evidence"), "element-by-element comparison by id against the frozen first version"))
        for old_, new_ in edit_pairs(" ".join([str(a.revise)] + [ln for ln in must_lines() if re.search(r"(?i)edit|revis|convert|replace", ln)])):
            seen_t = [k for k in ("title", "caption") if old_.lower() in strip_markup(str(spec.get(k) or "")).lower() and new_.lower() not in strip_markup(str(spec.get(k) or "")).lower()]
            seen_t += ["panel %s title" % p["id"] for p in spec["panels"] if old_.lower() in strip_markup(str(p.get("title") or "")).lower()]
            checks.append(check("edit_variant_consistency", not seen_t, ("after the edit (%s -> %s) these still name '%s': %s" % (old_, new_, old_, ", ".join(seen_t))) if seen_t else
                                "no title, caption or panel title still names the replaced variant '%s'" % old_, "title, caption and panel titles searched for the replaced and the new variant"))
            if seen_t:
                say("ATTENTION the edited figure still names the replaced variant '%s' in %s: make it name '%s' (if the edit forbids touching the title, say so in an exception)." % (old_, ", ".join(seen_t), new_))
            break
    elif os.path.exists(os.path.join(OUT, "edit_record.json")):
        record = jload(os.path.join(OUT, "edit_record.json"))
    exceptions = []
    for u in spec.get("unresolved", []):
        if not isinstance(u, dict):
            u = {"item": str(u)}
        u = dict(u)
        u["source"] = tidy(resolve_src(u.pop("src", None), problems, "unresolved"), "%s %s" % (u.get("item", ""), u.get("detail", "")))
        u.setdefault("state", "unresolved")
        exceptions.append(u)
    exceptions += unreadable_inputs()
    for x in spec.get("_strength") or []:
        exceptions.append({"item": "relation %s -> %s (panel %s)" % (x["from"], x["to"], x["panel"]), "state": "drawn as %s, not as a demonstrated relation" % (x["now"]["type"] if x["now"]["type"] == "association" else x["now"]["certainty"]),
                           "detail": x["reason"], "source": [{"id": x["source"], "quote": x["quote"]}], "found_by": "engine evidence-class check"})
    try:
        exceptions += auto_exceptions(exceptions + [spec.get("footnotes"), spec.get("caption")])
    except Exception:
        pass
    for info in meta["charts"]:
        if info["missing_rows"]:
            exceptions.append({"item": "panel %s: rows without a numeric value" % info["panel"], "state": "not drawn, not imputed", "detail": {"file": info["file"], "rows": info["missing_rows"][:60], "count": len(info["missing_rows"])}})
    for c in checks:
        if c["result"] != "pass":
            exceptions.append({"item": c["check"], "state": "check needs attention", "detail": c["detail"][:500]})
    if exp["fallback_log"]:
        exceptions.append({"item": "export renderer fallback", "state": "resolved" if exp["renderer"] else "failed", "detail": exp["fallback_log"], "used": exp["renderer"]})
    files = [p for p in (prev_svg, png, pdf) if os.path.exists(p)]
    status = "completed" if len(files) == 3 and not problems and ok_rel and all(r["pass"] for r in rb) and not spec.get("_starter") else "partial"
    if spec.get("_starter"):
        exceptions.append({"item": "starter draft", "state": "not a finished figure", "detail": "entity names taken from the work order and the material by the engine; no relations drawn yet"})
    with open(os.path.join(OUT, "element_source_map.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["element_id", "type", "label_or_relation", "certainty", "source_id", "file", "locator", "quote"])
        for c in cmap:
            for s in (c["source"] or [{}]):
                w.writerow([c["element_id"], c["type"], c.get("label") or "%s -%s-> %s" % (c.get("from", ""), c.get("relation", ""), c.get("to", "")), c.get("certainty", ""), s.get("id", ""), s.get("file", ""), s.get("locator", ""), s.get("quote", "")])
    rel_rows = [c for c in cmap if c["type"] == "relation"]
    if rel_rows:
        names = {(c["panel"], c["element_id"].split("-node-")[-1]): c["label"] for c in cmap if c["type"] == "entity"}
        extra = []
        for c in rel_rows:
            for k in (c.get("evidence") if isinstance(c.get("evidence"), dict) else {}) or {}:
                if k not in extra:
                    extra.append(k)
        with open(os.path.join(OUT, "edge_table.csv"), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["edge_id", "panel", "from", "to", "type", "label", "status", "layer"] + extra + ([] if extra else ["evidence"]) + ["source_id", "locator", "quote"])
            for c in rel_rows:
                ev = c.get("evidence")
                s0 = (c["source"] or [{}])
                w.writerow([c["element_id"], c["panel"], names.get((c["panel"], c["from"]), c["from"]), names.get((c["panel"], c["to"]), c["to"]), c["relation"], c.get("label", ""), c.get("certainty", ""), c.get("layer", "")] +
                           ([ev.get(k, "") if isinstance(ev, dict) else "" for k in extra] if extra else [ev if isinstance(ev, str) else ""]) +
                           ["; ".join(x.get("id", "") for x in s0), "; ".join(x.get("label") or x.get("locator", "") for x in s0), " | ".join(x.get("quote", "") for x in s0)])
    if meta["charts"]:
        with open(os.path.join(OUT, "plotted_values.csv"), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["panel", "file", "row_or_rows (of the source file, or of data/<panel>_prepared.csv when derive/reduce is used)", "group", "x", "y", "lo", "hi", "n", "statistic"])
            for info in meta["charts"]:
                for v in info.get("values", []):
                    w.writerow([info["panel"], info["file"]] + v)
    if spec.get("caption"):
        with open(os.path.join(OUT, "figure_caption.md"), "w", encoding="utf-8") as f:
            f.write("# %s\n\n%s\n" % (strip_markup(spec.get("title", "Figure")), spec["caption"]))
    for s in ("figkit.py", "kit_sources.py", "kit_table.py", "fk_text.py", "fk_layout.py", "fk_chart.py", "fk_draw.py", "fk_export.py", "fk_flow.py"):
        os.makedirs(os.path.join(OUT, "rebuild"), exist_ok=True)
        try:
            shutil.copy(os.path.join(HERE, s), os.path.join(OUT, "rebuild", s))
        except OSError:
            pass
    ddir = os.path.join(OUT, "data")
    for p in spec["panels"]:
        if p["type"] == "chart" and (p.get("derive") or p.get("reduce")):
            os.makedirs(ddir, exist_ok=True)
            pc, pr = fk_chart.prepare(p, *read_table(p["data"]))
            with open(os.path.join(ddir, p["id"] + "_prepared.csv"), "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["row"] + pc + ["source_rows_in_" + os.path.basename(p["data"])])
                for k, r in enumerate(pr, 1):
                    w.writerow([k] + [r.get(c, "") for c in pc] + [r.get("_src", k)])
    for p in spec["panels"]:
        for q in [p] + list(p.get("overlays") or []):
            if q.get("data"):
                os.makedirs(ddir, exist_ok=True)
                try:
                    src_p = table_path(q["data"])
                    dst = os.path.join(ddir, os.path.basename(src_p))
                    if os.path.abspath(src_p) != os.path.abspath(dst):
                        shutil.copy(src_p, dst)
                except (ValueError, OSError):
                    pass
    for f in glob.glob(os.path.join(WORK, "*.py")):
        shutil.copy(f, os.path.join(OUT, "rebuild", os.path.basename(f)))
    with open(os.path.join(OUT, "rebuild", "rebuild.sh"), "w", encoding="utf-8") as f:
        f.write("""#!/bin/sh
# sh rebuild.sh [INPUT_FOLDER]   rebuilds the delivered figure from figure_spec.json into ../_rebuilt
cd "$(dirname "$0")" || exit 1
mkdir -p ../_work ../_rebuilt && cp -f ../data/* ../_work/ 2>/dev/null
KIT_INPUT="${1:-/input}" KIT_WORK="$PWD/../_work" KIT_OUTPUT="$PWD/../_rebuilt" python3 figkit.py build --spec ../figure_spec.json
""")
    inv = lambda p: {"path": p, "format": os.path.splitext(p)[1][1:], "bytes": os.path.getsize(p), "sha256": fk_export.sha(p)}
    inputs = [{"file": rel(p), "sha256": fk_export.sha(p)} for p in walk_inputs()]
    ex = {"figure_png": dict(inv(png), dpi=dpi, pixels=pi.get("pixels")) if os.path.exists(png) else None,
          "figure_pdf": dict(inv(pdf), pages=di.get("pages")) if os.path.exists(pdf) else None,
          "other_files": [inv(p) for p in exp["files"] if p not in (png, pdf)],
          "grayscale_preview": gray, "renderer": exp["renderer"], "physical_size_mm": [w_mm, h_mm]}
    res = {
        "status": status,
        "editable_source": {"path": prev_svg, "format": "layered SVG with live text and stable ids", "sha256": fk_export.sha(prev_svg),
                            "layers": facts["layers"], "specification": os.path.join(OUT, "figure_spec.json"),
                            "before_edit": os.path.join(OUT, "figure_before_edit.svg") if record else None,
                            "rebuild_command": "sh /app/output/rebuild/rebuild.sh /input   (first argument = case input folder; writes ../_rebuilt)"},
        "export_artifact": ex, "content_map": cmap, "compliance_checks": checks, "exceptions": exceptions,
        "title": strip_markup(spec.get("title", "")), "caption": spec.get("caption", ""),
        "edit_record": record, "design_decisions": spec.get("decisions", []),
        "unsupported_or_omitted": spec.get("omitted", []),
        "provenance": {"engine": "figkit %s" % VERSION, "inputs": inputs, "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "build_seconds": round(time.time() - t0, 1), "python": sys.version.split()[0]},
        "uncertainty": [c for c in cmap if c.get("certainty") not in (None, "stated", "observed")],
    }
    try:
        nb_ = jload(os.path.join(WORK, ".builds")).get("n", 0) + 1
    except (OSError, ValueError):
        nb_ = 1
    open_ = [c["check"] for c in checks if c["result"] != "pass"]
    if "source_preserving_edit" in open_ and status == "completed":
        status = res["status"] = "partial"
    res["run_record"] = {"builds_so_far": nb_, "minutes_since_start": round(ks_elapsed(), 1), "checks_passed": "%d/%d" % (len(checks) - len(open_), len(checks)),
                         "open_checks": open_, "relations_redrawn_by_evidence_class": len(spec.get("_strength") or []),
                         "edit": "done" if record else "not requested or not done yet",
                         "note": "measured by the engine during this run; the platform's own trace is the authority for time and requests"}
    write_result(res)
    say("BUILT status=%s  %.0f x %.0f mm  renderer=%s  %.1fs" % (status, w_mm, h_mm, exp["renderer"], time.time() - t0))
    if spec.get("_starter") or os.environ.get("KIT_STARTER"):
        say("STARTER draft built (not counted).")
        return
    cnt_f = os.path.join(WORK, ".builds")
    try:
        st = jload(cnt_f)
    except (OSError, ValueError):
        st = {"n": 0, "size": 0, "stuck": 0}
    n_build = st["n"] + 1
    grown = len(cmap) != st["size"] or bool(a.revise and not st.get("revised"))
    st = {"n": n_build, "size": len(cmap), "stuck": 0 if grown else st["stuck"] + 1, "revised": bool(a.revise) or st.get("revised", False)}
    HINT = {"layout_collisions": "shorten the named labels or move their detail to the caption; one try is enough",
            "minimum_type_size": "remove node notes / shorten labels, or drop nodes no must-show item needs",
            "physical_size": "fewer or shorter nodes, or move a panel's text to the caption",
            "numbers_traceable": "add the passage that has the number to src, or fix the number; if it is computed say so in the label",
            "source_coverage": "add src to the named elements",
            "pdf_export": "shorten the labels that were cut", "png_export": "content touches the edge: shorten long labels",
            "source_preserving_edit": "if the named ids belong to the requested edit, add them (or just the panel id, e.g. \"A\") to edit_scope; otherwise undo that change"}
    told = st.setdefault("told", {})
    req = float(cv.get("min_font_pt") or 5.0)
    n_nodes = sum(len(p.get("nodes", [])) for p in spec["panels"])
    for c in checks:
        if c["result"] == "pass":
            continue
        told[c["check"]] = told.get(c["check"], 0) + 1
        if ks_elapsed() > 6.5 and c["check"] not in ("source_preserving_edit", "entities_and_relations_round_trip"):
            continue
        if (a.revise and c["check"] in ("minimum_type_size", "physical_size", "png_export", "not_colour_only")) or told[c["check"]] > (1 if c["check"] in ("minimum_type_size", "physical_size") else 2):
            say("(already disclosed in exceptions - leave it and go on: %s)" % c["check"])
            continue
        if c["check"] == "minimum_type_size" and minpt < req:
            keep = max(.3, (minpt / req) ** 1.6)
            HINT["minimum_type_size"] = "the page is too full: to reach %g pt cut about %d%% of the text%s. Do this ONCE (drop node notes, shorten items, move detail to the caption), then accept the result; font_pt, direction and layout do not change it - the engine already searched them" % (
                req, round(100 * (1 - keep)), " (about %d of %d nodes fit)" % (max(4, int(n_nodes * keep)), n_nodes) if n_nodes > 8 else "")
        if c["result"] != "pass":
            say("ATTENTION %s: %s\n   -> %s" % (c["check"], c["detail"][:420], HINT.get(c["check"], "disclosed in exceptions; fix only if it is one spec edit")))
    jsave(cnt_f, st)
    for w_ in warn[:10]:
        if ("flow continuity" in w_ or "sends '" in w_) and ks_elapsed() < 8:
            unit_ = re.findall(r"'([^']+)'", w_)
            try:
                from kit_sources import rank_passages
                pp_ = rank_passages((unit_[0] if unit_ else "") + " flows water enters leaves through outlet pumped from to", 2, 700)
                w_ += "".join("\n       %s %s" % (q["id"], t[:330]) for q, t in pp_)
            except Exception:
                pass
        say("NOTE", w_)
    for p_ in problems[:10]:
        say("SOURCE", p_)
    if weak and ks_elapsed() < 7:
        say("CITATIONS THAT DO NOT NAME BOTH ENDS (%d): cite the sentence that shows the relation - one line per relation in <panel>.cite (`from | to | P027`) - or change the relation to what the source says, or mark it proposed:" % len(weak))
        for r, lost, pid_, sent in weak[:6]:
            say("  %s -> %s cites %s, which does not mention %s%s" % (r["from"], r["to"], ",".join(map(str, r.get("src") if isinstance(r.get("src"), list) else [r.get("src")])), "/".join(lost),
                "; candidate %s: %s" % (pid_, sent[:210]) if pid_ else "; no passage names both: is this relation stated anywhere?"))
    miss = [k for k in ("caption",) if not spec.get(k)]
    if miss:
        say("NOTE spec has no", miss)
    if len(pend_) and pend_ != [p["id"] for p in spec["panels"]]:
        say("NOTE still empty and not drawn yet: panel(s) %s" % ", ".join(map(str, pend_)))
    say("build %d, %.1f min since brief. Deliverables and result.json are complete and saved." % (n_build, ks_elapsed()))
    if a.revise and spec.get("caption"):
        say("CHECK the caption still describes the edited figure (it is part of the delivery): %s" % strip_markup(str(spec["caption"]))[:420])
    want_edit = [ln.strip() for ln in must_lines() if re.search(r"(?i)^\s*(edit|revision)[\w.\[\]]*\s*:", ln) and "text" in ln[:40].lower()]
    if want_edit and not st.get("revised") and (st["stuck"] >= 3 or ks_elapsed() > 6) and any(p.get("edges") or p["type"] != "diagram" for p in spec["panels"]):
        say("EDIT NOW (%.1f min): the first version is complete enough and its open points are disclosed. The requested edit is NOT DONE YET; a missing edit costs far more than any polish. Append its lines / spec change, set edit_scope, `build --revise \"...\"`: %s" % (ks_elapsed(), want_edit[0][:500]))
    elif st["stuck"] >= 3 or ks_elapsed() > (7.5 if st.get("revised") else 8):
        say("STOP RULE (%.1f min): complete; open points are disclosed. Run verify now and finish. No layout, font or wording polishing." % ks_elapsed())
    if not spec.get("title") or not spec.get("caption"):
        say("NEXT: add title and caption to /app/work/spec.json (they are still missing).")
    elif walking() and not a.revise:
        say("NEXT: run `next` for the next requirement.")
    elif any(p["type"] == "diagram" and not p.get("edges") for p in spec["panels"]):
        say("NEXT: append the first 6 relations to <panel>.edges and build again. Think only about these 6.")
    elif st["stuck"] < 3 and ks_elapsed() < 5.5:
        say("NEXT: re-read the must-show list (and, if it says 'all' of a table, its rows): name what is still missing, and append further relations/panels that must-show items need (at most 6 lines per response), or fix the ATTENTION lines; then run review once, look at figure.png once, do the requested edit with --revise, verify, stop.")
    say("%d/%d checks pass. result.json saved (%d mapped elements)." % (sum(c["result"] == "pass" for c in checks), len(checks), len(cmap)))


# --- element-level editing -------------------------------------------------------------
ELEM = re.compile(r"<([A-Za-z][\w:.-]*)([^<>]*?)(/?)>", re.S)


def elements_by_id(text):
    """id -> outer markup, by a tolerant tag scanner (bytes outside edits stay untouched)."""
    out, stack = {}, []
    for m in re.finditer(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<!DOCTYPE.*?>|</\s*([\w:.-]+)\s*>|<([A-Za-z][\w:.-]*)((?:\"[^\"]*\"|'[^']*'|[^<>\"'])*)>", text, re.S):
        if m.group(2):
            attrs = m.group(3)
            idm = re.search(r"\bid\s*=\s*(\"([^\"]*)\"|'([^']*)')", attrs)
            ident = (idm.group(2) if idm and idm.group(2) is not None else idm.group(3)) if idm else None
            if attrs.rstrip().endswith("/"):
                if ident:
                    out[ident] = (m.start(), m.end(), m.group(2))
            else:
                stack.append((m.group(2), ident, m.start()))
        elif m.group(1):
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][0] == m.group(1):
                    tag, ident, st = stack[k]
                    del stack[k:]
                    if ident:
                        out[ident] = (st, m.end(), tag)
                    break
    return out


def svg_diff(before, after, reason):
    a, b = open(before, encoding="utf-8").read(), open(after, encoding="utf-8").read()
    ea, eb = elements_by_id(a), elements_by_id(b)
    ta, tb = {k: a[v[0]:v[1]] for k, v in ea.items()}, {k: b[v[0]:v[1]] for k, v in eb.items()}
    changed = [k for k in ta if k in tb and ta[k] != tb[k]]
    leaf = [k for k in changed if not any(o != k and o in changed and ea[k][0] <= ea[o][0] and ea[o][1] <= ea[k][1] for o in changed)]
    return {"request": reason, "before": {"path": before, "sha256": fk_export.sha(before)}, "after": {"path": after, "sha256": fk_export.sha(after)},
            "changed": [{"id": k, "before": ta[k][:400], "after": tb[k][:400]} for k in leaf][:60],
            "containers_of_changes": [k for k in changed if k not in leaf][:40],
            "added": [k for k in tb if k not in ta][:80], "removed": [k for k in ta if k not in tb][:80],
            "unchanged_elements": sum(1 for k in ta if tb.get(k) == ta[k]),
            "rollback": "restore %s" % before}


def cmd_svgtree(a):
    t = open(table_path(a.file) if not os.path.exists(a.file) else a.file, encoding="utf-8").read()
    els = elements_by_id(t)
    say("%d elements with id; showing id, tag, text" % len(els))
    for k, (s, e, tag) in list(els.items())[:160]:
        inner = clean(re.sub(r"<[^>]+>", " ", t[s:e]))
        say("  %-38s %-8s %s" % (k, tag, inner[:80]))
    m = re.search(r"<svg[^>]*>", t, re.S)
    say(m.group(0)[:300] if m else "")


def cmd_edit(a):
    """ops: [{"id":..., "op":"text|attr|style|remove|insert_after|insert_before|replace", ...}]"""
    src = a.file if os.path.exists(a.file) else table_path(a.file)
    ops = jload(a.ops)
    ops = ops.get("ops", ops) if isinstance(ops, dict) else ops
    os.makedirs(OUT, exist_ok=True)
    before = os.path.join(OUT, "figure_before_edit.svg")
    if os.path.abspath(src) != os.path.abspath(before):
        shutil.copy(src, before)
    text = open(before, encoding="utf-8").read()
    log = []
    from html import escape
    for op in ops:
        els = elements_by_id(text)
        i, kind = op.get("id"), op.get("op")
        if i not in els:
            log.append({"op": op, "result": "failed: id not found"})
            continue
        s, e, tag = els[i]
        chunk = text[s:e]
        if kind == "text":
            new = escape(str(op["value"]))
            if op.get("old"):
                o = escape(str(op["old"]))
                if o not in chunk:
                    log.append({"op": op, "result": "failed: old text not found in element"})
                    continue
                repl = chunk.replace(o, new, 1)
            else:
                body = re.findall(r">([^<>]*[^\s<>][^<>]*)<", chunk)
                if len(body) != 1:
                    log.append({"op": op, "result": "failed: element holds %d text runs; give 'old'" % len(body)})
                    continue
                repl = chunk.replace(">" + body[0] + "<", ">" + new + "<", 1)
        elif kind in ("attr", "style"):
            head = re.match(r"<[^>]*>", chunk, re.S).group(0)
            h2 = head
            for k, v in (op.get("set") or {op.get("name"): op.get("value")}).items():
                v = escape(str(v), quote=True)
                if re.search(r"\b%s\s*=\s*\"[^\"]*\"" % re.escape(k), h2):
                    h2 = re.sub(r"\b%s\s*=\s*\"[^\"]*\"" % re.escape(k), lambda m: '%s="%s"' % (k, v), h2, count=1)
                else:
                    h2 = re.sub(r"(/?>)$", lambda m: ' %s="%s"%s' % (k, v, m.group(1)), h2)
            repl = h2 + chunk[len(head):]
        elif kind == "remove":
            repl = ""
        elif kind == "replace":
            repl = op["svg"]
        elif kind == "insert_after":
            repl = chunk + op["svg"]
        elif kind == "insert_before":
            repl = op["svg"] + chunk
        else:
            log.append({"op": op, "result": "failed: unknown op"})
            continue
        text = text[:s] + repl + text[e:]
        log.append({"op": op, "result": "applied"})
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:
        sys.exit("edited SVG would not parse (%s); nothing written. Check op 'svg' fragments." % exc)
    after = os.path.join(OUT, "figure.svg")
    with open(after, "w", encoding="utf-8") as f:
        f.write(text)
    rec = svg_diff(before, after, a.reason or "element-level edit requested by the work order")
    rec["operations"] = log

    def mm(v):
        m = re.match(r"([\d.]+)\s*(mm|cm|in|pt|px)?", v or "")
        if not m:
            return None
        return float(m.group(1)) * {"mm": 1, "cm": 10, "in": 25.4, "pt": 25.4 / 72, "px": 25.4 / 96, None: 25.4 / 96}[m.group(2)]
    w, h = mm(root.get("width")), mm(root.get("height"))
    vb = [float(x) for x in re.split(r"[ ,]+", root.get("viewBox", "").strip()) if x]
    if not w and vb:
        w, h = vb[2] * 25.4 / 96, vb[3] * 25.4 / 96
    exp = fk_export.export(after, os.path.join(OUT, "figure"), w, h, 300)
    exp0 = fk_export.export(before, os.path.join(OUT, "figure_before_edit"), w, h, 300)
    jsave(os.path.join(OUT, "edit_record.json"), rec)
    say("EDIT: %d applied, %d failed; changed %d leaf elements, added %d, removed %d, byte-identical %d" % (
        sum(x["result"] == "applied" for x in log), sum(x["result"] != "applied" for x in log), len(rec["changed"]), len(rec["added"]), len(rec["removed"]), rec["unchanged_elements"]))
    for x in log:
        if x["result"] != "applied":
            say(" -", x["result"], json.dumps(x["op"], ensure_ascii=False)[:160])
    pi, di = fk_export.inspect_png(os.path.join(OUT, "figure.png")), fk_export.inspect_pdf(os.path.join(OUT, "figure.pdf"), [])
    meta_p = os.path.join(WORK, "edit_meta.json")
    em = jload(meta_p) if os.path.exists(meta_p) else {}
    problems, cmap = [], []
    for op, x in zip(ops, log):
        cmap.append({"element_id": op.get("id"), "type": "edit", "operation": op.get("op"), "value": op.get("value") or op.get("set") or op.get("svg", "")[:200],
                     "reason": op.get("reason", ""), "result": x["result"], "source": resolve_src(op.get("src"), problems, str(op.get("id")))})
    allowed = em.get("allowed_ids")
    outside = [c["id"] for c in rec["changed"] if allowed and c["id"] not in allowed]
    checks = [check("source_preserving_edit", not outside, "changed %s; byte-identical elements %d%s" % ([c["id"] for c in rec["changed"]][:20], rec["unchanged_elements"], "; OUTSIDE allowed list: %s" % outside if outside else ""), "element-by-element comparison by id"),
              check("png_export", not pi.get("blank") and bool(pi.get("pixels")), str(pi), "decoded pixels"),
              check("pdf_export", str(di.get("pages", "")) == "1", str(di), "pdfinfo/pdffonts")]
    inv = lambda p: {"path": p, "bytes": os.path.getsize(p), "sha256": fk_export.sha(p)}
    write_result({"status": "completed" if all(x["result"] == "applied" for x in log) and exp["renderer"] else "partial",
                  "editable_source": {"path": after, "format": "SVG (edited in place)", "sha256": fk_export.sha(after), "original": inv(src), "before_edit": before},
                  "export_artifact": {"figure_png": inv(os.path.join(OUT, "figure.png")), "figure_pdf": inv(os.path.join(OUT, "figure.pdf")), "before_preview": exp0["files"], "renderer": exp["renderer"]},
                  "content_map": cmap + em.get("content_map", []), "compliance_checks": checks + em.get("compliance_checks", []),
                  "exceptions": em.get("exceptions", []) + [{"item": str(x["op"].get("id")), "state": x["result"]} for x in log if x["result"] != "applied"], "edit_record": rec,
                  "provenance": {"engine": "figkit %s" % VERSION, "inputs": [{"file": rel(p), "sha256": fk_export.sha(p)} for p in walk_inputs()]}})
    say("result.json saved. Add extra content_map/exceptions through %s if needed, then rerun." % meta_p)


def cmd_review(a):
    """Claims next to the sentences they cite, plus the requirement list: a semantic self-check for the agent."""
    r = jload(os.path.join(OUT, "result.json"))
    names = {(c["panel"], c["element_id"].split("-node-")[-1]): c["label"] for c in r.get("content_map") or [] if c.get("type") == "entity"}
    say("# CLAIM | cited sentence. Ask for each: same direction? same strength (stated/cited/proposed)? same condition? If the sentence does not say it: fix src, certainty, label, or delete.")
    used = 0
    for c in r.get("content_map") or []:
        if c.get("type") not in ("relation", "text", "chart", "entity", "note", "panel-title"):
            continue
        if c["type"] == "entity" and not re.search(r"\d", c.get("label", "") + c.get("note", "")):
            continue
        if c["type"] == "relation":
            t = "%s -%s-> %s%s [%s]" % (names.get((c["panel"], c["from"]), c["from"]), c["relation"], names.get((c["panel"], c["to"]), c["to"]), " '%s'" % c["label"] if c.get("label") else "", c.get("certainty"))
        else:
            t = "%s: %s %s" % (c["type"], c.get("label", ""), c.get("note", "") or "")
        q = " || ".join("%s: %s" % (x.get("id"), x.get("quote") or x.get("locator", "")) for x in c.get("source") or []) or "NO SOURCE"
        line = "%s\n     %s" % (t[:190], q[:300])
        used += len(line)
        if used > 9000:
            say("... more: see element_source_map.csv")
            break
        say(line)
    blob = " ".join(str(c.get(k, "")) for c in r.get("content_map") or [] for k in ("label", "note", "evidence", "relation", "kind")) + " " + " ".join(str(r.get(k, "")) for k in ("title", "caption", "exceptions", "design_decisions", "unsupported_or_omitted", "edit_record"))
    seen = ""
    try:
        import xml.etree.ElementTree as ET
        seen = " ".join(" ".join(t.itertext()) for t in ET.parse(os.path.join(OUT, "figure.svg")).getroot().iter("{http://www.w3.org/2000/svg}text"))
    except Exception:
        pass
    print_must(blob[:400000], visible=seen or None)


def cmd_verify(a):
    p = os.path.join(OUT, "result.json")
    r = jload(p)
    bad = [k for k in contract() if k not in r]
    if r.get("case_id") != case_id():
        bad.append("case_id mismatch")

    def files(o):
        if isinstance(o, dict):
            if isinstance(o.get("path"), str) and o.get("sha256"):
                yield o["path"], o["sha256"]
            for v in o.values():
                yield from files(v)
        elif isinstance(o, list):
            for v in o:
                yield from files(v)
    n = 0
    for f in ("figure.svg", "figure.png", "figure.pdf"):
        if not os.path.exists(os.path.join(OUT, f)):
            bad.append("missing deliverable " + f)
    if not r.get("content_map") or not r.get("compliance_checks"):
        bad.append("content_map/compliance_checks empty: nothing has been built")
    for f, h in files({k: r.get(k) for k in ("editable_source", "export_artifact")}):
        n += 1
        if not os.path.exists(f):
            bad.append("missing file " + f)
        elif fk_export.sha(f) != h:
            bad.append("hash differs: " + f)
    att = [c["check"] for c in (r.get("compliance_checks") or []) if c.get("result") != "pass"]
    if att:
        say("OPEN CHECKS (disclosed in exceptions):", att)
    if not bad and ks_elapsed() > 5.5:
        say("DONE at %.1f min: the delivery is complete and checked. FINAL STEP: reply with one short sentence and end. Do not view the image, open result.json, edit_record.json or REPORT.md, list files or run any command again: everything is written and verified, and every extra call only adds time (the run is cut at minute 15)." % ks_elapsed())
    nrev, fresh = review_state()
    if ks_elapsed() < 5.5 and (nrev == 0 or (nrev < 2 and not fresh)):
        say("NOT DONE YET: %s (%.1f of 15 min used)." % ("run review once - claims against quotes, requirements, possibly missing terms" if nrev == 0 else "content changed since the last review: run review again and close the remaining gaps", ks_elapsed()))
    say("VERIFY", ("OK" if r.get("status") == "completed" else "INCOMPLETE (status %s)" % r.get("status")) if not bad else "PROBLEMS: %s" % bad, "| status=%s | %d files hashed | %d map entries | %d checks | %d exceptions" % (
        r.get("status"), n, len(r.get("content_map") or []), len(r.get("compliance_checks") or []), len(r.get("exceptions") or [])))
    return 1 if bad else 0


def cmd_selftest(a):
    ex = next((p for p in (os.path.join(os.path.dirname(HERE), "examples", "synthetic"), os.path.join(HERE, "examples", "synthetic")) if os.path.isdir(p)), "")
    d = tempfile.mkdtemp(prefix="figkit_")
    env = dict(os.environ, KIT_INPUT=os.path.join(ex, "input"), KIT_WORK=d + "/work", KIT_OUTPUT=d + "/out")
    os.makedirs(d + "/work")
    shutil.copy(os.path.join(ex, "spec.json"), d + "/work/spec.json")
    for c in (["brief"], ["build"], ["verify"]):
        r = subprocess.run([sys.executable, os.path.abspath(__file__)] + c, env=env, capture_output=True, text=True)
        say("$", " ".join(c), "exit", r.returncode, "|", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:])
        if r.returncode:
            return 1
    # negative tests: deliberately damage the delivered drawing and require the checks to notice
    svg = open(d + "/out/figure.svg", encoding="utf-8").read()
    spec = jload(d + "/out/figure_spec.json")
    charts = {p["id"]: p for p in spec["panels"] if p["type"] == "chart"}
    rd = lambda f: fk_chart.load_table(next(os.path.join(a, x) for a, _, fs in os.walk(os.path.join(ex, "input")) for x in fs if x == os.path.basename(f)))
    n = [0, 0]

    def probe(name, damaged, ok):
        n[1] += 1
        n[0] += bool(ok)
        say("  negative test %-46s %s" % (name, "caught" if ok and damaged else "MISSED"))
    moved = re.sub(r'<circle cx="([\d.]+)" cy="([\d.]+)"([^>]*data-mark="point")', lambda m: '<circle cx="%s" cy="%.3f"%s' % (m.group(1), float(m.group(2)) - 25, m.group(3)), svg, count=1)
    probe("data point moved", moved != svg, not all(r["pass"] for r in fk_chart.read_back(moved, rd, charts)))
    gone = svg.replace('data-mark="point"', 'data-mark="none"', 1)
    probe("data point removed", gone != svg, not all(r["pass"] for r in fk_chart.read_back(gone, rd, charts)))
    eb = re.sub(r'(data-role="error"[^>]*d="M[\d.]+ )([\d.]+)', lambda m: m.group(1) + "%.3f" % (float(m.group(2)) - 30), svg, count=1)
    probe("error bar stretched", eb != svg, not all(r["pass"] for r in fk_chart.read_back(eb, rd, charts)))
    want = sorted((p["id"], e["from"], e["type"], e["to"]) for p in spec["panels"] if p["type"] == "diagram" for e in p["edges"])
    flip = re.sub(r'data-type="inhibition"', 'data-type="activation"', svg, count=1)
    probe("inhibition changed to activation", flip != svg, sorted(svg_facts(flip)["edges"]) != want)
    rev = re.sub(r'data-from="(\w+)" data-to="(\w+)"', r'data-from="\2" data-to="\1"', svg, count=1)
    probe("relation reversed", rev != svg, sorted(svg_facts(rev)["edges"]) != want)
    # line files, requirement walk, timeline, edit and review in a second clean directory
    d2 = tempfile.mkdtemp(prefix="figkit2_")
    env2 = dict(os.environ, KIT_INPUT=os.path.join(ex, "input"), KIT_WORK=d2 + "/work", KIT_OUTPUT=d2 + "/out")
    os.makedirs(d2 + "/work")
    run = lambda *c: subprocess.run([sys.executable, os.path.abspath(__file__)] + list(c), env=env2, capture_output=True, text=True)

    def put(name, text, mode="w"):
        with open(os.path.join(d2, "work", name), mode, encoding="utf-8") as f:
            f.write(text)
    run("brief")
    put("spec.json", json.dumps({"title": "Line files", "caption": "Synthetic example.", "canvas": {"size_mm": [180, 130]}, "layout": [["A"], ["T"]],
                                 "panels": [{"id": "A", "type": "diagram", "title": "A. Loop"}, {"id": "T", "type": "timeline", "title": "Schedule", "unit": "day", "src": "P001", "items": [
                                     {"lane": "Phase", "start": 0, "end": 3, "text": "first"}, {"lane": "Sampling", "at": [1, 3], "text": "water"}]}]}))
    put("notes.items", "- | Schematic, not to scale. | P001\n")
    put("T.items", "- | first | P001 | Phase | 0 | 3\n- | water | P001 | Sampling | - | - | 1,3\n")
    put("A.groups", "g1 | Group one | - | P001\n")
    put("A.nodes", "# id | label | kind | group | src\nx | X | protein | g1 | P001\ny | Y | protein | g1 | P001\nz | Z | protein | g1 | P001\ny | Y2 | protein | g1 | P001\n")
    put("A.edges", "x | y | activation | - | stated | P001\ny | z | inhibition | - | stated | P001 | Fig 1 | dash=dotted\nx | z | flow | a | stated | P001\nx | z | flow | delete\n")
    steps = [run("next"), run("build"), run("show", "P001"), run("find", "the"), run("audit"), run("review")]
    sp = jload(d2 + "/out/figure_spec.json") if os.path.exists(d2 + "/out/figure_spec.json") else {"panels": []}
    dia = next((p for p in sp["panels"] if p["id"] == "A"), {"nodes": [], "edges": []})
    ok = all(r.returncode == 0 and "Traceback" not in r.stderr for r in steps) and len(dia["nodes"]) == 3 and len(dia["edges"]) == 2 and any(q.get("label") == "Y2" for q in dia["nodes"]) and any("not to scale" in str(f) for f in sp.get("footnotes", []))
    say("  line files, next, timeline, audit, review              %s" % ("ok" if ok else "FAILED " + " ".join(r.stderr[-200:] for r in steps)))
    put("A.nodes", "w | W | protein | g1 | P001\n", "a")
    put("A.edges", "z | w | activation | - | stated | P001\n", "a")
    r = run("build", "--revise", "add W")
    rec = jload(d2 + "/out/edit_record.json") if os.path.exists(d2 + "/out/edit_record.json") else {}
    ok2 = r.returncode == 0 and bool(rec) and run("verify").returncode == 0
    say("  edit of a line-file figure (--revise, verify)          %s" % ("ok" if ok2 else "FAILED " + r.stdout[-200:] + r.stderr[-200:]))
    rb = subprocess.run(["sh", os.path.join(d2, "out", "rebuild", "rebuild.sh"), os.path.join(ex, "input")], capture_output=True, text=True, env=dict(os.environ))
    a1, a2 = os.path.join(d2, "out", "figure.svg"), os.path.join(d2, "out", "_rebuilt", "figure.svg")
    ok3 = rb.returncode == 0 and os.path.exists(a2) and svg_facts(open(a1, encoding="utf-8").read())["edges"] == svg_facts(open(a2, encoding="utf-8").read())["edges"]
    say("  delivered rebuild.sh reproduces the relations           %s" % ("ok" if ok3 else "FAILED " + rb.stdout[-200:] + rb.stderr[-200:]))
    n[1] += 3
    n[0] += ok + ok2 + ok3
    say("selftest passed %d of %d (5 negative tests, 3 workflow tests)" % tuple(n))
    say("selftest output (example only, not a formal result):", d + "/out")
    return 0 if n[0] == n[1] else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("brief")
    p = sub.add_parser("show"); p.add_argument("ids", nargs="+")
    p = sub.add_parser("find"); p.add_argument("words", nargs="+")
    p = sub.add_parser("table"); p.add_argument("file"); p.add_argument("rows", nargs="?")
    p = sub.add_parser("build"); p.add_argument("--spec"); p.add_argument("--revise"); p.add_argument("--restart", action="store_true")
    p = sub.add_parser("svgtree"); p.add_argument("file")
    p = sub.add_parser("edit"); p.add_argument("file"); p.add_argument("ops"); p.add_argument("--reason")
    sub.add_parser("audit")
    p = sub.add_parser("start"); p.add_argument("kind", nargs="?", default="schematic")
    p = sub.add_parser("set"); p.add_argument("key"); p.add_argument("value", nargs="+")
    p = sub.add_parser("fromtable"); p.add_argument("table"); p.add_argument("--where", default=""); p.add_argument("--dash", default=""); p.add_argument("--type", default="path"); p.add_argument("--kind", default="concept"); p.add_argument("--panel", default="A"); p.add_argument("--from", dest="from_"); p.add_argument("--to"); p.add_argument("--value"); p.add_argument("--p")
    p = sub.add_parser("prune"); p.add_argument("where"); p.add_argument("--panel", default="A"); p.add_argument("--inset", default="N"); p.add_argument("--title", default="Links removed from the main view")
    p = sub.add_parser("next"); p.add_argument("item", nargs="?", type=int)
    sub.add_parser("review")
    sub.add_parser("verify")
    sub.add_parser("selftest")
    a = ap.parse_args()
    try:
        rc = globals()["cmd_" + a.cmd](a)
    except Exception as exc:  # never leave the agent with a stack trace to debug
        import traceback
        tb = traceback.extract_tb(exc.__traceback__)[-1]
        say("CANNOT %s: %s: %s (at %s:%s). The last good delivery is untouched. Undo or simplify the entry you just wrote and run again; do not read or edit the engine." % (
            a.cmd.upper(), type(exc).__name__, str(exc)[:200], os.path.basename(tb.filename), tb.lineno))
        sys.exit(3)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
