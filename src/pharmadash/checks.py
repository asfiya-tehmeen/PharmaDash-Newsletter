"""Code-only fact checks: number extraction, ledger matching, arithmetic, conflicts, corroboration, deal wording.

Nothing here calls a model. Every check is deterministic and unit-tested.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations

from . import calc
from .claims import Claim, Ledger

SCALES = {"trillion": 1e12, "tn": 1e12, "t": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9,
          "million": 1e6, "mn": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}
MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()
URL = re.compile(r"https?://\S+|\]\([^)]*\)")
NUM = re.compile(
    r"(?P<pre>[~≈]|about |around |roughly |nearly |over |up to |more than )?"
    r"(?P<cur>US\$|\$|€|£)?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s?(?P<scale>trillion|billion|million|thousand|bn|tn|mn)\b|(?P<scale2>[BMKT])\b)?"
    r"(?P<pct>\s?%|\s?percent\b)?", re.I)


@dataclass
class Num:
    text: str            # as written, e.g. "$19.8 billion"
    value: float         # normalized: dollars, or percent points, or a plain count
    kind: str            # money | pct | count
    precision: float     # half a unit of the last shown digit, in normalized units
    sentence: str = ""
    approx: bool = False
    in_headline: bool = False
    pos: int = 0


def _sentences(text: str) -> list[tuple[int, str]]:
    out, pos = [], 0
    for part in re.split(r"(?<=[.!?])\s+|\n+", text):
        if part.strip():
            out.append((text.find(part, pos), part.strip()))
            pos = max(pos, text.find(part, pos))
    return out


def extract_numbers(text: str, headline_chars: int = 0) -> list[Num]:
    """Every checkable number in `text`. Years, dates, 'Q3', 'Issue 5', list markers and small plain counts are skipped."""
    clean = URL.sub(lambda m: " " * len(m.group(0)), text)
    clean = re.sub(r"^\s*\d+\.\s", lambda m: " " * len(m.group(0)), clean, flags=re.M)   # numbered list markers
    found = []
    for m in NUM.finditer(clean):
        raw = m.group("num")
        before = clean[max(0, m.start("num") - 8):m.start("num")].lower()
        after = clean[m.end():m.end() + 12]
        if re.search(r"[A-Za-z]-$", before):                                                  # product codes like SSGJ-707
            continue
        if re.search(r"(q|fy|issue|#|no\.|h)\s?$", before) or re.match(r"^[-–]?(?:q[1-4]|h[12])\b", after, re.I):
            continue
        if re.search(r"(" + "|".join(MONTHS) + r")[a-z]*\.?\s?$", before):                  # "July 1"
            continue
        scale_word = (m.group("scale") or m.group("scale2") or "").lower()
        has_pct = bool(m.group("pct")) or bool(re.match(r"\s?[-–]\s?\d+(?:\.\d+)?\s?(?:%|percent)", after))   # "60-70%"
        has_cur = bool(m.group("cur"))
        num = float(raw.replace(",", ""))
        if not (has_cur or has_pct or scale_word):
            if re.fullmatch(r"(19|20)\d\d", raw) or num <= 12:                               # years and tiny counts
                continue
            if re.match(r"\s?(th|st|nd|rd)\b", after):
                continue
        scale = SCALES.get(scale_word, 1)
        dec = len(raw.split(".")[1]) if "." in raw else 0
        value = num * scale
        kind = "pct" if has_pct else ("money" if has_cur or (scale_word and has_cur) else "count")
        if kind == "count" and scale_word:
            kind = "count"
        precision = 0.5 * (10 ** -dec) * (1 if kind == "pct" else scale)
        shown = clean[m.start():m.end()].strip()
        found.append(Num(text=shown, value=value, kind=kind, precision=precision,
                         approx=bool(m.group("pre")) and m.group("pre").strip() in ("~", "≈", "about", "around", "roughly", "nearly"),
                         in_headline=m.start() < headline_chars, pos=m.start()))
    for n in found:
        for start, sent in _sentences(text):
            if start <= n.pos < start + len(sent) + 1:
                n.sentence = sent
                break
    return found


def claim_candidates(c: Claim) -> list[Num]:
    """Numbers a ledger claim can be matched against: those in its text plus its normalized value."""
    cands = extract_numbers(c.claim)
    cands += extract_numbers(c.quote) if c.quote else []
    v = c.value.replace(",", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", v)
    if m:
        num = float(m.group(0))
        unit = f"{c.unit} {c.value}".lower()
        scale = next((s for w, s in SCALES.items() if len(w) > 2 and w in unit), 1)
        kind = "pct" if "%" in unit or "percent" in unit else ("money" if any(x in unit for x in ("usd", "$", "eur", "dkk", "chf", "gbp", "jpy")) else "count")
        dec = len(m.group(0).split(".")[1]) if "." in m.group(0) else 0
        cands.append(Num(text=c.value, value=num * scale, kind=kind, precision=0.5 * 10 ** -dec * (1 if kind == "pct" else scale)))
    return cands


def same_number(a: Num, b: Num) -> bool:
    if a.kind != b.kind:
        return False
    tol = max(a.precision, b.precision, abs(b.value) * 1e-9)
    return abs(a.value - b.value) <= tol * 1.0001


def unit_mismatch(a: Num, b: Num) -> bool:
    """Same digits but off by a factor of 1,000 (million vs billion) or 1,000,000."""
    if a.kind != b.kind or a.kind == "pct" or a.value == 0 or b.value == 0:
        return False
    ratio = a.value / b.value
    return any(abs(ratio / f - 1) < 1e-3 for f in (1e3, 1e-3, 1e6, 1e-6))


def match_to_ledger(n: Num, ledger: Ledger) -> tuple[list[Claim], bool]:
    """Ledger claims whose numbers equal `n`; second value is True if only a unit-scale (million/billion) match exists."""
    hits, scale_err = [], False
    for c in ledger.claims:
        for cand in claim_candidates(c):
            if same_number(n, cand):
                hits.append(c)
                break
            if unit_mismatch(n, cand):
                scale_err = True
    return hits, (scale_err and not hits)


def sentence_figures(sentence: str, ledger: Ledger, skip: Num | None = None) -> list[tuple[Num, Claim]]:
    """Money/count numbers in a sentence that match a ledger claim (one entry per distinct ledger claim)."""
    out, used = [], set()
    for m in extract_numbers(sentence):
        if m.kind == "pct" or (skip is not None and m.text == skip.text):
            continue
        hits, _ = match_to_ledger(m, ledger)
        if hits and hits[0].id not in used:
            used.add(hits[0].id)
            out.append((m, hits[0]))
    return out


def derive_percent(n: Num, ledger: Ledger) -> tuple[str, Claim | None, Claim | None, list[float]]:
    """Check a % against the figures that sit in the SAME sentence (never against unrelated ledger pairs).

    Returns (result, old_claim, new_claim, computed_changes) where result is:
      'match'    a pair of figures in the sentence produces this %
      'mismatch' the sentence has two or more ledger figures but none produces this %
      'none'     fewer than two ledger figures in the sentence, so the % cannot be derived
    """
    if n.kind != "pct":
        return "none", None, None, []
    figs = sentence_figures(n.sentence, ledger, skip=n)
    computed = []
    for (a, ca), (b, cb) in combinations(figs, 2):
        if a.kind != b.kind:
            continue
        for old, new, co, cn in ((a, b, ca, cb), (b, a, cb, ca)):
            try:
                pc = calc.pct_change(old.value, new.value, 1)
            except ZeroDivisionError:
                continue
            if abs(abs(pc) - n.value) <= max(n.precision, 0.05):
                return "match", co, cn, [pc]
            computed.append(pc)
    return ("mismatch" if computed else "none"), None, None, computed


NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
RATIO = re.compile(r"\b(?P<vague>almost|nearly|about|roughly|more than|over)?\s?(?P<n>two|three|four|five|six|seven|eight|nine|ten|\d+(?:\.\d+)?)"
                   r"(?:\s?times\b|x\b|-?fold\b)|\b(?P<w>doubled|tripled|quadrupled|tenfold)\b", re.I)


def ratio_issues(sentence: str, ledger: Ledger) -> list[str]:
    """'almost four times', 'tenfold', 'doubled': must be backed by two ledger figures in the same sentence."""
    problems = []
    for m in RATIO.finditer(sentence):
        stated = NUMBER_WORDS.get((m.group("n") or "").lower()) or (float(m.group("n")) if m.group("n") else
                 {"doubled": 2, "tripled": 3, "quadrupled": 4, "tenfold": 10}[m.group("w").lower()])
        figs = [f for f, _ in sentence_figures(sentence, ledger) if f.value > 0]
        ratios = [max(a.value, b.value) / min(a.value, b.value) for a, b in combinations(figs, 2) if a.kind == b.kind]
        if not ratios:
            problems.append(f"'{m.group(0).strip()}' needs both figures stated in the same sentence")
        elif not any(abs(r - stated) / stated <= 0.15 for r in ratios):
            problems.append(f"'{m.group(0).strip()}' but the figures in the sentence give {', '.join(f'{r:.1f}x' for r in ratios)}")
    return problems


def recompute_derived(ledger: Ledger) -> list[str]:
    """Re-run every 'derived' claim's arithmetic from its parents; report any that no longer add up."""
    problems = []
    by_id = {c.id: c for c in ledger.claims}
    for c in ledger.claims:
        if c.origin != "derived" or len(c.derived_from) != 2:
            continue
        a, b = (by_id.get(i) for i in c.derived_from)
        if not a or not b:
            problems.append(f"{c.id}: parent claim missing")
            continue
        try:
            if abs(calc.pct_change(a.value, b.value) - float(c.value)) > 0.051:
                problems.append(f"{c.id}: stored {c.value}% but {a.id}->{b.id} computes to {calc.pct_change(a.value, b.value)}%")
        except (ZeroDivisionError, ValueError):
            problems.append(f"{c.id}: could not recompute")
    return problems


