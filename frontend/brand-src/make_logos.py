#!/usr/bin/env python3
"""Brand kit generator: four B-mark concepts + a custom monoline wordmark, no fonts needed.

    python3 frontend/brand-src/make_logos.py            # name = buddy
    python3 frontend/brand-src/make_logos.py buddhy     # any word made of b u d h y

Writes SVGs and a brand sheet to frontend/public/brand/ (served at /brand/).
"""
import os
import sys
from pathlib import Path

NAME = (sys.argv[1] if len(sys.argv) > 1 else "buddy").lower()
OUT = Path(__file__).resolve().parent.parent / "public" / "brand"

BLUE_HI, BLUE_LO, BLUE, BLUE_DEEP = "#4aa0f8", "#1456c4", "#1b6fe0", "#0f4fb8"
INK, MINT, MINT_DARK = "#0a2a63", "#1f9d6b", "#34d399"

# ------------------------------------------------------------------ marks (120 x 120)
def grad(id_="g", a=BLUE_HI, b=BLUE_LO, user=True):
    box = 'gradientUnits="userSpaceOnUse" x1="24" y1="12" x2="104" y2="110"' if user else 'x1="0" y1="0" x2="1" y2="1"'
    return f'<linearGradient id="{id_}" {box}><stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient>'

B_FACET = "M36 18H66A19 19 0 0 1 66 56H44V62H69A20 20 0 0 1 69 102H36A8 8 0 0 1 28 94V26A8 8 0 0 1 36 18Z"
B_CHAT = "M36 16H66A20 20 0 0 1 66 56H44V62H70A19 19 0 0 1 82 95.5L98 111L64 100H36A8 8 0 0 1 28 92V24A8 8 0 0 1 36 16Z"

def mark(kind, fill, dot, accent=None):
    """Return SVG elements for a mark. fill = paint for the body, accent = second tone (faceted/ring)."""
    a = accent or fill
    if kind == "ribbon":
        return (f'<path d="M40 20V102M40 20H66A20 20 0 0 1 66 60H40M40 60H70A21 21 0 0 1 70 102H40" fill="none" stroke="{fill}" '
                f'stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/><circle cx="90" cy="60" r="6" fill="{dot}"/>')
    if kind == "faceted":
        return (f'<path d="M36 18H66A19 19 0 0 1 66 56H44V62H69A20 20 0 0 1 69 102H36A8 8 0 0 1 28 94V26A8 8 0 0 1 36 18Z" fill="{fill}"/><circle cx="99" cy="59" r="6.5" fill="{dot}"/>')
    if kind == "chat":
        return (f'<path d="M36 16H66A20 20 0 0 1 66 56H44V62H70A19 19 0 0 1 82 95.5L98 111L64 100H36A8 8 0 0 1 28 92V24A8 8 0 0 1 36 16Z" fill="{fill}"/><circle cx="98" cy="36" r="6.5" fill="{dot}"/>')
    if kind == "ring":
        return (f'<rect x="26" y="14" width="14" height="92" rx="7" fill="{fill}"/><circle cx="58" cy="36" r="17" fill="none" stroke="{fill}" stroke-width="13"/>'
                f'<circle cx="61" cy="81" r="20" fill="none" stroke="{fill}" stroke-width="13"/><circle cx="103" cy="58" r="6.5" fill="{dot}"/>')
    raise ValueError(kind)

CONCEPTS = {
    "ribbon":  ("One-line B", "A single ribbon that never lifts: one flow from start to finish. Shares its stroke with the wordmark."),
    "faceted": ("Faceted B", "A solid B with a soft light across it. The most legible and most premium at small sizes."),
}

def mark_svg(kind, variant="color", size=120):
    body, defs = "", ""
    if variant == "color":
        defs = grad("g")
        body = mark(kind, "url(#g)", MINT, accent="#4aa0f8" if kind == "faceted" else None)
        if kind == "faceted":  # light facet across the solid B
            body += f'<clipPath id="cb"><path d="{B_FACET}"/></clipPath><path clip-path="url(#cb)" d="M10 8H100L10 84Z" fill="#fff" fill-opacity=".13"/>'
    elif variant == "white":
        body = mark(kind, "#ffffff", MINT_DARK, accent="#cfe3fb" if kind == "faceted" else None)
    elif variant == "mono":
        body = mark(kind, INK, INK)
    elif variant == "mono-white":
        body = mark(kind, "#ffffff", "#ffffff")
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 120 120"><defs>{defs}</defs>{body}</svg>\n'

