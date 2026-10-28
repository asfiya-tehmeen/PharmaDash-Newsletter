"""Fetch a web page and reduce it to readable paragraph text (for quoting and claim extraction)."""
from __future__ import annotations

import re
from html.parser import HTMLParser

from .fetch_utils import fetch

HEADERS = {"User-Agent": "PharmaDash-research/0.1 (editorial research tool; respects robots and paywalls)"}
SKIP = {"script", "style", "nav", "header", "footer", "aside", "form", "noscript", "svg"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth_skip = 0
        self.blocks: list[str] = []
        self.cur: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.depth_skip += 1
        if tag in ("p", "li", "h1", "h2", "h3", "br", "tr", "div"):
            self._flush()

    def handle_endtag(self, tag):
        if tag in SKIP and self.depth_skip:
            self.depth_skip -= 1
        if tag in ("p", "li", "h1", "h2", "h3", "tr", "div"):
            self._flush()

    def handle_data(self, data):
        if not self.depth_skip:
            self.cur.append(data)

    def _flush(self):
        t = re.sub(r"\s+", " ", "".join(self.cur)).strip()
        if len(t) >= 50:   # drops menu items and button labels
            self.blocks.append(t)
        self.cur = []


def page_text(url: str, max_chars: int = 9000) -> str | None:
    """Readable text of the page, or None if it could not be fetched (blocked pages are logged, never bypassed)."""
    html = fetch(url, headers=HEADERS, ttl_hours=48)
    if not html:
        return None
    p = _Text()
    p.feed(html)
    p._flush()
    text = "\n".join(dict.fromkeys(p.blocks))   # de-duplicate repeated blocks
    return text[:max_chars] or None
