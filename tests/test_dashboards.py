from pathlib import Path

import pytest

from pharmadash import dashboards as DB
from pharmadash.claims import Ledger

FIX = Path(__file__).parent / "fixtures"


def load():
    return DB.Dash.model_validate_json((FIX / "dash_ma_supercycle.json").read_text(encoding="utf-8")), Ledger.load(FIX / "ledger_ma_supercycle.json")


def test_parse_amount_scales_to_chart_unit():
    assert DB.parse_amount("$209B", "B") == 209
    assert DB.parse_amount("~$1.3T", "B") == 1300
    assert DB.parse_amount("$527M", "M") == 527
    assert DB.parse_amount("42%", "%") == 42


def test_bar_heights_come_from_labels():
    d, _ = load()
    assert [p.value for p in d.chart.points] == [86, 150, 115, 209, 250]
    assert d.chart.points[-1].booked == 106


def test_regression_ma_supercycle_matches_ledger_and_rules():
    d, led = load()
    assert DB.check_against_ledger(d, led) == []
    page = DB.render(d)
    assert DB.lint_html(page) == []
    for must in ("PharmaDash · M&amp;A Series · Issue 03", '<span class="em">M&amp;A supercycle</span>', "$527M", "+44%",
                 "--accent:#10916B", "--panel:#0E141B", "Space Grotesk", "IBM Plex Mono"):
        assert must in page
    assert len(__import__("re").findall(r'class="kpi[ "]', page)) == 4 and page.count("<li>") == 4


def test_invented_figure_is_caught():
    d, led = load()
    d.chart.points[3].text = "$290B"
    assert any("$290B" in p for p in DB.check_against_ledger(d, led))


def test_unit_slip_is_caught():
    d, led = load()
    d.kpis[0].value = "$106M"
    assert any("1,000x" in p for p in DB.check_against_ledger(d, led))


def test_figure_in_wrong_claim_is_caught():
    d, led = load()
    d.chart.points[0].claim = "C004"      # the 2025 claim cited for the 2022 bar
    assert any("cited claim" in p for p in DB.check_against_ledger(d, led))


def test_shape_rules():
    d, _ = load()
    data = d.model_dump()
    data["kpis"] = data["kpis"][:3]
    with pytest.raises(ValueError):
        DB.Dash.model_validate(data)


def test_html_is_escaped():
    d, _ = load()
    d.dek = "<script>alert(1)</script>"
    assert "<script>alert(1)" not in DB.render(d)


def test_prose_check_catches_bad_multiplier_and_unknown_numbers():
    from pharmadash.agents.dashboard import prose_problems
    d, led = load()
    assert prose_problems(d, led) == []
    d.reading[0].text = "Value rose from $86 billion in 2022 and has more than quadrupled since."
    assert any("quadrupled" in p for p in prose_problems(d, led))
    d, led = load()
    d.reading[1].text = "Deal value reached $320 billion."
    assert any("$320 billion" in p for p in prose_problems(d, led))


def test_tidy_removes_claim_ids_and_fixes_title_spacing():
    d, _ = load()
    d.kpis[0].sub = "C006 – as of early June"
    d.title_before, d.title_em, d.title_after = "Deals Soar", "From 2022", "to 2025"
    DB.tidy(d)
    assert d.kpis[0].sub == "as of early June"
    assert (d.title_before + d.title_em + d.title_after).count("  ") == 0 and d.title_after == " to 2025"


def test_long_headline_is_flagged():
    from pharmadash.agents.dashboard import prose_problems
    d, led = load()
    d.title_em = "supercycle " * 8
    assert any("too long" in p for p in prose_problems(d, led))
