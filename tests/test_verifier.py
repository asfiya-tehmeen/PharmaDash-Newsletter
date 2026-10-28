from pharmadash import report
from pharmadash.agents import verifier
from pharmadash.claims import Claim, Ledger

DRAFT = """# Pharma M&A hits **$106 billion**

*Deals are up, and the average is $527 million.*

---

Sun Pharma acquired Organon for $11.75 billion. The average deal rose to $527 billion, up 44%. Deal size went from $365 million to $527 million, up 61%.
"""


def ledger():
    l = Ledger(topic="t", built="2026-10-28")
    for text, v, u in (("Total 2026 M&A $106 billion", "106", "USD billion"), ("Average deal 2025 $365 million", "365", "USD million"),
                       ("Average deal 2026 $527 million", "527", "USD million")):
        l.add(Claim(claim=text, value=v, unit=u, as_of="2026", source_url="http://x.com/1", source_type="secondary", status="single-source"))
    l.add(Claim(claim="SEC: revenue", value="10", unit="USD", as_of="2026", source_url="http://sec.gov/1", source_type="primary", status="verified"))
    return l


def test_code_checks_without_model():
    l = ledger()
    verifier.verify_draft(DRAFT, l, use_model=False)
    by_text = {c.text: c for c in l.draft_checks}
    assert by_text["$527 billion"].status == "conflict"                      # million vs billion slip
    assert by_text["$106 billion"].status == "single-source" and by_text["$106 billion"].in_headline
    assert by_text["61%"].status == "conflict" and "44.4%" in by_text["61%"].notes   # recomputed from the sentence's own figures
    assert any(c.kind == "deal-wording" for c in l.draft_checks)            # Organon deal value has no qualifier
    assert by_text["$11.75 billion"].status == "unverified"
    assert {c.id for c in verifier.failures(l)} >= {by_text["$527 billion"].id, by_text["$106 billion"].id}


def test_report_lists_problems_first():
    l = ledger()
    verifier.verify_draft(DRAFT, l, use_model=False)
    md = report.render(l, "demo")
    assert md.index("Needs your attention") < md.index("## Summary") < md.index("## Ledger")
    assert "CONFLICT" in md and "off by 1,000x" in md


def test_typography_cleanup_and_ranges():
    from pharmadash import checks, style
    out = style.clean_typography("out\u2011licensing 60\u201170 % lower (C015) and (C001, C002)  x  ")
    assert out == "out-licensing 60-70% lower and x"
    assert [(n.text, n.kind) for n in checks.extract_numbers("upfronts 60-70% lower")] == [("60", "pct"), ("70%", "pct")]
    assert [n.text for n in checks.extract_numbers("SSGJ-707 got $1.25 billion")] == ["$1.25 billion"]


def test_fix_flagged_replaces_sentence_with_markdown(monkeypatch):
    from pharmadash.agents import writer
    from pharmadash.claims import DraftCheck
    art = "# T\n\nIntro line. A similar pace would push the total to near **$200 billion**.\n\nEnd."
    flagged = [DraftCheck(text="$200 billion", sentence="A similar pace would push the total to near **$200 billion**.", notes="not in ledger")]
    monkeypatch.setattr(writer.llm, "ask_json", lambda *a, **k: writer.Fixes(fixes=[writer.Fix(
        original="A similar pace would push the total to near $200 billion.", replacement="Full-year 2026 totals are not yet disclosed.")]))
    new, n = writer.fix_flagged(art, flagged, Ledger(topic="t", built="x"), log=lambda s: None)
    assert n == 1 and "$200 billion" not in new and "not yet disclosed" in new


def test_fix_keeps_italic_dek_and_list_markers(monkeypatch):
    from pharmadash.agents import writer
    from pharmadash.claims import DraftCheck
    art = "# T\n\n*Deals hit 250 billion this year, says nobody.*\n\n1. **Velocity** - a bad claim here.\n"
    flagged = [DraftCheck(text="x", sentence="*Deals hit 250 billion this year, says nobody.*", notes="n"),
               DraftCheck(text="y", sentence="**Velocity** - a bad claim here.", notes="n")]
    monkeypatch.setattr(writer.llm, "ask_json", lambda *a, **k: writer.Fixes(fixes=[
        writer.Fix(original="Deals hit 250 billion this year, says nobody.", replacement="Deal totals are not yet disclosed."),
        writer.Fix(original="Velocity - a bad claim here.", replacement="**Velocity** - watch Q2 pace.")]))
    new, n = writer.fix_flagged(art, flagged, Ledger(topic="t", built="x"), log=lambda s: None)
    assert n == 2
    assert "*Deal totals are not yet disclosed.*" in new and "****" not in new
    assert "1. **Velocity** - watch Q2 pace." in new


def test_lint_catches_merged_bullets_and_missing_dashboard_pointer():
    from pharmadash import style
    md = ("# T\n\n*dek*\n\n---\n\nIntro.\n\n---\n\n## By the numbers\n\n"
          "* **~30%**: China's share, up from 21%.**$60 billion**: Deal value in Q1.\n\n---\n\n"
          "*PharmaDash breaks down x*\n\n*Sources: x*\n")
    issues = style.lint(md, 0, 9999, dashboards=["growth"])
    assert any("merged" in i for i in issues) and any("See the dashboard" in i for i in issues)
