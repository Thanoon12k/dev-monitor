"""Render a 1080x1350 Arabic poster for a Viraliq post.

    python tools/viraliq/poster.py spec.json out.png

spec: {"kind": "trend|news|course|tip|debate", "badge": "...", "title": "...",
       "hook": "...", "points": ["...", ...], "footer": "..."}
Needs Pillow built with libraqm (for Arabic shaping); falls back to
arabic_reshaper + python-bidi when raqm is missing.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "fonts", "Cairo.ttf")
W, H, PAD = 1080, 1350, 80
RAQM = features.check("raqm")
BRAND = os.environ.get("VIRALIQ_BRAND", "Golden Code · الكود الذهبي")

# Golden Code identity: near-black with warm gold, as on the page cover.
BG_TOP, BG_BOTTOM = (10, 8, 5), (38, 28, 10)
GOLD_HI, GOLD_LO = (250, 214, 110), (200, 140, 24)
GOLD = (239, 193, 76)
LOGO = os.path.join(HERE, "assets", "logo.png")
BADGES = {"trend": "ترند اليوم", "news": "خبر تقني", "course": "دورة مجانية",
          "tip": "نصيحة اليوم", "debate": "جدل السوشيال"}


def font(size, weight=700):
    f = ImageFont.truetype(FONT, size, layout_engine=ImageFont.Layout.RAQM if RAQM else ImageFont.Layout.BASIC)
    try:
        f.set_variation_by_axes([weight, 0])
    except OSError:
        pass
    return f


def shape(text):
    if RAQM:
        return text
    import arabic_reshaper
    from bidi.algorithm import get_display
    return get_display(arabic_reshaper.reshape(text))


def tlen(f, text):
    return f.getlength(shape(text), direction="rtl") if RAQM else f.getlength(shape(text))


def wrap(text, f, width):
    lines, cur = [], ""
    for word in text.split():
        cand = (cur + " " + word).strip()
        if cur and tlen(f, cand) > width:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def rtl(d, x, y, text, f, fill):
    """Draw text right-aligned so its right edge sits at x."""
    kw = {"direction": "rtl"} if RAQM else {}
    d.text((x, y), shape(text), font=f, fill=fill, anchor="ra", **kw)


def fit(text, width, max_lines, start, low):
    size = start
    while size > low:
        lines = wrap(text, font(size, 900), width)
        if len(lines) <= max_lines:
            return size, lines
        size -= 4
    return low, wrap(text, font(low, 900), width)[:max_lines]


def gradient(size, c1, c2):
    w, h = size
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    return img


def gold_text(img, x, y, text, f):
    """Right-aligned text at x filled with the vertical gold gradient."""
    mask = Image.new("L", img.size, 0)
    kw = {"direction": "rtl"} if RAQM else {}
    ImageDraw.Draw(mask).text((x, y), shape(text), font=f, fill=255, anchor="ra", **kw)
    box = mask.getbbox()
    if box:
        fill = gradient((box[2] - box[0], box[3] - box[1]), GOLD_HI, GOLD_LO)
        img.paste(fill, box[:2], mask.crop(box))


def logo(size):
    im = Image.open(LOGO).convert("RGB").resize((size, size), Image.LANCZOS)
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).ellipse((0, 0, size - 1, size - 1), fill=255)
    return im, m


def render(spec, out):
    img = gradient((W, H), BG_TOP, BG_BOTTOM)

    # warm glow + faint grid + code glyphs, like the cover
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((-300, -250, 600, 600), fill=GOLD + (60,))
    g.ellipse((500, 950, 1400, 1700), fill=GOLD + (40,))
    glow = glow.filter(ImageFilter.GaussianBlur(140))
    img.paste(glow, (0, 0), glow)
    d = ImageDraw.Draw(img, "RGBA")
    for x in range(0, W, 60):
        d.line([(x, 0), (x, H)], fill=GOLD + (10,))
    for y in range(0, H, 60):
        d.line([(0, y), (W, y)], fill=GOLD + (10,))
    marks = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    md, mono = ImageDraw.Draw(marks), font(64, 800)
    for txt, xy in (("</>", (440, 88)), ("#", (40, 470)), ("AI", (80, 1100)), ("fn", (930, 1100))):
        md.text(xy, txt, font=mono, fill=GOLD + (28,))
    img.paste(marks, (0, 0), marks)
    d = ImageDraw.Draw(img, "RGBA")

    right = W - PAD
    # logo (top-left) and gold-outlined pill with green dot (top-right)
    lg, lm = logo(96)
    img.paste(lg, (PAD, 70), lm)
    d.ellipse((PAD - 3, 67, PAD + 99, 169), outline=GOLD + (140,), width=3)
    bf = font(34, 800)
    label = spec.get("badge") or BADGES.get(spec.get("kind"), BADGES["trend"])
    bw = tlen(bf, label) + 92
    d.rounded_rectangle((right - bw, 86, right, 152), 33, fill=(20, 15, 8, 230), outline=GOLD + (170,), width=2)
    d.ellipse((right - 44, 111, right - 28, 127), fill=(74, 222, 128))
    rtl(d, right - 60, 90, label, bf, GOLD)

    # title: white, last line in gold (single line -> all gold)
    size, lines = fit(spec["title"], W - 2 * PAD, 4, 92, 52)
    tf = font(size, 900)
    y = 215
    for i, ln in enumerate(lines):
        if i == len(lines) - 1:
            gold_text(img, right, y, ln, tf)
        else:
            rtl(d, right, y, ln, tf, (255, 255, 255))
        y += int(size * 1.45)
    y += 34
    d.line([(right - 360, y), (right, y)], fill=GOLD + (200,), width=3)
    y += 34

    hook = spec.get("hook")
    if hook:
        hf = font(38, 600)
        for ln in wrap(hook, hf, W - 2 * PAD)[:3]:
            rtl(d, right, y, ln, hf, (235, 226, 205))
            y += 60
        y += 22

    # numbered point cards
    pf = font(34, 700)
    footer_top = H - 150
    for i, p in enumerate(spec.get("points", [])[:4], 1):
        lines = wrap(p, pf, W - 2 * PAD - 130)[:2]
        h = 44 + 52 * len(lines)
        if y + h > footer_top - 20:
            break
        d.rounded_rectangle((PAD, y, right, y + h), 24, fill=(255, 220, 140, 14), outline=GOLD + (70,), width=2)
        cx = right - 50
        d.ellipse((cx - 30, y + h / 2 - 30, cx + 30, y + h / 2 + 30), fill=GOLD)
        d.text((cx, y + h / 2), str(i), font=font(34, 900), fill=(15, 11, 5), anchor="mm")
        ty = y + 18
        for ln in lines:
            rtl(d, right - 100, ty, ln, pf, (255, 255, 255))
            ty += 52
        y += h + 18

    # footer: gold rule, brand in gold, page link
    d.rectangle((0, footer_top + 30, W, H), fill=(0, 0, 0, 120))
    d.line([(0, footer_top + 30), (W, footer_top + 30)], fill=GOLD + (120,), width=2)
    gold_text(img, right, footer_top + 60, BRAND, font(40, 900))
    note = spec.get("footer") or "تابع الصفحة ليوصلك كل جديد"
    d.text((PAD, footer_top + 70), shape(note), font=font(30, 600), fill=(235, 226, 205),
           **({"direction": "rtl"} if RAQM else {}))
    img.save(out, "PNG", optimize=True)
    return out


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        render(json.load(f), sys.argv[2])
    print(sys.argv[2])
