"""Turn a validated figure spec into one layered, editable SVG."""
import math
import re
from html import escape

from fk_chart import draw_chart, INK
from fk_layout import Box, layout_diagram
import fk_text
from fk_text import FONT_STACK, svg_text, width, wrap, strip_markup

MM = 6.0  # user units per millimetre

# kind -> (shape, fill, stroke, legend label)
KINDS = {
    "protein": ("round", "#DCEBF7", "#2B6CA3", "Protein"),
    "receptor": ("receptor", "#D5E8D4", "#3B7A3A", "Receptor / membrane protein"),
    "enzyme": ("hex", "#E4DDF3", "#6C4AA5", "Enzyme"),
    "complex": ("double", "#D3E3EF", "#1F5680", "Complex"),
    "gene": ("rect", "#FFF2CC", "#9C7A11", "Gene"),
    "mrna": ("wave", "#FDE9D9", "#B8632A", "RNA"),
    "small_molecule": ("ellipse", "#FBE3E1", "#B0413E", "Small molecule / metabolite"),
    "metabolite": ("ellipse", "#FBE3E1", "#B0413E", "Small molecule / metabolite"),
    "ion": ("ellipse", "#E8F6F3", "#2E8B7A", "Ion"),
    "drug": ("ellipse", "#F9D9E7", "#A0366F", "Drug / perturbation"),
    "cell": ("round", "#E9F3DC", "#5E8A2B", "Cell"),
    "organism": ("round", "#EDEFE0", "#70773A", "Organism / cohort"),
    "tissue": ("round", "#F3E7DC", "#8C6239", "Tissue"),
    "phenotype": ("octagon", "#F2F2F2", "#555555", "Phenotype / outcome"),
    "process": ("rect", "#EEF1F5", "#4A5A6A", "Process / step"),
    "step": ("rect", "#EEF1F5", "#4A5A6A", "Process / step"),
    "equipment": ("rect", "#DCE9F2", "#33658A", "Equipment / part"),
    "instrument": ("rect", "#DCE9F2", "#33658A", "Equipment / part"),
    "sample": ("ellipse", "#E3F1E7", "#3C7F57", "Sample / material"),
    "material": ("ellipse", "#E3F1E7", "#3C7F57", "Sample / material"),
    "data": ("para", "#E8E6F5", "#5A50A0", "Data / signal"),
    "software": ("rect", "#E6ECF5", "#4A5FA0", "Software / model"),
    "model": ("rect", "#E6ECF5", "#4A5FA0", "Software / model"),
    "decision": ("diamond", "#FFF6DD", "#A67C00", "Decision"),
    "milestone": ("flag", "#FCE8D6", "#C05A12", "Milestone / deliverable"),
    "question": ("round", "#E8EEF9", "#34539E", "Question / aim"),
    "result": ("round", "#E4F3EC", "#23795A", "Result"),
    "conclusion": ("round", "#DFF0E8", "#1D6A4D", "Conclusion"),
    "limitation": ("round", "#F7ECEC", "#9A4A4A", "Limitation / not established"),
    "concept": ("round", "#EEF1F5", "#4A5A6A", "Concept"),
}

# type -> (stroke, dash, head, width, legend label)
EDGES = {
    "activation": ("#1D6A4D", "", "arrow", 2.2, "Activation / promotion"),
    "inhibition": ("#B3261E", "", "tbar", 2.2, "Inhibition"),
    "binding": ("#34539E", "", "dot", 2.0, "Binding / association (physical)"),
    "phosphorylation": ("#6C4AA5", "", "arrowP", 2.0, "Phosphorylation"),
    "modification": ("#6C4AA5", "", "arrowM", 2.0, "Covalent modification (M, or as labelled)"),
    "dimerisation": ("#34539E", "", "none", 4.4, "Dimerisation / complex formation (double line)"),
    "cleavage": ("#8C4B9E", "7 4", "arrowCUT", 2.2, "Proteolytic cleavage / shedding / release"),
    "degradation": ("#8E5A5A", "3 3", "arrow", 2.2, "Degradation / loss"),
    "transport": ("#8C6239", "9 4", "arrow", 2.2, "Transport / translocation"),
    "expression": ("#9C7A11", "", "open", 2.0, "Transcription / expression"),
    "conversion": ("#33658A", "", "arrow", 2.2, "Conversion / reaction"),
    "flow": ("#3A4652", "", "arrow", 2.0, "Sequence / flow"),
    "material": ("#33658A", "", "arrow", 2.8, "Material flow"),
    "gas": ("#2E8B7A", "", "open", 2.4, "Gas flow"),
    "liquid": ("#2B6CA3", "", "arrow", 2.8, "Liquid flow"),
    "energy": ("#C05A12", "10 3 2 3", "arrow", 2.4, "Energy / heat / light / electrical"),
    "signal": ("#5A50A0", "3 3", "open", 1.8, "Signal / data"),
    "data": ("#5A50A0", "3 3", "open", 1.8, "Signal / data"),
    "control": ("#A67C00", "3 3", "open", 1.8, "Control"),
    "return": ("#70773A", "8 4", "arrow", 2.0, "Return / recycle loop"),
    "waste": ("#70773A", "8 4", "arrow", 2.0, "Waste / exhaust"),
    "dependency": ("#3A4652", "", "open", 1.8, "Dependency / input to"),
    "causal": ("#1B1F24", "", "arrow", 2.4, "Causal effect (as stated)"),
    "path": ("#46515C", "", "arrow", 2.0, "Fitted directed path (statistical model)"),
    "association": ("#5B6570", "", "none", 2.0, "Association (no direction claimed)"),
    "comparison": ("#5B6570", "6 4", "none", 1.8, "Comparison"),
    "evidence": ("#34539E", "", "open", 1.8, "Supports / evidence for"),
    "contains": ("#5B6570", "", "none", 1.6, "Part of / contains"),
    "assembly": ("#33658A", "", "dot", 2.0, "Mechanical / assembly joint"),
}
CERTAINTY_DASH = "5 5"
PDASH = [CERTAINTY_DASH]  # work orders may ask for dotted
PROPOSED = ("proposed", "uncertain", "inferred", "hypothetical", "model")
CITED = ("cited", "prior", "literature", "background")
GREY = "#7A828B"
POS, NEG = "#1F5F8B", "#B3481E"


def _num(v):
    try:
        return float(str(v).replace("\u2212", "-"))
    except (TypeError, ValueError):
        return None


def _tone(x):
    return x


def _shape(n, kind):
    b = n["_box"]
    shape, fill, stroke, _ = KINDS.get(kind, KINDS["concept"])
    fill, stroke = n.get("fill", fill), n.get("stroke", stroke)
    sw = 2.6 if n.get("emphasis") else 1.6
    dash = ' stroke-dasharray="5 4"' if n.get("certainty") in PROPOSED else ""
    st = 'fill="%s" stroke="%s" stroke-width="%.1f"%s' % (fill, stroke, sw, dash)
    x, y, w, h = b.x, b.y, b.w, b.h
    if n.get("_flat"):
        shape = "hex"
    if shape == "ellipse":
        return '<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="%.2f" %s/>' % (x, y, w, h, min(h / 2, 34), st)
    if shape == "round":
        return '<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="9" %s/>' % (x, y, w, h, st)
    if shape == "double":
        return ('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="9" %s/>'
                '<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="6" fill="none" stroke="%s" stroke-width="0.9"/>') % (
            x, y, w, h, st, x + 4, y + 4, w - 8, h - 8, stroke)
    if shape == "hex":
        k = min(14, h * .35)
        p = [(x + k, y), (x + w - k, y), (x + w, y + h / 2), (x + w - k, y + h), (x + k, y + h), (x, y + h / 2)]
    elif shape == "octagon":
        k = 10
        p = [(x + k, y), (x + w - k, y), (x + w, y + k), (x + w, y + h - k), (x + w - k, y + h), (x + k, y + h), (x, y + h - k), (x, y + k)]
    elif shape == "para":
        k = 10
        p = [(x + k, y), (x + w, y), (x + w - k, y + h), (x, y + h)]
    elif shape == "diamond":
        p = [(x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2)]
    elif shape == "flag":
        k = 12
        p = [(x, y), (x + w - k, y), (x + w, y + h / 2), (x + w - k, y + h), (x, y + h)]
    elif shape == "receptor":
        return ('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="5" %s/>'
                '<path d="M%.2f %.2fv%.2fM%.2f %.2fv%.2f" stroke="%s" stroke-width="3.2"/>') % (
            x, y, w, h, st, x + 6, y + 4, h - 8, x + w - 6, y + 4, h - 8, stroke)
    elif shape == "wave":
        return '<path d="M%.2f %.2fh%.2fv%.2fq%.2f 9 %.2f 0t%.2f 0z" %s/>' % (
            x, y, w, h - 4, -w / 4, -w / 2, -w / 2, st)
    else:
        return '<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="2.5" %s/>' % (x, y, w, h, st)
    return '<polygon points="%s" %s/>' % (" ".join("%.2f,%.2f" % q for q in p), st)


