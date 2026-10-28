"""Dashboard builder. Pure code, no model calls: data JSON in, one standalone HTML file out.

Bar heights are parsed out of the label text ("$209B" -> 209), so a label and its bar can never disagree.
`check_against_ledger` makes sure every figure shown on the page exists in the claims ledger.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from . import checks
from .claims import Ledger

TPL = Path(__file__).parent / "templates"
TOKENS = json.loads((TPL / "tokens.json").read_text(encoding="utf-8"))
DEFAULT_ACCENTS = ["#10916B", "#1F5FE0", "#E5223C", "#7A3FF2", "#0CB5C4", "#D22A38", "#1C8C6A", "#C6893F"]
SCALE = {"B": 1e9, "M": 1e6, "K": 1e3, "T": 1e12}


class Point(BaseModel):
    label: str
    text: str = Field(description='Label exactly as shown on the chart, e.g. "$209B", "~$150B" or "n/d"')
    style: Literal["actual", "approx", "projected", "nd"] = "actual"
    claim: str = Field("", description="Ledger claim id this figure comes from")
    booked_text: str = Field("", description="Projected bars only: the part already booked, e.g. $106B")
    highlight: bool = False
    value: float = 0.0          # filled by code from `text`
    booked: Optional[float] = None


class Ref(BaseModel):
    text: str
    label: str
    value: float = 0.0
    claim: str = ""


class Chart(BaseModel):
    kind: Literal["bar", "hbar", "line"] = "bar"
    title: str
    unit_label: str = Field("", description='Shown after the title, e.g. "$ billions per year"')
    prefix: str = ""
    suffix: str = ""
    actual_label: str = "Reported"
    points: list[Point]
    ref: Optional[Ref] = None

    @model_validator(mode="after")
    def _parse(self):
        if not 1 <= len(self.points) <= 8:
            raise ValueError("a chart needs 1 to 8 points")
        for p in self.points:
            p.value = 0.0 if p.style == "nd" else parse_amount(p.text, self.suffix)
            if p.booked_text:
                p.booked = parse_amount(p.booked_text, self.suffix)
        if self.ref:
            self.ref.value = parse_amount(self.ref.text, self.suffix)
        return self


class Kpi(BaseModel):
    label: str
    value: str
    delta: str = ""
    sub: str
    gold: bool = False
    claim: str = ""


class Reading(BaseModel):
    lead: str
    text: str


class Dash(BaseModel):
    file_stem: str
    series: str
    issue: int
    title_before: str = ""
    title_em: str
    title_after: str = ""
    dek: str
    accent: str = "#10916B"
    panel: str = TOKENS["default_panel"]
    kpis: list[Kpi]
    chart: Chart
    mini: Optional[Chart] = None
    mini_title: str = ""
    mini_caption: str = ""
    reading_title: str = "Reading the numbers"
    reading: list[Reading]
    sources: str
    caveat: str

    @model_validator(mode="after")
    def _shape(self):
        if len(self.kpis) != 4:
            raise ValueError("a dashboard has exactly 4 KPI cards")
        if len(self.reading) != 4:
            raise ValueError("the Reading block has exactly 4 bullets")
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", self.accent):
            raise ValueError("accent must be a #RRGGBB colour")
        if self.panel not in TOKENS["panel_shades"]:
            self.panel = TOKENS["default_panel"]
        return self


def parse_amount(text: str, suffix: str = "") -> float:
    """'$209B' -> 209 when the chart suffix is B. Percent and plain numbers are returned as written."""
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(trillion|billion|million|thousand|[BMKT])?\b", text.replace("~", ""), re.I)
    if not m:
        raise ValueError(f"no number in chart label {text!r}")
    v = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "")
    unit = {"trillion": "T", "billion": "B", "million": "M", "thousand": "K"}.get(unit.lower(), unit.upper())
    if unit and suffix.upper() in SCALE and unit != suffix.upper():      # label says $1.2T on a chart drawn in B
        v = v * SCALE[unit] / SCALE[suffix.upper()]
    return v


def _rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mix(hex_: str, other: tuple[int, int, int], t: float) -> str:
    r, g, b = _rgb(hex_)
    return "#%02X%02X%02X" % tuple(round(c + (o - c) * t) for c, o in zip((r, g, b), other))


def tidy(d: Dash) -> Dash:
    """Code-side clean-up of model text: no claim ids on the page, spaces around the highlighted title words."""
    ids = re.compile(r"\(?\bC\d{3}\b\)?\s*[–—-]?\s*")
    for k in d.kpis:
        k.sub, k.label = ids.sub("", k.sub).strip(), ids.sub("", k.label).strip()
    for r in d.reading:
        r.lead, r.text = ids.sub("", r.lead).strip(), ids.sub("", r.text).strip()
    d.dek, d.mini_caption = ids.sub("", d.dek).strip(), ids.sub("", d.mini_caption).strip()
    d.title_before, d.title_em, d.title_after = d.title_before.lstrip(), d.title_em.strip(), d.title_after.rstrip()
    if d.title_before and not d.title_before.endswith(" "):
        d.title_before += " "
    if d.title_after and d.title_after[0].isalnum():
        d.title_after = " " + d.title_after
    return d


def prose(d: Dash) -> str:
    """All sentences the model wrote (dek, KPI sub-lines, caption, Reading), one per line, for the fact-check."""
    lines = [d.dek] + [f"{k.label}: {k.value} {k.sub}." for k in d.kpis] + ([d.mini_caption] if d.mini_caption else [])
    lines += [f"{r.lead} {r.text}" for r in d.reading]
    return chr(10).join(x for x in lines if x.strip())


def _e(s: str) -> str:
    return html.escape(s, quote=True)


def _legend(c: Chart) -> str:
    seen = {p.style for p in c.points}
    items = [f'<span class="lg"><span class="sw" style="background:var(--accent)"></span> {_e(c.actual_label)}</span>'] if "actual" in seen or not seen else []
    if "approx" in seen:
        items.append('<span class="lg"><span class="sw" style="background:var(--accent);opacity:.62;border:1px dashed var(--accent-light)"></span> Approximate</span>')
    if "projected" in seen:
        items.append('<span class="lg"><span class="sw hatch"></span> Projected</span>')
    if "nd" in seen:
        items.append('<span class="lg"><span class="sw" style="border:1px dashed #6F7E90"></span> Not disclosed</span>')
    return "".join(items)


def _aria(c: Chart, what: str) -> str:
    parts = []
    for p in c.points:
        suffix = {"approx": " (approximate)", "projected": " (projected)", "nd": " (not disclosed)"}.get(p.style, "")
        parts.append(f"{p.label}: {p.text}{suffix}")
    return f"{c.kind.replace('hbar', 'Horizontal bar').replace('bar', 'Bar').replace('line', 'Line')} chart of {what}. " + "; ".join(parts) + "."


def render(d: Dash) -> str:
    """Return the complete standalone HTML page."""
    css = (TPL / "base.css").read_text(encoding="utf-8")
    r, g, b = _rgb(d.accent)
    for k, v in {"{{ACCENT}}": d.accent, "{{ACCENT_SOFT}}": _mix(d.accent, (255, 255, 255), .82), "{{PANEL}}": d.panel,
                 "{{ACCENT_RGB}}": f"{r},{g},{b}"}.items():
        css = css.replace(k, v)
    light = _mix(d.accent, (255, 255, 255), .45)
    css += (f"\n:root{{--accent-light:{light}}}\n.lg .sw.hatch{{background:repeating-linear-gradient(45deg,var(--accent),var(--accent) 3px,transparent 3px,transparent 6px);"
            "border:1px dashed var(--accent)}\n.kpi .val .pct{font-size:14px}\n.grid2.single{grid-template-columns:1fr}\n")
    data = {"accent": d.accent, "accentLight": light, "accentRgb": f"{r},{g},{b}", "gold": "#D99A0B",
            "chart": d.chart.model_dump(), "mini": d.mini.model_dump() if d.mini else None}
    fonts = TOKENS["fonts"]["google_css"]
    kpis = "\n".join(
        f'    <div class="kpi{" gold" if k.gold else ""}"><div class="lab">{_e(k.label)}</div>'
        f'<div class="val">{_e(k.value)}' + (f' <span class="pct">{_e(k.delta)}</span>' if k.delta else "") +
        f'</div><div class="sub">{_e(k.sub)}</div></div>' for k in d.kpis)
    reading = "\n".join(f"        <li><b>{_e(x.lead)}</b> {_e(x.text)}</li>" for x in d.reading)
    mini = ""
    if d.mini:
        mini = (f'    <div class="mini">\n      <p class="blocktitle">{_e(d.mini_title or d.mini.title)}</p>\n'
                f'      <svg class="mini-svg" id="mini" viewBox="0 0 360 200" role="img" aria-label="{_e(_aria(d.mini, d.mini.title))}"></svg>\n'
                f'      <p class="cap">{_e(d.mini_caption)}</p>\n    </div>\n')
    title_html = f'{_e(d.title_before)}<span class="em">{_e(d.title_em)}</span>{_e(d.title_after)}'
    page_title = re.sub(r"\s+", " ", f"{d.title_before}{d.title_em}{d.title_after}").strip()
    js = (TPL / "dashboard.js").read_text(encoding="utf-8")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PharmaDash — {_e(page_title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{fonts}" rel="stylesheet">
<style>
{css}</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">PharmaDash · {_e(d.series)} · Issue {d.issue:02d}</div>
  <h1>{title_html}</h1>
  <p class="dek">{_e(d.dek)}</p>

  <div class="kpis">
{kpis}
  </div>

  <div class="panel">
    <div class="panel-top">
      <div class="ptitle"><b>{_e(d.chart.title)}</b>{(" &nbsp;·&nbsp; " + _e(d.chart.unit_label)) if d.chart.unit_label else ""}</div>
      <div class="legend">{_legend(d.chart)}</div>
    </div>
    <svg class="chart" id="chart" viewBox="0 0 920 430" role="img" aria-label="{_e(_aria(d.chart, d.chart.title))}"></svg>
  </div>

  <div class="grid2{"" if d.mini else " single"}">
{mini}    <div class="read">
      <p class="blocktitle">{_e(d.reading_title)}</p>
      <ul>
{reading}
      </ul>
    </div>
  </div>

  <footer>
    <span class="foot-brand">PharmaDash</span> &nbsp;·&nbsp; <b>Sources:</b> {_e(d.sources)} <b>Note:</b> {_e(d.caveat)}
  </footer>
</div>

<script>
window.__DASH__ = {json.dumps(data, ensure_ascii=False).replace("</", "<\\/")};
</script>
<script>
{js}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------- checks

def _figure_ok(text: str, claim_id: str, ledger: Ledger) -> str:
    """'' if the figure in `text` exists in the ledger (in the named claim when given), else a short problem."""
    nums = checks.extract_numbers(text)
    if not nums:
        return ""      # plain small counts and "n/d" cannot be matched reliably; they are shown in the report as unchecked
    by_id = {c.id: c for c in ledger.claims}
    for n in nums:
        hits, scale_err = checks.match_to_ledger(n, ledger)
        if claim_id and claim_id in by_id and by_id[claim_id] not in hits:
            if hits:
                return f"{text}: the figure exists in the ledger, but not in the cited claim {claim_id}"
            return f"{text}: not found in cited claim {claim_id}" + (" (unit looks off by 1,000x)" if scale_err else "")
        if not hits:
            return f"{text}: not found in the ledger" + (" (unit looks off by 1,000x)" if scale_err else "")
    return ""


def check_against_ledger(d: Dash, ledger: Ledger) -> list[str]:
    """Every figure on the page must be in the ledger. Approximate bars (style=approx) are allowed only if the ledger has them too."""
    problems = []
    for k in d.kpis:
        for t in [k.value] + ([k.delta] if k.delta else []):
            p = _figure_ok(t, k.claim if t == k.value else "", ledger)
            if p:
                problems.append(f"KPI '{k.label}': {p}")
    for name, c in (("chart", d.chart), ("mini chart", d.mini)):
        if not c:
            continue
        for p in c.points:
            if p.style == "nd":
                continue
            msg = _figure_ok(p.text, p.claim, ledger)
            if msg:
                problems.append(f"{name} point {p.label}: {msg}")
            if p.booked_text:
                msg = _figure_ok(p.booked_text, "", ledger)
                if msg:
                    problems.append(f"{name} point {p.label} (booked): {msg}")
        if c.ref:
            msg = _figure_ok(c.ref.text, c.ref.claim, ledger)
            if msg:
                problems.append(f"{name} reference line: {msg}")
    return problems


def lint_html(page: str) -> list[str]:
    """Rules every dashboard must meet, checked on the final HTML."""
    issues = []
    if re.search(r"<script[^>]+src=", page, re.I):
        issues.append("external script found (dashboards must be self-contained)")
    for lib in ("chart.js", "d3.", "plotly", "highcharts", "echarts", "apexcharts"):
        if lib in page.lower():
            issues.append(f"chart library reference: {lib}")
    for needed in ("viewBox", "aria-label", "prefers-reduced-motion", "Space Grotesk", "max-width:1060px", "@media(max-width:780px)"):
        if needed not in page:
            issues.append(f"missing {needed}")
    if "{{" in page:
        issues.append("unfilled template placeholder")
    return issues


def build(d: Dash, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{d.file_stem}.data.json").write_text(d.model_dump_json(indent=2), encoding="utf-8")
    path = out_dir / f"{d.file_stem}.html"
    path.write_text(render(d), encoding="utf-8")
    return path
