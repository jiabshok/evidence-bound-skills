"""Deterministic layered layout, orthogonal routing and label placement.

Coordinates are in user units; 6 units = 1 mm (so 1080 units = 180 mm).
"""
import heapq
from collections import defaultdict

from fk_text import width, wrap

CELL = 6


class Box:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    def pad(self, p):
        return Box(self.x - p, self.y - p, self.w + 2 * p, self.h + 2 * p)

    def hit(self, o):
        return (self.x < o.x + o.w and o.x < self.x + self.w and
                self.y < o.y + o.h and o.y < self.y + self.h)

    def overlap(self, o):
        dx = min(self.x + self.w, o.x + o.w) - max(self.x, o.x)
        dy = min(self.y + self.h, o.y + o.h) - max(self.y, o.y)
        return dx * dy if dx > 0 and dy > 0 else 0.0

    def tup(self):
        return (round(self.x, 2), round(self.y, 2), round(self.w, 2), round(self.h, 2))


def size_node(n, fs, max_w):
    """Set n['_lines'], n['_w'], n['_h'] from its label and kind."""
    label = str(n.get("label", n["id"]))
    prefix = ""
    if n.get("step") is not None:
        prefix = "%s. " % n["step"]
    longest = max([width(t, fs, True) for t in (prefix + label).replace("/", "/ ").replace("-", "- ").split()] + [0])
    if n.get("note"):
        longest = max(longest, max(width(t, fs * 0.86) for t in str(n["note"]).replace("/", "/ ").replace("-", "- ").split() or [""]) - 10)
    max_w = max(max_w, min(longest + 1, 260))  # never break inside a word
    lines = wrap(prefix + label, fs, max_w, True)
    sub = wrap(str(n["note"]), fs * 0.86, max_w + 10) if n.get("note") else []
    w = max([width(l, fs, True) for l in lines] + [width(l, fs * 0.86) for l in sub])
    h = len(lines) * fs * 1.22 + len(sub) * fs * 0.86 * 1.22
    icon = n.get("glyph")
    pad_w, pad_h = 22, 18
    if n.get("kind") in ("decision",):
        pad_w, pad_h = 40 + 0.55 * w, 26 + 0.85 * h
    if n.get("kind") in ("small_molecule", "metabolite", "ion", "sample", "phenotype"):
        pad_w, pad_h = 34, 24
    n["_lines"], n["_sub"] = lines, sub
    n["_icon"] = (46 if n.get("kind") != "decision" else 0) if icon else 0
    if icon and n.get("kind") == "decision":
        n.pop("glyph", None)
    n["_w"] = max(64, w + pad_w)
    n["_h"] = max(36, h + pad_h) + n["_icon"]


def _order_ranks(ids, edges, explicit, side=()):
    total_in = defaultdict(int)
    for a, b in edges:
        total_in[b] += 1
    """Longest-path ranks with back edges removed."""
    succ = defaultdict(list)
    for a, b in edges:
        if a in ids and b in ids and a != b:
            succ[a].append(b)
    state, back = {}, set()

    def dfs(root):
        stack = [(root, iter(succ[root]))]
        state[root] = 1
        while stack:
            u, it = stack[-1]
            for v in it:
                if state.get(v) == 1:
                    back.add((u, v))
                elif v not in state:
                    state[v] = 1
                    stack.append((v, iter(succ[v])))
                    break
            else:
                state[u] = 2
                stack.pop()

    indeg = defaultdict(int)
    for a in succ:
        for b in succ[a]:
            indeg[b] += 1
    for i in sorted(ids, key=lambda k: (indeg[k], ids.index(k))):
        if i not in state:
            dfs(i)
    rank = {i: 0 for i in ids}
    for _ in range(len(ids) + 1):
        changed = False
        for a in succ:
            for b in succ[a]:
                if (a, b) not in back and rank[b] < rank[a] + 1:
                    rank[b] = rank[a] + 1
                    changed = True
        if not changed:
            break
    # pull sources next to their first consumer
    for i in ids:
        if indeg[i] == 0 and succ[i]:
            t = min(rank[j] for j in succ[i]) - 1
            rank[i] = max(rank[i], t)
    for i in ids:
        if indeg[i] == 0 and len(succ[i]) == 1 and i in side and total_in[i] == 0 and total_in[succ[i][0]] > 1:
            rank[i] = rank[succ[i][0]]
    for i, r in explicit.items():
        if i in rank:
            rank[i] = r
    used = sorted(set(rank.values()))
    m = {r: k for k, r in enumerate(used)}
    return {i: m[r] for i, r in rank.items()}