def glyph(name, cx, cy, s, color):
    """Small parametric icons built from editable strokes (46 unit design box)."""
    k = s / 46.0
    g = {
        "cell": '<ellipse cx="0" cy="0" rx="21" ry="17"/><circle cx="4" cy="1" r="7"/>',
        "bacteria": '<rect x="-20" y="-8" width="32" height="16" rx="8"/><path d="M12 0q5-6 9 0t-2 8"/>',
        "virus": '<circle r="11"/><path d="M0-11v-8M0 11v8M-11 0h-8M11 0h8M-8-8l-6-6M8-8l6-6M-8 8l-6 6M8 8l6 6"/>',
        "dna": '<path d="M-9-20C-9-8 9-8 9 2S-9 12-9 21M9-20C9-8-9-8-9 2S9 12 9 21M-7-13h14M-5-4h10M-7 6h14M-6 15h12"/>',
        "protein": '<path d="M-18 8c0-22 14-22 14-6s12 14 12-4 12-10 10 8-20 16-24 8"/>',
        "antibody": '<path d="M0 20V0L-13-16M0 0L13-16M-8-18L-16-10M8-18L16-10"/>',
        "mouse": '<ellipse cx="2" cy="4" rx="15" ry="10"/><circle cx="-13" cy="-2" r="7"/><circle cx="-16" cy="-9" r="4"/><path d="M17 4q8 2 5 12"/>',
        "human": '<circle cx="0" cy="-13" r="7"/><path d="M-13 20c0-18 4-22 13-22s13 4 13 22z"/>',
        "group": '<circle cx="-9" cy="-9" r="5"/><circle cx="9" cy="-9" r="5"/><path d="M-19 15c0-14 4-17 10-17s9 3 9 17zM0 15c0-14 4-17 9-17s10 3 10 17z"/>',
        "brain": '<path d="M0-16c-6-5-16-1-15 6-6 3-5 12 1 14 1 8 10 10 14 5V-16zM0-16c6-5 16-1 15 6 6 3 5 12-1 14-1 8-10 10-14 5"/>',
        "heart": '<path d="M0 18C-30-4-14-24 0-10 14-24 30-4 0 18z"/>',
        "lung": '<path d="M0-18v14M0-4c-4 0-6-8-11-8-7 0-9 16-8 26 1 6 14 4 15-4zM0-4c4 0 6-8 11-8 7 0 9 16 8 26-1 6-14 4-15-4z"/>',
        "plant": '<path d="M0 20V-6M0 4C-16 4-18-8-18-14-6-14 0-8 0 4zM0-4C12-4 16-14 16-20 4-20 0-12 0-4z"/>',
        "leaf": '<path d="M-16 16C-18-10 2-18 18-18 18 2 8 18-10 14zM-18 20L8-8"/>',
        "beaker": '<path d="M-12-18h24M-10-18v30q0 6 6 6h8q6 0 6-6v-30M-10 0h20"/>',
        "flask": '<path d="M-6-20h12M-4-20v14L-16 14q-2 5 4 5h24q6 0 4-5L4-6v-14M-10 6h20"/>',
        "tube": '<path d="M-7-20h14M-5-20v32a5 6 0 0 0 10 0v-32M-5 0h10"/>',
        "dish": '<ellipse cx="0" cy="-2" rx="21" ry="8"/><path d="M-21-2v7c0 11 42 11 42 0v-7"/>',
        "syringe": '<path d="M-20 20l8-8M-14 8l6 6L10-4l-6-6zM7-7l6-6M9-17l8 8M-6 2l4 4M0-4l4 4"/>',
        "pill": '<rect x="-19" y="-8" width="38" height="16" rx="8"/><path d="M0-8v16"/>',
        "microscope": '<path d="M-14 20h28M-4 14h12M-6-18l8-3 7 20-8 3zM8-4c8 4 8 16-2 18"/>',
        "laser": '<rect x="-20" y="-8" width="24" height="16" rx="2"/><path d="M4 0h17M8-6l8-4M8 6l8 4"/>',
        "lens": '<path d="M0-20c9 12 9 28 0 40-9-12-9-28 0-40z"/>',
        "mirror": '<path d="M-12 18L12-18M-8 20l3-4M0 10l3-4M6 0l3-4M12-10l3-4"/>',
        "detector": '<path d="M-14-16h14a16 16 0 0 1 0 32h-14zM-14 0h-7M16 0h5"/>',
        "camera": '<rect x="-20" y="-11" width="40" height="26" rx="4"/><circle cx="0" cy="2" r="8"/><path d="M-8-11l3-6h10l3 6"/>',
        "furnace": '<rect x="-20" y="-14" width="40" height="28" rx="3"/><path d="M-12 8q4-8 0-14M0 8q4-8 0-14M12 8q4-8 0-14"/>',
        "heater": '<path d="M-20 14h40M-14 8q5-7 0-13t0-13M0 8q5-7 0-13t0-13M14 8q5-7 0-13t0-13"/>',
        "pump": '<circle r="15"/><path d="M-6-9L10 0-6 9z"/>',
        "valve": '<path d="M-18-10L18 10V-10L-18 10zM0 0v-14M-8-14h16"/>',
        "cylinder": '<path d="M-9-10c0-6 4-8 9-8s9 2 9 8v28h-18zM-3-18v-4h6v4"/>',
        "vessel": '<path d="M-13-12c0-8 26-8 26 0v22c0 9-26 9-26 0z"/><path d="M0-18v-4M0 17v5"/>',
        "column": '<rect x="-9" y="-20" width="18" height="40" rx="4"/><path d="M-9-10h18M-9 10h18M-5-5l3 3M2 0l3 3M-4 4l3 3"/>',
        "electrode": '<path d="M-10-20v36M10-20v36M-18 2h36v16h-36zM-10-20h-6M10-20h6"/>',
        "battery": '<rect x="-18" y="-9" width="34" height="18" rx="2"/><path d="M16-4h4v8h-4M-10-4v8M-14 0h8M4 0h8"/>',
        "chip": '<rect x="-13" y="-13" width="26" height="26" rx="2"/><path d="M-13-7h-6M-13 0h-6M-13 7h-6M13-7h6M13 0h6M13 7h6M-7-13v-6M0-13v-6M7-13v-6M-7 13v6M0 13v6M7 13v6"/>',
        "computer": '<rect x="-20" y="-16" width="40" height="26" rx="2"/><path d="M-10 18h20M0 10v8"/>',
        "database": '<ellipse cx="0" cy="-13" rx="15" ry="6"/><path d="M-15-13v26c0 8 30 8 30 0v-26M-15 0c0 8 30 8 30 0"/>',
        "document": '<path d="M-13-20h18l8 8v32h-26zM5-20v8h8M-7-4h14M-7 3h14M-7 10h9"/>',
        "network": '<circle cx="-14" cy="-10" r="4"/><circle cx="-14" cy="10" r="4"/><circle cx="2" cy="-14" r="4"/><circle cx="2" cy="2" r="4"/><circle cx="2" cy="16" r="4"/><circle cx="16" cy="0" r="4"/><path d="M-10-10L-2-13M-10-9L-2 1M-10 9L-2 3M-10 11L-2 15M6-13L13-2M6 2h6M6 15L13 3"/>',
        "chart": '<path d="M-18-18v36h38M-10 12V2M-1 12v-18M8 12v-11M16 12v-22"/>',
        "curve": '<path d="M-18-18v36h38M-14 12c8 0 8-22 16-22s8 14 16 10"/>',
        "gear": '<circle r="7"/><path d="M0-18v7M0 11v7M-18 0h7M11 0h7M-13-13l5 5M8 8l5 5M13-13l-5 5M-8 8l-5 5"/>',
        "clock": '<circle r="17"/><path d="M0-10V0l8 5"/>',
        "thermometer": '<path d="M-5 6v-20a5 5 0 0 1 10 0v20a9 9 0 1 1-10 0zM0-8v18"/>',
        "magnet": '<path d="M-15-16h9v16a6 6 0 0 0 12 0v-16h9v16a15 15 0 0 1-30 0zM-15-8h9M6-8h9"/>',
        "wave": '<path d="M-21 0c5-18 9-18 14 0s9 18 14 0 9-18 14 0"/>',
        "crystal": '<path d="M0-20l17 10v20L0 20l-17-10v-20zM0-20V0M0 0l17 10M0 0l-17 10"/>',
        "molecule": '<circle cx="-10" cy="6" r="6"/><circle cx="8" cy="10" r="4"/><circle cx="4" cy="-10" r="7"/><path d="M-6 1l6-6M5-3l2 9"/>',
        "droplet": '<path d="M0-20C10-4 14 2 14 8a14 12 0 0 1-28 0c0-6 4-12 14-28z"/>',
        "globe": '<circle r="18"/><path d="M-18 0h36M0-18c-12 10-12 26 0 36M0-18c12 10 12 26 0 36"/>',
        "satellite": '<rect x="-6" y="-6" width="12" height="12"/><path d="M-22-5h12v10h-12zM10-5h12v10h-12zM0 6v6M-8 18q8-8 16 0"/>',
        "robot": '<rect x="-14" y="-8" width="28" height="22" rx="3"/><circle cx="-5" cy="2" r="2.5"/><circle cx="5" cy="2" r="2.5"/><path d="M0-8v-8M-3-18h6"/>',
        "check": '<circle r="17"/><path d="M-8 0l6 6L9-6"/>',
        "question": '<circle r="17"/><path d="M-5-5c0-8 11-8 11 0 0 5-6 5-6 10M0 10v1"/>',
        "target": '<circle r="17"/><circle r="10"/><circle r="3"/>',
        "warning": '<path d="M0-17L19 16H-19zM0-5v10M0 10v1"/>',
    }
    body = g.get(name)
    if not body:
        return ""
    return '<g data-role="glyph" data-glyph="%s" transform="translate(%.2f %.2f) scale(%.4f)" fill="#ffffff" fill-opacity="0.75" stroke="%s" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">%s</g>' % (
        name, cx, cy, k, color, body)


