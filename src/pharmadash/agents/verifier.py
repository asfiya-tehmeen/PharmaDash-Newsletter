"""Verifier agent. Code does the number matching and arithmetic; the model only judges meaning.

It sees the draft text and the claims ledger, never the writer's reasoning.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel

from .. import checks, config, llm, style
from ..claims import DraftCheck, Ledger

PROMPT = Path(__file__).parent.parent / "prompts" / "verifier.md"
RANK = {"verified": 3, "single-source": 2, "unverified": 1, "conflict": 0}


class Verdict(BaseModel):
    n: int
    verdict: Literal["supports", "contradicts", "unclear"]
    note: str = ""


class Verdicts(BaseModel):
    items: list[Verdict]


class NamedFact(BaseModel):
    sentence: str
    supported_by: list[str]


class NamedFacts(BaseModel):
    items: list[NamedFact]


def _headline_chars(draft: str) -> int:
    """Everything before the first '---' rule (title and dek) counts as headline text."""
    m = re.search(r"^\s*---\s*$", draft, re.M)
    return m.start() if m else min(len(draft), 600)


def _ledger_digest(ledger: Ledger, limit: int = 2600) -> str:
    out, size = [], 0
    for c in ledger.claims:
        line = f"{c.id}: {c.claim[:140]}"
        size += len(line) + 1
        if size > limit:
            break
        out.append(line)
    return "\n".join(out)


def verify_draft(draft: str, ledger: Ledger, log: Callable[[str], None] = print, use_model: bool = True) -> list[DraftCheck]:
    """Check every number and wording rule in `draft`. Updates `ledger` (statuses, notes, draft_checks) and returns the checks."""
    by_id = {c.id: c for c in ledger.claims}
    ledger.draft_checks = []
    draft = style.clean_typography(style.body_of(draft))   # the standard footer is not article content

    # 1. ledger self-checks (pure code)
    for problem in checks.recompute_derived(ledger):
        ledger.notes.append(f"ARITHMETIC: {problem}")
    corroborated = checks.corroborate(ledger)
    if corroborated:
        log(f"  {corroborated} claim(s) upgraded: confirmed by two independent sources")
    for a, b in checks.find_conflicts(ledger):
        for c in (a, b):
            c.status = "conflict"
            c.notes = (c.notes + f" Disagrees with {b.id if c is a else a.id} ({a.value} vs {b.value} {a.unit}); the article must show both.").strip()
        ledger.notes.append(f"CONFLICT: {a.id} vs {b.id}: {a.claim[:70]} ({a.value} vs {b.value} {a.unit})")

    # 2. every number in the draft
    head = _headline_chars(draft)
    seen = set()
    for n in checks.extract_numbers(draft, head):
        key = (n.text, n.sentence)
        if key in seen:
            continue
        seen.add(key)
        hits, scale_err = checks.match_to_ledger(n, ledger)
        chk = DraftCheck(text=n.text, sentence=n.sentence[:220], in_headline=n.in_headline)
        if hits:
            words = set(re.findall(r"[a-z]{4,}", n.sentence.lower()))
            hits.sort(key=lambda c: -len(words & set(re.findall(r"[a-z]{4,}", c.claim.lower()))))   # most relevant claim first
            chk.matched = [c.id for c in hits]
            chk.status = max((c.status for c in hits), key=lambda s: RANK[s])
            if any(c.status == "conflict" for c in hits):
                chk.status, chk.notes = "conflict", "Ledger holds conflicting figures for this; the article must say so."
            elif n.approx and chk.status == "verified":
                chk.notes = "approximate in the article; ledger value is exact"
        elif scale_err:
            chk.status, chk.notes = "conflict", "Digits match a ledger figure but the unit is off by 1,000x (million vs billion?)."
        else:
            result, co, cn, computed = checks.derive_percent(n, ledger)
            if result == "match":
                chk.kind, chk.matched = "derived", [co.id, cn.id]
                ok = all(by_id[i].status == "verified" for i in chk.matched)
                chk.status = "verified" if ok else "single-source"
                chk.notes = f"recomputed in code: ({cn.value} - {co.value}) / {co.value} = {computed[0]}% (from {co.id} and {cn.id})"
            elif result == "mismatch":
                chk.status = "conflict"
                chk.notes = ("The ledger figures in this sentence give " + " or ".join(f"{abs(c)}%" for c in dict.fromkeys(computed)) +
                             f", not {n.text}. Recomputed in code.")
            else:
                chk.notes = ("No ledger claim contains this number, and it cannot be derived from two ledger figures in the same sentence."
                             if n.kind == "pct" else "No ledger claim contains this number.")
        if chk.in_headline and chk.status != "verified" and chk.status != "conflict":
            chk.notes = (chk.notes + " Headline/dek figures need a primary source or two independent sources.").strip()
            chk.status = "unverified" if chk.status == "unverified" else "single-source"
        ledger.draft_checks.append(chk)

    # 2b. multiplier wording ("almost four times", "tenfold") must be backed by two figures in the same sentence
    done = set()
    for _, sent in checks._sentences(draft):
        if sent in done:
            continue
        done.add(sent)
        for problem in checks.ratio_issues(sent, ledger):
            ledger.draft_checks.append(DraftCheck(text=problem[:80], sentence=sent[:220], kind="number", status="conflict",
                                                  notes=f"Multiplier claim: {problem}. Recomputed in code."))

    # 3. deal-value wording
    for sent in checks.deal_wording_issues(draft):
        ledger.draft_checks.append(DraftCheck(
            text=sent[:80], sentence=sent, kind="deal-wording", status="unverified",
            notes="Deal value without saying upfront / total / milestone-dependent / 'as announced', or announced vs closed."))

    # 4. model pass: does the sentence MEAN what the ledger claim says? plus non-numeric assertions
    if use_model and ledger.claims:
        try:
            _semantic_pass(draft, ledger, log)
        except (llm.DailyLimitReached, llm.BudgetExceeded) as e:
            ledger.notes.append(f"Meaning check skipped ({e}). Numbers were matched by code only.")
        except (ValueError, llm.RequestTooLarge) as e:
            ledger.notes.append(f"Meaning check incomplete: {e}")
    elif use_model:
        ledger.notes.append("No ledger claims to compare against; every number is unverified.")

    for i, c in enumerate(ledger.draft_checks, 1):
        c.id = f"D{i:03d}"
    return ledger.draft_checks


def _semantic_pass(draft: str, ledger: Ledger, log: Callable[[str], None]) -> None:
    cfg = config.load_config()
    system = PROMPT.read_text(encoding="utf-8")
    by_id = {c.id: c for c in ledger.claims}

    matched = [c for c in ledger.draft_checks if c.matched and c.kind == "number"]
    for start in range(0, len(matched), 8):
        batch = matched[start:start + 8]
        lines = [f"{i}) DRAFT: {c.sentence[:200]}\n   LEDGER {c.matched[0]}: {by_id[c.matched[0]].claim[:200]} (as of {by_id[c.matched[0]].as_of})"
                 for i, c in enumerate(batch, 1)]
        log(f"  meaning check, batch {start // 8 + 1}...")
        res = llm.ask_json(cfg["models"]["verifier"], system,
                           "For each numbered pair say whether the DRAFT sentence is supported, contradicted, or unclear "
                           "given the LEDGER claim.\n\n" + "\n".join(lines), Verdicts, max_tokens=1200)
        for v in res.items:
            if 1 <= v.n <= len(batch):
                c = batch[v.n - 1]
                if v.verdict == "contradicts" and not v.note.strip():
                    v = Verdict(n=v.n, verdict="unclear", note="model objected but gave no reason; check by hand")
                if v.verdict == "contradicts":
                    c.status, c.notes = "conflict", f"Meaning differs from {c.matched[0]}: {v.note}"
                elif v.verdict == "unclear" and v.note.strip():
                    c.notes = (c.notes + f" Meaning unclear vs {c.matched[0]}: {v.note}").strip()
                    if c.status == "verified":
                        c.status = "single-source"

    digest = _ledger_digest(ledger)
    body = re.sub(r"\n+", "\n", draft)
    chunks = [body[i:i + 2200] for i in range(0, min(len(body), 8800), 2200)]
    for k, chunk in enumerate(chunks, 1):
        log(f"  named-fact check, part {k} of {len(chunks)}...")
        res = llm.ask_json(cfg["models"]["verifier"], system,
                           f"LEDGER:\n{digest}\n\nDRAFT PART:\n{chunk}\n\nList up to 6 non-numeric factual assertions "
                           "(rankings, firsts, named deals/approvals/launches, who did what). For each give the sentence and the "
                           "ledger ids that support it (empty list if none).", NamedFacts, max_tokens=1200)
        for f in res.items:
            ids = [i for i in f.supported_by if i in by_id]
            status = max((by_id[i].status for i in ids), key=lambda s: RANK[s]) if ids else "unverified"
            ledger.draft_checks.append(DraftCheck(
                text=f.sentence[:90], sentence=f.sentence[:220], kind="named-fact", matched=ids, status=status,
                notes="" if ids else "No ledger claim supports this assertion."))


def failures(ledger: Ledger) -> list[DraftCheck]:
    """Checks the writer must fix (or the editor must look at): unverified, conflicting, or weak headline figures."""
    return [c for c in ledger.draft_checks if c.status in ("unverified", "conflict") or (c.in_headline and c.status != "verified")]
