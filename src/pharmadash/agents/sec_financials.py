"""SEC Financials agent: pulls reported numbers straight from SEC filings (no model involved, so no guessing)."""
from __future__ import annotations

import re

from .. import calc
from ..claims import Claim, Ledger
from ..tools import sec_edgar

METRICS = {"revenue": "revenue", "net_income": "net income", "rd_expense": "R&D expense"}
ALIASES = {"Eli Lilly": ["Lilly"], "Bristol Myers Squibb": ["Bristol Myers", "BMS"], "Johnson & Johnson": ["J&J", "Johnson & Johnson"],
           "Novo Nordisk": ["Novo"], "Gilead Sciences": ["Gilead"], "Sun Pharma": ["Sun Pharma"]}


def companies_in_text(text: str, watchlist: list[dict]) -> list[dict]:
    """Watchlist companies mentioned by name, short name, or ticker."""
    found = []
    for c in watchlist:
        names = {c["name"], c["name"].split()[0], *ALIASES.get(c["name"], [])}
        names = {n for n in names if len(n) >= 3}
        hit = any(re.search(r"\b" + re.escape(n) + r"\b", text, re.I) for n in names)
        if not hit and c["ticker"] and c["ticker"].isalpha() and len(c["ticker"]) >= 3:
            hit = bool(re.search(r"\b" + re.escape(c["ticker"]) + r"\b", text))   # tickers are case-sensitive
        if hit:
            found.append(c)
    return found


def sec_claims(companies: list[dict], ledger: Ledger, years: int = 2) -> None:
    """Add annual (last `years`) and latest-quarter figures for each company, plus YoY growth computed in code."""
    for c in companies:
        if not c["cik"]:
            ledger.notes.append(f"{c['name']}: not an SEC filer. Use the company's own results release and label it a press-release figure.")
            continue
        try:
            for key, label in METRICS.items():
                series = sec_edgar.metric_series(c["cik"], key)
                pts = series["points"][-years:]
                if not pts:
                    ledger.notes.append(f"{c['name']}: {label} not in SEC structured data. {series.get('note', '')}")
                    continue
                cur = series["unit"]
                made = []
                for p in pts:
                    made.append(ledger.add(Claim(
                        claim=f"{c['name']} {label}, 12 months ended {p['period_end']}: {calc.human_money(p['value'], cur)}",
                        value=str(p["value"]), unit=cur, as_of=p["period_end"], source_url=p["url"],
                        source_type="primary", source_note=f"SEC XBRL company facts, {p['form']} filed {p['filed']}",
                        status="verified", origin="sec",
                        notes=" ".join(x for x in (
                            f"Foreign filer, reported in {cur}; not converted." if cur != "USD" else "",
                            f"XBRL tag: {series.get('concept', '?')}.",
                            "Narrower than total R&D: excludes acquired in-process R&D, so say 'R&D expense excluding acquired in-process R&D'."
                            if "Excluding" in series.get("concept", "") else "") if x))))
                if len(made) == 2 and float(made[0].value) > 0:
                    g = calc.pct_change(made[0].value, made[1].value)
                    ledger.add(Claim(
                        claim=f"{c['name']} {label} changed {g:+}% between fiscal periods ending {made[0].as_of} and {made[1].as_of}",
                        value=str(g), unit="%", as_of=made[1].as_of, source_url=made[1].source_url, source_type="primary",
                        source_note="computed in code from the two SEC values", status="verified", origin="derived",
                        derived_from=[made[0].id, made[1].id]))
            q = sec_edgar.metric_series(c["cik"], "revenue", annual=False)["points"]
            if q:
                p = q[-1]
                ledger.add(Claim(claim=f"{c['name']} revenue, 3 months ended {p['period_end']}: {calc.human_money(p['value'], 'USD')}",
                                 value=str(p["value"]), unit="USD", as_of=p["period_end"], source_url=p["url"], source_type="primary",
                                 source_note=f"SEC XBRL company facts, {p['form']} filed {p['filed']}", status="verified", origin="sec"))
        except sec_edgar.SecConfigError as e:
            ledger.notes.append(f"SEC data skipped: {e}")
            return
