"""Delimited/JSON table loading."""
import csv
import io
import json
import math
from collections import OrderedDict


def xlsx_sheets(path):
    """{sheet name: rows of strings} using only the standard library (cached values, no formulas)."""
    import re
    import zipfile
    import xml.etree.ElementTree as ET
    M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(M + "si"):
            shared.append("".join(t.text or "" for t in si.iter(M + "t")))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = OrderedDict()
    for sh in ET.fromstring(z.read("xl/workbook.xml")).iter(M + "sheet"):
        tgt = rels[sh.get(R)].lstrip("/")
        tgt = tgt if tgt.startswith("xl/") else "xl/" + tgt
        rows = []
        for row in ET.fromstring(z.read(tgt)).iter(M + "row"):
            cells = {}
            for c in row.findall(M + "c"):
                col = 0
                for ch in re.match(r"[A-Z]+", c.get("r", "A")).group(0):
                    col = col * 26 + ord(ch) - 64
                v, t = c.find(M + "v"), c.get("t")
                if t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(M + "t"))
                elif v is None:
                    val = ""
                else:
                    val = shared[int(v.text)] if t == "s" else v.text
                cells[col - 1] = (val or "").strip()
            rows.append([cells.get(k, "") for k in range(max(cells) + 1 if cells else 0)])
        out[sh.get("name")] = rows
    return out


def sheet_blocks(rows):
    """Split a worksheet into tables: blank rows and one-cell title rows separate blocks."""
    blocks, cur, title = [], [], ""
    for r in list(rows) + [[]]:
        filled = [c for c in r if str(c).strip()]
        if len(filled) <= 1:
            if cur:
                blocks.append((title, cur))
                cur = []
                title = ""
            if filled:
                title = filled[0]
            continue
        cur.append(r)
    out = []
    for title, b in blocks:
        wide = max(len(r) for r in b)
        head = b[0]
        if sum(1 for c in head if num(c) is not None) > len([c for c in head if c]) / 2:  # no header row: numeric first line
            cols, body = ["col%d" % (k + 1) for k in range(wide)], b
        else:
            cols, body = [(head[k] if k < len(head) and head[k] else "col%d" % (k + 1)) for k in range(wide)], b[1:]
        seen = {}
        for k, c in enumerate(cols):
            seen[c] = seen.get(c, 0) + 1
            if seen[c] > 1:
                cols[k] = "%s (%d)" % (c, seen[c])
        out.append((title, cols, [{c: (r[k] if k < len(r) else "") for k, c in enumerate(cols)} for r in body]))
    if not out and rows:
        one = [r for r in rows if any(str(c).strip() for c in r)]
        if one:
            cols = [c or "col%d" % (k + 1) for k, c in enumerate(one[0])]
            out.append(("", cols, [{c: (r[k] if k < len(r) else "") for k, c in enumerate(cols)} for r in one[1:]]))
    return out


def load_table(path):
    if ".xlsx" in path.lower():
        path, _, sheet = path.partition("!")
        sh = xlsx_sheets(path)
        sheet, _, bk = sheet.partition("@")
        name = sheet or max(sh, key=lambda k: len(sh[k]))
        if name not in sh:
            raise ValueError("sheet '%s' not in %s; sheets: %s" % (name, path, list(sh)))
        bl = sheet_blocks(sh[name])
        if not bl:
            return [], []
        if bk:
            if not bk.isdigit() or not 1 <= int(bk) <= len(bl):
                raise ValueError("block '%s' not in sheet %s; it has %d table block(s)" % (bk, name, len(bl)))
            b = bl[int(bk) - 1]
        else:
            b = max(bl, key=lambda t: len(t[1]) * (len(t[2]) + 1))
        return b[1], b[2]
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if path.lower().endswith(".json"):
        d = json.loads(text)
        if isinstance(d, dict):
            for v in d.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    d = v
                    break
        if isinstance(d, list) and d and isinstance(d[0], dict):
            cols = list(OrderedDict((k, 1) for r in d for k in r))
            return cols, [{k: ("" if r.get(k) is None else str(r.get(k))) for k in cols} for r in d]
        raise ValueError("JSON file holds no list of records: " + path)
    lines = text.splitlines(True)
    skip = 0
    while skip < len(lines) and lines[skip].lstrip().startswith("#"):
        skip += 1
    body = "".join(lines[skip:])
    first = lines[skip] if skip < len(lines) else ""
    delim = "\t" if first.count("\t") > first.count(",") else (";" if first.count(";") > first.count(",") else ",")
    rd = csv.reader(io.StringIO(body), delimiter=delim)
    rows = [r for r in rd if any(c.strip() for c in r)]
    if not rows:
        return [], []
    cols = [c.strip() for c in rows[0]]
    out = []
    for r in rows[1:]:
        out.append({c: (r[k].strip() if k < len(r) else "") for k, c in enumerate(cols)})
    return cols, out


def num(s):
    s = str(s).strip().replace("−", "-").replace(",", "")
    if s in ("", "NA", "N/A", "nan", "NaN", "null", "None", "-", "--", "ND"):
        return None
    try:
        v = float(s)
        return v if math.isfinite(v) else None
    except ValueError:
        return None