def icon_svg(kind, size=512, rx=27):
    """App icon: rounded square, white mark."""
    inner = mark(kind, "#ffffff", MINT_DARK, accent="#cfe3fb" if kind == "faceted" else None)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 120 120"><defs>{grad("gi", "#3b92f5", BLUE_DEEP, user=False)}</defs>'
            f'<rect width="120" height="120" rx="{rx}" fill="url(#gi)"/><g transform="translate(60 60) scale(.74) translate(-60 -60)">{inner}</g></svg>\n')

# ------------------------------------------------------------------ custom monoline wordmark
# x-height 40, ascender 0, baseline 60, descender to ~82. Stroke 9, round caps. Letters are built from circles, stems and arcs.
LETTER_W = {"b": 40, "u": 38, "d": 40, "h": 38, "y": 38}

def letter(ch, x):
    if ch == "b":
        return f'M{x} 0V60', f'<circle cx="{x + 20}" cy="40" r="20"/>'
    if ch == "d":
        return f'M{x + 40} 0V60', f'<circle cx="{x + 20}" cy="40" r="20"/>'
    if ch == "u":
        return f'M{x} 20V40A19 19 0 0 0 {x + 38} 40M{x + 38} 20V60', ''
    if ch == "h":
        return f'M{x} 0V60M{x} 40A19 19 0 0 1 {x + 38} 40V60', ''
    if ch == "y":
        return f'M{x} 20V40A19 19 0 0 0 {x + 38} 40M{x + 38} 20V66Q{x + 38} 82 {x + 16} 82', ''
    raise ValueError(f"letter {ch!r} not drawn yet")

def wordmark(color, gap=11):
    paths, extra, x = [], [], 4.5
    for ch in NAME:
        d, e = letter(ch, x)
        paths.append(d); extra.append(e)
        x += LETTER_W[ch] + gap
    width = x - gap + 4.5
    g = (f'<g fill="none" stroke="{color}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round">'
         f'<path d="{"".join(paths)}"/>{"".join(extra)}</g>')
    return g, width

def lockup_svg(kind, on="light"):
    word_color = "#ffffff" if on == "dark" else INK
    body = mark(kind, "#ffffff", MINT_DARK, accent="#cfe3fb" if kind == "faceted" else None) if on == "dark" else mark(kind, "url(#g)", MINT, accent="#4aa0f8" if kind == "faceted" else None)
    if on != "dark" and kind == "faceted":
        body += f'<clipPath id="cb"><path d="{B_FACET}"/></clipPath><path clip-path="url(#cb)" d="M10 8H100L10 84Z" fill="#fff" fill-opacity=".13"/>'
    w, ww = wordmark(word_color)
    s = 1.22
    top = 12                                  # shared top edge of the B and the tallest letters
    y0 = top + 4.5 * s                        # wordmark origin (ascender centreline)
    base = y0 + 60 * s                        # baseline
    bottom = base + 4.5 * s                   # lowest edge of the stroke on the baseline
    k = (bottom - top) / 96                   # mark scale so the B spans ascender top to baseline
    tx, ty = -21 * k, top - 13 * k            # B visible box starts at x=21, y=13 in the 120 box
    mark_w = (96 - 21) * k
    x0 = mark_w + 30
    total = x0 + ww * s + 10
    H = base + 28 * s + 12
    bg = f'<rect width="{total:.0f}" height="{H:.0f}" fill="{INK}"/>' if on == "dark" else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{total:.0f}" height="{H:.0f}" viewBox="0 0 {total:.0f} {H:.0f}"><defs>{grad("g")}</defs>{bg}'
            f'<g transform="translate({tx:.1f} {ty:.1f}) scale({k:.4f})">{body}</g><g transform="translate({x0:.1f} {y0:.1f}) scale({s})">{w}</g></svg>\n')

def wordmark_svg(on="light"):
    w, ww = wordmark("#ffffff" if on == "dark" else INK)
    bg = f'<rect width="{ww + 20:.0f}" height="112" fill="{INK}"/>' if on == "dark" else ""
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{ww + 20:.0f}" height="112" viewBox="-10 -14 {ww + 20:.0f} 112">{bg}{w}</svg>\n'

