"""Renders factcheck_report.md. Unresolved problems come first."""
from __future__ import annotations

from datetime import date

from .agents.verifier import failures
from .claims import Ledger

ICON = {"verified": "OK", "single-source": "1 SOURCE", "conflict": "CONFLICT", "unverified": "UNVERIFIED"}


def render(ledger: Ledger, title: str = "") -> str:
    bad = failures(ledger)
    attention = [n for n in ledger.notes if n.startswith(("CONFLICT", "ARITHMETIC", "Meaning check", "No ledger", "DASHBOARD", "STYLE"))]
    counts: dict[str, int] = {}
    for c in ledger.draft_checks:
        counts[c.status] = counts.get(c.status, 0) + 1
    out = [f"# Fact-check report{': ' + title if title else ''}", f"*Generated {date.today().isoformat()}. Not investment advice.*", ""]

    out.append("## Needs your attention")
    if not bad and not attention:
        out += ["Nothing unresolved.", ""]
    for c in bad:
        out.append(f"- **{ICON[c.status]}** `{c.id}` {c.text}" + (" *(headline/dek)*" if c.in_headline else ""))
        out.append(f"  - In the article: \"{c.sentence.strip(chr(42) + chr(32))}\"")
        if c.notes:
            out.append(f"  - {c.notes}")
        if c.matched:
            out.append(f"  - Ledger: {', '.join(c.matched)}")
    out += [f"- {n}" for n in attention]
    if ledger.pages_blocked:
        out += ["", "**Sources that could not be read (blocked or unavailable):**"] + [f"- {u}" for u in ledger.pages_blocked]

    total = len(ledger.draft_checks)
    out += ["", "## Summary",
            f"- Items checked in the article: **{total}** "
            f"(verified {counts.get('verified', 0)}, single-source {counts.get('single-source', 0)}, "
            f"conflict {counts.get('conflict', 0)}, unverified {counts.get('unverified', 0)})",
            f"- Ledger claims: {len(ledger.claims)}; pages read: {len(ledger.pages_read)}",
            "- Rules applied: headline/dek figures need a primary source or two independent sources; deal values must say "
            "upfront / total / as announced; arithmetic is recomputed in code; million-vs-billion slips are flagged."]

    out += ["", "## Every item checked"]
    for c in ledger.draft_checks:
        out.append(f"- `{c.id}` **{ICON[c.status]}** [{c.kind}] {c.text}" + (f" ({', '.join(c.matched)})" if c.matched else "")
                   + (f". {c.notes}" if c.notes else ""))

    out += ["", "## Ledger"]
    for c in ledger.claims:
        src = f"[{c.source_type}]({c.source_url})" if c.source_url else c.source_type
        out.append(f"- `{c.id}` {ICON[c.status]}: {c.claim} (as of {c.as_of or 'n/a'}; {src}; {c.source_note})"
                   + (f" Second source: {c.second_source_url}" if c.second_source_url else ""))
    return "\n".join(out) + "\n"


def sources_md(ledger: Ledger, title: str = "") -> str:
    """sources.md: every claim with its link, so you can click through before posting."""
    out = [f"# Sources{': ' + title if title else ''}", f"*Built {ledger.built}. Primary sources are listed first.*", ""]
    for kind in ("primary", "secondary"):
        rows = [c for c in ledger.claims if c.source_type == kind]
        if not rows:
            continue
        out.append(f"## {kind.capitalize()} sources")
        for c in rows:
            link = f"<{c.source_url}>" if c.source_url else "(no link: " + (c.source_note or "see ledger") + ")"
            out.append(f"- `{c.id}` {c.claim} (as of {c.as_of or 'n/a'}) {link}" + (f" and <{c.second_source_url}>" if c.second_source_url else ""))
        out.append("")
    if ledger.pages_blocked:
        out += ["## Could not be read", *[f"- {u}" for u in ledger.pages_blocked], ""]
    return chr(10).join(out)
