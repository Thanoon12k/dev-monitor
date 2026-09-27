"""Build poster.html from poster.src.html: inline fonts @font-face, brand mark, icons, animation script."""
import os, re
D = os.path.dirname(os.path.abspath(__file__))
AR = "U+0600-06FF,U+0750-077F,U+0870-088E,U+0890-0891,U+0897-08E1,U+08E3-08FF,U+200C-200E,U+2010-2011,U+204F,U+2E41,U+FB50-FDFF,U+FE70-FE74,U+FE76-FEFC"
LA = "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD"
faces = []
for fam, slug, weights in (("Alexandria", "alexandria", (500, 600, 700, 800, 900)), ("Readex Pro", "readex-pro", (400, 500, 600, 700))):
    for w in weights:
        for sub, rng in (("arabic", AR), ("latin", LA)):
            faces.append(f"@font-face{{font-family:'{fam}';font-weight:{w};src:url(fonts/{slug}-{sub}-{w}-normal.woff2) format('woff2');unicode-range:{rng}}}")
mark = open(os.path.join(D, "assets/mark.svg")).read()
mark = mark.replace('fill="#5b3550"', 'fill="currentColor"')
check = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>'
anim_path = os.path.join(D, "anim.js")
anim = f"<script>\n{open(anim_path).read()}\n</script>" if os.path.exists(anim_path) else ""
src = open(os.path.join(D, "poster.src.html")).read()
out = (src.replace("%%FONTS%%", "\n".join(faces)).replace("%%MARK_SVG%%", mark)
          .replace("%%CHECK%%", check).replace("%%ANIM%%", anim))
open(os.path.join(D, "poster.html"), "w").write(out)
print("built poster.html", len(out), "bytes")
