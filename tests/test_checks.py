from pharmadash import checks
from pharmadash.claims import Claim, Ledger


def nums(t):
    return [(n.text, n.kind, n.value) for n in checks.extract_numbers(t)]


def test_extraction_kinds_and_skips():
    t = "Lilly booked **$19.8 billion** in Q3 2026, up 56% (about 201 deals). Issue 5 on July 1, 2026 had 3 things."
    got = nums(t)
    assert ("$19.8 billion", "money", 19.8e9) in got
    assert ("56%", "pct", 56.0) in got
    assert any(k == "count" and v == 201 for _, k, v in got)
    assert len(got) == 3     # Q3, 2026, Issue 5, July 1, "3 things" are skipped


def test_short_scale_letters_and_ranges():
    assert nums("$106B across deals") == [("$106B", "money", 106e9)]
    assert nums("$527M average") == [("$527M", "money", 527e6)]


def ledger():
    l = Ledger(topic="t", built="2026-10-28")
    l.add(Claim(claim="Total M&A value 2026 so far $106 billion", value="106", unit="USD billion", as_of="2026-06", status="single-source",
                source_url="http://a.com/x"))
    l.add(Claim(claim="Average deal size 2025 $365 million", value="365", unit="USD million", as_of="2025", status="single-source", source_url="http://a.com/x"))
    l.add(Claim(claim="Average deal size 2026 $527 million", value="527", unit="USD million", as_of="2026", status="single-source", source_url="http://a.com/x"))
    return l


def test_match_and_precision():
    l = ledger()
    n = checks.extract_numbers("$106B booked")[0]
    assert [c.id for c in checks.match_to_ledger(n, l)[0]] == ["C001"]
    wrong = checks.extract_numbers("$107B booked")[0]
    assert checks.match_to_ledger(wrong, l) == ([], False)


def test_million_vs_billion_mismatch_is_caught():
    hits, scale_err = checks.match_to_ledger(checks.extract_numbers("average deal $527 billion")[0], ledger())
    assert hits == [] and scale_err


def test_percent_derived_only_from_figures_in_same_sentence():
    l = ledger()
    n = checks.extract_numbers("The average deal rose from $365 million to $527 million, up 44%.")[-1]
    res, co, cn, pcs = checks.derive_percent(n, l)
    assert (res, co.id, cn.id, pcs) == ("match", "C002", "C003", [44.4])
    wrong = checks.extract_numbers("The average deal rose from $365 million to $527 million, up 61%.")[-1]
    assert checks.derive_percent(wrong, l)[0] == "mismatch"
    lonely = checks.extract_numbers("Deals are up 44% this year.")[0]
    assert checks.derive_percent(lonely, l)[0] == "none"      # no unrelated pair can vouch for it


def test_multiplier_claims_need_two_figures_in_the_sentence():
    l = ledger()
    assert checks.ratio_issues("Deal size rose to $527 million from $365 million, about 1.4x.", l) == []
    assert checks.ratio_issues("Revenue is almost four times the $365 million of 2025.", l)       # only one figure given
    assert "give" in checks.ratio_issues("It is about 4 times: $527 million vs $365 million.", l)[0]


def test_recompute_flags_bad_derived():
    l = ledger()
    l.add(Claim(claim="g", value="50.0", unit="%", origin="derived", derived_from=["C002", "C003"]))
    assert "computes to 44.4%" in checks.recompute_derived(l)[0]


def test_corroboration_needs_different_sites():
    l = Ledger(topic="t", built="x")
    for url in ("http://a.com/1", "http://b.com/2"):
        l.add(Claim(claim="Deal total $1.38 billion", value="1.38", unit="USD billion", as_of="2026-10-27", source_url=url, status="single-source"))
    assert checks.corroborate(l) == 2 and l.claims[0].status == "verified"
    same = Ledger(topic="t", built="x")
    for url in ("http://a.com/1", "http://a.com/2"):
        same.add(Claim(claim="Deal total $1.38 billion", value="1.38", unit="USD billion", as_of="2026-10-27", source_url=url, status="single-source"))
    assert checks.corroborate(same) == 0


def test_conflict_between_trackers():
    l = Ledger(topic="t", built="x")
    l.add(Claim(claim="Global biopharma M&A value for 2026 forecast", value="250", unit="USD billion", as_of="2026", source_url="http://pitchbook.com/a"))
    l.add(Claim(claim="Global biopharma M&A value for 2026 forecast", value="150", unit="USD billion", as_of="2026", source_url="http://iqvia.com/b"))
    assert len(checks.find_conflicts(l)) == 1


def test_deal_wording():
    assert checks.deal_wording_issues("Sun Pharma acquired Organon for $11.75 billion.")
    assert not checks.deal_wording_issues("Pfizer paid $1.25 billion upfront in the licensing deal.")
    assert not checks.deal_wording_issues("Deal values are $6.7 billion as announced.")