ROUTE = [True]


def layout_diagram(panel, avail_w, fs=17):
    """Lay out with the requested direction, or try both and keep the better one."""
    want = str(panel.get("direction", "auto")).upper()
    if want == "WRAP":
        res = wrap_layout(panel, avail_w, fs)
        if res is not None:
            return res
        want = "TB"
    if want in ("LR", "TB"):
        return _layout(panel, avail_w, fs, want)
    best = None
    for d in ("LR", "TB"):
        res = _layout(panel, avail_w, fs, d)
        over = max(0.0, res["w"] - avail_w)
        asp = res["h"] / max(1.0, avail_w)
        score = over * 8 + abs(asp - 0.5) * 420 + (asp > 0.95) * 260 + 22 * sum(len(e["pts"]) > 4 for e in res["edges"]) \
            + 300 * sum(bool(e.get("unrouted")) for e in res["edges"])
        for e in res["edges"]:
            b = e.get("label_box")
            if b:
                score += sum(b.overlap(n["_box"]) for n in res["nodes"]) * 1.5
        if best is None or score < best[0]:
            best = (score, d)
    panel["_direction"] = best[1]
    return _layout(panel, avail_w, fs, best[1])


def wrap_layout(panel, avail_w, fs):
    """Long routes: ranks flow in serpentine rows; groups become coloured runs of cells."""
    nodes, edges = panel["nodes"], panel.get("edges", [])
    ids = [n["id"] for n in nodes]
    by = {n["id"]: n for n in nodes}
    pairs = [(e["from"], e["to"]) for e in edges if e.get("type") not in ("association", "comparison")]
    explicit = {n["id"]: n["rank"] for n in nodes if isinstance(n.get("rank"), (int, float))}
    gorder = {g["id"]: k for k, g in enumerate(panel.get("groups", []))}
    steps = [n.get("step") for n in nodes]
    if all(isinstance(x, (int, float)) or (isinstance(x, str) and x.replace(".", "", 1).isdigit()) for x in steps) and len(set(steps)) > 2:
        order = sorted(set(float(x) for x in steps))
        rank = {n["id"]: order.index(float(n["step"])) for n in nodes}
    else:
        rank = _order_ranks(ids, pairs, explicit)
        # keep group members contiguous
        keyed = sorted(set((gorder.get(by[i].get("group"), -1), rank[i]) for i in ids))
        rank = {i: keyed.index((gorder.get(by[i].get("group"), -1), rank[i])) for i in ids}
    nr = max(rank.values()) + 1
    if nr < 5:
        return None
    labelled = any(e.get("label") and abs(rank.get(e["from"], 0) - rank.get(e["to"], 0)) == 1 for e in edges)
    gap = 92 if labelled else 46
    cols = max(2, min(5, int((avail_w + gap) // (165 + gap))))
    cols = min(cols, nr)
    if nr / cols > 1 and nr % cols == 1 and cols > 3:
        cols -= 1
    cw = (avail_w - 28 - gap * (cols - 1)) / cols
    for n in nodes:
        for shrink in (30, 52, 80, 110, 150, 190):
            size_node(n, fs, max(60, cw - shrink))
            if n["_w"] <= cw + 1:
                break
        if n.get("kind") == "decision" and (n["_h"] > 150 or n["_w"] > cw + 1):
            n["kind"] = "process"
            for shrink in (58, 80, 110, 150):
                size_node(n, fs, max(60, cw - shrink))
                if n["_w"] + 26 <= cw + 1:
                    break
            n["kind"], n["_flat"] = "decision", True
            n["_w"] = min(cw, n["_w"] + 26)
    rows = [[] for _ in range((nr + cols - 1) // cols)]
    cell = {r: [i for i in ids if rank[i] == r] for r in range(nr)}
    heights = []
    for k in range(len(rows)):
        heights.append(max(sum(by[i]["_h"] for i in cell[r]) + 26 * (len(cell[r]) - 1) for r in range(k * cols, min(nr, (k + 1) * cols))))
    hdr = 30
    for g in panel.get("groups", []):
        span = max([sum(1 for r in range(k * cols, min(nr, (k + 1) * cols)) if any(by[i].get("group") == g["id"] for i in cell[r])) for k in range(len(rows))] or [1])
        firsts = [k for k in range(len(rows)) if any(by[i].get("group") == g["id"] for r in range(k * cols, min(nr, (k + 1) * cols)) for i in cell[r])]
        if firsts:
            k = firsts[0]
            span = sum(1 for r in range(k * cols, min(nr, (k + 1) * cols)) if any(by[i].get("group") == g["id"] for i in cell[r]))
            if width(str(g.get("label", "")), fs * .9, True) > span * cw + (span - 1) * gap:
                hdr = 50
    y = hdr + 4 if panel.get("groups") else 10
    vgap = 40 + hdr if panel.get("groups") else 46
    for k, h in enumerate(heights):
        for r in range(k * cols, min(nr, (k + 1) * cols)):
            c = r - k * cols
            if k % 2:
                c = cols - 1 - c
            x = 14 + c * (cw + gap)
            tot = sum(by[i]["_h"] for i in cell[r]) + 26 * (len(cell[r]) - 1)
            yy = y + (h - tot) / 2
            for i in cell[r]:
                n = by[i]
                n["_box"] = Box(x + (cw - n["_w"]) / 2, yy, n["_w"], n["_h"])
                yy += n["_h"] + 26
        y += h + vgap
    H = y - vgap + 22
    gout = []
    for g in panel.get("groups", []):
        for k in range(len(rows)):
            mem = [by[i]["_box"] for i in ids if by[i].get("group") == g["id"] and rank[i] // cols == k]
            if not mem:
                continue
            x0, x1 = min(b.x for b in mem), max(b.x + b.w for b in mem)
            cs = [c for c in range(cols) if any(abs(14 + c * (cw + gap) + cw / 2 - b.cx) < 2 for b in mem)]
            x0, x1 = 14 + min(cs) * (cw + gap) - 8, 14 + max(cs) * (cw + gap) + cw + 8
            y0, y1 = min(b.y for b in mem), max(b.y + b.h for b in mem)
            first = not any(q["id"].split("__")[0] == g["id"] for q in gout)
            gout.append({"id": g["id"] + ("" if first else "__%d" % k), "label": g.get("label", g["id"]) if first else str(g.get("label", g["id"])) + " (cont.)",
                         "box": Box(x0, y0 - hdr, x1 - x0, y1 - y0 + hdr + 12), "wrapped": True, "kind": g.get("kind", "")})
    res = {"nodes": nodes, "groups": gout, "edges": [], "w": avail_w, "h": H}
    if ROUTE[0]:
        route_all(res, edges, by, fs)
    return res


def _layout(panel, avail_w, fs, direction):
    """Return dict(nodes, groups, edges, w, h); coordinates relative to panel origin."""
    nodes = panel["nodes"]
    edges = panel.get("edges", [])
    groups = panel.get("groups", [])
    ids = [n["id"] for n in nodes]
    by = {n["id"]: n for n in nodes}
    pairs = [(e["from"], e["to"]) for e in edges if e.get("type") not in ("association", "comparison")]
    gid = {n["id"]: n.get("group") for n in nodes}
    group_ids = [g["id"] for g in groups]
    axis = panel.get("group_axis")
    if groups and axis not in ("rank", "lane"):
        pos = {g: k for k, g in enumerate(group_ids)}
        fwd = sum(1 for a, b in pairs if pos.get(gid.get(a), 0) < pos.get(gid.get(b), 0))
        bwd = sum(1 for a, b in pairs if pos.get(gid.get(a), 0) > pos.get(gid.get(b), 0))
        axis = "rank" if fwd >= bwd else "lane"
    explicit = {n["id"]: n["rank"] for n in nodes if isinstance(n.get("rank"), (int, float))}

    side = {e["from"] for e in edges if e.get("type") in ("inhibition", "activation", "control", "binding", "energy")}
    rank = {}
    band_of_rank = {}
    if groups and axis == "rank":
        base = 0
        loose = [i for i in ids if gid[i] not in group_ids]
        sections = [(None, loose)] if loose else []
        sections += [(g, [i for i in ids if gid[i] == g]) for g in group_ids]
        for g, members in sections:
            if not members:
                continue
            local = _order_ranks(members, pairs, {k: v for k, v in explicit.items() if k in members}, side)
            span = max(local.values()) + 1
            for i in members:
                rank[i] = base + local[i]
            for r in range(span):
                band_of_rank[base + r] = g
            base += span
    else:
        rank = _order_ranks(ids, pairs, explicit, side)

    nranks = max(rank.values()) + 1 if rank else 1
    # -- choose a wrap width that fits the panel
    horizontal = direction == "LR"
    lane_mode = bool(groups) and axis == "lane"
    for attempt in range(6):
        if horizontal:
            max_label = max(78, (avail_w - 40 - (54 if lane_mode else 0)) / nranks - 88)
            max_label = min(190, max_label)
        else:
            widest = max([sum(1 for i in ids if rank[i] == r) for r in range(nranks)] or [1])
            max_label = min(210, max(82, (avail_w - 120) / widest - 64))
        max_label *= 0.9 ** attempt
        for n in nodes:
            size_node(n, fs, max_label)
        res = _place(nodes, by, ids, rank, nranks, pairs, groups, group_ids, gid, axis,
                     horizontal, avail_w, band_of_rank, edges, fs)
        if res["w"] <= avail_w + 1:
            break
    # spare width: longer label lines make a flatter drawing (and so larger type on a fixed page)
    if res["w"] < .94 * avail_w and any(len(n["_lines"]) + len(n["_sub"]) > 2 for n in nodes):
        best = (res["h"], max_label)
        for f in (1.3, 1.7, 2.2):
            ml = min(300, max_label * f)
            for n in nodes:
                size_node(n, fs, ml)
            r2 = _place(nodes, by, ids, rank, nranks, pairs, groups, group_ids, gid, axis,
                        horizontal, avail_w, band_of_rank, edges, fs)
            if r2["w"] <= avail_w + 1 and r2["h"] < best[0] - 6:
                best = (r2["h"], ml)
        for n in nodes:
            size_node(n, fs, best[1])
        res = _place(nodes, by, ids, rank, nranks, pairs, groups, group_ids, gid, axis,
                     horizontal, avail_w, band_of_rank, edges, fs)
    if ROUTE[0]:
        route_all(res, edges, by, fs)
    return res


def _place(nodes, by, ids, rank, nranks, pairs, groups, group_ids, gid, axis, horizontal,
           avail_w, band_of_rank, edges, fs):
    lane_mode = bool(groups) and axis == "lane"
    lanes = group_ids if lane_mode else [None]
    loose = [i for i in ids if lane_mode and gid[i] not in group_ids]
    if loose:
        lanes = [None] + lanes
    cells = defaultdict(list)
    for i in ids:
        lane = (gid[i] if gid[i] in group_ids else None) if lane_mode else None
        cells[(rank[i], lane)].append(i)
    # barycentre ordering
    adj = defaultdict(list)
    for a, b in pairs:
        if a in by and b in by:
            adj[a].append(b)
            adj[b].append(a)
    pos = {}
    for key, lst in cells.items():
        for k, i in enumerate(lst):
            pos[i] = k - (len(lst) - 1) / 2
    for sweep in range(8):
        order = range(nranks) if sweep % 2 == 0 else range(nranks - 1, -1, -1)
        for r in order:
            for lane in lanes:
                lst = cells.get((r, lane))
                if not lst or len(lst) < 2:
                    continue
                lst.sort(key=lambda i: (sum(pos[j] for j in adj[i] if rank[j] != r) /
                                        max(1, sum(1 for j in adj[i] if rank[j] != r)), ids.index(i)))
                for k, i in enumerate(lst):
                    pos[i] = k - (len(lst) - 1) / 2

    # main axis sizes
    ms = "_w" if horizontal else "_h"
    cs = "_h" if horizontal else "_w"
    thick = [max([by[i][ms] for i in ids if rank[i] == r] or [40]) for r in range(nranks)]
    lab = defaultdict(float)
    for e in edges:
        a, b = e["from"], e["to"]
        if a not in by or b not in by:
            continue
        if e.get("label"):
            lo, hi = sorted((rank[a], rank[b]))
            if hi > lo:
                need = (min(130, width(str(e["label"]), fs * 0.84)) + 34) if horizontal else 46
                lab[lo] = max(lab[lo], need)
    gaps = [max(58 if horizontal else 42, lab[r]) for r in range(nranks)]
    for r in range(1, nranks):
        if band_of_rank and band_of_rank.get(r) != band_of_rank.get(r - 1):
            gaps[r - 1] += 26 if not horizontal else 34
    head = 30 if groups else 0
    main0 = 26 if not lane_mode else (30 if not horizontal else 26)
    if horizontal and lane_mode:
        main0 = 40
    if not horizontal and band_of_rank:
        main0 += 10
    start = []
    cur = main0 + (head if (band_of_rank and not horizontal) else 0)
    for r in range(nranks):
        start.append(cur)
        cur += thick[r] + gaps[r]
    main_len = cur - gaps[-1] + 26
    if horizontal and main_len < avail_w and nranks > 1:
        extra = min((avail_w - main_len) / (nranks - 1), 110)
        for r in range(nranks):
            start[r] += extra * r
        main_len += extra * (nranks - 1)
    # cross axis
    cross_gap = 30 if horizontal else 38
    lane_off, lane_len = {}, {}
    cur = head + 6 if (not lane_mode or horizontal) else 20
    if not horizontal and band_of_rank:
        cur = 84
    for lane in lanes:
        need = 40
        for r in range(nranks):
            lst = cells.get((r, lane), [])
            if lst:
                need = max(need, sum(by[i][cs] for i in lst) + cross_gap * (len(lst) - 1))
        pad = 20
        if lane is not None and horizontal:
            pad = 26
        lane_off[lane] = cur + pad
        lane_len[lane] = need
        cur += need + 2 * pad + (12 if lane_mode else 0)
    cross_len = cur + 8
    if not horizontal and cross_len < avail_w and not lane_mode:
        shift = (avail_w - cross_len) - (84 if band_of_rank else 0)
        shift = max(0, shift)
        lane_len[None] += shift
        cross_len += shift

    for (r, lane), lst in cells.items():
        total = sum(by[i][cs] for i in lst) + cross_gap * (len(lst) - 1)
        space = lane_len[lane]
        gap = cross_gap
        if not horizontal and len(lst) > 1:
            gap = min(120, (space - sum(by[i][cs] for i in lst)) / len(lst))
            gap = max(cross_gap, gap)
            total = sum(by[i][cs] for i in lst) + gap * (len(lst) - 1)
        c = lane_off[lane] + (space - total) / 2
        for i in lst:
            n = by[i]
            m = start[r] + (thick[r] - n[ms]) / 2
            if horizontal:
                n["_box"] = Box(m, c, n["_w"], n["_h"])
            else:
                n["_box"] = Box(c, m, n["_w"], n["_h"])
            c += n[cs] + gap

    W = main_len if horizontal else cross_len
    H = cross_len if horizontal else main_len
    W = max(W, 10)
    if horizontal and W < avail_w:
        dx = (avail_w - W) / 2
        for n in nodes:
            n["_box"].x += dx
        W = avail_w
    gout = []
    for g in groups:
        mem = [by[i]["_box"] for i in ids if gid[i] == g["id"]]
        if not mem:
            continue
        x0, y0 = min(b.x for b in mem), min(b.y for b in mem)
        x1, y1 = max(b.x + b.w for b in mem), max(b.y + b.h for b in mem)
        if lane_mode and horizontal:
            box = Box(6, y0 - 34, W - 12, y1 - y0 + 50)
        elif not horizontal and not lane_mode:
            box = Box(6, y0 - 32, W - 12, y1 - y0 + 46)
        elif horizontal and band_of_rank:
            ya = min(n["_box"].y for n in nodes)
            yb = max(n["_box"].y + n["_box"].h for n in nodes)
            lw = width(str(g.get("label", g["id"])), fs * .9, True) + 22
            ww = max(x1 - x0 + 30, 0)
            box = Box(x0 - 15 - max(0, lw - ww) / 2, ya - 36, max(ww, lw), yb - ya + 52)
        else:
            box = Box(x0 - 18, y0 - 34, x1 - x0 + 36, y1 - y0 + 50)
        gout.append({"id": g["id"], "label": g.get("label", g["id"]), "box": box, "kind": g.get("kind", "")})
    top = min([g["box"].y for g in gout] + [n["_box"].y for n in nodes])
    if top < 4:
        for n in nodes:
            n["_box"].y += 4 - top
        for g in gout:
            g["box"].y += 4 - top
    bottom = max([g["box"].y + g["box"].h for g in gout] + [n["_box"].y + n["_box"].h for n in nodes])
    return {"nodes": nodes, "groups": gout, "edges": [], "w": W, "h": max(H if horizontal else 0, bottom) + 10}


# --- routing -----------------------------------------------------------------
def route_all(res, edges, by, fs):
    boxes = [n["_box"] for n in res["nodes"]]
    W, H = res["w"], res["h"]
    margin = 24
    cols, rows = int((W + 2 * margin) / CELL) + 2, int((H + 2 * margin) / CELL) + 2

    def cell(x, y):
        return int(round((x + margin) / CELL)), int(round((y + margin) / CELL))

    def pt(c):
        return c[0] * CELL - margin, c[1] * CELL - margin

    blocked = set()
    near = {}
    for b in boxes:
        x0, y0 = cell(b.x - 5, b.y - 5)
        x1, y1 = cell(b.x + b.w + 5, b.y + b.h + 5)
        for i in range(x0, x1 + 1):
            for j in range(y0, y1 + 1):
                blocked.add((i, j))
        for i in range(x0 - 2, x1 + 3):
            for j in range(y0 - 2, y1 + 3):
                near[(i, j)] = 2.5
    for g in res["groups"]:
        b = g["box"]
        x0, y0 = cell(b.x, b.y)
        x1, y1 = cell(b.x + min(b.w, 14 + width(str(g["label"]), fs * 0.9, True)), b.y + 24)
        for i in range(x0, x1 + 1):
            for j in range(y0, y1 + 1):
                near[(i, j)] = 14
    used = {}
    port_use = defaultdict(int)

    diamonds = {id(n["_box"]) for n in res["nodes"] if n.get("kind") == "decision" and not n.get("_flat")}

    def ports(b, fx, fy, out):
        n_x = 5 if b.w > 90 else 3
        n_y = 3 if b.h > 40 else 1
        if id(b) in diamonds:
            n_x = n_y = 1
        res_p = []
        for k in range(n_x):
            t = (k + 1) / (n_x + 1)
            res_p.append((b.x + b.w * t, b.y, 0, -1, abs(t - .5)))
            res_p.append((b.x + b.w * t, b.y + b.h, 0, 1, abs(t - .5)))
        for k in range(n_y):
            t = (k + 1) / (n_y + 1)
            res_p.append((b.x, b.y + b.h * t, -1, 0, abs(t - .5)))
            res_p.append((b.x + b.w, b.y + b.h * t, 1, 0, abs(t - .5)))
        return res_p

    def span(e):
        a, b = by.get(e["from"]), by.get(e["to"])
        if not a or not b:
            return 1e9
        return abs(a["_box"].cx - b["_box"].cx) + abs(a["_box"].cy - b["_box"].cy)

    order = sorted(range(len(edges)), key=lambda k: span(edges[k]))
    out = [None] * len(edges)
    for k in order:
        e = edges[k]
        a, b = by.get(e["from"]), by.get(e["to"])
        if not a or not b:
            continue
        A, B = a["_box"], b["_box"]
        if a is b:
            x, y = A.x + A.w, A.cy
            pts = [(x, y - 8), (x + 22, y - 8), (x + 22, y + 10), (x, y + 10)]
            out[k] = dict(e, pts=pts)
            continue
        heap, best, came = [], {}, {}
        for (px, py, dx, dy, off) in ports(A, B.cx, B.cy, True):
            key = (a["id"], round(px), round(py))
            c = cell(px + dx * 8, py + dy * 8)
            while c in blocked and abs(pt(c)[0] - px) + abs(pt(c)[1] - py) < 30:
                c = (c[0] + dx, c[1] + dy)
            cost = off * 9 + port_use[key] * 26
            st = (c, (dx, dy))
            if cost < best.get(st, 1e9):
                best[st] = cost
                came[st] = ("S", (px, py))
                heapq.heappush(heap, (cost, cost, st))
        goals = {}
        for (px, py, dx, dy, off) in ports(B, A.cx, A.cy, False):
            key = (b["id"], round(px), round(py))
            c = cell(px + dx * 12, py + dy * 12)
            while c in blocked and abs(pt(c)[0] - px) + abs(pt(c)[1] - py) < 30:
                c = (c[0] + dx, c[1] + dy)
            cost = off * 9 + port_use[key] * 26
            if c not in goals or cost < goals[c][0]:
                goals[c] = (cost, (px, py), (-dx, -dy))
        tx, ty = cell(B.cx, B.cy)
        found = None
        iters = 0
        while heap and iters < 140000:
            iters += 1
            f, g, st = heapq.heappop(heap)
            if g > best.get(st, 1e9) + 1e-9:
                continue
            c, d = st
            if c in goals:
                gc, gp, gd = goals[c]
                if d == gd or True:
                    extra = gc + (0 if d == gd else 12)
                    if found is None or g + extra < found[0]:
                        found = (g + extra, st, gp)
            if found is not None and f >= found[0]:
                break
            for nd in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if nd[0] == -d[0] and nd[1] == -d[1]:
                    continue
                nc = (c[0] + nd[0], c[1] + nd[1])
                if not (0 <= nc[0] < cols and 0 <= nc[1] < rows):
                    continue
                if nc in blocked:
                    continue
                step = 1 + near.get(nc, 0) * 0.35
                if nd != d:
                    step += 7
                u = used.get(nc)
                if u:
                    step += 18 if nd in u or (-nd[0], -nd[1]) in u else 4
                ng = g + step
                ns = (nc, nd)
                if ng < best.get(ns, 1e9):
                    best[ns] = ng
                    came[ns] = (st, None)
                    h = abs(nc[0] - tx) + abs(nc[1] - ty)
                    h = max(0, h - (B.w + B.h) / CELL / 1.5)
                    heapq.heappush(heap, (ng + h, ng, ns))
        if found is None:
            pts = [(A.cx, A.cy), (B.cx, B.cy)]
            out[k] = dict(e, pts=_clip(pts, A, B), unrouted=True)
            continue
        path, st = [], found[1]
        while True:
            path.append(st)
            prev = came[st]
            if prev[0] == "S":
                start = prev[1]
                break
            st = prev[0]
        path.reverse()
        for idx, (c, d) in enumerate(path):
            used.setdefault(c, set()).add(d)
        pts = [start] + [pt(c) for c, _ in path] + [found[2]]
        pts = _ortho(pts)
        port_use[(a["id"], round(start[0]), round(start[1]))] += 1
        port_use[(b["id"], round(found[2][0]), round(found[2][1]))] += 1
        out[k] = dict(e, pts=pts)
    res["edges"] = [e for e in out if e]
    _labels(res, fs)


def _clip(pts, A, B):
    def edge(b, tx, ty):
        dx, dy = tx - b.cx, ty - b.cy
        s = min((b.w / 2) / abs(dx) if dx else 1e9, (b.h / 2) / abs(dy) if dy else 1e9)
        return b.cx + dx * s, b.cy + dy * s
    return [edge(A, *pts[1]), edge(B, *pts[0])]


def _ortho(pts):
    """Snap first/last legs so every segment is axis-aligned; merge collinear points."""
    pts = [tuple(p) for p in pts]
    if len(pts) >= 4:
        s, p = pts[0], pts[1]
        q = pts[2]
        if abs(s[0] - p[0]) < abs(s[1] - p[1]):
            # vertical exit: shift every leading point sharing x
            x0 = p[0]
            i = 1
            while i < len(pts) - 1 and abs(pts[i][0] - x0) < 1e-6:
                pts[i] = (s[0], pts[i][1])
                i += 1
        else:
            y0 = p[1]
            i = 1
            while i < len(pts) - 1 and abs(pts[i][1] - y0) < 1e-6:
                pts[i] = (pts[i][0], s[1])
                i += 1
        s, p = pts[-1], pts[-2]
        if abs(s[0] - p[0]) < abs(s[1] - p[1]):
            x0 = p[0]
            i = len(pts) - 2
            while i > 0 and abs(pts[i][0] - x0) < 1e-6:
                pts[i] = (s[0], pts[i][1])
                i -= 1
        else:
            y0 = p[1]
            i = len(pts) - 2
            while i > 0 and abs(pts[i][1] - y0) < 1e-6:
                pts[i] = (pts[i][0], s[1])
                i -= 1
    # re-orthogonalise any leftover diagonal
    fixed = [pts[0]]
    for p in pts[1:]:
        a = fixed[-1]
        if abs(a[0] - p[0]) > 0.5 and abs(a[1] - p[1]) > 0.5:
            fixed.append((p[0], a[1]))
        fixed.append(p)
    out = []
    for p in fixed:
        if out and abs(out[-1][0] - p[0]) < 0.5 and abs(out[-1][1] - p[1]) < 0.5:
            continue
        out.append(p)
    i = 1
    while i < len(out) - 1:
        a, b, c = out[i - 1], out[i], out[i + 1]
        if (abs(a[0] - b[0]) < 0.6 and abs(b[0] - c[0]) < 0.6) or \
                (abs(a[1] - b[1]) < 0.6 and abs(b[1] - c[1]) < 0.6):
            out.pop(i)
        else:
            i += 1
    return out


def _labels(res, fs):
    from fk_text import fsz
    boxes = [n["_box"].pad(2) for n in res["nodes"]]
    heads = []
    for g in res["groups"]:
        b = g["box"]
        heads.append(Box(b.x, b.y, width(str(g["label"]), fs * 0.9, True) + 18, 24))
    segs = []
    for e in res["edges"]:
        for p, q in zip(e["pts"], e["pts"][1:]):
            segs.append((id(e), Box(min(p[0], q[0]) - 1.5, min(p[1], q[1]) - 1.5,
                                    abs(p[0] - q[0]) + 3, abs(p[1] - q[1]) + 3)))
    placed = [e["label_box"].pad(2) for e in res["edges"] if e.get("_kept") and e.get("label_box")]
    lfs = fsz(fs * 0.84)
    for e in sorted(res["edges"], key=lambda x: -len(str(x.get("label") or ""))):
        if not e.get("label") or (e.get("_kept") and e.get("label_box")):
            continue
        best = None
        longest_ = max([width(q, lfs) for q in str(e["label"]).split()] + [0]) + 2
        for maxw in (170, 125, 92):
            lines = wrap(str(e["label"]), lfs, max(maxw, longest_))
            w = max(width(l, lfs) for l in lines) + 8
            h = len(lines) * lfs * 1.18 + 4
            pts = e["pts"]
            total = sum(abs(p[0] - q[0]) + abs(p[1] - q[1]) for p, q in zip(pts, pts[1:]))
            for p, q in zip(pts, pts[1:]):
                L = abs(p[0] - q[0]) + abs(p[1] - q[1])
                if L < 14:
                    continue
                horiz = abs(p[1] - q[1]) < 1
                for t in (.5, .4, .6, .3, .7, .2, .8, .1, .9):
                    cx = p[0] + (q[0] - p[0]) * t
                    cy = p[1] + (q[1] - p[1]) * t
                    options = [(cx, cy - h / 2 - 4), (cx, cy + h / 2 + 4), (cx, cy), (cx, cy - h / 2 - 16), (cx, cy + h / 2 + 16)] if horiz else \
                        [(cx + w / 2 + 5, cy), (cx - w / 2 - 5, cy), (cx, cy), (cx + w / 2 + 18, cy), (cx - w / 2 - 18, cy)]
                    for rank_o, (ox, oy) in enumerate(options):
                        bx = Box(ox - w / 2, oy - h / 2, w, h)
                        cost = rank_o * 3 + abs(t - .5) * 12 - min(L, 120) * 0.06 + (170 - maxw) * 0.05
                        for b in boxes:
                            cost += bx.overlap(b) * 2.2
                        for b in placed:
                            cost += bx.overlap(b) * 2.5
                        for b in heads:
                            cost += bx.overlap(b) * 1.0
                        for eid, sb in segs:
                            o = bx.overlap(sb)
                            if o:
                                cost += o * (0.15 if eid == id(e) else 0.5)
                        if bx.x < 2 or bx.y < 2 or bx.x + bx.w > res["w"] - 2 or bx.y + bx.h > res["h"] - 2:
                            cost += 260
                        if best is None or cost < best[0]:
                            best = (cost, bx, lines)
        if best:
            e["label_box"], e["label_lines"] = best[1], best[2]
            placed.append(best[1].pad(2))
