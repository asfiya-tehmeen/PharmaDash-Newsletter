from pharmadash import calc
from pharmadash.agents import researcher, sec_financials
from pharmadash.claims import Ledger, source_type

PAGE = "Lilly reported third-quarter revenue of $19.8 billion, up 56% from a year earlier.  Guidance was raised."
WATCH = [{"name": "Eli Lilly", "ticker": "LLY", "cik": "1", "form": "10-K"},
         {"name": "Novo Nordisk", "ticker": "NVO", "cik": "2", "form": "20-F"},
         {"name": "Merck", "ticker": "MRK", "cik": "3", "form": "10-K"}]


def raw(quote, value="19.8"):
    return researcher.RawClaim(claim="x", value=value, unit="USD billion", as_of="Q3", quote=quote)


def test_real_quote_accepted():
    assert researcher.accept(raw("third-quarter revenue of $19.8 billion"), PAGE)[0]


def test_invented_quote_rejected():
    assert researcher.accept(raw("revenue of $21.0 billion", "21.0"), PAGE) == (False, "quote not found on page")


def test_number_must_be_in_quote():
    assert researcher.accept(raw("up 56% from a year earlier", "19.8"), PAGE)[1] == "number not in quote"


def test_long_quote_rejected():
    page = " ".join(f"w{i}" for i in range(40))
    assert researcher.accept(raw(page, ""), page)[1] == "quote longer than 25 words"


def test_company_detection_and_source_types():
    names = [c["name"] for c in sec_financials.companies_in_text("Lilly beats Novo on obesity; NVO falls", WATCH)]
    assert names == ["Eli Lilly", "Novo Nordisk"]
    assert source_type("https://sec.gov/x", [])[0] == "primary"
    assert source_type("https://investor.lilly.com/x", ["lilly"])[0] == "primary"
    assert source_type("https://endpoints.news/x", ["lilly"])[0] == "secondary"


def test_calc():
    assert calc.pct_change(100, 156) == 56.0
    assert calc.cagr(100, 121, 2) == 10.0
    assert calc.total([0.1, 0.2]) == 0.3
    assert calc.human_money(19_800_000_000) == "$19.8 billion"


def test_sec_claims_with_derived_growth(monkeypatch):
    def fake(cik, metric, annual=True):
        if not annual:
            return {"points": []}
        if metric != "revenue":
            return {"points": [], "note": "n/a"}
        return {"unit": "USD", "points": [
            {"period_end": "2023-12-31", "value": 100, "form": "10-K", "filed": "2024-02-01", "url": "u1"},
            {"period_end": "2024-12-31", "value": 125, "form": "10-K", "filed": "2025-02-01", "url": "u2"}]}
    monkeypatch.setattr(sec_financials.sec_edgar, "metric_series", fake)
    ledger = Ledger(topic="t", built="2026-10-28")
    sec_financials.sec_claims([WATCH[0]], ledger)
    growth = [c for c in ledger.claims if c.origin == "derived"][0]
    assert growth.value == "25.0" and growth.derived_from == ["C001", "C002"]
    assert any("net income not in SEC" in n for n in ledger.notes)
