"""Researcher agent: finds primary sources, reads the pages itself, and keeps only claims it can prove with a quote."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from .. import config, llm
from ..claims import Claim, Ledger, source_type
from ..tools import webpage

PROMPT = Path(__file__).parent.parent / "prompts" / "researcher.md"


class RawClaim(BaseModel):
    claim: str
    value: str
    unit: str
    as_of: str
    quote: str


class RawClaims(BaseModel):
    claims: list[RawClaim]


def _norm(s: str) -> str:
    for a, b in ((" ", " "), (" ", " "), ("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                 ("–", "-"), ("—", "-"), ("‑", "-")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).lower().strip()


def _numbers(s: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", s.replace(",", ""))


def accept(raw: RawClaim, page: str) -> tuple[bool, str]:
    """A claim is kept only if its quote is on the page, the quote is short, and the claim's number is in the quote."""
    q = _norm(raw.quote)
    if not q or q not in _norm(page):
        return False, "quote not found on page"
    if len(q.split()) > 25:
        return False, "quote longer than 25 words"
    nums = _numbers(raw.value)
    if nums and not all(n in _numbers(raw.quote) for n in nums):
        return False, "number not in quote"
    return True, ""


def pick_urls(candidates: list[str], company_words: list[str], already: set[str], limit: int) -> list[str]:
    """Primary sources first, then the rest in the order given."""
    seen, ranked = set(), []
    for u in candidates:
        if u in seen or u in already or not u.startswith("http"):
            continue
        seen.add(u)
        ranked.append(u)
    ranked.sort(key=lambda u: source_type(u, company_words)[0] != "primary")   # stable sort keeps given order
    return ranked[:limit]


def extract_from_page(url: str, topic: str, ledger: Ledger, company_words: list[str], cfg: dict,
                      log: Callable[[str], None]) -> None:
    text = webpage.page_text(url)
    if not text:
        ledger.pages_blocked.append(url)
        log(f"  could not read {url[:70]} (blocked or unavailable); skipped")
        return
    ledger.pages_read.append(url)
    stype, snote = source_type(url, company_words)
    ask = f"Topic: {topic}\nPage URL: {url}\n\nPAGE TEXT:\n{text}"
    try:
        raws = llm.ask_json(cfg["models"]["research"], PROMPT.read_text(encoding="utf-8"), ask, RawClaims, max_tokens=2500).claims
    except ValueError as e:
        ledger.notes.append(f"Could not extract claims from {url}: {e}")
        return
    kept = 0
    for r in raws:
        ok, why = accept(r, text)
        if not ok:
            ledger.notes.append(f"Rejected claim from {url} ({why}): {r.claim[:90]}")
            continue
        ledger.add(Claim(claim=r.claim, value=r.value, unit=r.unit, as_of=r.as_of, source_url=url, source_type=stype,
                         source_note=snote, status="single-source", quote=r.quote, origin="web"))
        kept += 1
    log(f"  {url[:70]}: kept {kept} of {len(raws)} claims")


def research(topic: str, known_urls: list[str], ledger: Ledger, company_words: list[str],
             log: Callable[[str], None] = print, max_pages: int = 4) -> None:
    cfg = config.load_config()
    log("searching for primary sources (press release / SEC / FDA)...")
    try:
        found = llm.web_search("For this story find the company press release, SEC filing or regulator page with the exact figures, "
                               f"and give the full URLs: {topic}")
    except llm.DailyLimitReached:
        found = ""
        ledger.notes.append("Web search skipped: Groq daily limit reached for search models. Used only the source links found in discovery.")
        log("  web search unavailable today (daily limit); using discovery links only")
    found_urls = [u.rstrip(".,);]") for u in re.findall(r"https?://[^\s)\]>]+", found)]
    ledger.notes.append(f"Web search ({date.today().isoformat()}) returned {len(found_urls)} URL(s).")
    urls = pick_urls(found_urls + known_urls, company_words, set(ledger.pages_read), max_pages)
    for u in urls:
        extract_from_page(u, topic, ledger, company_words, cfg, log)
