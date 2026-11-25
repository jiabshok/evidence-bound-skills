"""Export SVG to PNG/PDF (and TIFF/EPS on request) and inspect the real files."""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _run(cmd, timeout=60):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _chromium(svg, png, pdf, w_mm, h_mm, dpi):
    from playwright.sync_api import sync_playwright
    text = open(svg, encoding="utf-8").read()
    text = text[text.index("<svg"):]
    html = ("<!doctype html><html><head><meta charset='utf-8'><style>@page{size:%.3fmm %.3fmm;margin:0}"
            "html,body{margin:0;padding:0;background:#fff}svg{display:block;width:%.3fmm;height:%.3fmm}</style></head><body>%s</body></html>") % (
        w_mm, h_mm, w_mm, h_mm, text)
    px_w, px_h = int(round(w_mm / 25.4 * 96)), int(round(h_mm / 25.4 * 96))
    with sync_playwright() as pw:
        b = None
        for kw in ({}, {"executable_path": shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("chromium-browser") or "/nonexistent"}):
            try:
                b = pw.chromium.launch(args=["--no-sandbox", "--disable-gpu"], timeout=25000, **kw)
                break
            except Exception:
                continue
        if b is None:
            raise RuntimeError("no launchable chromium")
        ctx = b.new_context(viewport={"width": px_w, "height": px_h}, device_scale_factor=dpi / 96.0)
        page = ctx.new_page()
        page.set_content(html, wait_until="load", timeout=20000)
        page.screenshot(path=png, clip={"x": 0, "y": 0, "width": px_w, "height": px_h})
        page.pdf(path=pdf, width="%.3fmm" % w_mm, height="%.3fmm" % (h_mm + 0.2), print_background=True, page_ranges="1")
        ver = b.version
        b.close()
    return "playwright chromium " + ver


def _cairosvg(svg, png, pdf, w_mm, h_mm, dpi):
    import cairosvg
    cairosvg.svg2pdf(url=svg, write_to=pdf)
    cairosvg.svg2png(url=svg, write_to=png, output_width=int(round(w_mm / 25.4 * dpi)), background_color="white")
    return "cairosvg " + getattr(cairosvg, "__version__", "?")


def _rsvg(svg, png, pdf, w_mm, h_mm, dpi):
    if not shutil.which("rsvg-convert"):
        raise RuntimeError("rsvg-convert missing")
    r = _run(["rsvg-convert", "-w", str(int(w_mm / 25.4 * dpi)), "-b", "white", "-o", png, svg])
    r2 = _run(["rsvg-convert", "-f", "pdf", "-o", pdf, svg])
    if r.returncode or r2.returncode:
        raise RuntimeError(r.stderr + r2.stderr)
    return "rsvg-convert"


def _inkscape(svg, png, pdf, w_mm, h_mm, dpi):
    if not shutil.which("inkscape"):
        raise RuntimeError("inkscape missing")
    _run(["inkscape", svg, "--export-type=png", "--export-dpi=%d" % round(dpi), "--export-filename=" + png], 90)
    _run(["inkscape", svg, "--export-type=pdf", "--export-filename=" + pdf], 90)
    return "inkscape"


def _soffice(svg, png, pdf, w_mm, h_mm, dpi):
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        raise RuntimeError("soffice missing")
    d = tempfile.mkdtemp()
    _run([exe, "--headless", "--convert-to", "pdf", "--outdir", d, svg], 120)
    out = os.path.join(d, os.path.splitext(os.path.basename(svg))[0] + ".pdf")
    shutil.copy(out, pdf)
    return "libreoffice draw"