GLYPHS = ("cell bacteria virus dna protein antibody mouse human group brain heart lung plant leaf beaker flask tube dish "
          "syringe pill microscope laser lens mirror detector camera furnace heater pump valve cylinder vessel column "
          "electrode battery chip computer database document network chart curve gear clock thermometer magnet wave "
          "crystal molecule droplet globe satellite robot check question target warning").split()


def scissors(x, y, color):
    return ('<path d="M%.2f %.2fL%.2f %.2fM%.2f %.2fL%.2f %.2f" stroke="%s" stroke-width="1.5" fill="none"/>' % (x - 2.4, y - 2, x + 5, y + 3.4, x - 2.4, y + 2, x + 5, y - 3.4, color)
            + "".join('<circle cx="%.2f" cy="%.2f" r="1.9" fill="#ffffff" stroke="%s" stroke-width="1.3"/>' % (x - 3.6, y + k, color) for k in (-3, 3)))


def _head(kind, p, q, color, w):
    """Arrow head at q coming from p; returns (svg, shortened end point)."""
    ang = math.atan2(q[1] - p[1], q[0] - p[0])
    c, s = math.cos(ang), math.sin(ang)

    def at(dx, dy):
        return q[0] + dx * c - dy * s, q[1] + dx * s + dy * c
    if kind == "none":
        return "", q
    if kind == "tbar":
        a, b = at(-3, -8), at(-3, 8)
        return '<path d="M%.2f %.2fL%.2f %.2f" stroke="%s" stroke-width="%.1f" fill="none"/>' % (*a, *b, color, w + 1), at(-3, 0)
    if kind == "dot":
        a = at(-5, 0)
        return '<circle cx="%.2f" cy="%.2f" r="4.6" fill="%s"/>' % (*a, color), at(-8, 0)
    if kind == "open":
        a, b = at(-10, -5.5), at(-10, 5.5)
        return '<path d="M%.2f %.2fL%.2f %.2fL%.2f %.2f" stroke="%s" stroke-width="%.1f" fill="none" stroke-linejoin="round"/>' % (
            *a, *q, *b, color, w), at(-1.5, 0)
    a, b = at(-11, -5), at(-11, 5)
    out = '<polygon points="%.2f,%.2f %.2f,%.2f %.2f,%.2f" fill="%s"/>' % (*q, *a, *b, color)
    if kind.startswith("arrow") and len(kind) > 5:
        m = at(-20, 0)
        out += '<circle cx="%.2f" cy="%.2f" r="%.1f" fill="#ffffff" stroke="%s" stroke-width="1.4"/>' % (*m, max(8.0, fk_text.fsz(11) * .72), color)
        out += scissors(m[0], m[1], color) if kind == "arrowCUT" else svg_text(m[0], m[1], [kind[5:]], 11, bold=True, fill=color)
    return out, at(-9, 0)


def edge_id(e, seen):
    base = "edge-%s-%s-%s" % (e["from"], e.get("type", "flow"), e["to"])
    k, i = base, 2
    while k in seen:
        k, i = "%s-%d" % (base, i), i + 1
    seen.add(k)
    return k


def draw_diagram(panel, res, ox, oy, pid, fs, registry):
    s = ['<g id="%s-groups" data-layer="compartments">' % pid]
    for n, g in enumerate(res["groups"]):
        b = g["box"]
        mem = g["kind"] == "membrane"
        gl = wrap(str(g["label"]), fs * .9, max(60, b.w - 14), True) if g.get("wrapped") else [str(g["label"])]
        tint = ["#F6F8FA", "#F8F6F1", "#F3F7F3", "#F7F4F8", "#F3F6F8", "#F8F4F3"][n % 6]
        s.append('<g id="%s-group-%s" data-role="group" data-label="%s"><rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="10" fill="%s" stroke="%s" stroke-width="%s"%s/>%s</g>' % (
            pid, g["id"], escape(strip_markup(str(g["label"]))), b.x + ox, b.y + oy, b.w, b.h, tint,
            "#8A94A0" if mem else "#C4CBD3", "2.6" if mem else "1.2", "" if mem else ' stroke-dasharray="6 3"',
            svg_text(b.x + ox + 10, b.y + oy + 14 + (len(gl) - 1) * fs * .55, gl, fs * .9, "start", True, "#46515C")))
        registry.append({"element_id": "%s-group-%s" % (pid, g["id"]), "panel": pid, "type": "group", "label": strip_markup(str(g["label"])), "src": panel_src(panel, "groups", g["id"])})
    s.append("</g>")
    s.append('<g id="%s-edges" data-layer="relations">' % pid)
    seen = set()
    labels = []
    over = {}
    for e in res["edges"]:
        s_main, lab_main = s, labels
        if e.get("layer"):
            s = over.setdefault(str(e["layer"]), {"e": [], "l": [], "n": []})["e"]
            labels = over[str(e["layer"])]["l"]
        t = e.get("type", "flow")
        color, dash, head, w, _ = EDGES[t]
        if e.get("certainty") in PROPOSED:
            dash = PDASH[0]
        if e.get("certainty") in CITED:
            color = GREY
        ew = panel.get("edge_width")
        if ew and _num(e.get(ew.get("field", "value"))) is not None:
            v = _num(e[ew.get("field", "value")])
            vmax = float(ew.get("max") or max(abs(_num(q.get(ew.get("field", "value"))) or 0) for q in res["edges"]) or 1)
            w = 1.2 + 5.3 * min(1.0, abs(v) / vmax)
            if ew.get("sign", True) and e.get("certainty") not in CITED:
                color = POS if v >= 0 else NEG
        if e.get("width"):
            w = float(e["width"])
        if e.get("color"):
            color = e["color"]
        if e.get("dash"):
            dash = {"solid": "", "dashed": "8 5", "dotted": "2 4", "dashdot": "9 4 2 4"}.get(e["dash"], e["dash"])
        if e.get("double"):
            head = "none"
        if t == "dimerisation":
            e.setdefault("double", True)
        eid = "%s-%s" % (pid, edge_id(e, seen))
        pts = [(x + ox, y + oy) for x, y in e["pts"]]
        if head == "arrowM":
            mm = re.match(r"(?i)(ubiquit|acetyl|methyl|sumo|glycos|palmit)", strip_markup(str(e.get("label", ""))))
            head = "arrow" + ({"ubiquit": "Ub", "acetyl": "Ac", "methyl": "Me", "sumo": "Su", "glycos": "Gl", "palmit": "Pa"}[mm.group(1).lower()] if mm else "M")
        h, end = _head(head, pts[-2], pts[-1], color, w)
        h0 = ""
        p2 = pts[:-1] + [end]
        if e.get("bidirectional"):
            h0, st = _head(head, pts[1], pts[0], color, w)
            p2[0] = st
        d = _rounded(p2)
        s.append('<g id="%s" data-role="edge" data-from="%s" data-to="%s" data-type="%s" data-certainty="%s"%s><path d="%s" fill="none" stroke="%s" stroke-width="%.1f"%s stroke-linejoin="round"/>%s%s%s</g>' % (
            eid, e["from"], e["to"], t, e.get("certainty", "stated"), ' data-bidirectional="1"' if e.get("bidirectional") else "", d, color, w,
            ' stroke-dasharray="%s"' % dash if dash else "", '<path d="%s" fill="none" stroke="#ffffff" stroke-width="%.1f"/>' % (d, max(1.0, w * .45)) if e.get("double") else "", h, h0))
        if e.get("label_box"):
            b = e["label_box"]
            labels.append('<g id="%s-label" data-role="edge-label" data-edge="%s"><rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="3" fill="#ffffff" fill-opacity="0.88"/>%s</g>' % (
                eid, eid, b.x + ox, b.y + oy, b.w, b.h, svg_text(b.cx + ox, b.cy + oy, e["label_lines"], fs * .84, fill=color)))
        registry.append({"element_id": eid, "panel": pid, "type": "relation", "relation": t, "from": e["from"], "to": e["to"],
                         "label": strip_markup(str(e.get("label", ""))), "certainty": e.get("certainty", "stated"), "evidence": e.get("evidence"), "layer": e.get("layer"),
                         "style": {k: e[k] for k in ("width", "dash", "color", "double") if e.get(k)} or None, "value": e.get((panel.get("edge_width") or {}).get("field", "value")), "src": e.get("src")})
        s, labels = s_main, lab_main
    s.append("</g>")
    s.append('<g id="%s-nodes" data-layer="entities">' % pid)
    for n in res["nodes"]:
        k = n.get("kind", "concept")
        b = n["_box"]
        nid = "%s-node-%s" % (pid, n["id"])
        s_main = s
        if n.get("layer"):
            s = over.setdefault(str(n["layer"]), {"e": [], "l": [], "n": []})["n"]
        nb = dict(n)
        nb["_box"] = Box(b.x + ox, b.y + oy, b.w, b.h)
        s.append('<g id="%s" data-role="node" data-node="%s" data-kind="%s" data-label="%s">%s' % (
            nid, n["id"], k, escape(strip_markup(str(n.get("label", n["id"])))), _shape(nb, k)))
        cy = b.cy + oy
        if n["_icon"]:
            col = KINDS.get(k, KINDS["concept"])[2]
            s.append(glyph(n["glyph"], b.cx + ox, b.y + oy + 28, 40, col))
            cy += n["_icon"] / 2 - 2
        nl, ns = len(n["_lines"]), len(n["_sub"])
        th = nl * fs * 1.22
        sh = ns * fs * .86 * 1.22
        s.append(svg_text(b.cx + ox, cy - sh / 2, n["_lines"], fs, bold=True, ident=nid + "-text"))
        if ns:
            s.append(svg_text(b.cx + ox, cy + th / 2, n["_sub"], fs * .86, fill="#3A4652", ident=nid + "-note"))
        s.append("</g>")
        s = s_main
        registry.append({"element_id": nid, "panel": pid, "type": "entity", "kind": k, "label": strip_markup(str(n.get("label", n["id"]))),
                         "note": strip_markup(str(n.get("note", ""))), "certainty": n.get("certainty", "stated"), "evidence": n.get("evidence"), "layer": n.get("layer"), "src": n.get("src")})
    s.append("</g>")
    s.append('<g id="%s-edge-labels" data-layer="relation-labels">%s</g>' % (pid, "".join(labels)))
    for name, o in over.items():
        lid = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in name)
        s.append('<g id="layer-%s" data-layer="%s" data-role="overlay">%s</g>' % (lid, escape(name), "\n".join(o["e"] + o["n"] + o["l"])))
    return "\n".join(s)


