import json
from types import SimpleNamespace as NS

import pytest
from pydantic import BaseModel

from pharmadash import llm


def reply(content=None, tool_calls=None, usage=(100, 50)):
    msg = NS(content=content, tool_calls=tool_calls)
    return NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=usage[0], completion_tokens=usage[1]))


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.chat = NS(completions=NS(create=lambda **kw: self.replies.pop(0)))


@pytest.fixture(autouse=True)
def fresh_usage(monkeypatch):
    monkeypatch.setattr(llm, "USAGE", llm.Usage())


def test_tool_loop_calls_tool_then_answers(monkeypatch):
    call = NS(id="1", function=NS(name="add", arguments=json.dumps({"a": 2, "b": 3})))
    monkeypatch.setattr(llm, "_client", FakeClient([reply(tool_calls=[call]), reply("The sum is 5")]))
    tools = {"add": ({"type": "function", "function": {"name": "add", "parameters": {}}}, lambda a, b: a + b)}
    assert llm.run_agent("openai/gpt-oss-120b", "sys", "q", tools) == "The sum is 5"
    assert llm.USAGE.calls == 2 and llm.USAGE.cost_usd > 0


def test_tool_error_is_reported_to_model_not_raised(monkeypatch):
    call = NS(id="1", function=NS(name="boom", arguments="{}"))
    fake = FakeClient([reply(tool_calls=[call]), reply("done")])
    monkeypatch.setattr(llm, "_client", fake)
    tools = {"boom": ({"type": "function", "function": {"name": "boom", "parameters": {}}}, lambda: 1 / 0)}
    assert llm.run_agent("openai/gpt-oss-120b", "s", "q", tools) == "done"


class Out(BaseModel):
    n: int


def test_ask_json_retries_once_on_bad_json(monkeypatch):
    monkeypatch.setattr(llm, "_client", FakeClient([reply("not json"), reply('{"n": 7}')]))
    assert llm.ask_json("openai/gpt-oss-120b", "s", "q", Out).n == 7


def test_budget_cap_stops_run(monkeypatch):
    monkeypatch.setattr(llm, "_client", FakeClient([reply("x")]))
    llm.USAGE.input_tokens = 10**9
    with pytest.raises(llm.BudgetExceeded):
        llm.chat("openai/gpt-oss-120b", [])


def test_wait_parsing_and_pool_stops_when_wait_is_long(monkeypatch):
    import time
    assert llm._wait_seconds("try again in 5m25.296s.") == pytest.approx(325.296)
    assert llm._wait_seconds("try again in 1h2m3s") == 3723
    monkeypatch.setattr(llm, "_dead_until", {m: time.time() + 3 * 3600 for m in ("a", "b")})
    with pytest.raises(llm.DailyLimitReached):
        llm.pool({"model_pool": ["a", "b"]}, "a")