def export(svg, stem, w_mm, h_mm, dpi=300, extra=()):
    png, pdf = stem + ".png", stem + ".pdf"
    log, used = [], None
    for fn in (_chromium, _cairosvg, _rsvg, _inkscape, _soffice):
        for p in (png, pdf):
            if os.path.exists(p):
                os.remove(p)
        try:
            used = fn(svg, png, pdf, w_mm, h_mm, dpi)
        except Exception as exc:
            log.append("%s: %s" % (fn.__name__.strip("_"), str(exc).splitlines()[0][:140] if str(exc) else type(exc).__name__))
            used = None
            continue
        if os.path.exists(pdf) and not os.path.exists(png) and shutil.which("pdftoppm"):
            _run(["pdftoppm", "-r", str(int(round(dpi))), "-png", "-singlefile", pdf, stem])
        if os.path.exists(png) and os.path.getsize(png) > 800 and os.path.exists(pdf) and os.path.getsize(pdf) > 500:
            break
        log.append("%s: produced no usable file" % fn.__name__.strip("_"))
        used = None
    try:
        from PIL import Image
        im = Image.open(png).convert("RGB")
        im.save(png, dpi=(dpi, dpi))
        for f in extra:
            f = f.lower().lstrip(".")
            if f in ("tif", "tiff"):
                im.save(stem + ".tiff", dpi=(dpi, dpi), compression="tiff_lzw")
            elif f in ("jpg", "jpeg"):
                im.save(stem + ".jpg", dpi=(dpi, dpi), quality=95)
    except Exception as exc:
        log.append("png metadata: %s" % exc)
    if "eps" in [f.lower().lstrip(".") for f in extra] and shutil.which("pdftops") and os.path.exists(pdf):
        _run(["pdftops", "-eps", pdf, stem + ".eps"])
    files = [stem + e for e in (".png", ".pdf", ".tiff", ".jpg", ".eps") if os.path.exists(stem + e)]
    return {"renderer": used, "fallback_log": log, "files": files}


def inspect_png(png):
    try:
        from PIL import Image, ImageChops
        im = Image.open(png)
        rgb = im.convert("RGB")
        bg = Image.new("RGB", rgb.size, rgb.getpixel((2, 2)))
        box = ImageChops.difference(rgb, bg).getbbox()
        small = rgb.resize((max(1, rgb.width // 4), max(1, rgb.height // 4)))
        cols = small.getcolors(1 << 22) or []
        ink = 1 - max((c for c, _ in cols), default=0) / float(small.width * small.height)
        m = None
        if box:
            m = [box[0], box[1], rgb.width - box[2], rgb.height - box[3]]
        return {"pixels": [rgb.width, rgb.height], "dpi": [round(float(x)) for x in im.info.get("dpi", (0, 0))],
                "ink_fraction": round(ink, 4), "content_margins_px": m,
                "touches_edge": bool(m and min(m) < 3), "blank": box is None}
    except Exception as exc:
        return {"error": str(exc)}


def inspect_pdf(pdf, labels):
    out = {}
    try:
        r = _run(["pdfinfo", pdf])
        for ln in r.stdout.splitlines():
            if ln.startswith(("Pages", "Page size")):
                out[ln.split(":")[0].strip().lower().replace(" ", "_")] = ln.split(":", 1)[1].strip()
        f = _run(["pdffonts", pdf]).stdout.splitlines()[2:]
        out["fonts"] = len(f)
        out["fonts_not_embedded"] = [x.split()[0] for x in f if len(x.split()) > 5 and " no " in (" " + " ".join(x.split()[-5:-2]) + " ") and x.split()[-5] == "no"]
        txt = _run(["pdftotext", "-layout", pdf, "-"]).stdout
        norm = lambda t: re.sub(r"[\s­−-]+", "", t)
        blob = norm(txt) + norm(_run(["pdftotext", "-raw", pdf, "-"]).stdout)
        want = [x for x in labels if x.strip()]
        lost = []
        for lab in want:
            words = [norm(w) for w in re.split(r"\s+", lab) if norm(w)]
            if not all(w in blob for w in words):
                lost.append(lab)
        out["labels_checked"] = len(want)
        out["labels_not_found_as_text"] = lost[:20]
    except Exception as exc:
        out["error"] = str(exc)
    return out


def inspect_gray(png):
    """Save a grayscale preview used for print/CVD checking."""
    try:
        from PIL import Image
        p = png[:-4] + "_grayscale_preview.png"
        im = Image.open(png).convert("L")
        im.thumbnail((1400, 1400))
        im.save(p)
        return p
    except Exception:
        return None