def panel_src(panel, key, ident):
    for g in panel.get(key, []):
        if g["id"] == ident:
            return g.get("src") or panel.get("src")
    return panel.get("src")


def _rounded(pts, r=7):
    if len(pts) < 3:
        return "M" + "L".join("%.2f %.2f" % p for p in pts)
    d = "M%.2f %.2f" % pts[0]
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        l1 = math.hypot(b[0] - a[0], b[1] - a[1])
        l2 = math.hypot(c[0] - b[0], c[1] - b[1])
        rr = min(r, l1 / 2, l2 / 2)
        if rr < 1:
            d += "L%.2f %.2f" % b
            continue
        p = (b[0] + (a[0] - b[0]) / l1 * rr, b[1] + (a[1] - b[1]) / l1 * rr)
        q = (b[0] + (c[0] - b[0]) / l2 * rr, b[1] + (c[1] - b[1]) / l2 * rr)
        d += "L%.2f %.2fQ%.2f %.2f %.2f %.2f" % (*p, *b, *q)
    return d + "L%.2f %.2f" % pts[-1]


def draw_timeline(panel, x, y, w, pid, fs, registry, measure=False):
    """Lanes on one calibrated time axis: bars for periods, diamonds for time points."""
    items = panel.get("items", [])
    unit = str(panel.get("unit") or "")
    lanes = []
    for it in items:
        if str(it.get("lane") or "") not in lanes:
            lanes.append(str(it.get("lane") or ""))
    ends = [float(v) for it in items for v in ([it["start"], it["end"]] if it.get("start") is not None else it["at"])]
    lo, hi = float(panel.get("start", min(ends))), float(panel.get("end", max(ends)))
    if hi <= lo:
        hi = lo + 1
    sf = fs * .9
    ll = [wrap(l, sf, w * .2, True) for l in lanes]
    lw = max([width(t, sf, True) for q in ll for t in q] + [0]) + 18
    x0, x1 = x + lw, x + w - 26
    X = lambda v: x0 + (float(v) - lo) / (hi - lo) * (x1 - x0)
    ticks = panel.get("ticks")
    if not ticks:
        step = next(q for q in (.1, .2, .5, 1, 2, 5, 7, 10, 20, 50, 100, 200, 500, 1000, 5000, 1e9) if (hi - lo) / q <= 14)
        k0 = math.ceil(lo / step - 1e-9)
        ticks = [round(k0 * step + j * step, 6) for j in range(int((hi - k0 * step) / step + 1e-9) + 1)]
    out, bgs, grid, cy = [], [], [], y + 4
    pal = ["#CFE0EE", "#D8EAD9", "#F6E3C5", "#E5DCF2", "#F5D7D7", "#DDE3E8"]
    edge = ["#2B6CA3", "#3B7A3A", "#B8732A", "#6C4AA5", "#B0413E", "#4A5A6A"]
    rows = []
    for k, lane in enumerate(lanes):
        sub = []  # sub-rows so that texts never collide
        for j, it in enumerate(items):
            if str(it.get("lane") or "") != lane:
                continue
            txt = str(it.get("text", ""))
            a, b = (X(it["start"]), X(it["end"])) if it.get("start") is not None else (X(min(it["at"])), X(max(it["at"])))
            point = it.get("start") is None
            lines = wrap(txt, sf, max(60, b - a - 8)) if not point else [txt]
            inside = not point and max([width(t, sf) for t in lines] + [0]) <= b - a - 6 and len(lines) <= 3
            if not inside:
                lines = wrap(txt, sf, 250)
            tw = max([width(t, sf) for t in lines] + [0])
            if inside:
                span, tx, anc = (a - 3, b + 3), (a + b) / 2, "middle"
            elif b + 10 + tw <= x + w - 2:
                span, tx, anc = (a - 8, b + 14 + tw), b + 10, "start"
            elif a - 10 - tw >= x0 - 4:
                span, tx, anc = (a - 14 - tw, b + 8), a - 10, "end"
            else:
                tx = min(max((a + b) / 2, x0 + tw / 2), x + w - 4 - tw / 2)
                span, anc = (min(a - 8, tx - tw / 2 - 4), max(b + 8, tx + tw / 2 + 4)), "below"
            h = max(sf * 1.7, len(lines) * sf * 1.2 + 6) + (sf * 1.3 if anc == "below" else 0)
            for r in sub:
                if all(span[1] < q[0] or span[0] > q[1] for q in r["spans"]):
                    break
            else:
                r = {"spans": [], "items": [], "h": 0}
                sub.append(r)
            r["spans"].append(span)
            r["items"].append((j, it, a, b, lines, tx, anc))
            r["h"] = max(r["h"], h)
        rows.append((k, sub))
    top = cy
    for k, sub in rows:
        lane_h = sum(r["h"] for r in sub) + 4 * len(sub) + 4
        if not measure:
            bgs.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="%s" stroke="none"/>' % (x, cy, w, lane_h, "#F7F8FA" if k % 2 == 0 else "#FFFFFF"))
            out.append(svg_text(x + 5, cy + lane_h / 2, ll[k], sf, "start", True))
        yy = cy + 4
        for r in sub:
            for j, it, a, b, lines, tx, anc in r["items"]:
                eid = "%s-item-%d" % (pid, j)
                col, ec = pal[k % 6], edge[k % 6]
                if not measure:
                    g = ['<g id="%s" data-role="timeline-item" data-lane="%s">' % (eid, escape(lanes[k], True))]
                    mid = yy + r["h"] / 2 - (sf * .65 if anc == "below" else 0)
                    bh = sf * 1.7 if anc != "middle" else r["h"]
                    if it.get("start") is not None:
                        dash = ' stroke-dasharray="6 4"' if it.get("certainty") in ("proposed", "not reported") else ""
                        g.append('<rect data-start="%s" data-end="%s" x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="3" fill="%s" stroke="%s" stroke-width="1.2"%s/>' % (it["start"], it["end"], a, mid - bh / 2, max(2.5, b - a), bh, it.get("color", col), ec, dash))
                    else:
                        for v in it["at"]:
                            g.append('<path data-at="%s" d="M%.2f %.2f l6 -7 l6 7 l-6 7 z" fill="%s" stroke="none"/>' % (v, X(v) - 6, mid, ec))
                    ty, an = (mid, anc) if anc != "below" else (mid + bh / 2 + sf * .7, "middle")
                    g.append(svg_text(tx, ty, lines, sf, an))
                    g.append("</g>")
                    out.append("".join(g))
                    when = "%s-%s" % (it["start"], it["end"]) if it.get("start") is not None else ", ".join(str(v) for v in it["at"])
                    registry.append({"element_id": eid, "panel": pid, "type": "text", "label": strip_markup(str(it.get("text", ""))), "src": it.get("src") or panel.get("src"),
                                     "evidence": "timeline lane %s, %s %s" % (lanes[k], unit, when)})
            yy += r["h"] + 4
        cy += lane_h
    if not measure:
        g = ['<g id="%s-time-axis" data-role="axis" data-domain="%g %g" data-range="%.2f %.2f">' % (pid, lo, hi, x0, x1)]
        g.append('<path d="M%.2f %.2fH%.2f" stroke="#46515C" stroke-width="1.4" fill="none"/>' % (x0, cy + 3, x1))
        for t in ticks:
            grid.append('<path d="M%.2f %.2fV%.2f" stroke="#C3CAD2" stroke-width="0.7" stroke-dasharray="2 3" fill="none"/>' % (X(t), top, cy + 3))
            g.append('<path d="M%.2f %.2fv6" stroke="#46515C" stroke-width="1.2" fill="none"/>' % (X(t), cy + 3))
            g.append(svg_text(X(t), cy + 9 + sf * .7, ["%g" % float(t)], sf, "middle"))
        g.append(svg_text(x + 5, cy + 9 + sf * .7, [panel.get("axis_label") or ("Time (%s)" % unit if unit else "Time")], sf, "start", True))
        g.append("</g>")
        body = "\n".join(bgs + grid + out)
        axis = "".join(g)
        return '<g id="%s-text" data-layer="text">\n%s\n%s\n</g>' % (pid, body, axis), cy + 10 + sf * 1.5 - y
    return "", cy + 10 + sf * 1.5 - y


