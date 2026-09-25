"""Arabic-safe graphics rendered with Pillow (ffmpeg drawtext breaks Arabic shaping)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

W, H = 1080, 1920
def _raqm_ok():
    try:  # on Windows, raqm can be present without FriBiDi -> broken RTL; use the reshaper fallback then
        return bool(features.check("raqm")) and bool(features.check("fribidi"))
    except Exception:
        return bool(features.check("raqm"))


RAQM = _raqm_ok()

try:  # fallback shaping when libraqm is missing
    import arabic_reshaper
    from bidi.algorithm import get_display
except ImportError:  # pragma: no cover
    arabic_reshaper = None


def _is_rtl(t):
    return any("؀" <= ch <= "ۿ" for ch in t)


def _shape(t):
    if RAQM or not _is_rtl(t) or arabic_reshaper is None:
        return t
    return get_display(arabic_reshaper.reshape(t))


FONT_CANDIDATES = [
    "fonts/Cairo-Bold.ttf",                                     # put any Arabic .ttf here to override
    "/usr/share/fonts/truetype/noto/NotoKufiArabic-Bold.ttf",   # Linux
    "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/tahomabd.ttf", "C:/Windows/Fonts/segoeuib.ttf",  # Windows
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Unicode.ttf",           # macOS
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def resolve_font(path):
    for p in [path, *FONT_CANDIDATES]:
        if p and Path(p).exists():
            return p
    raise FileNotFoundError("No Arabic font found: sudo apt install fonts-noto-core")


def font(path, size):
    path = resolve_font(path)
    kw = {"layout_engine": ImageFont.Layout.RAQM} if RAQM else {}
    return ImageFont.truetype(path, size, **kw)


def _kw(t):
    return {"direction": "rtl", "language": "ar"} if RAQM and _is_rtl(t) else {}


def text_size(draw, t, f, stroke=0):
    b = draw.textbbox((0, 0), _shape(t), font=f, stroke_width=stroke, **_kw(t))
    return b[2] - b[0], b[3] - b[1], b


def wrap(draw, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if text_size(draw, test, f)[0] <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


_FALLBACK = {"…": ["...", "،"], "•": ["|", "-", "،"], "!": ["!", ""], "?": ["?", "؟"]}


def _has_glyph(f, ch):
    """False when the font would draw the 'missing glyph' box for ch."""
    def render(c):
        img = Image.new("L", (f.size * 3, f.size * 2))
        ImageDraw.Draw(img).text((f.size // 2, 0), c, font=f, fill=255)
        return img.tobytes()
    try:
        return render(ch) != render("\ue000")
    except Exception:
        return True


def fix_glyphs(text, f):
    """Arabic-only fonts (e.g. Noto Kufi) lack … and • -> use the first replacement the font can draw."""
    for ch, alts in _FALLBACK.items():
        if ch in text and not _has_glyph(f, ch):
            alt = next((a for a in alts if all(_has_glyph(f, c) for c in a)), " ")
            text = text.replace(ch, alt)
    return text


def draw_block(draw, text, f, cy, max_w=W - 140, fill="white", stroke=6, stroke_fill="black",
               box=None, pad=34, line_gap=14):
    """Draws centred multi-line text around vertical centre cy. Returns (top,bottom)."""
    text = fix_glyphs(text, f)
    lines = wrap(draw, text, f, max_w)
    sizes = [text_size(draw, ln, f, stroke) for ln in lines]
    lh = max(s[1] for s in sizes)
    total = lh * len(lines) + line_gap * (len(lines) - 1)
    top = cy - total // 2
    if box:
        bw = max(s[0] for s in sizes) + pad * 2
        draw.rounded_rectangle([(W - bw) // 2, top - pad, (W + bw) // 2, top + total + pad], radius=28, fill=box)
    y = top
    for ln, (w, h, b) in zip(lines, sizes):
        draw.text(((W - w) // 2 - b[0], y - b[1]), _shape(ln), font=f, fill=fill,
                  stroke_width=stroke, stroke_fill=stroke_fill, **_kw(ln))
        y += lh + line_gap
    return top, top + total


def hook_overlay(text, font_path, out, accent=(229, 9, 20)):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = font(font_path, 78)
    top, bottom = draw_block(d, text, f, cy=520, box=(0, 0, 0, 150), stroke=5)
    d.rectangle([W // 2 - 90, bottom + 46, W // 2 + 90, bottom + 54], fill=accent + (255,))
    img.save(out)
    return out


def brand_overlay(domain, label, font_path, out, accent=(229, 9, 20)):
    """Always-on: small drama/episode label on top, domain pill at bottom."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if label:
        f = font(font_path, 40)
        draw_block(d, label, f, cy=250, box=(0, 0, 0, 120), stroke=2, pad=18)
    if not domain:
        img.save(out)
        return out
    f = font(font_path, 44)
    w, h, _ = text_size(d, domain, f)
    y = H - 590  # above TikTok/Reels caption & buttons safe zone
    d.rounded_rectangle([(W - w) // 2 - 44, y - 26, (W + w) // 2 + 44, y + h + 34], radius=40, fill=accent + (235,))
    draw_block(d, domain, f, cy=y + h // 2 + 4, stroke=0)
    img.save(out)
    return out


def end_card(frame_path, lines, domain, font_path, out, accent=(229, 9, 20)):
    """Blurred cliffhanger frame + CTA."""
    bg = Image.open(frame_path).convert("RGB")
    # fill 9:16
    s = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * s) + 1, int(bg.height * s) + 1))
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
    bg = bg.filter(ImageFilter.GaussianBlur(28))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 150))
    img = Image.alpha_composite(bg.convert("RGBA"), dark)
    d = ImageDraw.Draw(img)
    q, cta, title = lines
    draw_block(d, q, font(font_path, 84), cy=640, stroke=6)
    draw_block(d, cta, font(font_path, 60), cy=900, stroke=3)
    if domain:
        f = font(font_path, 84)
        w, h, _ = text_size(d, domain, f)
        d.rounded_rectangle([(W - w) // 2 - 50, 1080, (W + w) // 2 + 50, 1080 + h + 80], radius=50, fill=accent + (255,))
        draw_block(d, domain, f, cy=1080 + (h + 80) // 2 + 4, stroke=0)
    if title:
        draw_block(d, title, font(font_path, 52), cy=1400, stroke=3, fill=(255, 220, 120))
    img.convert("RGB").save(out, quality=92)
    return out


def cover(frame_path, text, font_path, out):
    img = Image.open(frame_path).convert("RGB").resize((W, H))
    ov = Image.open(hook_overlay(text, font_path, str(Path(out).with_suffix(".tmp.png"))))
    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    img.save(out, quality=90)
    Path(out).with_suffix(".tmp.png").unlink(missing_ok=True)
    return out
