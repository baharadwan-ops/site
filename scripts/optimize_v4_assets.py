#!/usr/bin/env python3
"""Optimize V4 gallery/hero images and self-host IBM Plex Sans Arabic."""
from __future__ import annotations
import html, json, os, re, urllib.parse, urllib.request
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "index.html"
OUT = ROOT / "assets" / "optimized"
FONTS = ROOT / "assets" / "fonts"

def attr(tag, name):
    m = re.search(r"\b" + re.escape(name) + r"\s*=\s*([\"'])(.*?)\1", tag, re.I | re.S)
    return html.unescape(m.group(2)) if m else None

def set_attr(tag, name, value):
    pat = re.compile(r"\b" + re.escape(name) + r"\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
    new = f'{name}="{html.escape(str(value), quote=True)}"'
    if pat.search(tag):
        return pat.sub(new, tag, count=1)
    return tag[:-1] + " " + new + ("/>" if tag.endswith("/>") else ">")

def local_source(url):
    rel = urllib.parse.unquote(url).split("?", 1)[0].split("#", 1)[0]
    p = (ROOT / rel).resolve()
    if not p.is_file() or ROOT.resolve() not in p.parents:
        raise FileNotFoundError(f"Missing source image: {rel}")
    return p, rel

def variants(source, outdir, stem, widths, quality):
    outdir.mkdir(parents=True, exist_ok=True)
    result = []
    with Image.open(source) as raw:
        im = ImageOps.exif_transpose(raw)
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        ow, oh = im.size
        seen = set()
        for wanted in widths:
            w = min(wanted, ow)
            if w in seen:
                continue
            seen.add(w)
            h = max(1, round(oh * w / ow))
            img = im.copy()
            if w != ow:
                img.thumbnail((w, h), Image.Resampling.LANCZOS)
            target = outdir / f"{stem}-{img.width}.webp"
            img.save(target, "WEBP", quality=quality, method=6)
            result.append({"path": target.relative_to(ROOT).as_posix(),
                           "width": img.width, "height": img.height,
                           "bytes": target.stat().st_size})
        return result, ow, oh

def font_assets():
    css_url = "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;700&display=swap"
    req = urllib.request.Request(css_url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/css,*/*;q=0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        css = r.read().decode("utf-8")
    FONTS.mkdir(parents=True, exist_ok=True)
    faces, files, regular_arabic = [], [], None
    for m in re.finditer(r"@font-face\s*\{([^}]+)\}", css, re.I | re.S):
        block = m.group(1)
        wm = re.search(r"font-weight\s*:\s*(\d+)", block, re.I)
        sm = re.search(r"src\s*:\s*url\((['\"]?)(https://[^) '\"]+)\1\)\s*format\(['\"]woff2['\"]\)", block, re.I)
        um = re.search(r"unicode-range\s*:\s*([^;]+)", block, re.I)
        if not (wm and sm and um):
            continue
        weight = int(wm.group(1))
        if weight not in (400, 700):
            continue
        urange = um.group(1).strip()
        subset = "arabic" if re.search(r"U\+0?600", urange, re.I) else ("latin" if re.search(r"U\+0000", urange, re.I) else None)
        if not subset:
            continue
        path = FONTS / f"ibm-plex-sans-arabic-{subset}-{weight}.woff2"
        request = urllib.request.Request(sm.group(2), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=30) as r:
            path.write_bytes(r.read())
        rel = path.relative_to(ROOT).as_posix()
        faces.append("@font-face{" +
            'font-family:"IBM Plex Sans Arabic";font-style:normal;' +
            f"font-weight:{weight};font-display:swap;" +
            f'src:url("{rel}") format("woff2");unicode-range:{urange};' + "}")
        files.append({"path": rel, "subset": subset, "weight": weight, "bytes": path.stat().st_size})
        if subset == "arabic" and weight == 400:
            regular_arabic = rel
    if not any(x["subset"] == "arabic" for x in files):
        raise RuntimeError("Google Fonts did not provide an Arabic IBM Plex Sans Arabic WOFF2 subset.")
    if not regular_arabic:
        regular_arabic = next(x["path"] for x in files if x["subset"] == "arabic")
    return "".join(faces), regular_arabic, files

def main():
    doc = HTML.read_text(encoding="utf-8")
    manifest = {"images": [], "fonts": [], "notes": []}

    # Fix accessible name and remove the invalid explicit group role from native article slides.
    doc = doc.replace('aria-label="بهاء رضوان - الصفحة الرئيسية"',
                      'aria-label="BAHA RADWAN - الصفحة الرئيسية"')
    doc = re.sub(r'(<article\b[^>]*?)\s+role="group"([^>]*>)', r"\1\2", doc, flags=re.I)

    cache = {}
    count = {"img_tags": 0}
    def replace_img(m):
        tag = m.group(0)
        src = attr(tag, "src")
        if not src or src.startswith(("data:", "https://", "http://")):
            return tag
        count["img_tags"] += 1
        decoded = urllib.parse.unquote(src)
        before = doc[max(0, m.start()-240):m.start()]
        hero = decoded.endswith("1 (4).webp") or ("hero-visual" in before and attr(tag, "fetchpriority") == "high")
        source, rel = local_source(decoded)
        if hero:
            outdir, stem, widths, quality = OUT / "hero", "hero-main", [720, 1040], 84
        elif rel.startswith("img/"):
            outdir, stem, widths, quality = OUT / "img", Path(rel).stem, [640, 1024], 80
        elif rel.startswith("al-Adha/"):
            outdir, stem, widths, quality = OUT / "al-Adha", Path(rel).stem, [640, 1024], 80
        else:
            stem = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(rel).stem).strip("-").lower() or "upload"
            outdir, widths, quality = OUT / "uploads", [640, 1024], 80
        key = (rel, hero)
        if key not in cache:
            vs, ow, oh = variants(source, outdir, stem, widths, quality)
            cache[key] = {"source": rel, "variants": vs, "hero": hero, "original_width": ow, "original_height": oh}
        item = cache[key]
        vs = item["variants"]
        srcset = ", ".join(f'{v["path"]} {v["width"]}w' for v in vs)
        sizes = "100vw" if not hero else "(max-width: 768px) 100vw, 520px"
        tag = set_attr(tag, "src", vs[0]["path"])
        tag = set_attr(tag, "srcset", srcset)
        tag = set_attr(tag, "sizes", sizes)
        tag = set_attr(tag, "width", item["original_width"])
        tag = set_attr(tag, "height", item["original_height"])
        tag = set_attr(tag, "decoding", "async")
        if hero:
            tag = set_attr(tag, "loading", "eager")
            tag = set_attr(tag, "fetchpriority", "high")
        else:
            tag = set_attr(tag, "loading", "lazy")
        return tag

    doc = re.sub(r"<img\b[^>]*>", replace_img, doc, flags=re.I | re.S)
    hero = next((x for x in cache.values() if x["hero"]), None)
    if not hero:
        raise RuntimeError("Approved hero image 1 (4).webp was not found.")
    hv = hero["variants"]
    hero_srcset = ", ".join(f'{v["path"]} {v["width"]}w' for v in hv)
    hero_sizes = "(max-width: 768px) 100vw, 520px"
    preload = (f'<link rel="preload" as="image" href="{hv[0]["path"]}" '
               f'imagesrcset="{hero_srcset}" imagesizes="{hero_sizes}" fetchpriority="high"/>')
    doc, n = re.subn(r'<link\b[^>]*rel=["\']preload["\'][^>]*>', preload, doc, count=1, flags=re.I)
    if not n:
        doc = doc.replace("</head>", preload + "\n</head>", 1)

    font_css, font_preload, fonts = font_assets()
    doc = re.sub(r'<link\b[^>]*fonts\.googleapis\.com[^>]*>', "", doc, flags=re.I)
    doc = re.sub(r'<link\b[^>]*fonts\.gstatic\.com[^>]*>', "", doc, flags=re.I)
    doc = doc.replace("</head>",
        f'<link rel="preload" href="{font_preload}" as="font" type="font/woff2" crossorigin/>\n</head>', 1)

    sm = re.search(r"<style\b[^>]*>(.*?)</style>", doc, re.I | re.S)
    if not sm:
        raise RuntimeError("Inline style block not found.")
    css = font_css + sm.group(1)
    css += "\n[data-theme=dark] .btn-primary{background:#7155a8;color:#fff;}[data-theme=dark] .btn-primary:hover{background:#62478f;color:#fff;}\n"
    import rcssmin
    css = rcssmin.cssmin(css)
    doc = doc[:sm.start(1)] + css + doc[sm.end(1):]
    HTML.write_text(doc, encoding="utf-8")

    manifest["images"] = list(cache.values())
    manifest["fonts"] = fonts
    manifest["html_image_tags"] = count["img_tags"]
    manifest["notes"] = [
        "Responsive WebP variants generated for all local gallery images and the approved 1 (4).webp hero image.",
        "IBM Plex Sans Arabic WOFF2 subsets are self-hosted; Google Fonts CSS and font CDN requests are removed.",
        "The hero image preload uses the same srcset and high fetch priority as the hero image element.",
        "The visible BAHA RADWAN brand text matches its accessible label; invalid role=group was removed from article slides.",
        "Dark-mode primary button background now provides at least 4.5:1 contrast with white text.",
        "GitHub Pages cache headers cannot be set by this build and must be validated on the deployed site."
    ]
    p = OUT / "image-optimization-manifest-v4.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "image_sources": len(cache),
        "img_tags": count["img_tags"],
        "webp_variants": sum(len(x["variants"]) for x in cache.values()),
        "webp_bytes": sum(v["bytes"] for x in cache.values() for v in x["variants"]),
        "font_files": len(fonts),
        "font_bytes": sum(x["bytes"] for x in fonts),
        "hero_variants": hv
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
