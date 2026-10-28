"""The claims ledger: every number or named fact, where it came from, and how well it is backed."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["verified", "single-source", "conflict", "unverified"]


class Claim(BaseModel):
    id: str = ""
    claim: str                      # plain-English statement
    value: str = ""                 # the number as a string, e.g. "19.8" (kept as text to avoid float noise)
    unit: str = ""                  # "USD", "%", "patients"...
    as_of: str = ""                 # date or period the number describes
    source_url: str = ""
    source_type: Literal["primary", "secondary"] = "secondary"
    source_note: str = ""           # e.g. "SEC XBRL, 10-K", "company press release via PR Newswire"
    second_source_url: str = ""
    status: Status = "unverified"
    notes: str = ""
    quote: str = ""                 # short exact snippet from the page (kept under 25 words)
    origin: Literal["sec", "web", "competitor", "derived"] = "web"
    derived_from: list[str] = Field(default_factory=list)


class DraftCheck(BaseModel):
    """One number or named fact found in the article, and what the ledger says about it."""
    id: str = ""
    text: str                       # the number as written, or the assertion
    sentence: str = ""
    kind: Literal["number", "derived", "named-fact", "deal-wording"] = "number"
    matched: list[str] = Field(default_factory=list)      # ledger claim ids
    status: Status = "unverified"
    in_headline: bool = False
    notes: str = ""


class Ledger(BaseModel):
    topic: str
    built: str
    claims: list[Claim] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)       # things that went wrong or need attention
    pages_read: list[str] = Field(default_factory=list)
    pages_blocked: list[str] = Field(default_factory=list)
    draft_checks: list[DraftCheck] = Field(default_factory=list)

    def add(self, c: Claim) -> Claim:
        c.id = f"C{len(self.claims) + 1:03d}"
        self.claims.append(c)
        return c

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Ledger":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


# Domains whose content is issued by the company/regulator itself count as primary sources.
PRIMARY_DOMAINS = ("sec.gov", "fda.gov", "clinicaltrials.gov", "prnewswire.com", "businesswire.com",
                   "globenewswire.com", "ema.europa.eu", "cms.gov", "congress.gov", "federalregister.gov")


def source_type(url: str, company_words: list[str]) -> tuple[str, str]:
    host = re.sub(r"^https?://(www\.)?", "", url).split("/")[0].lower()
    if any(host.endswith(d) for d in PRIMARY_DOMAINS):
        return "primary", f"official/wire source ({host})"
    if any(w in host for w in company_words) or host.startswith(("investor", "ir.", "media.", "news.")):
        return "primary", f"company website ({host})"
    return "secondary", f"news/analyst ({host})"