TINT = {"#3B5B78": "#EEF3F8", "#2F6B4F": "#EDF5F0", "#6B4C8A": "#F3EFF8", "#B0561A": "#FBF1E9", "#9A3324": "#FBEDEA"}
BANDS = ["#3B5B78", "#2F6B4F", "#6B4C8A", "#B0561A"]


def rich_item(val, text, x, cy, w, fs, panel, eid, tight):
    """key / box:Title / ns / label:Name / grid items; returns (svg, height, title) or None."""
    low = val.lower().strip()
    col = panel.get("_color", "#1D5E8C")
    lh = 1.17 if tight else 1.24
    if low in ("key", "claim", "headline"):
        lines = wrap(text, fs * 1.14, w - 12, True)
        h = len(lines) * fs * 1.14 * 1.2
        return '<g id="%s" data-role="text-item">%s</g>' % (eid, svg_text(x + 6, cy + h / 2, lines, fs * 1.14, "start", True, col)), h, ""
    if low.startswith("label:") or low.startswith("label "):
        name = val[6:].strip()
        lw = max(52.0, width(name, fs, True) + 14)
        if lw > .4 * w:  # long name: on its own line above the text
            lines = wrap(text, fs, w - 16)
            h = (1 + max(1, len(lines))) * fs * lh
            return '<g id="%s" data-role="text-item">%s%s</g>' % (eid, svg_text(x + 6, cy + fs * lh / 2, [name], fs, "start", True, col), svg_text(x + 10, cy + fs * lh + (h - fs * lh) / 2, lines, fs, "start")), h, name
        lines = wrap(text, fs, w - lw - 10)
        h = max(1, len(lines)) * fs * lh
        return '<g id="%s" data-role="text-item">%s%s</g>' % (eid, svg_text(x + 6, cy + fs * lh / 2, [name], fs, "start", True, col), svg_text(x + 4 + lw, cy + h / 2, lines, fs, "start")), h, name
    if low.startswith("box") or low == "ns" or low.startswith("ns:"):
        ns = low.startswith("ns")
        title = val.split(":", 1)[1].strip() if ":" in val else ("Not significant" if ns else "")
        c = "#9A3324" if ns else col
        parts = [q.strip() for q in text.split(";") if q.strip()]
        pad, out, yy = 7.0, [], cy + 7.0
        if title:
            tl = wrap(title, fs, w - 2 * pad - 6, True)
            out.append(svg_text(x + pad + 3, yy + len(tl) * fs * lh / 2, tl, fs, "start", True, c))
            yy += len(tl) * fs * lh + 2
        for q in parts:
            ql = wrap(q, fs, w - 2 * pad - 22)
            hh = len(ql) * fs * lh
            if ns:
                a, b = x + pad + 7, yy + fs * lh / 2
                out.append('<path d="M%.2f %.2fl7 7m0 -7l-7 7" stroke="%s" stroke-width="1.6" fill="none"/>' % (a - 3.5, b - 3.5, c))
            else:
                out.append('<circle cx="%.2f" cy="%.2f" r="2.6" fill="%s"/>' % (x + pad + 7, yy + fs * lh / 2, c))
            out.append(svg_text(x + pad + 18, yy + hh / 2, ql, fs, "start"))
            yy += hh + 2
        h = yy - cy + 5
        return '<g id="%s" data-role="text-item"><rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="5" fill="%s" stroke="%s" stroke-width="1.4"/>%s</g>' % (eid, x + 2, cy, w - 4, h, TINT.get(c, "#F2F6FA"), c, "".join(out)), h, title
    if low == "grid":  # crossed design: "rows T1 warmed, T0 ambient; cols W0 0 cm, W1 -10 cm; n 3"
        m = {k.lower(): v for k, v in re.findall(r"(?i)\b(rows?|cols?|columns?|n|reps?)\b[\s:=]+([^;]+)", text)}
        rows_ = [q.strip() for q in (m.get("rows") or m.get("row") or "").split(",") if q.strip()]
        cols_ = [q.strip() for q in (m.get("cols") or m.get("col") or m.get("columns") or "").split(",") if q.strip()]
        n = int((_num(m.get("n") or m.get("reps") or m.get("rep") or "1") or 1))
        if not rows_ or not cols_ or n > 12:
            return None
        lw = max(width(q, fs, True) for q in rows_) + 12
        cw = (w - lw - 10) / len(cols_)
        side = min(fs * 1.15, (cw - 8) / max(1, n) - 3)
        if side < 4:
            return None
        if any(width(tok, fs, True) > cw - 4 for q in cols_ for tok in q.split()) or max(len(wrap(q, fs, cw - 4, True)) for q in cols_) > 2:
            # too narrow for column heads: name the columns by shade in a list instead
            heads = cols_
            shades = ["#BFD9EE", "#5E9CCB", "#1F4E79", "#0B2E4A", "#8AB6A3", "#3F7F67"]
            out, yy = [], cy
            step = fs * lh + 3
            for j, q in enumerate(heads):
                for i in range(n):
                    out.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="2.5" fill="%s" stroke="#46515C" stroke-width="0.8"/>' % (x + 8 + i * (fs * .95 + 3), yy + 2, fs * .95, fs * .95, shades[j % 6]))
                out.append(svg_text(x + 14 + n * (fs * .95 + 3), yy + 2 + fs * .5, [q], fs, "start", True, "#1F3B57"))
                yy += step
            tl = wrap("each under: %s (n = %d per cell)" % (", ".join(rows_), n), fs, w - 12)
            out.append(svg_text(x + 6, yy + len(tl) * fs * lh / 2, tl, fs, "start"))
            yy += len(tl) * fs * lh
            return '<g id="%s" data-role="text-item">%s</g>' % (eid, "".join(out)), yy - cy, ""
        hl = [wrap(q, fs, cw - 4, True) for q in cols_]
        hh = max(len(q) for q in hl) * fs * lh
        shades = ["#BFD9EE", "#5E9CCB", "#1F4E79", "#0B2E4A", "#8AB6A3", "#3F7F67"]
        out = [svg_text(x + lw + cw * (j + .5), cy + hh / 2, hl[j], fs, "middle", True, "#1F3B57") for j in range(len(cols_))]
        yy = cy + hh + 3
        for i, r in enumerate(rows_):
            out.append(svg_text(x + 6, yy + side / 2, [r], fs, "start", True, "#B0561A" if i == 0 else "#46515C"))
            for j in range(len(cols_)):
                x0 = x + lw + cw * (j + .5) - (n * (side + 3) - 3) / 2
                for q in range(n):
                    out.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="2.5" fill="%s" stroke="%s" stroke-width="%.1f"/>' % (x0 + q * (side + 3), yy, side, side, shades[j % 6], "#B0561A" if i == 0 else "#46515C", 1.5 if i == 0 else .8))
            yy += max(side + 6, fs * lh)
        cap = "each square = one replicate (n = %d per cell)" % n
        cl = wrap(cap, fs, w - 12)
        out.append(svg_text(x + 6, yy + len(cl) * fs * lh / 2, cl, fs, "start", fill="#46515C"))
        yy += len(cl) * fs * lh
        return '<g id="%s" data-role="text-item">%s</g>' % (eid, "".join(out)), yy - cy, ""
    return None


