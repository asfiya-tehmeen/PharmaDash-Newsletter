"""The only file that talks to Groq. Every agent calls these helpers.

- chat(): one model call, with automatic retry on rate limits (429) and usage/cost tracking.
- run_agent(): a tool-use loop. The model may call our Python tools (SEC, news, FDA, ...) until it answers.
- web_search(): Groq's server-side "browser search" (gpt-oss models). It cannot be combined with
  our own tools or structured output in one call, so agents reach it through a normal tool, `web_search`.
- ask_json(): get a reply validated against a pydantic model (retries once with the error fed back).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from groq import Groq, RateLimitError, APIStatusError
from pydantic import BaseModel, ValidationError

from . import config


class BudgetExceeded(RuntimeError):
    pass


class DailyLimitReached(RuntimeError):
    pass


@dataclass
class Usage:
    """Running totals for one pharmadash run. Checked against usage_limits in config.yaml."""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    searches: int = 0
    fetches: int = 0
    calls: int = 0
    by_model: dict = field(default_factory=dict)

    def add(self, model: str, in_tok: int, out_tok: int, pricing: dict) -> None:
        p = pricing.get(model, {"input": 0.15, "output": 0.60})   # unknown model: assume gpt-oss-120b rates
        cost = in_tok / 1e6 * p["input"] + out_tok / 1e6 * p["output"]
        self.input_tokens += in_tok
        self.output_tokens += out_tok
        self.cost_usd += cost
        self.calls += 1
        m = self.by_model.setdefault(model, {"in": 0, "out": 0})
        m["in"] += in_tok
        m["out"] += out_tok

    def summary(self, plan: str = "free") -> str:
        base = (f"{self.calls} model calls, {self.input_tokens:,} tokens in / {self.output_tokens:,} out, "
                f"{self.searches} web searches")
        if plan == "free":
            return f"{base}. Cost: $0 on the Groq free tier (would be ~${self.cost_usd:.3f} at paid rates)"
        return f"{base}. Estimated cost: ~${self.cost_usd:.3f}"


USAGE = Usage()
_client: Groq | None = None


def client() -> Groq:
    global _client
    if _client is None:
        key = config.groq_api_key()
        if not key:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to the .env file.")
        _client = Groq(api_key=key, max_retries=0)   # we do our own retry below so we can show messages
    return _client


def _check_budget(cfg: dict) -> None:
    lim = cfg["usage_limits"]
    if cfg.get("plan", "free") == "free":
        used = USAGE.input_tokens + USAGE.output_tokens
        if used >= lim["max_tokens_per_run"]:
            raise BudgetExceeded(f"Token cap for this run reached ({used:,}). Raise usage_limits.max_tokens_per_run in config.yaml.")
    elif USAGE.cost_usd >= lim["max_cost_usd"]:
        raise BudgetExceeded(f"Spending cap reached (${USAGE.cost_usd:.2f}). Raise usage_limits.max_cost_usd in config.yaml.")


class RequestTooLarge(RuntimeError):
    """The request would exceed Groq's per-minute token limit for one call. Callers must send less text."""


# Free-tier limits (gpt-oss-120b/20b, qwen3.8-27b): 8,000 tokens per minute, 200,000 per day, each model separately.
TPM_LIMIT = 8000
_recent: dict[str, list[tuple[float, int]]] = {}   # model -> [(time, tokens)] for the last 60 seconds
_dead_until: dict[str, float] = {}                  # model -> wall-clock time when its daily allowance frees up


def estimate_tokens(messages: list[dict]) -> int:
    return int(len(json.dumps(messages, default=str)) / 3.3) + 50


def _pace(model: str, need: int) -> None:
    """Sleep until `need` tokens fit inside this model's per-minute allowance."""
    while True:
        now = time.monotonic()
        window = [(t, n) for t, n in _recent.get(model, []) if now - t < 60]
        _recent[model] = window
        used = sum(n for _, n in window)
        if used + need <= TPM_LIMIT or not window:
            return
        wait = 60 - (now - window[0][0]) + 0.5
        print(f"  (pacing for Groq's free limit: waiting {wait:.0f}s)")
        time.sleep(max(wait, 1))


def _wait_seconds(message: str) -> float:
    """Groq says e.g. 'Please try again in 5m25.296s'. Returns seconds (default 15 minutes if it cannot be read)."""
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", message)
    if not m or not any(m.groups()):
        return 900.0
    h, mi, sec = (float(x) if x else 0.0 for x in m.groups())
    return h * 3600 + mi * 60 + sec


def pool(cfg: dict, preferred: str, only_openai: bool = False) -> list[str]:
    """Preferred model first, then the other free models. If every model has used up its daily allowance, wait for
    the earliest one to free up when that is under 20 minutes (the allowance is a rolling window), else stop cleanly."""
    order = [preferred] + [m for m in cfg.get("model_pool", []) if m != preferred]
    if only_openai:
        order = [m for m in order if m.startswith("openai/")] or order
    while True:
        now = time.time()
        live = [m for m in order if _dead_until.get(m, 0) <= now]
        if live:
            return live
        soonest = min(_dead_until[m] for m in order) - now
        if soonest > 20 * 60:
            raise DailyLimitReached("Groq's free daily token limit is used up. Progress is saved; run again later with --resume.")
        print(f"  (daily token allowance used up; waiting {soonest / 60:.1f} min for it to free up)")
        time.sleep(soonest + 1)


