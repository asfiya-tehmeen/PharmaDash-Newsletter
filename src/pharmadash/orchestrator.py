"""Coordinates the agents. Milestone 4: the research stage (topic -> claims ledger)."""
from __future__ import annotations

from datetime import date
from typing import Callable

from . import config, topics as T
from .agents import competitor, researcher, sec_financials, verifier, writer
from .claims import Ledger
from .tools import fetch_utils


def research_topic(topic: T.Topic | str, log: Callable[[str], None] = print) -> Ledger:
    """Build a claims ledger: SEC numbers (code) + primary-source page claims (quoted) + competitor comparison."""
    cfg = config.load_config()
    if isinstance(topic, str):
        title, text, known = topic, topic, []
    else:
        title, text, known = topic.headline, f"{topic.headline}. {topic.angle}", topic.sources
    ledger = Ledger(topic=title, built=date.today().isoformat())

    main = sec_financials.companies_in_text(text, cfg["watchlist"])
    log(f"companies in topic: {', '.join(c['name'] for c in main) or 'none from the watchlist'}")
    log("SEC financials...")
    sec_financials.sec_claims(main, ledger)

    words = [c["name"].split()[0].lower() for c in cfg["watchlist"] if len(c["name"].split()[0]) >= 4]
    researcher.research(title, known, ledger, words, log)

    if main:
        log("competitor comparison...")
        competitor.compare(title, main, ledger, cfg["watchlist"])

    ledger.notes += [f"Source unreachable: {u['url']} ({u['error']})" for u in fetch_utils.UNREACHABLE]
    return ledger


def write_and_verify(title: str, angle: str, ledger: Ledger, dashboards: list[tuple[str, str]],
                     log: Callable[[str], None] = print, max_rounds: int = 3) -> str:
    """Write, check with code, send flagged sentences back to the writer, repeat; finish with the full meaning check.

    Anything still flagged after `max_rounds` stays in ledger.draft_checks so the fact-check report shows it.
    """
    from . import style
    article = writer.write_article(title, angle, ledger, dashboards, log)
    hard = [i for i in style.lint(article, dashboards=[d for d, _ in dashboards]) if not i.startswith("(soft)")]
    if hard:      # one revision for format problems (short, no italic dek, quote too long...)
        article = writer.repair_structure(article, hard, ledger, log)
    for round_no in range(1, max_rounds + 1):
        verifier.verify_draft(article, ledger, log=log, use_model=False)
        bad = verifier.failures(ledger)
        log(f"check {round_no}: {len(ledger.draft_checks)} items, {len(bad)} to fix")
        if not bad:
            break
        article, changed = writer.fix_flagged(article, bad, ledger, log)
        if not changed:
            break
    verifier.verify_draft(article, ledger, log=log, use_model=True)    # final pass includes the meaning check
    ledger.notes += [f"STYLE: {i}" for i in style.lint(article) if not i.startswith("(soft)")]
    return article
