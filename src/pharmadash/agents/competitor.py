"""Competitor agent: picks peers, then compares them using the same SEC numbers (computed in code)."""
from __future__ import annotations

from pydantic import BaseModel

from .. import config, llm
from ..claims import Ledger
from . import sec_financials


class Peers(BaseModel):
    peers: list[str]


def choose_peers(topic: str, main: list[dict], watchlist: list[dict], want: int = 2) -> list[dict]:
    """Peers = the closest other watchlist companies. The model may only pick from the watchlist."""
    cfg = config.load_config()
    names = [c["name"] for c in watchlist if c["cik"] and c not in main]
    try:
        reply = llm.ask_json(cfg["models"]["research"],
                             "Pick the closest commercial competitors for the story. Choose ONLY from the provided list.",
                             f"Story: {topic}\nAlready included: {[c['name'] for c in main]}\nChoose {want} from: {names}",
                             Peers, max_tokens=300)
    except ValueError:
        return []
    by_name = {c["name"]: c for c in watchlist}
    return [by_name[n] for n in dict.fromkeys(reply.peers) if n in by_name and by_name[n] not in main][:want]


def compare(topic: str, main: list[dict], ledger: Ledger, watchlist: list[dict]) -> list[dict]:
    peers = choose_peers(topic, main, watchlist)
    ledger.notes.append("Competitor set: " + (", ".join(c["name"] for c in peers) or "none found"))
    sec_financials.sec_claims(peers, ledger)
    for c in ledger.claims:
        if c.origin in ("sec", "derived") and any(c.claim.startswith(p["name"]) for p in peers):
            c.notes = (c.notes + " Competitor comparison figure.").strip()
    ledger.notes.append("Competitor pipeline stage, patent expiry and market share are not in SEC structured data; "
                        "add them from company pipeline pages if the article needs them.")
    return peers
