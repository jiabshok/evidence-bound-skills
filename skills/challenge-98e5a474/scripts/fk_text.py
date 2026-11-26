"""Text metrics, rich-text parsing and wrapping shared by the figure engine.

Only the standard library is required. Pillow is used when present to obtain
real glyph widths; otherwise a conservative estimate is used.
"""
import os
import re
import subprocess
from functools import lru_cache
from html import escape

FLOOR = [0.0]  # smallest allowed text size in user units (set per figure)


def fsz(size):
    return max(size, FLOOR[0])


FONT_STACK = "'DejaVu Sans','Noto Sans CJK SC','Noto Sans SC','Arial',sans-serif"

try:
    from PIL import ImageFont
except Exception:  # pragma: no cover - optional dependency
    ImageFont = None


@lru_cache(None)
def font_file(bold=False):
    names = ["DejaVu Sans:bold" if bold else "DejaVu Sans", "Arial", "sans"]
    for name in names:
        try:
            out = subprocess.run(["fc-match", "-f", "%{file}", name],
                                 capture_output=True, text=True, timeout=10).stdout
            if out and os.path.exists(out) and out.lower().endswith((".ttf", ".otf", ".ttc")):
                return out
        except Exception:
            pass
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/System/Library/Fonts/Supplemental/Arial.ttf"):
        if os.path.exists(path):
            return path
    return None


@lru_cache(None)
def _pil_font(bold):
    path = font_file(bold)
    if not (ImageFont and path):
        return None
    try:
        return ImageFont.truetype(path, 100)
    except Exception:
        return None


def is_cjk(ch):
    o = ord(ch)
    return 0x2E80 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF


@lru_cache(8192)
def _latin_width(text, bold):
    font = _pil_font(bold)
    if font is not None:
        try:
            return font.getlength(text) / 100.0
        except Exception:
            pass
    total = 0.0
    for ch in text:
        if ch in "il.,:;'|!jtf()[] ":
            total += 0.36
        elif ch in "mwMW@%":
            total += 0.92
        elif ch.isupper():
            total += 0.70
        else:
            total += 0.60
    return total * (1.08 if bold else 1.0)


def plain_width(text, size, bold=False):
    latin = "".join(c for c in text if not is_cjk(c))
    cjk = len(text) - len(latin)
    return (_latin_width(latin, bold) + cjk) * size


# --- rich text: *italic*  _{sub}  ^{sup} -------------------------------------
ITALIC = r"(?<![\w*])\*(?=[^\s*])[^*\n]{1,70}?(?<=[^\s*])\*(?![\w*])"
TOKEN = re.compile(r"(" + ITALIC + r"|_\{[^}]*\}|\^\{[^}]*\})")


UNIT_EXP = re.compile(r"(?:^|(?<=[\s(·/\[]))(m|cm|mm|km|L|mL|kg|g|mg|µg|μg|ng|s|min|h|hr|yr|ha|mol|mmol|kJ|kPa)([-−])([1-4])(?![\w.%-])")


def tidy_markup(t):
    """10^9, L^-1 and 'mg L-1' get proper superscripts."""
    t = re.sub(r"[_^]\{?([\u00b5\u03bc])\}?(?=[A-Za-z])", r"\1", str(t))
    t = re.sub(r"\^([-−+]?\d+)(?![}\d])", r"^{\1}", str(t))
    return UNIT_EXP.sub(lambda m: "%s^{\u2212%s}" % (m.group(1), m.group(3)), t)


def runs(text):
    """Split markup into (string, style) runs; style is '', 'i', 'sub', 'sup'."""
    text = tidy_markup(text)
    out = []
    for part in TOKEN.split(text):
        if not part:
            continue
        if part.startswith("*") and part.endswith("*") and len(part) > 2:
            out.append((part[1:-1], "i"))
        elif part.startswith("_{"):
            out.append((part[2:-1], "sub"))
        elif part.startswith("^{"):
            out.append((part[2:-1], "sup"))
        else:
            out.append((part, ""))
    return out


def strip_markup(text):
    return "".join(s for s, _ in runs(str(text)))


def width(text, size, bold=False):
    size = fsz(size)
    total = 0.0
    for s, style in runs(text):
        total += plain_width(s, max(size * 0.72, FLOOR[0]) if style in ("sub", "sup") else size, bold)
    return total


