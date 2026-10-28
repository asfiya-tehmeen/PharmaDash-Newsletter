"""openFDA client: recent drug approvals (Drugs@FDA submissions)."""
from __future__ import annotations

from .fetch_utils import fetch

BASE = "https://api.fda.gov/drug/drugsfda.json"


def recent_approvals(since: str, limit: int = 25) -> list[dict]:
    """Original approvals (submission type ORIG, status AP) with action date >= since (YYYY-MM-DD)."""
    day = since.replace("-", "")
    query = f"submissions.submission_status_date:[{day} TO 20991231] AND submissions.submission_type:ORIG"
    data = fetch(BASE, params={"search": query, "limit": limit}, ttl_hours=6, as_json=True)
    if not data:
        return []
    out = []
    for r in data.get("results", []):
        subs = [s for s in r.get("submissions", [])
                if s.get("submission_type") == "ORIG" and s.get("submission_status") == "AP"
                and s.get("submission_status_date", "0") >= day]
        if not subs:
            continue
        prods = r.get("products", [{}])
        out.append({
            "sponsor": r.get("sponsor_name"), "brand": prods[0].get("brand_name"),
            "ingredient": ", ".join(i["name"] for i in prods[0].get("active_ingredients", [])),
            "approved": subs[0]["submission_status_date"],
            "source": "FDA (openFDA Drugs@FDA)",
        })
    out.sort(key=lambda x: x["approved"], reverse=True)
    return out
