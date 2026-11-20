#!/usr/bin/env python3
"""Buddy brand files: glass B mark, app icon, favicon, spaced-caps BUDDY wordmark and lockups.
Same geometry as frontend/src/brand.jsx. Run:  python3 frontend/brand-src/make_logos.py
Writes to frontend/public/brand/ (served at /brand/)."""
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "public" / "brand"
B_STEM = "M36 18H44V102H36A8 8 0 0 1 28 94V26A8 8 0 0 1 36 18Z"
B_UP = "M44 18H66A19 19 0 0 1 66 56H44Z"
B_LO = "M44 62H69A20 20 0 0 1 69 102H44Z"
CAP = 56


def mark_inner(white=False, p="m"):
    up = ('<stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#d9e8ff"/>' if white
          else '<stop offset="0" stop-color="#3a5fd0"/><stop offset="1" stop-color="#12296f"/>')
    return f'''<defs>
<linearGradient id="{p}u" x1=".1" y1="0" x2=".9" y2="1">{up}</linearGradient>
<linearGradient id="{p}l" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#d4ebff"/><stop offset=".55" stop-color="#7cbcf8"/><stop offset="1" stop-color="#4a95ee"/></linearGradient>
<linearGradient id="{p}s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".5"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
<linearGradient id="{p}h" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity=".45"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
<radialGradient id="{p}d" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#c6ffe0"/><stop offset=".5" stop-color="#34d399"/><stop offset="1" stop-color="#12935f"/></radialGradient>
<clipPath id="{p}cu"><path d="{B_UP}"/></clipPath><clipPath id="{p}cl"><path d="{B_LO}"/></clipPath><clipPath id="{p}cs"><path d="{B_STEM}"/></clipPath>
</defs>
<path d="{B_STEM}" fill="url(#{p}l)"/><path d="{B_UP}" fill="url(#{p}u)"/><path d="{B_LO}" fill="url(#{p}l)"/>
<rect x="44" y="18" width="48" height="15" fill="url(#{p}s)" clip-path="url(#{p}cu)" opacity="{'.25' if white else '.7'}"/>
<rect x="44" y="62" width="48" height="13" fill="url(#{p}s)" clip-path="url(#{p}cl)" opacity=".8"/>
<rect x="28" y="18" width="7" height="84" fill="url(#{p}h)" clip-path="url(#{p}cs)"/>
<g fill="none" stroke="#fff" stroke-opacity=".28" stroke-width="1"><path d="{B_UP}" clip-path="url(#{p}cu)"/><path d="{B_LO}" clip-path="url(#{p}cl)"/></g>
<circle cx="99" cy="59" r="7" fill="url(#{p}d)"/><circle cx="96.8" cy="56.6" r="2" fill="#fff" fill-opacity=".7"/>'''


