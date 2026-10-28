"""Dashboard agent: the model plans the content as JSON, code checks every figure against the ledger and builds the HTML.

A dashboard whose figures cannot be traced to the claims ledger is rejected, not published with a warning.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from .. import config, dashboards as DB, llm
from . import verifier
from ..claims import Ledger
from . import writer

PROMPT = Path(__file__).parent.parent / "prompts" / "dashboard.md"


class Concept(BaseModel):
    series: str
    headline: str
    chart_kind: str
    claim_ids: list[str]


class Concepts(BaseModel):
    items: list[Concept]


class Built(BaseModel):
    stem: str
    title: str
    path: str = ""
    problems: list[str] = []


def _stem(title: str, issue: int, n: int) -> str:
    return f"PharmaDash_{re.sub(r'[^A-Za-z0-9]+', '_', title).strip('_')[:40]}_{n}"


def plan_concepts(title: str, angle: str, ledger: Ledger, count: int) -> list[Concept]:
    cfg = config.load_config()
    res = llm.ask_json(cfg["models"]["dashboard"],
                       "You choose dashboard ideas for a pharma newsletter issue. Each idea is one page built from a few claims. "
                       "Pick ideas whose numbers are all in the CLAIMS list; prefer comparisons over time and rankings. Different ideas must show different things.",
                       f"ISSUE: {title}\nANGLE: {angle}\nReturn {count} dashboard ideas (series name like 'China Licensing Series', "
                       f"a headline, chart_kind bar|hbar|line, and the claim ids it will use).\n\nCLAIMS:\n{writer.ledger_digest(ledger, 3200)}",
                       Concepts, max_tokens=900)
    return res.items[:count]


def _ask_dash(concept: Concept, title: str, ledger: Ledger, issue: int, extra: str = "") -> DB.Dash:
    cfg = config.load_config()
    accents = ", ".join(DB.DEFAULT_ACCENTS)
    ask = (f"Today is {date.today().isoformat()}. ISSUE: {title}\nBuild this dashboard: series '{concept.series}', headline idea '{concept.headline}', "
           f"main chart kind {concept.chart_kind}. Issue number {issue}. file_stem: any short word (the program sets it).\n"
           f"Accent choices: {accents}\n\nCLAIMS (the only facts you may use):\n{writer.ledger_digest(ledger, 3600)}{extra}")
    return llm.ask_json(cfg["models"]["dashboard"], PROMPT.read_text(encoding="utf-8"), ask, DB.Dash, max_tokens=2600)


def prose_problems(d: DB.Dash, ledger: Ledger) -> list[str]:
    """Same number, ratio and deal-wording checks the article gets, applied to the dashboard's sentences (on a copy of the ledger)."""
    probe = ledger.model_copy(deep=True)
    verifier.verify_draft(DB.prose(d), probe, log=lambda s: None, use_model=False)
    title = (d.title_before + d.title_em + d.title_after).strip()
    long_title = [f"the headline is too long ({len(title)} characters, max 60); write a short punchy one, not the idea text"] if len(title) > 60 else []
    return long_title + [f"sentence '{c.sentence[:90]}': {c.notes or c.status}" for c in probe.draft_checks if c.status in ("unverified", "conflict") and c.kind in ("number", "derived")]


def make_dashboard(concept: Concept, title: str, ledger: Ledger, issue: int, n: int, out_dir: Path,
                   log: Callable[[str], None] = print) -> Built:
    """Plan, check against the ledger (one repair round), build. Returns problems instead of a path if it cannot be made safe."""
    log(f"dashboard {n}: {concept.headline}")
    extra, problems = "", []
    for attempt in range(2):
        try:
            d = _ask_dash(concept, title, ledger, issue, extra)
        except ValueError as e:
            problems = [f"the plan was invalid: {str(e)[:200]}"]
            extra = "\n\nYour last JSON was invalid: " + problems[0] + "\nFix it."
            continue
        d.file_stem, d.issue = _stem(concept.headline, issue, n), issue
        if d.accent not in DB.DEFAULT_ACCENTS:
            d.accent = DB.DEFAULT_ACCENTS[(n - 1) % len(DB.DEFAULT_ACCENTS)]
        DB.tidy(d)
        d.sources = "Figures from " + (", ".join(writer.outlet_names(ledger)[:5]) or "company disclosures") + f" (data as of {date.today().isoformat()})."
        problems = DB.check_against_ledger(d, ledger) + prose_problems(d, ledger)
        if not problems:
            path = DB.build(d, out_dir)
            lint = DB.lint_html(path.read_text(encoding="utf-8"))
            return Built(stem=d.file_stem, title=" ".join(x for x in (d.title_before + d.title_em + d.title_after).split()), path=str(path),
                         problems=[f"HTML rule: {x}" for x in lint])
        log(f"  {len(problems)} figure(s) not in the ledger; asking for a corrected version")
        extra = ("\n\nYour last version had figures that are not in the claims. Fix them (use a claim's own number, or remove the point):\n- "
                 + "\n- ".join(problems[:8]))
    return Built(stem=_stem(concept.headline, issue, n), title=concept.headline, problems=["REJECTED, not built: " + p for p in problems])


def make_dashboards(title: str, angle: str, ledger: Ledger, issue: int, out_dir: Path, count: int | None = None,
                    log: Callable[[str], None] = print) -> list[Built]:
    cfg = config.load_config()
    count = count or cfg.get("dashboards_per_issue", 2)
    log("planning dashboards...")
    built = []
    for n, concept in enumerate(plan_concepts(title, angle, ledger, count), 1):
        built.append(make_dashboard(concept, title, ledger, issue, n, out_dir, log))
    return built