def wrap(text, size, max_w, bold=False):
    """Wrap on spaces (and between CJK characters); never drops characters."""
    lines = []
    for para in str(text).split("\n"):
        words = []
        for tok in re.findall(r"\s+|[^\s]+", para):
            if tok.isspace():
                words.append(" ")
                continue
            if any(is_cjk(c) for c in tok) and not TOKEN.search(tok):
                buf = ""
                for c in tok:
                    if is_cjk(c):
                        if buf:
                            words.append(buf)
                            buf = ""
                        words.append(c)
                    else:
                        buf += c
                if buf:
                    words.append(buf)
            else:
                words.append(tok)
        cur = ""
        for w in words:
            trial = cur + w
            if cur and width(trial.rstrip(), size, bold) > max_w:
                lines.append(cur.rstrip())
                cur = "" if w == " " else w
            else:
                cur = trial
            while width(cur, size, bold) > max_w and len(cur) > 1 and " " not in cur.strip() \
                    and not TOKEN.search(cur):
                cut = len(cur) - 1
                while cut > 1 and width(cur[:cut], size, bold) > max_w:
                    cut -= 1
                for sep in "-/_":
                    k = cur.rfind(sep, 1, cut)
                    if k > 1:
                        cut = k + 1
                        break
                lines.append(cur[:cut])
                cur = cur[cut:]
        lines.append(cur.strip())
    return [ln for ln in lines if ln] or [""]


def tspans(text, size):
    """Return SVG markup for one line of rich text."""
    out = []
    shift = 0.0
    for s, style in runs(text):
        dy = 0.0
        attrs = ""
        if style == "sub":
            dy, attrs = 0.25 * size, ' font-size="%.2f"' % max(size * 0.72, FLOOR[0])
        elif style == "sup":
            dy, attrs = -0.35 * size, ' font-size="%.2f"' % max(size * 0.72, FLOOR[0])
        elif style == "i":
            attrs = ' font-style="italic"'
        delta = dy - shift
        if abs(delta) > 1e-6:
            attrs += ' dy="%.2f"' % delta
        shift = dy
        out.append("<tspan%s>%s</tspan>" % (attrs, escape(s)) if attrs else escape(s))
    return "".join(out)


def line_markup(text, x, y, size, anchor, bold):
    """One visual line. Mixed-style lines get explicit run positions so that every
    renderer (browser, cairo, LibreOffice, Inkscape) places them identically."""
    rs = runs(text)
    if len(rs) == 1 and rs[0][1] == "":
        return '<tspan x="%.2f" y="%.2f">%s</tspan>' % (x, y, escape(rs[0][0]))
    total = width(text, size, bold)
    cx = x - (total / 2 if anchor == "middle" else total if anchor == "end" else 0)
    out = []
    for s, style in rs:
        fs, yy, attrs = size, y, ""
        if style == "sub":
            fs, yy = max(size * 0.72, FLOOR[0]), y + 0.25 * size
        elif style == "sup":
            fs, yy = max(size * 0.72, FLOOR[0]), y - 0.35 * size
        elif style == "i":
            attrs = ' font-style="italic"'
        if fs != size:
            attrs += ' font-size="%.2f"' % fs
        lead = len(s) - len(s.lstrip(" "))
        cx += plain_width(" " * lead, fs, bold)
        body = s.strip(" ")
        out.append('<tspan x="%.2f" y="%.2f" text-anchor="start"%s>%s</tspan>' % (cx, yy, attrs, escape(body)))
        cx += plain_width(s[lead:], fs, bold)
    return "".join(out)


def svg_text(x, y, lines, size, anchor="middle", bold=False, fill="#1b1f24",
             ident=None, extra="", line_h=1.22):
    """Multi-line live text. y is the vertical centre of the block."""
    size = fsz(size)
    n = len(lines)
    top = y - (n - 1) * size * line_h / 2 + size * 0.35
    mixed = any(len(runs(l)) > 1 or runs(l)[0][1] for l in lines if l)
    a = "start" if mixed else anchor
    out = ['<text%s x="%.2f" y="%.2f" font-size="%.2f" text-anchor="%s"%s fill="%s"%s>' % (
        ' id="%s"' % ident if ident else "", x, top, size, a,
        ' font-weight="700"' if bold else "", fill, extra)]
    for i, ln in enumerate(lines):
        yy = top + i * size * line_h
        if mixed and len(runs(ln)) == 1 and runs(ln)[0][1] == "":
            total = width(ln, size, bold)
            xx = x - (total / 2 if anchor == "middle" else total if anchor == "end" else 0)
            out.append('<tspan x="%.2f" y="%.2f">%s</tspan>' % (xx, yy, escape(ln)))
        else:
            out.append(line_markup(ln, x, yy, size, anchor, bold))
    out.append("</text>")
    return "".join(out)