def _host(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url).split("/")[0].lower()


def corroborate(ledger: Ledger) -> int:
    """Two secondary claims with the same figure and period from DIFFERENT sites become 'verified' (rule: 2 independent sources)."""
    n = 0
    for a, b in combinations([c for c in ledger.claims if c.origin == "web"], 2):
        if a.source_url and b.source_url and _host(a.source_url) != _host(b.source_url) and a.as_of == b.as_of != "":
            if any(same_number(x, y) for x in claim_candidates(a) for y in claim_candidates(b) if x.value >= 1000 or x.kind == "pct"):
                for x, y in ((a, b), (b, a)):
                    if x.status != "verified":
                        x.status, x.second_source_url, n = "verified", y.source_url, n + 1
                        x.notes = (x.notes + " Corroborated by an independent source.").strip()
    return n


def find_conflicts(ledger: Ledger) -> list[tuple[Claim, Claim]]:
    """Same subject and period, different sites, figures that disagree by more than 1%."""
    out = []
    for a, b in combinations(ledger.claims, 2):
        if a.unit != b.unit or not a.unit or a.as_of != b.as_of or a.as_of in ("", "not stated"):
            continue
        if _host(a.source_url) == _host(b.source_url):
            continue
        if len(set(re.findall(r"[a-z]{4,}", a.claim.lower())) & set(re.findall(r"[a-z]{4,}", b.claim.lower()))) < 3:
            continue
        try:
            va, vb = float(a.value.replace(",", "")), float(b.value.replace(",", ""))
        except ValueError:
            continue
        if va and abs(va - vb) / abs(va) > 0.01:
            out.append((a, b))
    return out


DEAL_WORDS = re.compile(r"\b(deal|acquir\w+|acquisition|buy|bought|licens\w+|merger|takeover|buyout)\b", re.I)
DEAL_QUALIFIER = re.compile(r"\b(upfront|up to|total|as announced|milestones?|contingent|CVR|biobucks|equity value|enterprise value|announced)\b", re.I)


def deal_wording_issues(text: str) -> list[str]:
    """Sentences quoting a deal value without saying whether it is upfront / total / milestone-dependent / as announced."""
    issues = []
    for _, sent in _sentences(text):
        if re.search(r"\bdeals\b|\btotal value\b", sent, re.I):      # aggregate statistics, not one deal's price
            continue
        if DEAL_WORDS.search(sent) and any(n.kind == "money" and n.value >= 1e8 for n in extract_numbers(sent)):
            if not DEAL_QUALIFIER.search(sent):
                issues.append(sent[:160])
    return issues
