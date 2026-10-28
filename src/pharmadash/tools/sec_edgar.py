"""SEC EDGAR client: recent filings and XBRL financial facts.

Needs SEC_USER_AGENT in .env (name + email). Limited to 8 requests/second (SEC max is 10).
US filers (10-K/10-Q) report in the us-gaap taxonomy; foreign filers (20-F) mostly use ifrs-full,
and 6-K filings carry no structured numbers, so for those we say so rather than guess.
"""
from __future__ import annotations

from .. import config
from .fetch_utils import RateLimiter, fetch

_limiter = RateLimiter(8)
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{doc}"

# Concept names to try, in order, for each metric we care about.
CONCEPTS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "SalesRevenueNet", "Revenue", "RevenueFromContractsWithCustomers"],
    "net_income": ["NetIncomeLoss", "ProfitLoss", "ProfitLossAttributableToOwnersOfParent"],
    "rd_expense": ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
                   "ResearchAndDevelopmentExpenseSoftwareExcludingAcquiredInProcessCost"],
}


class SecConfigError(RuntimeError):
    pass


def _headers() -> dict:
    ua = config.sec_user_agent()
    if "@" not in ua:
        raise SecConfigError("SEC_USER_AGENT is not set in .env (needs your name and email).")
    return {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}


def _get(url: str, ttl_hours: float = 12):
    return fetch(url, headers=_headers(), limiter=_limiter, as_json=True, ttl_hours=ttl_hours)


def recent_filings(cik: str, forms: tuple[str, ...] = ("8-K", "10-Q", "10-K", "S-4", "20-F", "6-K"),
                   since: str | None = None, limit: int = 20) -> list[dict]:
    """Newest filings first. `since` is an ISO date (YYYY-MM-DD). Each has a direct document URL."""
    data = _get(SUBMISSIONS.format(cik=cik.zfill(10)), ttl_hours=3)
    if not data:
        return []
    r = data["filings"]["recent"]
    out = []
    for i, form in enumerate(r["form"]):
        if form not in forms:
            continue
        date = r["filingDate"][i]
        if since and date < since:
            continue
        acc = r["accessionNumber"][i]
        out.append({
            "company": data.get("name"), "form": form, "filed": date, "period": r["reportDate"][i],
            "description": r["primaryDocDescription"][i],
            "url": ARCHIVE.format(cik_int=int(cik), acc_nodash=acc.replace("-", ""), doc=r["primaryDocument"][i]),
        })
        if len(out) >= limit:
            break
    return out


def company_facts(cik: str) -> dict | None:
    return _get(FACTS.format(cik=cik.zfill(10)), ttl_hours=24)


def metric_series(cik: str, metric: str, annual: bool = True) -> dict:
    """Return {'metric','concept','unit','taxonomy','points':[{period_end, fy, form, value, filed, url}]}.

    annual=True keeps ~12-month periods (10-K/20-F); False keeps ~3-month periods (10-Q).
    The 'source' is always the SEC filing itself (primary source).
    """
    from datetime import date

    facts = company_facts(cik)
    if not facts:
        return {"metric": metric, "points": [], "note": "SEC data unavailable"}
    best = None      # companies change the XBRL tag they use over time, so take the tag with the most recent period
    for taxonomy in ("us-gaap", "ifrs-full"):
        tax = facts.get("facts", {}).get(taxonomy, {})
        for concept in CONCEPTS[metric]:
            if concept not in tax:
                continue
            for unit, rows in tax[concept]["units"].items():
                pts = {}
                for row in rows:
                    if "start" not in row:
                        continue
                    days = (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days
                    ok = 350 <= days <= 380 if annual else 80 <= days <= 100
                    if not ok:
                        continue
                    # keep the most recently filed value for each period (handles restatements)
                    if row["end"] not in pts or row["filed"] > pts[row["end"]]["filed"]:
                        pts[row["end"]] = {
                            "period_end": row["end"], "fy": row.get("fy"), "form": row["form"],
                            "value": row["val"], "filed": row["filed"],
                            "url": ARCHIVE.format(cik_int=int(cik), acc_nodash=row["accn"].replace("-", ""), doc=""),
                        }
                if pts:
                    points = sorted(pts.values(), key=lambda p: p["period_end"])
                    if best is None or points[-1]["period_end"] > best["points"][-1]["period_end"]:
                        best = {"metric": metric, "concept": concept, "taxonomy": taxonomy, "unit": unit, "points": points}
    if best:
        return best
    return {"metric": metric, "points": [],
            "note": "Not found in SEC structured data (common for 20-F filers or product-level figures). "
                    "Use the company's press release or filing text and label it as such."}
