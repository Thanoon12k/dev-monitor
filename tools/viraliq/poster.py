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

# kind -> (top colour, bottom colour, accent, default badge)
THEMES = {
    "trend": ((255, 92, 57), (40, 12, 40), (255, 190, 90), "ترند اليوم"),
    "news": ((29, 78, 216), (8, 14, 40), (56, 189, 248), "خبر تقني"),
    "course": ((15, 118, 110), (6, 30, 32), (94, 234, 212), "دورة مجانية"),
    "tip": ((109, 40, 217), (20, 10, 40), (216, 180, 254), "نصيحة اليوم"),
    "debate": ((190, 24, 93), (30, 8, 24), (253, 164, 175), "جدل السوشيال"),
}


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


def gradient(c1, c2):
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    return img


def render(spec, out):
    c1, c2, acc, badge = THEMES.get(spec.get("kind"), THEMES["trend"])
    img = gradient(c1, c2)

    # soft glow blobs
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((-260, -200, 520, 520), fill=acc + (70,))
    g.ellipse((640, 820, 1380, 1560), fill=c1 + (90,))
    img.paste(glow.filter(ImageFilter.GaussianBlur(120)), (0, 0), glow.filter(ImageFilter.GaussianBlur(120)))
    d = ImageDraw.Draw(img, "RGBA")
    for x in range(40, W, 48):  # dotted texture
        for y in range(40, H, 48):
            d.ellipse((x, y, x + 3, y + 3), fill=(255, 255, 255, 18))

    right = W - PAD
    # badge chip + date
    bf = font(34, 800)
    label = spec.get("badge") or badge
    bw = tlen(bf, label) + 56
    d.rounded_rectangle((right - bw, 80, right, 146), 33, fill=acc + (255,))
    rtl(d, right - 28, 86, label, bf, (20, 12, 20))
    date = spec.get("date") or (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y/%m/%d")
    d.text((PAD, 96), date, font=font(30, 600), fill=(255, 255, 255, 170))

    # title
    size, lines = fit(spec["title"], W - 2 * PAD, 4, 92, 52)
    tf = font(size, 900)
    y = 200
    for ln in lines:
        rtl(d, right + 3, y + 4, ln, tf, (0, 0, 0, 90))
        rtl(d, right, y, ln, tf, (255, 255, 255))
        y += int(size * 1.45)
    d.rounded_rectangle((right - 150, y + 8, right, y + 18), 5, fill=acc + (255,))
    y += 48

    hook = spec.get("hook")
    if hook:
        hf = font(38, 600)
        for ln in wrap(hook, hf, W - 2 * PAD)[:3]:
            rtl(d, right, y, ln, hf, (255, 255, 255, 215))
            y += 60
        y += 20

    # numbered point cards
    pf = font(34, 700)
    footer_top = H - 150
    for i, p in enumerate(spec.get("points", [])[:4], 1):
        lines = wrap(p, pf, W - 2 * PAD - 130)[:2]
        h = 44 + 52 * len(lines)
        if y + h > footer_top - 20:
            break
        d.rounded_rectangle((PAD, y, right, y + h), 26, fill=(255, 255, 255, 30), outline=(255, 255, 255, 50), width=2)
        cx = right - 50
        d.ellipse((cx - 30, y + h / 2 - 30, cx + 30, y + h / 2 + 30), fill=acc + (255,))
        d.text((cx, y + h / 2), str(i), font=font(34, 900), fill=(20, 12, 20), anchor="mm")
        ty = y + 18
        for ln in lines:
            rtl(d, right - 100, ty, ln, pf, (255, 255, 255))
            ty += 52
        y += h + 18

    # footer
    d.rectangle((0, footer_top + 30, W, H), fill=(0, 0, 0, 90))
    rtl(d, right, footer_top + 62, BRAND, font(38, 900), acc + (255,))
    note = spec.get("footer") or "تابع الصفحة ليوصلك كل جديد"
    d.text((PAD, footer_top + 70), shape(note), font=font(30, 600), fill=(255, 255, 255, 200),
           **({"direction": "rtl"} if RAQM else {}))
    img.save(out, "PNG", optimize=True)
    return out


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        render(json.load(f), sys.argv[2])
    print(sys.argv[2])
