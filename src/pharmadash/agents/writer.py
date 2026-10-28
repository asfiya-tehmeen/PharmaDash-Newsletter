"""Writer agent: turns a claims ledger into an article in the PharmaDash voice.

The model writes headline-to-closing-line only. Code adds the standard footer, the sources line and the disclaimer,
so those are always exact. A fix pass rewrites only the sentences the verifier flagged.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from pydantic import BaseModel

from .. import config, llm, style
from ..claims import DraftCheck, Ledger

PROMPT = Path(__file__).parent.parent / "prompts" / "writer.md"
FOOTER = ("*PharmaDash breaks down big pharma's financial performance, top drug results, and commercial developments. "
          "If this was useful, subscribe and share it with someone who watches this market.*")
OUTLETS = {"cnbc.com": "CNBC", "sec.gov": "SEC filings", "fda.gov": "FDA", "biopharmadive.com": "BioPharma Dive",
           "endpoints.news": "Endpoints News", "statnews.com": "STAT", "fiercepharma.com": "Fierce Pharma",
           "fiercebiotech.com": "Fierce Biotech", "reuters.com": "Reuters", "prnewswire.com": "PR Newswire",
           "businesswire.com": "Business Wire", "globenewswire.com": "GlobeNewswire", "clinicaltrials.gov": "ClinicalTrials.gov",
           "biospace.com": "BioSpace", "pharmaceutical-technology.com": "Pharmaceutical Technology"}


class Fix(BaseModel):
    original: str
    replacement: str


class Fixes(BaseModel):
    fixes: list[Fix]


def ledger_digest(ledger: Ledger, limit_chars: int = 4200, max_claims: int = 45) -> str:
    """Claims the writer may use. Verified primary figures first; conflicts included so the article can show both sides."""
    order = {"verified": 0, "single-source": 1, "conflict": 2, "unverified": 3}
    claims = sorted((c for c in ledger.claims if c.status != "unverified"), key=lambda c: (order[c.status], c.origin == "derived"))
    lines, size = [], 0
    for c in claims[:max_claims]:
        line = f"{c.id} | {c.claim[:170]} | as of {c.as_of or 'n/a'} | {c.status}, {c.source_type}"
        if c.status == "conflict":
            line += " | SOURCES DISAGREE: say so in the article"
        if c.quote:
            line += f' | quote: "{c.quote[:90]}"'
        size += len(line) + 1
        if size > limit_chars:
            break
        lines.append(line)
    return "\n".join(lines)


def outlet_names(ledger: Ledger) -> list[str]:
    seen = []
    for c in ledger.claims:
        host = re.sub(r"^www\.", "", urlparse(c.source_url).netloc.lower())
        if not host:
            continue
        name = next((n for d, n in OUTLETS.items() if host.endswith(d)), host)
        if c.source_note.startswith("SEC"):
            name = "SEC filings"
        if name not in seen:
            seen.append(name)
    return seen


def footer_block(ledger: Ledger, cfg: dict) -> str:
    sources = ", ".join(outlet_names(ledger)) or "company disclosures"
    caveat = ("Figures are as reported or announced and may vary by data provider and methodology; "
              "deal values may include milestone payments that may never be paid.")
    if any(c.status == "conflict" for c in ledger.claims):
        caveat = "Sources disagree on some figures; both are shown where relevant. " + caveat
    return (f"\n\n---\n\n{FOOTER}\n\n*Sources: {sources} (data as of {date.today().isoformat()}). {caveat} "
            f"{cfg.get('disclaimer', 'For information only; not investment advice.')}*\n")


def write_article(title: str, angle: str, ledger: Ledger, dashboards: list[tuple[str, str]],
                  log: Callable[[str], None] = print) -> str:
    """dashboards = [(file_stem, title), ...]. Returns the full article markdown including footer."""
    cfg = config.load_config()
    if not [c for c in ledger.claims if c.status != "unverified"]:
        raise ValueError("the claims ledger has no usable facts, so there is nothing to write from")
    lo, hi = cfg["article_word_target"]
    dash = "\n".join(f"- dashboards/{stem}.html : {t}" for stem, t in dashboards) or "- (none)"
    ask = (f"Today is {date.today().isoformat()}. Write the issue.\nWORKING TITLE: {title}\nANGLE: {angle}\n"
           f"LENGTH: {lo} to {hi} words.\nDASHBOARDS to point to:\n{dash}\n\nCLAIMS (the only facts you may use):\n{ledger_digest(ledger)}")
    log("writing the article...")
    resp = llm.chat(cfg["models"]["writer"], [{"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
                                              {"role": "user", "content": ask}], max_tokens=4200, temperature=0.5)
    text = (resp.choices[0].message.content or "").strip()
    text = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", text)
    start = text.find("# ")
    text = text[start:] if start >= 0 else text
    return style.clean_typography(text).rstrip() + footer_block(ledger, cfg)


def fix_flagged(article: str, flagged: list[DraftCheck], ledger: Ledger, log: Callable[[str], None] = print) -> tuple[str, int]:
    """Ask for replacement sentences for flagged ones. Returns (new article, number of sentences changed)."""
    cfg = config.load_config()
    seen, items = set(), []
    for c in flagged:
        if c.sentence and c.sentence not in seen:
            seen.add(c.sentence)
            items.append(f"- SENTENCE: {c.sentence}\n  PROBLEM: {c.text}: {c.notes or c.status}")
    if not items:
        return article, 0
    system = ("You correct sentences in a newsletter. For each flagged sentence return a corrected replacement that uses ONLY facts "
              "in the CLAIMS list. If the flagged number is not in the claims, remove it or write 'not disclosed'. If a deal value is "
              "flagged, state whether it is upfront, total including milestones, or as announced. Keep the voice and the markdown "
              "(bold, bullets). 'original' must be copied exactly from the sentence given.")
    res = llm.ask_json(cfg["models"]["writer"], system,
                       "CLAIMS:\n" + ledger_digest(ledger, 2800) + "\n\nFLAGGED:\n" + "\n".join(items[:8]), Fixes, max_tokens=1800)
    changed = 0
    for f in res.fixes:
        # the verifier stores sentences without markdown markers, so match on plain text and replace the marked-up original
        # bold markers (**) may sit anywhere in the article text, so allow them between any two characters
        pattern = r"[\s*]+".join(r"\**".join(re.escape(ch) for ch in w.strip("*")) for w in f.original.split())
        m = re.search(pattern, article)
        if m and f.replacement.strip() and f.replacement.strip() != f.original.strip():
            # keep the line's own markdown (italic dek, bold lead-in, list marker) exactly as it was
            start, end = m.start(), m.end()
            lead, trail = "", ""
            while start > 0 and article[start - 1] == "*":
                start, lead = start - 1, lead + "*"
            while end < len(article) and article[end] == "*":
                end, trail = end + 1, trail + "*"
            new = style.clean_typography(f.replacement.strip()).strip("*").strip()
            if (lead + new + trail).count("**") % 2:      # unbalanced bold would break the paste
                new = new.replace("**", "")
            article = article[:start] + lead + new + trail + article[end:]
            changed += 1
    log(f"  rewrote {changed} sentence(s)")
    return article, changed


def repair_structure(article: str, issues: list[str], ledger: Ledger, log: Callable[[str], None] = print) -> str:
    """One revision pass for house-format problems (too short, missing italic dek, ...). Facts must still come from the claims."""
    cfg = config.load_config()
    lo, hi = cfg["article_word_target"]
    ask = ("Revise this article so it fixes the problems below, keeping everything that is already correct. "
           f"Target {lo + 150} to {hi - 50} words. Use only facts from CLAIMS (you may add claims not yet used). Return the full article "
           "markdown from the '# Headline' line to the closing line, without footer or sources.\n\n"
           "PROBLEMS:\n" + "\n".join(f"- {i}" for i in issues) +
           "\n\nCLAIMS:\n" + ledger_digest(ledger, 2400) + "\n\nARTICLE:\n" + style.body_of(article))
    log("revising structure: " + "; ".join(issues))
    resp = llm.chat(cfg["models"]["writer"], [{"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
                                              {"role": "user", "content": ask}], max_tokens=4200, temperature=0.4)
    text = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", (resp.choices[0].message.content or "").strip())
    start = text.find("# ")
    text = text[start:] if start >= 0 else style.body_of(article)
    return style.clean_typography(text).rstrip() + footer_block(ledger, cfg)
