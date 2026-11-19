#!/usr/bin/env python3
"""Render the profile README cards into cards/.

Every card is a self-contained SVG meant to be shown through an <img> tag, so it
only uses what works there: one inline <style> block with CSS keyframes, SMIL
<animate> elements, and fonts subset with pyftsubset and embedded as base64
WOFF data URIs. No scripts, no external requests.

Cards play top to bottom: each one gets a start delay from its place in
CARD_ORDER. Under prefers-reduced-motion every animation is switched off and the
final frame is shown.

    python render_cards.py              # animated cards
    STATIC=1 python render_cards.py     # final frame only, for screenshots

Contribution data comes from data/contributions.json, which the daily GitHub
Action refreshes with data/query.graphql.
"""

from __future__ import annotations

import base64
import datetime as dt
import functools
import json
import os
import subprocess
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "cards"
DATA = ROOT / "data" / "contributions.json"
STATIC = os.environ.get("STATIC", "") not in ("", "0", "false")

# ---------------------------------------------------------------- content ---
PROFILE = {
    "name": "Sidharth S.",
    "role": "AI Data Engineer",
    "line": "Building data platforms on Azure and Databricks that process 2M+ records a day.",
    "status": "Open to AI data engineering roles",
    "meta": ["Kochi, India", "Azure · Databricks", "5+ years"],
    "portrait": "assets/portrait.jpg",  # set to None (or delete the file) to drop it
}

TILES = [
    {"file": "tile-portfolio", "label": "Portfolio", "title": "sidharthdata-dev", "sub": "Projects, impact, certifications", "icon": "globe"},
    {"file": "tile-linkedin", "label": "LinkedIn", "title": "in/sids2000", "sub": "Career and experience", "icon": "person"},
    {"file": "tile-resume", "label": "Résumé", "title": "Download PDF", "sub": "One page, always current", "icon": "doc"},
]

# Featured repos, in order. "blurb" overrides an empty or weak GitHub description;
# "tags" are optional chips. Names not found in the data are skipped.
FEATURED = [
    {
        "name": "Formula1-Data-Engineering-Project",
        "blurb": "Azure pipeline that ingests, transforms, analyses and loads Formula 1 race data from the 1950s onwards, sourced from the Ergast API.",
        "tags": ["Azure", "Python"],
    },
    {
        "name": "Data_Analysis_end_to_end_project",
        "blurb": "End-to-end Tokyo 2021 Olympics pipeline: Azure Blob Storage to Azure Databricks for transformation, then Power BI dashboards.",
        "tags": ["Databricks", "Power BI"],
    },
]

# ------------------------------------------------------------------ brand ---
# Taken from sidharthdata-dev.netlify.app (dark theme tokens).
C = {
    "bg": "#09090b",
    "surface": "#131316",
    "surface2": "#1a1a1e",
    "border": "#232328",
    "border2": "#2e2e34",
    "text": "#fafafa",
    "text2": "#b4b4bc",
    "text3": "#8e8e97",
    "violet": "#7c3aed",
    "violet_l": "#c4b5fd",
    "blue": "#3b82f6",
    "green": "#22c55e",
    "avatar_bg": "#0f1424",  # .id-card__avatar background
}
GRAD = [("0", "#7c3aed"), ("45%", "#5b6cf0"), ("75%", "#4f8ff7"), ("100%", "#7aa8f8")]
HEAT = ["#1a1a1e", "#2e1f5e", "#4c2a9e", "#7c3aed", "#a78bfa"]  # brand violet ramp
EASE = "cubic-bezier(.22,1,.36,1)"

W = 840  # card width in px; README shows them at 100%

# Global timeline: card start delays in seconds, top to bottom.
CARD_ORDER = ["hero", "tile-portfolio", "tile-linkedin", "tile-resume", "activity"] + [
    f"repo-{i + 1}" for i in range(len(FEATURED))
] + ["graph"]
STEP = 0.32


def start(card: str) -> float:
    return round(CARD_ORDER.index(card) * STEP, 2)


# ------------------------------------------------------------------ fonts ---
FONT_SRC = {
    "sans": (ROOT / "fonts" / "Geist-Variable.ttf", 400),
    "semi": (ROOT / "fonts" / "Geist-Variable.ttf", 600),
    "mono": (ROOT / "fonts" / "GeistMono-Variable.ttf", 400),
}
FAMILY = {"sans": "GeistC", "semi": "GeistC", "mono": "GeistMonoC"}
WEIGHT = {"sans": 400, "semi": 600, "mono": 400}
FALLBACK = {"sans": "system-ui,-apple-system,'Segoe UI',sans-serif", "mono": "ui-monospace,'SF Mono',monospace"}
_TMP = Path(tempfile.mkdtemp(prefix="cards-fonts-"))