# ------------------------------------------------------------------ write files + brand sheet
def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for k in CONCEPTS:
        d = OUT / k
        d.mkdir(exist_ok=True)
        (d / "mark.svg").write_text(mark_svg(k, "color"))
        (d / "mark-white.svg").write_text(mark_svg(k, "white"))
        (d / "mark-mono.svg").write_text(mark_svg(k, "mono"))
        (d / "icon.svg").write_text(icon_svg(k))
        (d / "icon-square.svg").write_text(icon_svg(k, rx=0))
        (d / "lockup.svg").write_text(lockup_svg(k, "light"))
        (d / "lockup-white.svg").write_text(lockup_svg(k, "dark"))
    (OUT / "wordmark.svg").write_text(wordmark_svg("light"))
    (OUT / "wordmark-white.svg").write_text(wordmark_svg("dark"))

    cards = []
    for k, (title, why) in CONCEPTS.items():
        cards.append(f'''<section class="c"><h2>{title}</h2><p class="why">{why}</p>
<div class="row"><div class="tile"><img src="{k}/mark.svg" width="150"><span>Mark</span></div>
<div class="tile"><img src="{k}/icon.svg" width="120" style="border-radius:27px"><span>App icon</span></div>
<div class="tile navy"><img src="{k}/mark-white.svg" width="150"><span>On dark</span></div>
<div class="tile"><img src="{k}/mark-mono.svg" width="150"><span>One colour</span></div></div>
<div class="row"><div class="tile wide"><img src="{k}/lockup.svg" height="96"><span>Lockup</span></div>
<div class="tile wide navy"><img src="{k}/lockup-white.svg" height="96"><span>Lockup on dark</span></div></div>
<div class="row small"><span>Small sizes</span><img src="{k}/mark.svg" width="48"><img src="{k}/mark.svg" width="32"><img src="{k}/mark.svg" width="24"><img src="{k}/mark.svg" width="16">
<img src="{k}/icon.svg" width="44" style="border-radius:10px"><img src="{k}/icon.svg" width="32" style="border-radius:7px"></div></section>''')
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{NAME.title()} brand kit</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,'SF Pro Text',Inter,sans-serif;margin:0;background:#f4f7fc;color:{INK}}}
main{{max-width:1040px;margin:0 auto;padding:36px 20px 80px}}h1{{font-size:30px;letter-spacing:-.02em;margin:0 0 4px}}.lead{{color:#5a6a85;margin:0 0 28px}}
.c{{background:#fff;border:1px solid #e3ebf6;border-radius:20px;padding:24px;margin:0 0 22px}}h2{{margin:0;font-size:20px}}.why{{color:#5a6a85;margin:4px 0 18px;font-size:14.5px}}
.row{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:14px}}.tile{{flex:1 1 170px;min-height:190px;border-radius:16px;background:#f4f7fc;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;padding:16px}}
.tile.navy{{background:{INK}}}.tile.navy span{{color:#9fc0f0}}.tile.wide{{flex:1 1 380px;min-height:150px}}.tile span{{font-size:12px;color:#7a8aa3}}
.small{{align-items:flex-end;gap:22px;padding-top:6px}}.small span{{font-size:12px;color:#7a8aa3;align-self:center}}
.pal{{display:flex;gap:10px;flex-wrap:wrap}}.sw{{width:130px;border-radius:14px;overflow:hidden;border:1px solid #e3ebf6;background:#fff}}.sw i{{display:block;height:60px}}.sw b,.sw em{{display:block;padding:0 10px;font-style:normal}}.sw b{{padding-top:8px;font-size:13px}}.sw em{{padding-bottom:8px;font-size:12px;color:#7a8aa3}}
.word{{display:flex;gap:14px;flex-wrap:wrap}}.word .tile{{flex:1 1 300px}}</style></head><body><main>
<h1>{NAME.title()} brand kit</h1><p class="lead">Two directions for the B, all with the same custom monoline wordmark. Mint dot = the hand-over: work moving from one agent to the next.</p>
{"".join(cards)}
<section class="c"><h2>Wordmark</h2><p class="why">Drawn from circles, stems and arcs, so it needs no font and stays sharp at any size.</p>
<div class="word"><div class="tile"><img src="wordmark.svg" height="70"></div><div class="tile navy"><img src="wordmark-white.svg" height="70"></div></div></section>
<section class="c"><h2>Colour</h2><div class="pal">
<div class="sw"><i style="background:linear-gradient(135deg,{BLUE_HI},{BLUE_LO})"></i><b>Buddy blue</b><em>{BLUE_HI} to {BLUE_LO}</em></div>
<div class="sw"><i style="background:{BLUE_DEEP}"></i><b>Deep blue</b><em>{BLUE_DEEP}</em></div>
<div class="sw"><i style="background:{INK}"></i><b>Ink</b><em>{INK}</em></div>
<div class="sw"><i style="background:{MINT}"></i><b>Hand-over mint</b><em>{MINT}</em></div>
<div class="sw"><i style="background:{MINT_DARK}"></i><b>Mint on dark</b><em>{MINT_DARK}</em></div></div>
<p class="why" style="margin-top:16px">Clear space: keep at least the width of the stem on every side. Minimum size: 16 px for the mark, 24 px tall for the lockup. Never stretch, recolour the dot or add shadows.</p></section>
</main></body></html>'''
    (OUT / "index.html").write_text(html)
    print("wrote", OUT, "for name:", NAME)

if __name__ == "__main__":
    main()