def draw_text_panel(panel, x, y, w, pid, fs, registry, measure=False):
    if panel.get("timeline"):
        return draw_timeline(panel, x, y, w, pid, fs, registry, measure)
    items = panel.get("items", [])
    if panel.get("columns") == 2 and len(items) > 3 and not panel.get("_half"):
        h = (len(items) + 1) // 2
        a_, ha = draw_text_panel(dict(panel, items=items[:h], _half="a"), x, y, w / 2 - 6, pid, fs, registry, measure)
        b_, hb = draw_text_panel(dict(panel, items=items[h:], _half="b", _off=h), x + w / 2 + 6, y, w / 2 - 6, pid, fs, registry, measure)
        return '<g id="%s-text" data-layer="text">%s%s</g>' % (pid, a_, b_), max(ha, hb)
    tone = "#6B7580" if panel.get("muted") else None
    s, cy = ['<g id="%s-text%s" data-layer="text">' % (pid, panel.get("_half", ""))], y
    tight = bool(panel.get("_tight"))
    for k, it in enumerate(items, panel.get("_off", 0)):
        if not isinstance(it, dict):
            it = {"text": str(it)}
        big = it.get("value")
        rich = rich_item(str(big or ""), str(it.get("text", "")), x, cy, w, fs, panel, "%s-item-%d" % (pid, k), tight)
        if rich:
            if not measure:
                s.append(rich[0])
                registry.append({"element_id": "%s-item-%d" % (pid, k), "panel": pid, "type": "text", "label": strip_markup((rich[2] + " " if rich[2] else "") + str(it.get("text", ""))), "src": it.get("src") or panel.get("src")})
            cy += rich[1] + fs * (.34 if tight else .5)
            continue
        if big and width(str(big), fs * 1.75, True) > .34 * w:  # long lead: own line above the text
            vl = wrap(str(big), fs * 1.25, w - 16, True)
            lines = wrap(str(it.get("text", "")), fs, w - 16)
            vh, th = len(vl) * fs * 1.25 * 1.22, len(lines) * fs * 1.22
            h = vh + th
            if not measure:
                s.append('<g id="%s-item-%d" data-role="text-item">%s%s</g>' % (
                    pid, k, svg_text(x + 6, cy + vh / 2, vl, fs * 1.25, "start", True, it.get("color", "#1D5E8C")),
                    svg_text(x + 6, cy + vh + th / 2, lines, fs, "start")))
        elif big:
            vw = width(str(big), fs * 1.75, True)
            lines = wrap(str(it.get("text", "")), fs, max(120, w - vw - 34))
            h = max(fs * 2.2, len(lines) * fs * 1.25 + 4)
            if not measure:
                s.append('<g id="%s-item-%d" data-role="text-item">%s%s</g>' % (
                    pid, k, svg_text(x + 6, y + (cy - y) + h / 2, [str(big)], fs * 1.75, "start", True, it.get("color", "#1D5E8C")),
                    svg_text(x + vw + 22, cy + h / 2, lines, fs, "start")))
        else:
            bullet = panel.get("bullets", True)
            lines = wrap(str(it.get("text", "")), fs, w - 24)
            h = len(lines) * fs * 1.25
            if not measure:
                s.append('<g id="%s-item-%d" data-role="text-item">%s%s</g>' % (
                    pid, k, '<circle cx="%.2f" cy="%.2f" r="3" fill="#34539E"/>' % (x + 9, cy + fs * .62) if bullet else "",
                    svg_text(x + 20 if bullet else x + 6, cy + h / 2, lines, fs, "start", **({"fill": tone} if tone else {}))))
        if not measure:
            registry.append({"element_id": "%s-item-%d" % (pid, k), "panel": pid, "type": "text", "label": strip_markup((str(big) + " " if big else "") + str(it.get("text", ""))), "src": it.get("src") or panel.get("src")})
        cy += h + fs * (.36 if tight else .55)
    s.append("</g>")
    return "\n".join(s), cy - y


