"""Shared fetching: disk cache, retry with backoff, polite rate limiting, unreachable-source log."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import httpx

from .. import config

DEFAULT_TTL_HOURS = 12
UNREACHABLE: list[dict] = []   # every source that failed; shown in the run summary
_lock = threading.Lock()


class RateLimiter:
    """Allows at most `per_second` calls per second (SEC asks for 10 max; we use 8)."""

    def __init__(self, per_second: float):
        self.gap = 1.0 / per_second
        self.next_time = 0.0

    def wait(self) -> None:
        with _lock:
            now = time.monotonic()
            delay = max(0.0, self.next_time - now)
            self.next_time = max(now, self.next_time) + self.gap
        if delay:
            time.sleep(delay)


def _cache_path(url: str, params: dict | None) -> Path:
    key = url + json.dumps(params or {}, sort_keys=True)
    return config.CACHE_DIR / (hashlib.sha256(key.encode()).hexdigest()[:32] + ".json")


def fetch(url: str, *, params: dict | None = None, headers: dict | None = None,
          ttl_hours: float = DEFAULT_TTL_HOURS, limiter: RateLimiter | None = None,
          retries: int = 3, as_json: bool = False, timeout: float = 30.0) -> str | dict | None:
    """GET a URL. Returns text (or parsed JSON), or None if the source is unreachable.

    Results are cached on disk with a timestamp. Blocked pages (401/403/429 after retries)
    are logged and skipped; we never try to get around blocks or paywalls.
    """
    cache_file = _cache_path(url, params)
    if cache_file.exists():
        try:
            entry = json.loads(cache_file.read_text(encoding="utf-8"))
            age_h = (time.time() - entry["fetched_at"]) / 3600
            if age_h < ttl_hours:
                return json.loads(entry["body"]) if as_json else entry["body"]
        except (json.JSONDecodeError, KeyError):
            pass

    last_error = ""
    for attempt in range(retries):
        if limiter:
            limiter.wait()
        try:
            r = httpx.get(url, params=params, headers=headers, timeout=timeout, follow_redirects=True)
            if r.status_code == 200:
                config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps({"url": url, "fetched_at": time.time(), "body": r.text}),
                                      encoding="utf-8")
                return r.json() if as_json else r.text
            last_error = f"HTTP {r.status_code}"
            if r.status_code in (401, 403, 404):
                break   # blocked or missing: retrying will not help
        except httpx.HTTPError as e:
            last_error = type(e).__name__
        time.sleep(2 ** attempt)   # 1s, 2s, 4s

    UNREACHABLE.append({"url": url, "error": last_error})
    return None
