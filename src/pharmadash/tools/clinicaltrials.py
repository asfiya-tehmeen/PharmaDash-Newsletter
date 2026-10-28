"""ClinicalTrials.gov v2 client: recent results postings and status changes for a sponsor."""
from __future__ import annotations

from .fetch_utils import fetch

BASE = "https://clinicaltrials.gov/api/v2/studies"


def recent_trials(sponsor: str, since: str, limit: int = 10) -> list[dict]:
    """Studies by `sponsor` whose record was updated on/after `since` (YYYY-MM-DD), newest first."""
    params = {
        "query.spons": sponsor,
        "filter.advanced": f"AREA[LastUpdatePostDate]RANGE[{since},MAX]",
        "sort": "LastUpdatePostDate:desc",
        "pageSize": limit,
        "fields": "NCTId,BriefTitle,OverallStatus,Phase,LastUpdatePostDate,PrimaryCompletionDate,HasResults",
    }
    data = fetch(BASE, params=params, ttl_hours=6, as_json=True)
    if not data:
        return []
    out = []
    for s in data.get("studies", []):
        p = s["protocolSection"]
        idm, st = p["identificationModule"], p["statusModule"]
        out.append({
            "nct_id": idm["nctId"], "title": idm.get("briefTitle"), "status": st.get("overallStatus"),
            "phase": ", ".join(p.get("designModule", {}).get("phases", [])),
            "updated": st.get("lastUpdatePostDateStruct", {}).get("date"),
            "primary_completion": st.get("primaryCompletionDateStruct", {}).get("date"),
            "has_results": s.get("hasResults", False),
            "url": f"https://clinicaltrials.gov/study/{idm['nctId']}",
        })
    return out