def chat(model: str, messages: list[dict], *, tools: list[dict] | None = None, tool_choice: str | None = None,
         response_format: dict | None = None, reasoning_effort: str = "low", max_tokens: int = 3500,
         temperature: float = 0.3) -> Any:
    """One call, paced to Groq's per-minute limit. Falls back to another free model when one's daily limit is gone."""
    cfg = config.load_config()
    _check_budget(cfg)
    est = estimate_tokens(messages) + (len(json.dumps(tools)) // 3 if tools else 0)
    if est > 6000:
        raise RequestTooLarge(f"Request is ~{est} tokens; the free plan allows ~8000 per minute. Send less text.")
    needs_openai = bool(tools) and any(t.get("type") == "browser_search" for t in tools)
    for _round in range(4):
        for m in pool(cfg, model, needs_openai):
            kwargs: dict = dict(model=m, messages=messages, max_completion_tokens=max_tokens, temperature=temperature)
            if m.startswith("openai/"):
                kwargs["reasoning_effort"] = reasoning_effort
            if tools:
                kwargs["tools"] = tools
                if tool_choice:
                    kwargs["tool_choice"] = tool_choice
            if response_format:
                kwargs["response_format"] = response_format
            for attempt in range(6):
                _pace(m, est + max_tokens // 2)
                try:
                    resp = client().chat.completions.create(**kwargs)
                except RateLimitError as e:
                    text = str(e).lower()
                    if "per day" in text or "(tpd)" in text:
                        _dead_until[m] = time.time() + _wait_seconds(text) + 5
                        print(f"  (daily limit reached on {m}; trying another model)")
                        break
                    wait = min(60, 5 * 2 ** attempt)
                    print(f"  (Groq rate limit; waiting {wait}s)")
                    time.sleep(wait)
                    continue
                except APIStatusError as e:
                    if e.status_code >= 500 and attempt < 3:
                        time.sleep(2 ** attempt)
                        continue
                    raise
                u = resp.usage
                _recent.setdefault(m, []).append((time.monotonic(), u.prompt_tokens + u.completion_tokens))
                USAGE.add(m, u.prompt_tokens, u.completion_tokens, cfg.get("pricing_per_million_tokens", {}))
                return resp
    raise RuntimeError("Groq kept returning rate-limit errors. Wait a few minutes, then resume with --resume.")


def web_search(query: str) -> str:
    """Groq browser search. Returns the model's findings with inline citation markers."""
    cfg = config.load_config()
    if USAGE.searches >= cfg["usage_limits"]["max_searches"]:
        return "Search limit for this run reached. Use the other tools or finish with what you have."
    USAGE.searches += 1
    from datetime import date
    resp = chat(cfg["models"]["search"],
                [{"role": "system", "content": f"Today is {date.today().isoformat()}. Search the web and report facts with source URLs. "
                                               "Prefer primary sources (company press releases, SEC, FDA). Do not guess. "
                                               "For every fact give the publication date of its source. Your training data is "
                                               "out of date: only trust pages you actually opened, and if the newest page you "
                                               "find is old, say so instead of presenting it as current."},
                 {"role": "user", "content": f"(Today is {date.today().isoformat()}.) {query}"}],
                tools=[{"type": "browser_search"}], tool_choice="required", max_tokens=1200)
    return resp.choices[0].message.content or ""


WEB_SEARCH_TOOL = {"type": "function", "function": {
    "name": "web_search", "description": "Search the live web. Returns findings with source URLs.",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}


def run_agent(model: str, system: str, user: str, tools: dict[str, tuple[dict, Callable[..., Any]]],
              *, max_turns: int | None = None, log: Callable[[str], None] = lambda s: None) -> str:
    """Tool-use loop. `tools` maps name -> (JSON schema in OpenAI function format, python function)."""
    cfg = config.load_config()
    max_turns = max_turns or cfg["usage_limits"]["max_turns_per_agent"]
    specs = [spec for spec, _ in tools.values()]
    messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for _ in range(max_turns):
        resp = chat(model, messages, tools=specs or None, tool_choice="auto" if specs else None, max_tokens=2500)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return msg.content or ""
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [{"id": c.id, "type": "function",
                                         "function": {"name": c.function.name, "arguments": c.function.arguments}}
                                        for c in msg.tool_calls]})
        for call in msg.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
                result = tools[name][1](**args) if name in tools else f"Unknown tool {name}"
            except Exception as e:   # tell the model, so it can try something else
                result = f"Tool error: {type(e).__name__}: {e}"
            log(f"{name}({str(call.function.arguments)[:80]})")
            text = result if isinstance(result, str) else json.dumps(result, default=str)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": text[:4500]})
    # out of turns: ask for a final answer without tools
    messages.append({"role": "user", "content": "Turn limit reached. Give your final answer now using what you have."})
    return chat(model, messages).choices[0].message.content or ""


def ask_json(model: str, system: str, user: str, schema: type[BaseModel], *, max_tokens: int = 3500) -> BaseModel:
    """Ask for JSON matching `schema`. Validates; on failure retries once, showing the model its error."""
    fmt = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()}}
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    err = ""
    for _ in range(2):
        if err:
            messages.append({"role": "user", "content": f"Your JSON was invalid: {err}\nReturn corrected JSON only."})
        raw = chat(model, messages, response_format=fmt, max_tokens=max_tokens).choices[0].message.content or ""
        try:
            return schema.model_validate_json(raw)
        except ValidationError as e:
            err = str(e)[:600]
            messages.append({"role": "assistant", "content": raw})
    raise ValueError(f"Model did not return valid {schema.__name__} JSON: {err}")