@functools.lru_cache(maxsize=None)
def static_font(key: str) -> Path:
    """Pin the variable font to one weight and save it as a static TTF."""
    src, wght = FONT_SRC[key]
    font = instancer.instantiateVariableFont(TTFont(src), {"wght": wght})
    path = _TMP / f"{key}.ttf"
    font.save(path)
    return path


@functools.lru_cache(maxsize=None)
def metrics(key: str):
    font = TTFont(static_font(key))
    return font.getBestCmap(), font["hmtx"].metrics, font["head"].unitsPerEm


def text_width(s: str, key: str, size: float, tracking: float = 0) -> float:
    cmap, hmtx, upem = metrics(key)
    total = 0
    for ch in s:
        glyph = cmap.get(ord(ch))
        total += hmtx[glyph][0] if glyph else upem * 0.55
    return total / upem * size + tracking * size * max(len(s) - 1, 0)


def subset_woff(key: str, chars: str) -> str:
    """Run pyftsubset on the static instance and return a base64 WOFF."""
    out = _TMP / f"{key}-{abs(hash(chars))}.woff"
    subprocess.run(
        [
            sys.executable, "-m", "fontTools.subset", str(static_font(key)),
            f"--text={chars}", f"--output-file={out}", "--flavor=woff",
            "--layout-features=kern,liga,tnum", "--no-hinting", "--desubroutinize",
            "--name-IDs=", "--notdef-outline", "--drop-tables+=meta",
        ],
        check=True,
    )
    return base64.b64encode(out.read_bytes()).decode()


def wrap(s: str, key: str, size: float, max_w: float, max_lines: int) -> list[str]:
    words, lines, cur = s.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if text_width(trial, key, size) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while text_width(last + "…", key, size) > max_w and " " in last:
            last = last.rsplit(" ", 1)[0]
        lines[-1] = last.rstrip(",.;:") + "…"
    return lines