def svg(w, h, vb, body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="{vb}">{body}</svg>\n'


def mark_svg(white=False):
    return svg(240, 240, "0 0 120 120", mark_inner(white))


def icon_svg(rx=27):
    body = (f'<defs><linearGradient id="ig" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4a8df0"/><stop offset="1" stop-color="#12296f"/></linearGradient>'
            f'<linearGradient id="ih" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".28"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient></defs>'
            f'<rect width="120" height="120" rx="{rx}" fill="url(#ig)"/><rect width="120" height="56" rx="{rx}" fill="url(#ih)"/>'
            f'<g transform="translate(60 60) scale(.74) translate(-60 -60)">{mark_inner(True, "i")}</g>')
    return svg(512, 512, "0 0 120 120", body)


LETTERS = {
    "B": (38, lambda x: f"M{x} 0V{CAP}M{x} 0H{x+20}A14 14 0 0 1 {x+20} 28H{x}M{x} 28H{x+24}A14 14 0 0 1 {x+24} {CAP}H{x}"),
    "U": (36, lambda x: f"M{x} 0V36A18 18 0 0 0 {x+36} 36V0"),
    "D": (44, lambda x: f"M{x} 0H{x+16}A28 28 0 0 1 {x+16} {CAP}H{x}V0"),
    "Y": (36, lambda x: f"M{x} 0L{x+18} 30L{x+36} 0M{x+18} 30V{CAP}"),
}


def word_parts(on="dark", sparkle=True, text="BUDDY"):
    x, d = 6, ""
    for ch in text:
        w, f = LETTERS[ch]
        d += f(x)
        x += w + 24
    end = x - 24 + 6
    a, b = ("#2f6fe8", "#d6e8ff") if on == "dark" else ("#1740a8", "#3b82e8")
    star = ""
    if sparkle:
        star = (f'<path transform="translate({end + 24} 28)" d="M0 -15C2 -5 5 -2 15 0C5 2 2 5 0 15C-2 5 -5 2 -15 0C-5 -2 -2 -5 0 -15Z" '
                f'fill="{"#8592a6" if on == "dark" else "#a3b0c4"}"/>')
    body = (f'<defs><linearGradient id="wg" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="{end}" y2="0"><stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient></defs>'
            f'<path d="{d}" fill="none" stroke="url(#wg)" stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/>{star}')
    return body, end + (46 if sparkle else 6)


def wordmark_svg(on="dark"):
    body, w = word_parts(on)
    bg = f'<rect x="-6" y="-6" width="{w}" height="68" fill="#0f1f4d"/>' if on == "dark" else ""
    return svg(round(w * 2.4), 163, f"-6 -6 {w} 68", bg + body)


def lockup_svg(on="light"):
    body, w = word_parts("dark" if on == "dark" else "light")
    mark = mark_inner(on == "dark", "k")
    ws = 46 / 68  # wordmark is 46 tall next to a 100 tall mark
    total = 100 + 30 + w * ws + 8
    bg = f'<rect width="{total:.0f}" height="100" fill="#0f1f4d"/>' if on == "dark" else ""
    inner = (f'{bg}<g transform="scale({100/120:.4f})">{mark}</g>'
             f'<g transform="translate(130 {(100 - 68 * ws) / 2 + 6 * ws:.1f}) scale({ws:.4f})">{body}</g>')
    return svg(round(total), 100, f"0 0 {total:.0f} 100", inner)


SHEET = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Buddy brand</title>
<style>body{margin:0;background:#0b1433;color:#e8efff;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Text',Inter,sans-serif}main{max-width:980px;margin:0 auto;padding:36px 20px 80px}
h1{font-size:28px;margin:0 0 4px}p{color:#9fb6e8;margin:0 0 24px}.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}
.t{background:#121f4a;border:1px solid #243767;border-radius:18px;min-height:210px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;padding:18px}
.t.l{background:#fff;border-color:#e3ebf6}.t span{font-size:12px;color:#9fb6e8}.t.l span{color:#5a6a85}.w{grid-column:1/-1}</style></head><body><main>
<h1>Buddy</h1><p>Glass B, green hand-over dot, spaced-caps wordmark.</p><div class="g">
<div class="t"><img src="mark.svg" width="130"><span>Mark</span></div>
<div class="t"><img src="mark-white.svg" width="130"><span>Mark on dark</span></div>
<div class="t"><img src="icon.svg" width="130" style="border-radius:30px"><span>App icon</span></div>
<div class="t l"><img src="mark.svg" width="130"><span>Mark on light</span></div>
<div class="t w"><img src="lockup-dark.svg" height="80"><span>Lockup on dark</span></div>
<div class="t l w"><img src="lockup.svg" height="80"><span>Lockup on light</span></div>
<div class="t"><img src="wordmark-dark.svg" height="46"><span>Wordmark</span></div>
<div class="t"><div style="display:flex;gap:14px;align-items:flex-end"><img src="favicon.svg" width="32"><img src="favicon.svg" width="24"><img src="favicon.svg" width="16"></div><span>Favicon sizes</span></div>
</div></main></body></html>"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in ("ribbon", "faceted"):  # earlier directions, replaced by the glass B
        d = OUT / old
        if d.is_dir():
            for f in d.iterdir():
                f.unlink()
            d.rmdir()
    for f in ("wordmark.svg", "wordmark-white.svg"):
        (OUT / f).unlink(missing_ok=True)
    (OUT / "mark.svg").write_text(mark_svg(False))
    (OUT / "mark-white.svg").write_text(mark_svg(True))
    (OUT / "icon.svg").write_text(icon_svg())
    (OUT / "icon-square.svg").write_text(icon_svg(rx=0))
    (OUT / "favicon.svg").write_text(icon_svg(rx=26))
    (OUT / "wordmark-dark.svg").write_text(wordmark_svg("dark"))
    (OUT / "wordmark-light.svg").write_text(wordmark_svg("light"))
    (OUT / "lockup.svg").write_text(lockup_svg("light"))
    (OUT / "lockup-dark.svg").write_text(lockup_svg("dark"))
    (OUT / "index.html").write_text(SHEET)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
