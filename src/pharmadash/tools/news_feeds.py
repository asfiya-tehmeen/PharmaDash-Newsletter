"""Reads the RSS feeds listed in config.yaml and returns recent headlines."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser

from .fetch_utils import fetch

USER_AGENT = {"User-Agent": "Mozilla/5.0 (PharmaDash research tool; RSS reader)"}


def fetch_news(sources: list[dict], lookback_days: int = 10, watch_terms: list[str] | None = None) -> list[dict]:
    """Newest first. Each item: source, title, link, published (ISO), summary (short), matches (watchlist hits)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    items = []
    for src in sources:
        body = fetch(src["rss"], headers=USER_AGENT, ttl_hours=2)
        if not body:
            continue   # already logged in UNREACHABLE
        for e in feedparser.parse(body).entries:
            ts = e.get("published_parsed") or e.get("updated_parsed")
            if not ts:
                continue
            when = datetime.fromtimestamp(mktime(ts), tz=timezone.utc)
            if when < cutoff:
                continue
            text = f"{e.get('title', '')} {e.get('summary', '')}".lower()
            items.append({
                "source": src["name"], "title": e.get("title", "").strip(), "link": e.get("link", ""),
                "published": when.date().isoformat(),
                "summary": e.get("summary", "")[:300],   # truncated: we paraphrase, never copy
                "matches": [t for t in (watch_terms or []) if t.lower() in text],
            })
    items.sort(key=lambda i: i["published"], reverse=True)
    return items