def render(spec, read, locked=None, scale=1.0, squeeze=False):
    """Return (svg, registry, meta). `read(file)` -> (cols, rows)."""
    cv = spec.get("canvas", {})
    W = float(cv.get("width_mm", 180)) * MM * scale
    fs = float(cv.get("font_pt", 8)) * (25.4 / 72) * MM
    fk_text.FLOOR[0] = float(cv.get("min_font_pt") or 5.0) * (25.4 / 72) * MM * 1.004 * (max(1.0, float(scale or 1.0)) if (cv.get("min_font_pt") or not cv.get("reserve")) else 1.0) * float(cv.get("_floor_boost") or 1.0)  # at final size: the drawing is scale times wider than the page
    theme = spec.get("theme") == "abstract"
    fs = max(fs, fk_text.FLOOR[0] * (1.02 if theme else 1 / 0.82))
    M = 10.0 if theme else 18.0
    if theme:
        for j, p in enumerate(q for q in spec["panels"]):
            p["_tight"] = True
            p.setdefault("_color", BANDS[min(j, 3) if len(spec["panels"]) <= 4 else (0 if j == 0 else 3 if j == len(spec["panels"]) - 1 else 1 if j == 1 else 2)])
            if p.get("type") == "chart":
                p.setdefault("ytop", True)
    panels = {p["id"]: p for p in spec["panels"]}
    rows = []
    for r in (spec.get("layout") or [[p["id"]] for p in spec["panels"]]):
        row = []
        for cell in ([r] if isinstance(r, str) else list(r)):
            col = [c for c in ([cell] if isinstance(cell, str) else list(cell)) if c in panels]
            if col:
                row.append(col)
        # the same id repeated in a row means "span"; keep it once
        uniq = []
        for col in row:
            if col not in uniq:
                uniq.append(col)
        if uniq:
            rows.append(uniq)
    seen = {i for r in rows for col in r for i in col}
    rows += [[[p]] for p in panels if p not in seen]
    registry, body, meta = [], [], {"panels": {}, "charts": [], "layout": {}}
    y = M
    if spec.get("title"):
        lines = wrap(spec["title"], fs * 1.3, W - 2 * M, True)
        h = len(lines) * fs * 1.3 * 1.22
        if theme:
            sub_ = wrap(str(spec.get("subtitle") or ""), fs, W - 2 * M - 12) if spec.get("subtitle") else []
            bh = h + len(sub_) * fs * 1.2 + 12
            body.append('<g id="figure-title" data-layer="title"><rect x="0" y="0" width="%.2f" height="%.2f" fill="#1F4E5F"/>%s%s</g>' % (
                W, bh, svg_text(M + 4, 6 + h / 2, lines, fs * 1.3, "start", True, "#FFFFFF"), svg_text(M + 4, 6 + h + len(sub_) * fs * .6, sub_, fs, "start", False, "#DCEAF0") if sub_ else ""))
            if sub_:
                registry.append({"element_id": "figure-subtitle", "panel": "", "type": "note", "label": strip_markup(str(spec["subtitle"])), "src": spec.get("subtitle_src") or spec.get("title_src")})
            y = bh + 8
            h = -10
        else:
            body.append('<g id="figure-title" data-layer="title">%s</g>' % svg_text(W / 2, y + h / 2, lines, fs * 1.3, bold=True))
        registry.append({"element_id": "figure-title", "panel": "", "type": "title", "label": strip_markup(spec["title"]), "src": spec.get("title_src")})
        y += h + 10
    multi = len(panels) > 1 if not locked else locked.get("_multi", len(panels) > 1)
    meta["multi"] = multi
    used_k, used_e, used_cert = set(), set(), set()
    for row in rows:
        weights = [max(float(panels[i].get("weight", 1)) for i in col) for col in row]
        gap = 8 if theme else 14
        tot = W - 2 * M - gap * (len(row) - 1)
        widths = [tot * w / sum(weights) for w in weights]
        columns = []
        for col, pw in zip(row, widths):
            prepared = []
            for pid in col:
                p = panels[pid]
                inner = pw - (20 if multi else 0)
                head_lines = wrap(("%s  " % pid if p.get("letter", multi and pid in "ABCDEFGHIJ" and not str(p.get("title", ""))[:1].isdigit()) else "") + str(p.get("title", "")), fs * 1.06, inner - 6, True) if (p.get("title") or multi) else []
                head = len(head_lines) * fs * 1.06 * 1.2 + ((10 if theme else 14) if head_lines else 0)
                t = p.get("type", "diagram")
                note = wrap(str(p["note"]), fs * .84, inner - 8) if p.get("note") else []
                nh = len(note) * fs * .84 * 1.25 + (8 if note else 0)
                res = None
                if t == "diagram":
                    res = layout_diagram(p, inner, fs)
                    if locked and pid in locked:
                        apply_lock(p, res, locked[pid], fs)
                    ch = res["h"]
                    for n in p["nodes"]:
                        used_k.add(n.get("kind", "concept"))
                        if n.get("certainty") in PROPOSED:
                            used_cert.add("dash")
                    for e in p.get("edges", []):
                        used_e.add(e.get("type", "flow"))
                        if e.get("certainty") in PROPOSED:
                            used_cert.add("dash")
                        if e.get("certainty") in CITED:
                            used_cert.add("grey")
                elif t == "chart":
                    ch = float(p.get("height_mm", 62)) * MM
                else:
                    _, ch = draw_text_panel(p, 0, 0, inner, pid, fs, registry, True)
                    ch += 6
                prepared.append({"p": p, "t": t, "res": res, "ch": ch, "hl": head_lines, "head": head, "note": note, "nh": nh,
                                 "full": ch + head + nh + (18 if multi else 0)})
                if locked and pid in locked.get("_frames", {}):
                    old_h = locked["_frames"][pid][3]
                    if t == "chart" or prepared[-1]["full"] <= old_h + .5:
                        prepared[-1]["full"] = old_h
            columns.append(prepared)
        row_h = max(sum(c["full"] for c in col) + gap * (len(col) - 1) for col in columns)
        x = M
        for prepared, pw in zip(columns, widths):
            spare = row_h - sum(c["full"] for c in prepared) - gap * (len(prepared) - 1)
            stretch = ([c for c in prepared if c["t"] == "chart"] or prepared) if not (locked and all(c["p"]["id"] in locked.get("_frames", {}) for c in prepared)) else prepared[-1:]
            for c in stretch:
                c["full"] += spare / len(stretch)
            cy = y
            for c in prepared:
                p, t, res, ch, head, note, nh, ph = c["p"], c["t"], c["res"], c["ch"], c["head"], c["note"], c["nh"], c["full"]
                pid = p["id"]
                meta.setdefault("frames", {})[pid] = [x, cy, pw, ph]
                body.append('<g id="panel-%s" data-role="panel" data-title="%s">' % (pid, escape(strip_markup(str(p.get("title", ""))))))
                ix, iy = x, cy
                if multi:
                    body.append('<rect id="panel-%s-frame" x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="8" fill="#ffffff" stroke="#D3D9DF" stroke-width="1.2"/>' % (pid, x, cy, pw, ph))
                    ix, iy = x + 10, cy + 9
                inner = pw - (20 if multi else 0)
                if theme and multi:
                    body[-1] = '<rect id="panel-%s-frame" x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="5" fill="%s" stroke="%s" stroke-width="1.2"/>' % (pid, x, cy, pw, ph, "#FFFFFF" if t == "chart" else TINT.get(p.get("_color"), "#F7F9FB"), p.get("_color", "#B8C2CC"))
                    iy = cy + 2
                if c["hl"] and theme:
                    body.append('<g id="panel-%s-band"><rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="5" fill="%s"/></g>%s' % (pid, x, cy, pw, head - 3, p.get("_color", "#3B5B78"), svg_text(ix + 1, cy + (head - 3) / 2, c["hl"], fs * 1.06, "start", True, "#FFFFFF", "panel-%s-title" % pid)))
                elif c["hl"]:
                    body.append(svg_text(ix + 3, iy + (head - 12) / 2, c["hl"], fs * 1.06, "start", True, "#1F3B57", "panel-%s-title" % pid))
                if c["hl"]:
                    if p.get("title"):
                        registry.append({"element_id": "panel-%s-title" % pid, "panel": pid, "type": "panel-title", "label": strip_markup(str(p["title"])), "src": p.get("src")})
                    iy += head
                avail = ph - (18 if multi else 0) - head - nh
                if t == "diagram":
                    oy = iy + max(0, (avail - ch) / 2)
                    ox = ix + max(0, (inner - res["w"]) / 2)
                    body.append(draw_diagram(p, res, ox, oy, pid, fs, registry))
                    meta["layout"][pid] = {"nodes": {n["id"]: (n["_box"].x, n["_box"].y, n["_box"].w, n["_box"].h) for n in res["nodes"]},
                                           "edges": [{"from": e["from"], "to": e["to"], "type": e.get("type", "flow"), "pts": [[a, b] for a, b in e["pts"]], "label": str(e.get("label") or ""), "label_lines": e.get("label_lines"),
                                                      "label_box": [e["label_box"].x, e["label_box"].y, e["label_box"].w, e["label_box"].h] if e.get("label_box") else None} for e in res["edges"]],
                                           "groups": [{"id": g["id"], "members": sorted(n["id"] for n in res["nodes"] if n.get("group") == g["id"]), "box": [g["box"].x, g["box"].y, g["box"].w, g["box"].h]} for g in res["groups"]], "w": res["w"], "h": res["h"],
                                           "sized": {n["id"]: [node_key(n), n["_lines"], n["_sub"], n["_w"], n["_h"], n["_icon"]] for n in res["nodes"]}}
                    meta["panels"][pid] = {"res": res, "ox": ox, "oy": oy, "inner": inner}
                elif t == "chart":
                    svg, info = draw_chart(p, ix, iy, inner, avail, read, fs * (1.0 if theme else .92), pid)
                    body.append(svg)
                    meta["charts"].append(info)
                    registry.append({"element_id": "%s-chart" % pid, "panel": pid, "type": "chart", "label": "%s of %s by %s" % (info["kind"], p.get("y") or p.get("value"), p.get("x")),
                                     "src": p.get("src") or [p["data"]], "data": info})
                else:
                    svg, _ = draw_text_panel(p, ix, iy + 2 + min(40, max(0, (avail - ch) / 4)), inner, pid, fs, registry)
                    body.append(svg)
                if note:
                    body.append(svg_text(ix + 4, cy + ph - nh / 2 - (6 if multi else 0), note, fs * .84, "start", fill="#46515C", ident="panel-%s-note" % pid))
                    registry.append({"element_id": "panel-%s-note" % pid, "panel": pid, "type": "note", "label": strip_markup(str(p["note"])), "src": p.get("note_src") or p.get("src")})
                body.append("</g>")
                cy += ph + gap
            x += pw + gap
        y += row_h + (8 if theme else 14)
    # legend
    leg = []
    lab_seen = set()
    if (len(used_k) > 1 and not theme) or any(k in used_k for k in ("gene", "complex")):
        for k in KINDS:
            if k in used_k and KINDS[k][3] not in lab_seen:
                lab_seen.add(KINDS[k][3])
                leg.append(("k", k, spec.get("legend_labels", {}).get(k, KINDS[k][3])))
    for t in EDGES:
        if t in used_e and EDGES[t][4] not in lab_seen:
            lab_seen.add(EDGES[t][4])
            leg.append(("e", t, spec.get("legend_labels", {}).get(t, EDGES[t][4])))
    if "dash" in used_cert:
        leg.append(("c", "", spec.get("legend_labels", {}).get("certainty", ("Dotted" if PDASH[0] == "2 4" else "Dashed") + ": proposed / not established")))
    if used_cert and any(p["type"] == "diagram" and p.get("edges") for p in spec["panels"]):
        leg.append(("w", {"w": 2, "c": "#222A33", "d": ""}, spec.get("legend_labels", {}).get("stated", "Solid, coloured: shown in this study" if spec.get("_shown") else "Solid, coloured: reported in this source")))
    if "grey" in used_cert:
        leg.append(("g", "cited", spec.get("legend_labels", {}).get("cited", "Grey: from cited literature, not this study")))
    for p in spec["panels"]:
        ew = p.get("edge_width")
        if ew and p["type"] == "diagram":
            vals = [abs(_num(e.get(ew.get("field", "value")))) for e in p["edges"] if _num(e.get(ew.get("field", "value"))) is not None]
            vm = float(ew.get("max") or (max(vals) if vals else 1))
            for f in (.25, .6, 1.0):
                leg.append(("w", {"w": 1.2 + 5.3 * f, "c": "#46515C", "d": ""}, "%s %.2g" % (ew.get("label", "|value|"), vm * f)))
            if ew.get("sign", True):
                leg.append(("w", {"w": 3, "c": POS, "d": ""}, ew.get("pos_label", "positive")))
                leg.append(("w", {"w": 3, "c": NEG, "d": ""}, ew.get("neg_label", "negative")))
    auto_ = {"dash": "dash" in used_cert, "grey": "grey" in used_cert}
    for x in spec.get("legend_extra", []):
        if not isinstance(x, dict):
            x = {"text": str(x)}
        tx_ = str(x.get("text", "")).lower()
        if (auto_["grey"] and re.match(r"gr[ae]y", tx_)) or (auto_["dash"] and re.search(r"propos", tx_)) or (used_cert and re.match(r"solid", tx_) and re.search(r"shown|stated|reported|this study|source", tx_)):
            continue  # the engine already explains this style
        leg.append(("w", {"w": float(x.get("width", 2)), "c": x.get("color", "#46515C"), "d": {"dashed": "8 5", "dotted": "2 4", "dashdot": "9 4 2 4"}.get(x.get("dash", ""), "")}, str(x.get("text", ""))))
    if leg and spec.get("legend", True):
        body.append('<g id="figure-legend" data-role="legend" data-layer="legend">')
        lx, ly, lf = M + 4, y + 10, fs * .86
        for typ, k, lab in leg:
            w = width(lab, lf) + 58
            if lx + w > W - M and lx > M + 4:
                lx, ly = M + 4, ly + lf * 1.75
            body.append('<g id="legend-%s-%s">' % (typ, (k if isinstance(k, str) else "style%d" % len(body)) or "certainty"))
            if typ == "w":
                body.append('<path d="M%.2f %.2fh32" stroke="%s" stroke-width="%.1f"%s fill="none"/>' % (lx, ly, k["c"], k["w"], ' stroke-dasharray="%s"' % k["d"] if k["d"] else ""))
            elif typ == "k":
                body.append(_shape({"_box": Box(lx, ly - 9, 30, 18)}, k))
            else:
                color, dash, head, sw, _ = EDGES[k] if typ == "e" else (GREY, "", "none", 2.4, "") if typ == "g" else ("#46515C", PDASH[0], "none", 2, "")
                h, end = _head("arrow" if head.startswith("arrow") else head, (lx, ly), (lx + 32, ly), color, sw)
                body.append('<path d="M%.2f %.2fL%.2f %.2f" stroke="%s" stroke-width="%.1f"%s fill="none"/>%s' % (
                    lx, ly, end[0], end[1], color, sw, ' stroke-dasharray="%s"' % dash if dash else "", h))
                if head.startswith("arrow") and len(head) > 5:
                    body.append('<circle cx="%.2f" cy="%.2f" r="%.1f" fill="#fff" stroke="%s" stroke-width="1.3"/>%s' % (lx + 13, ly, max(8.0, fk_text.fsz(11) * .72), color, scissors(lx + 13, ly, color) if head == "arrowCUT" else svg_text(lx + 13, ly, [head[5:]], 11, bold=True, fill=color)))
                if typ == "e" and k == "dimerisation":
                    body.append('<path d="M%.2f %.2fh32" stroke="#ffffff" stroke-width="%.1f" fill="none"/>' % (lx, ly, sw * .45))
            body.append(svg_text(lx + 39, ly, [lab], lf, "start"))
            body.append("</g>")
            lx += w
        body.append("</g>")
        y = ly + lf * 1.5
    foot = list(spec.get("footnotes", []))
    for k, t in enumerate(foot):
        txt = t["text"] if isinstance(t, dict) else str(t)
        lines = wrap(txt, fs * .82, W - 2 * M - 8)
        h = len(lines) * fs * .82 * 1.25
        body.append(svg_text(M + 4, y + h / 2 + 4, lines, fs * .82, "start", fill="#46515C", ident="footnote-%d" % k))
        registry.append({"element_id": "footnote-%d" % k, "panel": "", "type": "footnote", "label": strip_markup(txt), "src": t.get("src") if isinstance(t, dict) else None})
        y += h + 4
    H = y + M
    if locked and locked.get("_view") and not cv.get("height_mm"):
        H = max(H, locked["_view"][3])
    W_mm = W / MM / scale
    H_mm = H / MM / scale
    vx, vw, eff = 0.0, W, scale
    if cv.get("height_mm") and (locked or squeeze) and H_mm > float(cv["height_mm"]) + 1e-6:
        H_mm = float(cv["height_mm"])
        vw = H * W_mm / H_mm
        vx = -(vw - W) / 2
        eff = scale * vw / W
    elif cv.get("height_mm") and H_mm <= float(cv["height_mm"]) + 1e-6:
        H_mm = float(cv["height_mm"])
        pad = H_mm * MM * scale - H
        if not locked and cv.get("reserve"):  # room at the bottom for the edit the work order announces
            pad = max(0.0, pad - 1.6 * float(cv["reserve"]) * H_mm * MM * scale)
        if locked and locked.get("_shift") is not None and pad >= locked["_shift"]:
            pad = 2 * locked["_shift"]
        H = H_mm * MM * scale
        body = ['<g id="figure-content" transform="translate(0 %.2f)">' % (pad / 2)] + body + ["</g>"]
        meta["shift"] = pad / 2
    svg = ('<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="%.3fmm" height="%.3fmm" viewBox="%.2f 0 %.2f %.2f" font-family="%s">\n'
           "<title>%s</title>\n<desc>%s</desc>\n<rect id=\"background\" x=\"-20%%\" width=\"140%%\" height=\"100%%\" fill=\"#ffffff\"/>\n%s\n</svg>\n") % (
        W_mm, H_mm, vx, vw, H, FONT_STACK.replace('"', "'"), escape(strip_markup(spec.get("title", "Figure"))),
        escape(strip_markup(spec.get("caption", ""))[:1500]), "\n".join(body))
    meta["size_mm"] = [round(W_mm, 2), round(H_mm, 2)]
    meta["scale"] = eff
    meta["layout_scale"] = scale
    meta["view"] = [vx, 0.0, vw, H, meta.get("shift") or 0.0]
    meta["canvas_units"] = [W, H]
    meta["font_units"] = fs
    return svg, registry, meta