# ------------------------------------------------------------------- card ---
class Card:
    """Collects SVG body, used glyphs and CSS for one card."""

    def __init__(self, name: str, width: int, height: int, title: str):
        self.name, self.w, self.h, self.title = name, width, height, title
        self.t0 = start(name)
        self.body: list[str] = []
        self.defs: list[str] = []
        self.css: list[str] = []
        self.glyphs: dict[str, set[str]] = {"sans": set(), "semi": set(), "mono": set()}
        self._ids = 0

    def uid(self, stem: str) -> str:
        self._ids += 1
        return f"{stem}{self._ids}"

    def d(self, offset: float) -> str:
        """Absolute animation delay for something `offset` s into this card."""
        return f"{self.t0 + offset:.2f}s"

    def add(self, s: str):
        self.body.append(s)

    def text(self, x, y, s, key="sans", size=14, fill=None, anchor="start", cls="", delay=None,
             tracking=0.0, extra="", upper=False):
        if upper:
            s = s.upper()
        self.glyphs[key].update(s)
        fam = "mono" if key == "mono" else "sans"
        style = f"font:{WEIGHT[key]} {size}px {FAMILY[key]},{FALLBACK[fam]}"
        if tracking:
            style += f";letter-spacing:{tracking}em"
        if delay is not None:
            style += f";animation-delay:{self.d(delay)}"
        attrs = f'x="{x:.1f}" y="{y:.1f}" fill="{fill or C["text"]}" style="{style}"'
        if anchor != "start":
            attrs += f' text-anchor="{anchor}"'
        if cls:
            attrs += f' class="{cls}"'
        self.add(f"<text {attrs}{extra}>{escape(s)}</text>")

    def gradient(self, gid: str, x2="1", y2="0"):
        stops = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in GRAD)
        self.defs.append(f'<linearGradient id="{gid}" x1="0" y1="0" x2="{x2}" y2="{y2}">{stops}</linearGradient>')

    def frame(self, glow=False, accent=True):
        """Rounded panel in the site's dark surface colour."""
        self.gradient("edge")
        self.defs.append(
            '<linearGradient id="sheen" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0" stop-color="#7c3aed" stop-opacity=".10"/>'
            '<stop offset=".6" stop-color="#3b82f6" stop-opacity=".03"/>'
            '<stop offset="1" stop-color="#3b82f6" stop-opacity="0"/></linearGradient>'
        )
        r = 18
        self.add(f'<g class="a-fade" style="animation-delay:{self.d(0)}">')
        self.add(f'<rect x=".5" y=".5" width="{self.w - 1}" height="{self.h - 1}" rx="{r}" fill="{C["surface"]}" stroke="{C["border"]}"/>')
        self.add(f'<rect x=".5" y=".5" width="{self.w - 1}" height="{self.h - 1}" rx="{r}" fill="url(#sheen)"/>')
        if glow:
            self.defs.append(
                '<radialGradient id="glow" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" '
                f'gradientTransform="translate({self.w * 0.18:.0f} -40) scale({self.w * 0.7:.0f} 260)">'
                '<stop offset="0" stop-color="#7c3aed" stop-opacity=".28"/>'
                '<stop offset="1" stop-color="#7c3aed" stop-opacity="0"/></radialGradient>'
            )
            self.add(f'<rect x=".5" y=".5" width="{self.w - 1}" height="{self.h - 1}" rx="{r}" fill="url(#glow)"/>')
        self.add("</g>")
        if accent:  # gradient hairline along the top edge that sweeps in
            self.add(
                f'<g class="a-sweep" style="animation-delay:{self.d(0.1)}">'
                f'<rect x="{r}" y=".5" width="{self.w - 2 * r}" height="1.5" rx=".75" fill="url(#edge)" opacity=".9"/></g>'
            )

    def render(self) -> str:
        faces = []
        for key, chars in self.glyphs.items():
            if not chars:
                continue
            chars = "".join(sorted(chars | {" "}))
            data = subset_woff(key, chars)
            faces.append(
                f"@font-face{{font-family:{FAMILY[key]};font-weight:{WEIGHT[key]};"
                f"src:url(data:font/woff;base64,{data}) format('woff')}}"
            )
        css = "\n".join(faces + [BASE_CSS] + self.css + [motion_off_css()])
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{escape(self.title)}">'
            f"<title>{escape(self.title)}</title>"
            f"<style>{css}</style>"
            f"<defs>{''.join(self.defs)}</defs>"
            f"{''.join(self.body)}</svg>"
        )

    def save(self):
        OUT.mkdir(exist_ok=True)
        path = OUT / f"{self.name}.svg"
        path.write_text(self.render(), encoding="utf-8")
        print(f"  {path.relative_to(ROOT)}  {path.stat().st_size / 1024:.1f} KB")


BASE_CSS = f"""
.a-up{{animation:up .8s {EASE} both}}
.a-fade{{animation:fade .9s ease-out both}}
.a-pop{{animation:pop .6s {EASE} both;transform-box:fill-box;transform-origin:center}}
.a-grow{{animation:grow .9s {EASE} both;transform-box:fill-box;transform-origin:50% 100%}}
.a-sweep{{animation:sweep 1.1s {EASE} both;transform-box:fill-box;transform-origin:0 50%}}
.a-nudge{{animation:nudge 2.4s ease-in-out 2 both;transform-box:fill-box}}
.s{{display:none}}
@keyframes up{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:none}}}}
@keyframes fade{{from{{opacity:0}}to{{opacity:1}}}}
@keyframes pop{{from{{opacity:0;transform:scale(.3)}}to{{opacity:1;transform:none}}}}
@keyframes grow{{from{{transform:scaleY(0)}}to{{transform:none}}}}
@keyframes sweep{{from{{transform:scaleX(0);opacity:0}}to{{transform:none;opacity:1}}}}
@keyframes nudge{{0%,60%,100%{{transform:none}}75%{{transform:translate(3px,-3px)}}}}
""".strip()


def motion_off_css() -> str:
    """Final frame: CSS animations removed (fill-mode both leaves end state as the
    base style), SMIL-driven elements (.m) hidden and their static twins (.s) shown."""
    rules = "*{animation:none!important}.m{display:none!important}.s{display:inline!important}"
    return rules if STATIC else f"@media (prefers-reduced-motion:reduce){{{rules}}}"


def smil(el: str) -> str:
    """SMIL animate elements are dropped entirely in STATIC mode."""
    return "" if STATIC else el


