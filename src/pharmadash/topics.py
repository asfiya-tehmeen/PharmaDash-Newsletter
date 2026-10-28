"""Topic data model, ranking, and saving/loading of the topics files."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from . import config

SCORE_KEYS = ["recency", "financial_magnitude", "relevance", "dashboard_ability", "freshness_vs_history", "reader_interest"]


class KeyNumber(BaseModel):
    text: str = Field(description="The number with its meaning, e.g. 'Lilly Q3 revenue $X billion, +Y% YoY'")
    source_url: str = Field(description="The id of the source item, like n3 or w2")


class Scores(BaseModel):
    recency: float
    financial_magnitude: float
    relevance: float
    dashboard_ability: float
    freshness_vs_history: float
    reader_interest: float


class Topic(BaseModel):
    headline: str
    angle: str = Field(description="Two sentences on the angle")
    why_now: str
    key_numbers: list[KeyNumber]
    dashboard_types: list[str]
    sources: list[str] = Field(description="3 or more source ids (like n3, w2, s1) taken from the material provided")
    risk_flags: list[str]
    confidence: str = Field(description="low, medium or high")
    evergreen: bool = False
    scores: Scores
    total_score: float = 0.0     # filled in by code, not by the model


class TopicList(BaseModel):
    topics: list[Topic]


def rank(topics: list[Topic], weights: dict) -> list[Topic]:
    """Weighted score computed in code so the ranking follows config.yaml, not the model's mood."""
    for t in topics:
        t.total_score = round(sum(getattr(t.scores, k) * weights.get(k, 1.0) for k in SCORE_KEYS)
                              / sum(weights.get(k, 1.0) for k in SCORE_KEYS), 2)
    return sorted(topics, key=lambda t: t.total_score, reverse=True)


def resolve_ids(topics: list[Topic], registry: dict[str, str]) -> None:
    """The model cites short ids like n3 or w2; we swap in the real URL. Unknown ids are dropped and flagged,
    so a made-up link can never reach the topics file."""
    for t in topics:
        dropped = 0
        urls = []
        for sid in t.sources:
            if sid in registry:
                urls.append(registry[sid])
            else:
                dropped += 1
        t.sources = list(dict.fromkeys(urls))
        keep = []
        for k in t.key_numbers:
            if k.source_url in registry:
                k.source_url = registry[k.source_url]
                keep.append(k)
            else:
                dropped += 1
        t.key_numbers = keep
        if dropped:
            t.risk_flags.append(f"{dropped} citation(s) removed: id not found in gathered material")
        if len(t.sources) < 3:
            t.risk_flags.append("fewer than 3 sources")


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def check_numbers(topics: list[Topic], material: str) -> None:
    """Drop any 'key number' containing a figure that does not appear in the gathered material.
    Catches the model filling in details a headline never gave. Years are ignored."""
    seen = set(_NUM.findall(material.replace(",", "")))
    for t in topics:
        keep, dropped = [], 0
        for k in t.key_numbers:
            nums = [n for n in _NUM.findall(k.text.replace(",", "")) if not (n.isdigit() and len(n) == 4 and 1990 <= int(n) <= 2100)]
            if all(n in seen for n in nums):
                keep.append(k)
            else:
                dropped += 1
        t.key_numbers = keep
        if dropped:
            t.risk_flags.append(f"{dropped} key number(s) removed: figures not found in gathered sources")
        if not t.key_numbers:
            t.risk_flags.append("no verified key numbers yet; needs primary-source research")
        if t.confidence == "high" and (dropped or len(t.sources) < 3):
            t.confidence = "medium"
        if not t.key_numbers:
            t.confidence = "low"


def dedupe(topics: list[Topic], threshold: float = 0.5) -> list[Topic]:
    """Remove near-duplicate headlines (word overlap), keeping the first (highest-scored if sorted)."""
    kept: list[Topic] = []
    for t in topics:
        words = set(re.findall(r"[a-z0-9]+", t.headline.lower()))
        if any(len(words & w) / max(1, len(words | w)) > threshold for w in (set(re.findall(r"[a-z0-9]+", k.headline.lower())) for k in kept)):
            continue
        kept.append(t)
    return kept


def dedupe_by_sources(topics: list[Topic]) -> list[Topic]:
    """Two topics citing 2+ of the same sources are the same story told twice."""
    kept: list[Topic] = []
    for t in topics:
        if any(len(set(t.sources) & set(k.sources)) >= 2 for k in kept):
            continue
        kept.append(t)
    return kept


def slug(text: str, n: int = 6) -> str:
    return "-".join(re.sub(r"[^a-z0-9 ]", "", text.lower()).split()[:n])


def to_markdown(topics: list[Topic], day: str, focus: str | None) -> str:
    out = [f"# PharmaDash topic ideas, {day}", ""]
    if focus:
        out += [f"*Focus: {focus}*", ""]
    for i, t in enumerate(topics, 1):
        out += [f"## {i}. {t.headline}" + ("  *(evergreen)*" if t.evergreen else ""),
                f"**Score {t.total_score}/10 · confidence {t.confidence}**", "", t.angle, "",
                f"**Why now:** {t.why_now}", "", "**Key numbers spotted:**"]
        out += [f"- {k.text} ([source]({k.source_url}))" for k in t.key_numbers] or ["- none yet"]
        out += ["", f"**Dashboard ideas:** {', '.join(t.dashboard_types)}",
                f"**Risk flags:** {', '.join(t.risk_flags) or 'none'}", "**Sources:**"]
        out += [f"- {u}" for u in t.sources] + [""]
    return "\n".join(out)


def save(topics: list[Topic], focus: str | None, extra: dict | None = None) -> Path:
    config.TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    day = date.today().isoformat()
    base = config.TOPICS_DIR / f"{day}_topics"
    payload = {"date": day, "focus": focus, "topics": [t.model_dump() for t in topics], **(extra or {})}
    base.with_suffix(".json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    base.with_suffix(".md").write_text(to_markdown(topics, day, focus), encoding="utf-8")
    return base.with_suffix(".md")


def load_latest() -> tuple[list[Topic], Path]:
    files = sorted(config.TOPICS_DIR.glob("*_topics.json"))
    if not files:
        raise FileNotFoundError("No topics file yet. Run `pharmadash discover` first.")
    data = json.loads(files[-1].read_text(encoding="utf-8"))
    return [Topic.model_validate(t) for t in data["topics"]], files[-1]


def parse_selection(text: str, n: int) -> list[int]:
    """'1,3' -> [1, 3]; 'all' -> every topic; 'top3' -> [1, 2, 3]. Raises ValueError on bad input."""
    text = text.strip().lower()
    if text == "all":
        return list(range(1, n + 1))
    m = re.fullmatch(r"top\s*(\d+)", text)
    if m:
        return list(range(1, min(int(m.group(1)), n) + 1))
    nums = [int(x) for x in re.split(r"[,\s]+", text) if x]
    if not nums or any(i < 1 or i > n for i in nums):
        raise ValueError(f"Enter numbers between 1 and {n}, like 1,3 (or 'all' / 'top3').")
    return nums