def node_key(n):
    return "|".join(str(n.get(k) or "") for k in ("label", "note", "kind", "step", "glyph"))


def apply_lock(panel, res, lock, fs):
    """Keep earlier positions when revising; only new/resized nodes move."""
    from fk_layout import route_all, _labels
    old = lock["nodes"]
    common = [n for n in res["nodes"] if n["id"] in old]
    if not common:
        return
    placed = []
    for n in common:  # an unchanged node keeps its line breaks whatever else was added
        q = (lock.get("sized") or {}).get(n["id"])
        if q and q[0] == node_key(n):
            n["_lines"], n["_sub"], n["_w"], n["_h"], n["_icon"] = q[1:]
        x, y, w, h = old[n["id"]]
        if abs(w - n["_w"]) < .01 and abs(h - n["_h"]) < .01:
            n["_box"] = Box(x, y, w, h)
        else:
            n["_box"] = Box(x + (w - n["_w"]) / 2, y + (h - n["_h"]) / 2, n["_w"], n["_h"])
        placed.append(n["_box"])
    busy = []
    for q in lock.get("edges", []):
        if q.get("label_box"):
            busy.append((Box(*q["label_box"]), 90.0))
        for (xa, ya), (xb, yb) in zip(q["pts"], q["pts"][1:]):
            busy.append((Box(min(xa, xb) - 3, min(ya, yb) - 3, abs(xa - xb) + 6, abs(ya - yb) + 6), 55.0))
    gboxes = {g["id"]: g["box"] for g in res["groups"]}
    grp_old = {}
    for m in common:
        if m.get("group"):
            o = m["_box"]
            c = grp_old.get(m["group"])
            grp_old[m["group"]] = Box(min(c.x, o.x), min(c.y, o.y), 0, 0) if False else (o if c is None else Box(min(c.x, o.x), min(c.y, o.y), max(c.x + c.w, o.x + o.w) - min(c.x, o.x), max(c.y + c.h, o.y + o.h) - min(c.y, o.y)))
    pos = {m["id"]: m["_box"] for m in common}
    for n in res["nodes"]:
        if n["id"] in old:
            continue
        near = [pos[q] for e in panel.get("edges", []) for q in (e["from"], e["to"]) if n["id"] in (e["from"], e["to"]) and q != n["id"] and q in pos]
        cx = sum(q.cx for q in near) / len(near) if near else lock["w"] / 2
        cy = sum(q.cy for q in near) / len(near) if near else lock["h"] / 2
        zone = grp_old.get(n.get("group"))
        best = None
        ylim = lock["h"] + 160
        for gx in range(14, int(lock["w"] - n["_w"] - 8), 14):
            for gy in range(34, int(ylim - n["_h"]), 12):
                t = Box(gx, gy, n["_w"], n["_h"])
                if any(t.pad(16).hit(o) for o in placed):
                    continue
                cost = abs(t.cx - cx) * .6 + abs(t.cy - cy)
                if zone is not None:
                    Z = zone.pad(34)
                    if not (Z.x <= t.x and t.x + t.w <= Z.x + Z.w and Z.y <= t.y and t.y + t.h <= Z.y + Z.h):
                        cost += 260 + abs(t.cx - zone.cx) * .5 + abs(t.cy - zone.cy) * .5
                if t.y + t.h > lock["h"] - 8:
                    cost += 420
                cost += sum(w for o, w in busy if t.pad(4).hit(o)) * 3
                if best is None or cost < best[0]:
                    best = (cost, t)
        if best:
            n["_box"] = best[1]
        if zone is not None:
            Z, t = zone.pad(40), n["_box"]
            n["_outside"] = not (Z.x <= t.x and t.x + t.w <= Z.x + Z.w and Z.y <= t.y and t.y + t.h <= Z.y + Z.h)
        placed.append(n["_box"])
        pos[n["id"]] = n["_box"]
    res["w"] = max(lock["w"], max(n["_box"].x + n["_box"].w for n in res["nodes"]) + 10)
    res["h"] = max(lock["h"], max(n["_box"].y + n["_box"].h for n in res["nodes"]) + 14)
    if str(panel.get("direction", "")).upper() == "WRAP" and lock.get("groups"):
        keep = {g["id"]: g for g in lock["groups"]}
        for g in res["groups"]:
            if g["id"] in keep:
                g["box"] = Box(*keep[g["id"]]["box"])
        res["groups_locked"] = True
    saved = {g["id"]: g for g in lock.get("groups", [])}
    stay = {n["id"] for n in common if n["_box"].tup() == Box(*old[n["id"]]).tup()}
    for g in ([] if res.get("groups_locked") else res["groups"]):
        now = sorted(n["id"] for n in res["nodes"] if n.get("group") == g["id"] and not n.get("_outside"))
        sg = saved.get(g["id"])
        if sg and sg.get("members") is not None and set(now) <= set(sg["members"]) and all(i in stay for i in now):
            g["box"] = Box(*sg["box"])
            continue
        mem = [n["_box"] for n in res["nodes"] if n.get("group") == g["id"] and not n.get("_outside")]
        if not mem:  # continuation frame of a wrapped route
            continue
        b = g["box"]
        x0, y0 = min(m.x for m in mem), min(m.y for m in mem)
        x1, y1 = max(m.x + m.w for m in mem), max(m.y + m.h for m in mem)
        wide = b.w > lock["w"] - 30
        g["box"] = Box(b.x if wide else x0 - 18, y0 - 33, b.w if wide else x1 - x0 + 36, y1 - y0 + 48)
    by = {n["id"]: n for n in res["nodes"]}
    res["w"], res["h"] = (lock["w"], lock["h"]) if res["w"] <= lock["w"] + 11 and res["h"] <= lock["h"] + 15 else (res["w"], res["h"])
    for e in res["edges"]:
        e.pop("label_box", None)
    route_all(res, panel.get("edges", []), by, fs)
    moved = {i for i, t in old.items() if i in by and by[i]["_box"].tup() != Box(*t).tup()}
    pool = list(lock.get("edges", []))
    for e in res["edges"]:
        for q in pool:
            if (q["from"], q["to"], q["type"]) == (e["from"], e["to"], e.get("type", "flow")) and e["from"] not in moved and e["to"] not in moved:
                e["pts"] = [tuple(x) for x in q["pts"]]
                if q.get("label_lines") == e.get("label_lines") and q.get("label_box"):
                    e["label_box"] = Box(*q["label_box"])
                e["_kept"] = True
                pool.remove(q)
                break
    for e in res["edges"]:  # unchanged labels stay where they were and are obstacles for the new ones
        for q in lock.get("edges", []):
            if e.get("_kept") and q.get("label_box") and (q["from"], q["to"], q["type"]) == (e["from"], e["to"], e.get("type", "flow")) and q.get("label") == str(e.get("label") or ""):
                e["label_box"], e["label_lines"] = Box(*q["label_box"]), q["label_lines"]
    _labels(res, fs)
    for e in res["edges"]:
        for q in lock.get("edges", []):
            if e.get("_kept") and q.get("label_box") and (q["from"], q["to"], q["type"]) == (e["from"], e["to"], e.get("type", "flow")) and q.get("label") == str(e.get("label") or ""):
                e["label_box"], e["label_lines"] = Box(*q["label_box"]), q["label_lines"]