# -------------------------------------------------------------- data load ---
def load_data():
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    user = raw["data"]["user"]
    days = [
        (dt.date.fromisoformat(d["date"]), d["contributionCount"], d["weekday"])
        for w in user["contributionsCollection"]["contributionCalendar"]["weeks"]
        for d in w["contributionDays"]
    ]
    weeks = [
        [(dt.date.fromisoformat(d["date"]), d["contributionCount"], d["weekday"]) for d in w["contributionDays"]]
        for w in user["contributionsCollection"]["contributionCalendar"]["weeks"]
    ]
    repos = {r["name"]: r for r in user["repositories"]["nodes"]}
    total = user["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    return days, weeks, repos, total


def stats(days):
    days = sorted(days)
    longest = run = 0
    for _, n, _ in days:
        run = run + 1 if n else 0
        longest = max(longest, run)
    # current streak: today counts if it has contributions, otherwise start from yesterday
    current, i = 0, len(days) - 1
    if i >= 0 and days[i][1] == 0:
        i -= 1
    while i >= 0 and days[i][1] > 0:
        current += 1
        i -= 1
    active = sum(1 for _, n, _ in days if n)
    busiest = max(days, key=lambda d: (d[1], d[0])) if days else None
    if busiest and busiest[1] == 0:
        busiest = None
    return {"current": current, "longest": longest, "active": active, "span": len(days), "busiest": busiest}


def monthly(days, n=12):
    last = max(d for d, _, _ in days)
    keys = []
    y, m = last.year, last.month
    for _ in range(n):
        keys.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    keys.reverse()
    totals = OrderedDict((k, 0) for k in keys)
    for d, cnt, _ in days:
        if (d.year, d.month) in totals:
            totals[(d.year, d.month)] += cnt
    return totals


# ------------------------------------------------------------------ icons ---
ICONS = {
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 2.6 3.8 5.6 3.8 9s-1.2 6.4-3.8 9c-2.6-2.6-3.8-5.6-3.8-9S9.4 5.6 12 3z"/>',
    "person": '<circle cx="12" cy="8" r="3.6"/><path d="M4.8 20c.9-3.7 3.7-5.6 7.2-5.6s6.3 1.9 7.2 5.6"/>',
    "doc": '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/>',
    "repo": '<path d="M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5z"/><path d="M5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3"/>',
    "arrow": '<path d="M7 17 17 7M9 7h8v8"/>',
}
STAR = "M8 .9l2.1 4.4 4.8.6-3.5 3.3.9 4.8L8 11.7 3.7 14l.9-4.8L1.1 5.9l4.8-.6z"
FORK = '<circle cx="4" cy="3" r="1.8"/><circle cx="12" cy="3" r="1.8"/><circle cx="8" cy="13" r="1.8"/><path d="M4 4.8v1.4c0 1.2.9 2 2 2h4c1.1 0 2-.8 2-2V4.8M8 8.2v3"/>'


def icon(name, x, y, size=24, stroke=C["violet_l"], width=1.7):
    s = size / 24
    return (
        f'<g transform="translate({x} {y}) scale({s:.3f})" fill="none" stroke="{stroke}" '
        f'stroke-width="{width / s:.2f}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</g>'
    )


# ------------------------------------------------------------------ cards ---
def hero():
    portrait = ROOT / PROFILE["portrait"] if PROFILE.get("portrait") else None
    has_photo = bool(portrait and portrait.exists())
    c = Card("hero", W, 250, f"{PROFILE['name']}, {PROFILE['role']}")
    c.frame(glow=True)
    x = 44
    # status pill with a pulsing dot (SMIL) and a static twin for reduced motion
    if PROFILE.get("status"):
        label = PROFILE["status"]
        pw = text_width(label, "mono", 11.5, 0.02) + 40
        c.add(f'<g class="a-up" style="animation-delay:{c.d(0.15)}">')
        c.add(f'<rect x="{x}" y="30" width="{pw:.1f}" height="26" rx="13" fill="{C["surface2"]}" stroke="{C["border2"]}"/>')
        c.add(f'<circle cx="{x + 16}" cy="43" r="3.5" fill="{C["green"]}"/>')
        c.add(
            f'<circle class="m" cx="{x + 16}" cy="43" r="3.5" fill="none" stroke="{C["green"]}" stroke-width="1.5" opacity="0">'
            + smil(f'<animate attributeName="r" values="3.5;9" dur="2s" begin="{c.d(0.6)}" repeatCount="indefinite"/>'
                   f'<animate attributeName="opacity" values=".8;0" dur="2s" begin="{c.d(0.6)}" repeatCount="indefinite"/>')
            + "</circle>"
        )
        c.text(x + 28, 47, label, "mono", 11.5, C["text2"], tracking=0.02)
        c.add("</g>")
    c.text(x, 114, PROFILE["name"], "semi", 50, cls="a-up", delay=0.3, tracking=-0.03)
    c.gradient("role")
    c.text(x, 150, PROFILE["role"], "semi", 22, fill="url(#role)", cls="a-up", delay=0.45, tracking=-0.01)
    text_max = (W - 260 if has_photo else W - 88)
    line = wrap(PROFILE["line"], "sans", 15, text_max, 1)[0]
    c.text(x, 182, line, "sans", 15, C["text2"], cls="a-up", delay=0.6)
    meta = "   ·   ".join(PROFILE["meta"])
    c.text(x, 218, meta, "mono", 11.5, C["text3"], cls="a-up", delay=0.75, tracking=0.06, upper=True)

    if has_photo:
        cx, cy, r = W - 128, 125, 78
        mime = "image/png" if portrait.suffix.lower() == ".png" else "image/jpeg"
        data = base64.b64encode(portrait.read_bytes()).decode()
        c.defs.append(f'<clipPath id="pc"><circle cx="{cx}" cy="{cy}" r="{r}"/></clipPath>')
        c.gradient("ring", "1", "1")
        circ = 2 * 3.14159 * (r + 7)
        # soft violet glow under the avatar, as on the site (box-shadow 0 10px 30px -10px #7c3aed99)
        c.defs.append('<filter id="halo" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="13"/></filter>')
        c.add(f'<g class="a-fade" style="animation-delay:{c.d(0.6)}">'
              f'<circle cx="{cx}" cy="{cy + 12}" r="{r - 6}" fill="{C["violet"]}" fill-opacity=".6" filter="url(#halo)"/></g>')
        c.add(f'<g class="a-pop" style="animation-delay:{c.d(0.35)}">')
        c.add(f'<circle cx="{cx}" cy="{cy}" r="{r + 7}" fill="{C["avatar_bg"]}"/>')
        c.add(
            f'<image href="data:{mime};base64,{data}" x="{cx - r}" y="{cy - r}" width="{2 * r}" height="{2 * r}" '
            f'clip-path="url(#pc)" preserveAspectRatio="xMidYMid slice"/>'
        )
        c.add("</g>")
        # ring that draws itself (SMIL); the static twin is the finished ring
        ring = f'cx="{cx}" cy="{cy}" r="{r + 7}" fill="none" stroke="url(#ring)" stroke-width="2.5" transform="rotate(-90 {cx} {cy})"'
        c.add(f'<circle class="s" {ring}/>')
        c.add(
            f'<circle class="m" {ring} stroke-dasharray="{circ:.1f}" stroke-dashoffset="{0 if STATIC else circ:.1f}">'
            + smil(f'<animate attributeName="stroke-dashoffset" from="{circ:.1f}" to="0" dur="1.4s" begin="{c.d(0.5)}" '
                   f'fill="freeze" calcMode="spline" keyTimes="0;1" keySplines=".22 1 .36 1"/>')
            + "</circle>"
        )
    c.save()


def tile(t):
    c = Card(t["file"], 270, 132, f"{t['label']}: {t['title']}")
    c.frame()
    c.add(f'<g class="a-pop" style="animation-delay:{c.d(0.15)}">')
    c.add(f'<rect x="20" y="20" width="38" height="38" rx="11" fill="{C["violet"]}" fill-opacity=".16" stroke="{C["violet"]}" stroke-opacity=".35"/>')
    c.add(icon(t["icon"], 27, 27, 24))
    c.add("</g>")
    c.add(f'<g class="a-fade" style="animation-delay:{c.d(0.3)}"><g class="a-nudge" style="animation-delay:{c.d(1.2)}">')
    c.add(icon("arrow", 228, 22, 20, C["text3"], 1.8))
    c.add("</g></g>")
    c.text(20, 80, t["label"], "mono", 10.5, C["text3"], cls="a-up", delay=0.25, tracking=0.12, upper=True)
    c.text(20, 102, t["title"], "semi", 17, cls="a-up", delay=0.32, tracking=-0.01)
    c.text(20, 120, wrap(t["sub"], "sans", 12.5, 230, 1)[0], "sans", 12.5, C["text2"], cls="a-up", delay=0.4)
    c.save()


def activity(days, total):
    s = stats(days)
    months = monthly(days)
    c = Card("activity", W, 300, "Contributions per month")
    c.frame()
    c.text(32, 46, "Contributions per month", "semi", 18, cls="a-up", delay=0.1, tracking=-0.01)
    c.text(32, 68, f"{total:,} in the last year", "mono", 11.5, C["text3"], cls="a-up", delay=0.18, tracking=0.04, upper=True)

    # plot area
    px0, px1, py0, py1 = 44, 532, 96, 246
    vmax = max(months.values()) if months else 0
    top = max(4, vmax)
    step = max(1, -(-top // 4))
    top = step * 4
    for i in range(5):
        v = step * i
        y = py1 - (py1 - py0) * v / top
        c.add(f'<line class="a-fade" style="animation-delay:{c.d(0.2)}" x1="{px0}" x2="{px1}" y1="{y:.1f}" y2="{y:.1f}" '
              f'stroke="{C["border"]}" stroke-dasharray="{"" if i == 0 else "2 4"}"/>')
        c.text(px0 - 10, y + 3.5, str(v), "mono", 10, C["text3"], anchor="end", cls="a-fade", delay=0.2)
    c.gradient("bar", "0", "1")
    slot = (px1 - px0) / len(months)
    bw = min(26, slot * 0.6)
    for i, ((yr, mo), v) in enumerate(months.items()):
        cx = px0 + slot * (i + 0.5)
        label = dt.date(yr, mo, 1).strftime("%b")
        c.text(cx, py1 + 20, label, "mono", 10.5, C["text3"], anchor="middle", cls="a-fade", delay=0.3 + i * 0.04)
        h = (py1 - py0) * v / top
        delay = c.d(0.4 + i * 0.06)
        if v:
            c.add(f'<rect class="a-grow" style="animation-delay:{delay}" x="{cx - bw / 2:.1f}" y="{py1 - h:.1f}" '
                  f'width="{bw:.1f}" height="{h:.1f}" rx="5" fill="url(#bar)"/>')
            c.text(cx, py1 - h - 8, str(v), "semi", 11.5, C["violet_l"], anchor="middle", cls="a-up", delay=0.75 + i * 0.06)
        else:
            c.add(f'<rect class="a-fade" style="animation-delay:{delay}" x="{cx - bw / 2:.1f}" y="{py1 - 3}" '
                  f'width="{bw:.1f}" height="3" rx="1.5" fill="{C["border2"]}"/>')

    # stat tiles, 2 x 2
    b = s["busiest"]
    cells = [
        ("Current streak", str(s["current"]), "day" if s["current"] == 1 else "days"),
        ("Longest streak", str(s["longest"]), "day" if s["longest"] == 1 else "days"),
        ("Active days", str(s["active"]), f"of {s['span']}"),
        ("Busiest day", b[0].strftime("%b %-d") if b else "—",
         f"{b[1]} contribution{'s' if b[1] != 1 else ''}" if b else "no activity yet"),
    ]
    gx, gy, cw, ch, gap = 562, 30, 119, 116, 8
    for i, (label, value, sub) in enumerate(cells):
        x = gx + (i % 2) * (cw + gap)
        y = gy + (i // 2) * (ch + gap)
        d = 0.5 + i * 0.12
        c.add(f'<g class="a-up" style="animation-delay:{c.d(d)}">')
        c.add(f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="12" fill="{C["surface2"]}" stroke="{C["border"]}"/>')
        c.text(x + 14, y + 26, label, "mono", 9.5, C["text3"], tracking=0.06, upper=True)
        size = 30 if len(value) <= 4 else 22
        c.text(x + 14, y + 72, value, "semi", size, tracking=-0.03)
        c.text(x + 14, y + 96, wrap(sub, "sans", 11.5, cw - 20, 1)[0], "sans", 11.5, C["text2"])
        c.add("</g>")
    # live dot next to the current streak when it is running
    if s["current"]:
        x, y = gx + cw - 18, gy + 22
        c.add(f'<circle cx="{x}" cy="{y}" r="3" fill="{C["green"]}"/>')
        c.add(f'<circle class="m" cx="{x}" cy="{y}" r="3" fill="none" stroke="{C["green"]}" stroke-width="1.2" opacity="0">'
              + smil(f'<animate attributeName="r" values="3;8" dur="2s" begin="{c.d(1)}" repeatCount="indefinite"/>'
                     f'<animate attributeName="opacity" values=".8;0" dur="2s" begin="{c.d(1)}" repeatCount="indefinite"/>')
              + "</circle>")
    c.save()


def repo_card(i, spec, repo):
    name = f"repo-{i + 1}"
    c = Card(name, W, 150, f"{repo['name']} repository")
    c.frame()
    c.gradient("acc", "0", "1")
    c.add(f'<g class="a-grow" style="animation-delay:{c.d(0.1)}"><rect x="0" y="28" width="3.5" height="94" rx="1.75" fill="url(#acc)"/></g>')
    c.add(f'<g class="a-pop" style="animation-delay:{c.d(0.15)}">{icon("repo", 30, 26, 22)}</g>')
    c.text(62, 44, repo["name"].replace("_", " ").replace("-", " ") if spec.get("pretty") else repo["name"],
           "semi", 19, cls="a-up", delay=0.2, tracking=-0.01)
    c.add(f'<g class="a-fade" style="animation-delay:{c.d(0.3)}"><g class="a-nudge" style="animation-delay:{c.d(1.4)}">')
    c.add(icon("arrow", W - 50, 26, 20, C["text3"], 1.8))
    c.add("</g></g>")
    desc = spec.get("blurb") or repo.get("description") or "No description yet."
    for j, ln in enumerate(wrap(desc, "sans", 14.5, W - 92, 2)):
        c.text(30, 76 + j * 22, ln, "sans", 14.5, C["text2"], cls="a-up", delay=0.3 + j * 0.06)
    # meta row
    y, x = 128, 30
    c.add(f'<g class="a-up" style="animation-delay:{c.d(0.5)}">')
    lang = repo.get("primaryLanguage")
    if lang:
        c.add(f'<circle cx="{x + 5}" cy="{y - 4}" r="5" fill="{lang.get("color") or C["violet"]}"/>')
        c.text(x + 16, y, lang["name"], "sans", 12.5, C["text2"])
        x += 16 + text_width(lang["name"], "sans", 12.5) + 22
    c.add(f'<path transform="translate({x} {y - 12}) scale(.9)" d="{STAR}" fill="none" stroke="{C["text3"]}" stroke-width="1.4" stroke-linejoin="round"/>')
    c.text(x + 18, y, str(repo["stargazerCount"]), "sans", 12.5, C["text2"])
    x += 18 + text_width(str(repo["stargazerCount"]), "sans", 12.5) + 20
    c.add(f'<g transform="translate({x} {y - 12}) scale(.85)" fill="none" stroke="{C["text3"]}" stroke-width="1.5" stroke-linecap="round">{FORK}</g>')
    c.text(x + 17, y, str(repo["forkCount"]), "sans", 12.5, C["text2"])
    x += 17 + text_width(str(repo["forkCount"]), "sans", 12.5) + 20
    pushed = dt.datetime.fromisoformat(repo["pushedAt"].replace("Z", "+00:00"))
    c.text(x, y, f"Updated {pushed.strftime('%b %Y')}", "sans", 12.5, C["text3"])
    c.add("</g>")
    # tag chips, right-aligned
    rx = W - 30
    for k, tag in enumerate(reversed(spec.get("tags", []))):
        tw = text_width(tag, "mono", 10.5, 0.04) + 20
        rx -= tw
        c.add(f'<g class="a-pop" style="animation-delay:{c.d(0.6 + k * 0.08)}">')
        c.add(f'<rect x="{rx:.1f}" y="{y - 16}" width="{tw:.1f}" height="22" rx="11" fill="{C["violet"]}" fill-opacity=".12" stroke="{C["violet"]}" stroke-opacity=".3"/>')
        c.text(rx + tw / 2, y - 1, tag, "mono", 10.5, C["violet_l"], anchor="middle", tracking=0.04)
        c.add("</g>")
        rx -= 8
    c.save()


def graph(weeks, total):
    flat = [n for w in weeks for _, n, _ in w if n]
    flat.sort()

    def level(n):
        if n == 0:
            return 0
        if len(flat) < 4:
            return 4 if n == flat[-1] else 3
        q = [flat[int(len(flat) * p)] for p in (0.25, 0.5, 0.75)]
        return 1 + sum(n > t for t in q)

    first = weeks[0][0][0]
    last = weeks[-1][-1][0]
    c = Card("graph", W, 214, "Contribution graph")
    c.frame()
    c.text(32, 42, "Contribution graph", "semi", 16, cls="a-up", delay=0.1, tracking=-0.01)
    c.text(W - 32, 42, f"{total:,} contributions · {first.strftime('%b %Y')} – {last.strftime('%b %Y')}",
           "mono", 11, C["text3"], anchor="end", cls="a-up", delay=0.15, tracking=0.04, upper=True)
    cell, step = 11, 14
    gx = (W - (len(weeks) * step - (step - cell))) / 2 + 10
    gy = 74
    # weekday labels
    for row, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        c.text(gx - 10, gy + row * step + 9, name, "mono", 9.5, C["text3"], anchor="end", cls="a-fade", delay=0.2)
    b = stats([d for w in weeks for d in w])["busiest"]  # same tie-break as the activity card
    busiest = (b[0], b[1]) if b else (None, 0)
    seen = set()
    for wi, week in enumerate(weeks):
        x = gx + wi * step
        d0 = week[0][0]
        if d0.day <= 7 and (d0.year, d0.month) not in seen and wi < len(weeks) - 1:
            seen.add((d0.year, d0.month))
            c.text(x, gy - 10, d0.strftime("%b"), "mono", 9.5, C["text3"], cls="a-fade", delay=0.2 + wi * 0.012)
        c.add(f'<g class="a-up" style="animation-delay:{c.d(0.25 + wi * 0.014)}">')
        for d, n, wd in week:
            y = gy + wd * step
            lv = level(n)
            stroke = ' stroke="#ffffff" stroke-opacity=".06"' if lv == 0 else ""
            c.add(f'<rect x="{x:.1f}" y="{y}" width="{cell}" height="{cell}" rx="2.5" fill="{HEAT[lv]}"{stroke}/>')
        c.add("</g>")
    if busiest[1]:
        bd = busiest[0]
        wi = next(i for i, w in enumerate(weeks) if any(d == bd for d, _, _ in w))
        bx, by = gx + wi * step - 2, gy + bd.isoweekday() % 7 * step - 2
        c.add(f'<rect class="a-pop" style="animation-delay:{c.d(1.2)}" x="{bx:.1f}" y="{by}" width="{cell + 4}" height="{cell + 4}" '
              f'rx="4" fill="none" stroke="{C["violet_l"]}" stroke-width="1.3"/>')
    # legend
    lx = W - 32 - 5 * step - 34
    ly = gy + 7 * step + 18
    c.add(f'<g class="a-fade" style="animation-delay:{c.d(1)}">')
    c.text(lx - 8, ly + 9, "Less", "mono", 9.5, C["text3"], anchor="end")
    for k, col in enumerate(HEAT):
        c.add(f'<rect x="{lx + k * step}" y="{ly}" width="{cell}" height="{cell}" rx="2.5" fill="{col}"/>')
    c.text(lx + 5 * step + 4, ly + 9, "More", "mono", 9.5, C["text3"])
    c.add("</g>")
    c.save()


def main():
    days, weeks, repos, total = load_data()
    print(f"Rendering cards ({'static final frame' if STATIC else 'animated'}) -> {OUT.relative_to(ROOT)}/")
    hero()
    for t in TILES:
        tile(t)
    activity(days, total)
    for i, spec in enumerate(FEATURED):
        repo = repos.get(spec["name"])
        if repo is None:
            print(f"  skipped {spec['name']}: not in data/contributions.json", file=sys.stderr)
            continue
        repo_card(i, spec, repo)
    graph(weeks, total)
    write_preview()


def write_preview():
    """preview.html: the README's card markup in a ~830px GitHub-dark column,
    so the stack can be checked (and screenshotted in STATIC mode) before pushing."""
    import re

    body = re.sub(r"<!--.*?-->", "", (ROOT / "README.md").read_text(encoding="utf-8"), flags=re.S)
    (ROOT / "preview.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Profile preview</title>"
        "<style>body{margin:0;background:#0d1117;display:flex;justify-content:center;padding:32px 16px}"
        "main{width:830px;max-width:100%}img{display:block;margin:0 0 16px;max-width:100%}"
        "p{display:flex;justify-content:space-between;margin:0 0 16px}p img{margin:0}a{display:contents}</style>"
        f"<main>{body}</main>\n",
        encoding="utf-8",
    )
    print("  preview.html")


if __name__ == "__main__":
    main()
