"""Discovery agent: gather dated material with code, enrich with web search, then propose ranked topics.

Groq's free plan allows ~8,000 tokens per minute, so the material is kept compact: every source gets a short id
(n1, s1, w1...) and the model cites ids; code swaps in the real URLs afterwards. Topics are requested in small batches.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from .. import config, llm, topics as T
from ..tools import fetch_utils, news_feeds, openfda, sec_edgar

PROMPT = Path(__file__).parent.parent / "prompts" / "discovery.md"
BATCHES = 2          # 2 batches of 5 topics = 10 ideas
MAX_NEWS = 32


def gather(cfg: dict, log: Callable[[str], None]) -> tuple[str, dict[str, str], dict]:
    """Collect dated items from free sources. Returns (compact digest, id->url registry, counts)."""
    days = cfg["lookback_days"]
    since = (date.today() - timedelta(days=days)).isoformat()
    names = [c["name"] for c in cfg["watchlist"] if c["name"]]
    registry: dict[str, str] = {}
    counts = {}

    news = news_feeds.fetch_news(cfg["news_sources"], days, names)
    counts["news"] = len(news)
    log(f"news: {len(news)} items from RSS feeds")
    news.sort(key=lambda n: n["published"], reverse=True)
    news.sort(key=lambda n: not n["matches"])   # stable: watchlist mentions first, newest first within each group
    lines = ["NEWS (id | date | outlet | title [watchlist hits])"]
    for i, n in enumerate(news[:MAX_NEWS], 1):
        registry[f"n{i}"] = n["link"]
        tag = f" [{', '.join(n['matches'])}]" if n["matches"] else ""
        lines.append(f"n{i} | {n['published'][5:]} | {n['source']} | {n['title'][:110]}{tag}")

    lines.append("\nSEC FILINGS (id | date | company | form)")
    if "@" in config.sec_user_agent():
        n_f = 0
        for c in cfg["watchlist"]:
            if not c["cik"]:
                continue
            for f in sec_edgar.recent_filings(c["cik"], forms=("8-K", "10-Q", "10-K", "S-4", "20-F"), since=since, limit=2):
                n_f += 1
                registry[f"s{n_f}"] = f["url"]
                lines.append(f"s{n_f} | {f['filed'][5:]} | {c['name']} | {f['form']} {f['description'][:50]}")
        counts["sec"] = n_f
        log(f"sec: {n_f} recent filings")
    else:
        lines.append("(skipped: SEC_USER_AGENT not set)")
        log("sec: skipped (SEC_USER_AGENT not set in .env)")

    fda = openfda.recent_approvals(since, 8)
    counts["fda"] = len(fda)
    log(f"fda: {len(fda)} approvals")
    lines.append("\nFDA ORIGINAL APPROVALS (mostly generics; judge significance)")
    lines += [f"- {a['approved']} {a['sponsor']}: {a['brand']}" for a in fda]

    unreachable = [u["url"] for u in fetch_utils.UNREACHABLE]
    counts["unreachable"] = len(unreachable)
    if unreachable:
        lines.append("\nUNREACHABLE OUTLETS (covered by web search instead): " +
                     ", ".join(sorted({re.sub(r"https?://(www\.)?|/.*", "", u) for u in unreachable})))
    return "\n".join(lines), registry, counts


def _register_urls(notes: str, registry: dict[str, str]) -> str:
    """Replace each URL in the web notes with a short id (w1, w2...) and record it."""
    seen: dict[str, str] = {}

    def swap(m: re.Match) -> str:
        url = m.group(0).rstrip(".,);]")
        tail = m.group(0)[len(url):]
        if url not in seen:
            seen[url] = f"w{len(seen) + 1}"
            registry[seen[url]] = url
        return f"[{seen[url]}]{tail}"

    return re.sub(r"https?://[^\s)\]>]+", swap, notes)


def discover(focus: str | None = None, log: Callable[[str], None] = print) -> tuple[list[T.Topic], dict]:
    cfg = config.load_config()
    today = date.today().isoformat()
    system = PROMPT.read_text(encoding="utf-8")
    digest, registry, counts = gather(cfg, log)

    history = []
    if config.HISTORY_PATH.exists():
        history = json.loads(config.HISTORY_PATH.read_text(encoding="utf-8")).get("issues", [])
    past = "; ".join(f"Issue {h.get('issue')}: {h.get('title')}" for h in history) or \
        ("Issue 2 obesity pill war (Lilly vs Novo); Issue 3 M&A supercycle and patent cliff; Issue 4 AI in pharma; "
         "Issue 5 China licensing; Issue 6 drug pricing and reshoring; Issue 7 global markets")

    # Step A: a few web searches to fill gaps (each search is token-heavy, so only two)
    log("searching the web for gaps and fresh developments...")
    brief = (f"Today is {today}. Lookback {cfg['lookback_days']} days. {'Focus: ' + focus + '. ' if focus else ''}"
             f"Digest of what we already have:\n{digest[:2200]}\n\n"
             "Call web_search at most 2 times: (1) the biggest pharma earnings/guidance and M&A/licensing news of the last "
             f"{cfg['lookback_days']} days, (2) {'the focus topic' if focus else 'any theme the digest misses'}. "
             "Ask for publication dates. Then write 8-12 short bullets: date, what happened, key numbers, source URL. "
             "Only facts you saw in search results.")
    notes = llm.run_agent(cfg["models"]["research"], system, brief,
                          {"web_search": (llm.WEB_SEARCH_TOOL, llm.web_search)}, max_turns=4, log=lambda s: log("  " + s))
    notes = _register_urls(notes, registry)

    # Step B: ranked topics, in small batches that fit the free plan's per-minute limit
    all_topics: list[T.Topic] = []
    per = max(3, cfg["topic_count"] // BATCHES)
    for b in range(BATCHES):
        log(f"drafting topic ideas, batch {b + 1} of {BATCHES}...")
        already = "; ".join(t.headline for t in all_topics) or "none yet"
        ask = (f"Today is {today}. Propose {per} NEW topic ideas for the next issue ({cfg['lookback_days']}-day window)."
               f"{' Focus: ' + focus + '.' if focus else ''} Already proposed (do not repeat): {already}. "
               f"{'Include 1 evergreen idea.' if b == BATCHES - 1 else ''}\n"
               f"Past issues: {past}\n\nMATERIAL (cite ids only):\n{digest}\n\nWEB NOTES:\n{notes[:3000]}")
        all_topics += llm.ask_json(cfg["models"]["research"], system, ask, T.TopicList, max_tokens=3800).topics

    # keep the raw model output so a post-processing problem never costs another round of free-tier tokens
    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (config.RUNS_DIR / "last_discovery_raw.json").write_text(json.dumps(
        {"topics": [t.model_dump() for t in all_topics], "registry": registry, "digest": digest, "notes": notes}, indent=1), encoding="utf-8")

    T.resolve_ids(all_topics, registry)
    T.check_numbers(all_topics, digest + "\n" + notes)
    ranked = T.dedupe_by_sources(T.dedupe(T.rank(all_topics, cfg["scoring_weights"])))
    return ranked, {"counts": counts, "unreachable": sorted({u["url"] for u in fetch_utils.UNREACHABLE})}
