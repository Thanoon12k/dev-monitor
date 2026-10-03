"""Render a 1080x1080 Golden Code card (cream dotted page, white sheet, gold title boxes).

    python tools/viraliq/poster.py spec.json out.png

spec: {"kind": "tip|news|course|debate|trend|work",
       "tag": "نصيحة", "label": "قبل ما تدفع",          # the two pills (defaults by kind)
       "title": "٥ أسئلة | قبل التسليم",                  # 1-2 lines: "|" or newline splits
       "sub": "one short line under the title",
       "points": ["...", "...", "..."],                    # 3 to 5 outlines
       "warn": 3,                                          # optional: point number drawn in coral
       "follow": "تابعنا — ...", "cta": "احفظه"}
Old fields still work: "badge" (-> label), "hook" (-> sub).
Needs Pillow with libraqm for Arabic shaping (falls back to arabic_reshaper + python-bidi).
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont, features

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "fonts", "Cairo.ttf")
LOGO = os.path.join(HERE, "assets", "logo.png")
RAQM = features.check("raqm")
S = 1080

CREAM, PAPER, INK = (255, 246, 234), (255, 255, 255), (22, 19, 13)
GOLD, CORAL, TEAL = (255, 201, 60), (255, 92, 57), (18, 185, 156)
MUTED, WARN_BG = (92, 85, 74), (255, 224, 216)

FOLLOW = "تابعنا — كل أسبوع أداة أو موقع ينفعك بشغلك"
BRAND = "الكود الذهبي"
DEFAULTS = {  # kind -> (tag, label, cta)
    "tip": ("نصيحة", "احفظه", "احفظه"),
    "news": ("خبر", "تقنية", "شاركه"),
    "course": ("دورة مجانية", "تعلّم ببلاش", "احفظه"),
    "debate": ("سؤال", "شنو رأيك؟", "علّق"),
    "trend": ("ترند", "اليوم", "شاركه"),
    "work": ("شغلنا", "الموصل", "راسلنا"),
}
AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


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


KW = {"direction": "rtl"} if RAQM else {}


def width(f, text):
    return f.getlength(shape(text), **KW)


def wrap(text, f, max_w):
    lines, cur = [], ""
    for word in text.split():
        cand = (cur + " " + word).strip()
        if cur and width(f, cand) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    return lines + ([cur] if cur else [])


def text_at(d, xy, text, f, fill, anchor="ra"):
    d.text(xy, shape(text), font=f, fill=fill, anchor=anchor, **KW)


def pill(d, right, top, text, f, bg, fg, pad_x=24, h=None, shadow=0, left=None):
    """Rounded pill with a 4px ink border; anchored at its right edge (or left edge)."""
    w = width(f, text) + 2 * pad_x
    h = h or f.size + 24
    x1 = right - w if left is None else left
    x2 = x1 + w
    if shadow:
        d.rounded_rectangle((x1 - shadow, top + shadow, x2 - shadow, top + h + shadow), h // 2, fill=INK)
    d.rounded_rectangle((x1, top, x2, top + h), h // 2, fill=bg, outline=INK, width=4)
    text_at(d, ((x1 + x2) / 2, top + h / 2 + 1), text, f, fg, anchor="mm")
    return x1, x2, h


def title_lines(spec, f, max_w):
    raw = spec.get("title_lines") or spec.get("title", "")
    if isinstance(raw, list):
        return raw[:2]
    parts = [p.strip() for p in raw.replace("|", "\n").split("\n") if p.strip()]
    if len(parts) >= 2:
        return parts[:2]
    words = raw.split()
    if width(f, raw) <= max_w or len(words) < 2:
        return [raw]
    # split into two lines of similar width
    best = min(range(1, len(words)), key=lambda i: abs(width(f, " ".join(words[:i])) - width(f, " ".join(words[i:]))))
    return [" ".join(words[:best]), " ".join(words[best:])]


def render(spec, out):
    kind = spec.get("kind", "tip")
    tag0, label0, cta0 = DEFAULTS.get(kind, DEFAULTS["tip"])
    tag = spec.get("tag") or tag0
    label = spec.get("label") or spec.get("badge") or label0
    sub = spec.get("sub") or spec.get("hook") or ""
    points = [p for p in spec.get("points", []) if p][:5]
    follow = spec.get("follow") or FOLLOW
    cta = spec.get("cta") or cta0
    warn = spec.get("warn")

    img = Image.new("RGB", (S, S), CREAM)
    d = ImageDraw.Draw(img)
    for y in range(13, S, 26):  # dotted page
        for x in range(13, S, 26):
            d.ellipse((x - 1.6, y - 1.6, x + 1.6, y + 1.6), fill=INK)

    # sheet with hard offset shadow (down-left, as in the RTL design)
    L, T, R, B = 52, 50, S - 52, S - 50
    d.rounded_rectangle((L - 13, T + 13, R - 13, B + 13), 34, fill=INK)
    d.rounded_rectangle((L, T, R, B), 34, fill=PAPER, outline=INK, width=5)
    il, ir, it, ib = L + 5 + 40, R - 5 - 40, T + 5 + 36, B - 5 - 30
    inner_w = ir - il

    # top pills: coral tag on the right, teal label on the far left
    _, _, ph = pill(d, ir, it, tag, font(24, 900), CORAL, PAPER)
    pill(d, None, it + 2, label, font(21, 800), TEAL, PAPER, pad_x=20, h=ph - 4, left=il)
    y = it + ph + 22

    # title: each line in its own gold box
    size = {4: 64, 5: 56}.get(len(points), 76)  # more outlines -> smaller title
    while size > 44:
        tf = font(size, 900)
        lines = title_lines(spec, tf, inner_w - 40)
        if all(width(tf, ln) <= inner_w - 40 for ln in lines):
            break
        size -= 4
    for ln in lines:
        w = width(tf, ln)
        h = int(size * 1.36)
        d.rounded_rectangle((ir - w - 36, y, ir, y + h), 14, fill=GOLD, outline=INK, width=4)
        text_at(d, (ir - 18, y + h / 2 + 2), ln, tf, INK, anchor="rm")
        y += h + 10
    y += 8

    if sub:
        sf = font(29, 600)
        for ln in wrap(sub, sf, inner_w)[:2]:
            text_at(d, (ir, y), ln, sf, MUTED)
            y += 41
        y += 18

    # bottom block, laid out upwards from the sheet's inner bottom
    foot_line = ib - 29 - 4 - 20 - 26 + 6
    foot_mid = (foot_line + ib) / 2 + 8
    follow_h = 28 + 2 * 14 + 8
    follow_top = foot_line - 26 - follow_h

    # outline cards, shrunk until they fit between the subtitle and the follow pill
    room = follow_top - 20 - y
    for fs, pad, gap, nb in ((30, 16, 14, 50), (28, 13, 12, 46), (26, 10, 10, 42), (24, 7, 8, 40), (22, 5, 6, 36)):
        pf = font(fs, 700)
        rows = [wrap(p, pf, inner_w - 40 - nb - 16 - 8)[:2] for p in points]
        heights = [max(nb, len(r) * int(fs * 1.3)) + 2 * pad + 8 for r in rows]
        total = sum(heights) + gap * (len(rows) - 1)
        if total <= room:
            break
    cy = y + max(0, (room - total) / 2)
    for i, (r, h) in enumerate(zip(rows, heights), 1):
        is_warn = warn == i
        d.rounded_rectangle((il, cy, ir, cy + h), 20, fill=WARN_BG if is_warn else CREAM, outline=INK, width=4)
        bx = ir - 4 - 20
        mid = cy + h / 2
        d.rounded_rectangle((bx - nb, mid - nb / 2, bx, mid + nb / 2), 14, fill=CORAL if is_warn else GOLD, outline=INK, width=4)
        text_at(d, (bx - nb / 2, mid + 1), str(i).translate(AR_DIGITS), font(nb // 2 + 1, 900),
                PAPER if is_warn else INK, anchor="mm")
        lh = int(fs * 1.3)
        ty = mid - lh * len(r) / 2 + lh / 2
        for ln in r:
            text_at(d, (bx - nb - 16, ty + 1), ln, pf, INK, anchor="rm")
            ty += lh
        cy += h + gap

    # follow pill (full width, offset shadow)
    d.rounded_rectangle((il - 6, follow_top + 6, ir - 6, follow_top + follow_h + 6), follow_h // 2, fill=INK)
    d.rounded_rectangle((il, follow_top, ir, follow_top + follow_h), follow_h // 2, fill=GOLD, outline=INK, width=4)
    ff = font(28, 900)
    while width(ff, follow) > inner_w - 40 and ff.size > 20:
        ff = font(ff.size - 2, 900)
    text_at(d, ((il + ir) / 2, follow_top + follow_h / 2 + 1), follow, ff, INK, anchor="mm")

    # footer: rule, round logo in the bottom-right corner (fixed), brand + </> chip, teal CTA on the left
    d.line((il, foot_line, ir, foot_line), fill=INK, width=4)
    lg = 58
    logo = Image.open(LOGO).convert("RGB").resize((lg, lg), Image.LANCZOS)
    mask = Image.new("L", (lg, lg), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, lg - 1, lg - 1), fill=255)
    lx, ly = int(ir - lg), int(foot_mid - lg / 2)
    img.paste(logo, (lx, ly), mask)
    d.ellipse((lx - 2, ly - 2, lx + lg + 1, ly + lg + 1), outline=INK, width=4)
    bf = font(29, 900)
    text_at(d, (lx - 12, foot_mid), BRAND, bf, INK, anchor="rm")
    chip_r = lx - 12 - width(bf, BRAND) - 10
    cf = font(24, 900)
    cw = cf.getlength("</>") + 22
    d.rounded_rectangle((chip_r - cw, foot_mid - 22, chip_r, foot_mid + 22), 12, fill=GOLD, outline=INK, width=4)
    d.text((chip_r - cw / 2, foot_mid + 1), "</>", font=cf, fill=INK, anchor="mm")
    pill(d, None, foot_mid - 24, cta, font(24, 800), TEAL, PAPER, pad_x=20, h=48, left=il)

    img.save(out, "PNG", optimize=True)
    return out


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        render(json.load(f), sys.argv[2])
    print(sys.argv[2])
