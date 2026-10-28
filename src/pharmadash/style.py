"""Style metrics and structure lint, so 'does it sound like PharmaDash?' can be measured against your samples."""
from __future__ import annotations

import re
from pathlib import Path

from . import checks

SECTION_HINTS = {
    "numbers": ("by the numbers", "scoreboard", "the scale"),
    "engine": ("engine", "why china", "why the pill", "driver"),
    "who": ("who's", "marquee", "launch watch", "who is"),
    "why_now": ("why now", "floodgates", "why china, and why now", "catch"),
    "watch": ("what to watch", "what to watch next"),
}


def clean_typography(text: str) -> str:
    """Make model output paste cleanly: plain hyphens, no stray claim ids, single spaces, '60-70%' not '60 - 70 %'."""
    for a, b in (("‑", "-"), ("‐", "-"), (" ", " "), (" ", " "), (" ", " ")):
        text = text.replace(a, b)
    text = re.sub(r"\s?\(\s*C\d{3}(?:\s*,\s*C\d{3})*\s*\)", "", text)       # (C015) claim ids must never reach readers
    text = re.sub(r"(\d)\s+%", r"\1%", text)
    text = re.sub(r"(?<=\S)[ ]{2,}(?=\S)", " ", text)                          # double spaces inside lines
    text = re.sub(r"[ ]+$", "", text, flags=re.M)                                # trailing spaces / forced line breaks
    return text


def words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9$%'’.-]+", text)


def body_of(md: str) -> str:
    """Article text without the standard footer/sources lines."""
    return re.split(r"\n---\s*\n\s*\*PharmaDash breaks down", md)[0]


def metrics(md: str) -> dict:
    body = body_of(md)
    paras = [p for p in re.split(r"\n\s*\n", body) if p.strip() and not p.strip().startswith(("#", "---"))]
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", re.sub(r"[#>*_`-]", "", body)) if len(s.split()) > 2]
    heads = [h.lower() for h in re.findall(r"^##\s+(.+)$", body, re.M)]
    w = words(body)
    nums = checks.extract_numbers(body)
    lines = body.splitlines()
    return {
        "words": len(w),
        "sections (##)": len(heads),
        "bold phrases": len(re.findall(r"\*\*[^*]+\*\*", body)),
        "bullets": sum(1 for l in lines if re.match(r"\s*[-*]\s", l)),
        "avg sentence words": round(len(w) / max(1, len(sentences)), 1),
        "avg paragraph words": round(sum(len(p.split()) for p in paras) / max(1, len(paras)), 1),
        "numbers per 100 words": round(len(nums) / max(1, len(w)) * 100, 1),
        "horizontal rules": sum(1 for l in lines if l.strip() == "---"),
        "dashboard pointers": len(re.findall(r"dashboard", body, re.I)),
        "has italic dek": bool(re.search(r"^\*[^*\n].+\*\s*$", body, re.M)),
        "has table": bool(re.search(r"^\s*\|.+\|\s*$", body, re.M)),
        "has footer": "PharmaDash breaks down" in md,
        "has sources line": bool(re.search(r"^\*Sources:", md, re.M)),
        "_heads": heads,
    }


def lint(md: str, lo: int = 700, hi: int = 1200, dashboards: list[str] | None = None) -> list[str]:
    """Structural problems to fix or flag. Empty list = structure matches the house format."""
    m, issues = metrics(md), []
    body = body_of(md)
    if not body.lstrip().startswith("# "):
        issues.append("must start with a '# Headline' line")
    if not m["has italic dek"]:
        issues.append("missing the italic dek line under the headline")
    if m["horizontal rules"] < 2:
        issues.append("missing '---' separators around the intro")
    if m["has table"]:
        issues.append("contains a table; LinkedIn does not render tables")
    if not (lo <= m["words"] <= hi):
        issues.append(f"word count {m['words']} is outside {lo}-{hi}")
    heads = " | ".join(m["_heads"])
    for key, hints in SECTION_HINTS.items():
        if not any(h in heads for h in hints):
            issues.append(f"(soft) no section matching '{key.replace('_', ' ')}'")
    watch = re.search(r"##\s+What to watch.*?(?=\n##|\n---|\Z)", body, re.S | re.I)
    if watch:
        items = len(re.findall(r"^\s*[-*\d]+[.)]?\s", watch.group(0), re.M))
        text = watch.group(0)
        if items not in (0, 3) or (items == 0 and not re.search(r"\b(three|first|second|third|1\)|whether)\b", text, re.I)):
            issues.append(f"'What to watch' should hold exactly 3 concrete items (found {items or 'unclear'})")
    if re.search(r"^[-*] .*[a-z0-9%][.!?]\*\*[^*]+\*\*:", body, re.M):
        issues.append("two bullets were merged onto one line")
    if dashboards and "see the dashboard" not in body.lower():
        issues.append("missing the 'See the dashboard' pointer(s) to the dashboards: " + ", ".join(dashboards))
    for q in re.findall(r"[\"“]([^\"”]{3,})[\"”]", body):
        if len(q.split()) >= 15:
            issues.append(f"direct quote of {len(q.split())} words (limit is under 15): \"{q[:50]}...\"")
    return issues


def compare(article: str, sample_paths: list[Path]) -> str:
    """Side-by-side table (for the terminal / report, not for LinkedIn) of the article vs the average of the samples."""
    keys = ["words", "sections (##)", "bold phrases", "bullets", "avg sentence words", "avg paragraph words",
            "numbers per 100 words", "horizontal rules", "dashboard pointers"]
    mine = metrics(article)
    samples = [metrics(p.read_text(encoding="utf-8")) for p in sample_paths]
    lines = [f"{'metric':26} {'this article':>13} {'your samples (avg)':>20}", "-" * 62]
    for k in keys:
        avg = sum(s[k] for s in samples) / len(samples)
        lines.append(f"{k:26} {mine[k]:>13} {avg:>20.1f}")
    for k in ("has italic dek", "has footer", "has sources line", "has table"):
        lines.append(f"{k:26} {str(mine[k]):>13} {str(all(s[k] for s in samples)):>20}")
    return "\n".join(lines)
