from pharmadash.tools import fetch_utils, sec_edgar

FAKE_FACTS = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
    {"start": "2024-01-01", "end": "2024-12-31", "val": 100, "form": "10-K", "filed": "2025-02-20", "accn": "0001-25-000001", "fy": 2024},
    {"start": "2024-01-01", "end": "2024-12-31", "val": 105, "form": "10-K/A", "filed": "2025-06-01", "accn": "0001-25-000002", "fy": 2024},
    {"start": "2025-01-01", "end": "2025-03-31", "val": 30, "form": "10-Q", "filed": "2025-05-01", "accn": "0001-25-000003", "fy": 2025},
]}}}}}


def test_annual_series_keeps_latest_restatement(monkeypatch):
    monkeypatch.setattr(sec_edgar, "company_facts", lambda cik: FAKE_FACTS)
    s = sec_edgar.metric_series("1", "revenue")
    assert [p["value"] for p in s["points"]] == [105] and s["unit"] == "USD"


def test_quarterly_series(monkeypatch):
    monkeypatch.setattr(sec_edgar, "company_facts", lambda cik: FAKE_FACTS)
    assert sec_edgar.metric_series("1", "revenue", annual=False)["points"][0]["value"] == 30


def test_missing_metric_says_so(monkeypatch):
    monkeypatch.setattr(sec_edgar, "company_facts", lambda cik: {"facts": {}})
    assert "Not found" in sec_edgar.metric_series("1", "net_income")["note"]


def test_requires_user_agent(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    try:
        sec_edgar._headers()
        assert False
    except sec_edgar.SecConfigError:
        pass


def test_fetch_caches_and_logs_failures(monkeypatch, tmp_path):
    from pharmadash import config
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    calls = []

    class R:
        status_code, text = 200, '{"a": 1}'
        def json(self): return {"a": 1}

    monkeypatch.setattr(fetch_utils.httpx, "get", lambda *a, **k: calls.append(1) or R())
    assert fetch_utils.fetch("http://x/y", as_json=True) == {"a": 1}
    assert fetch_utils.fetch("http://x/y", as_json=True) == {"a": 1}
    assert len(calls) == 1   # second call served from cache

    class Blocked:
        status_code, text = 403, ""

    monkeypatch.setattr(fetch_utils.httpx, "get", lambda *a, **k: Blocked())
    assert fetch_utils.fetch("http://blocked/z") is None
    assert fetch_utils.UNREACHABLE[-1]["error"] == "HTTP 403"
