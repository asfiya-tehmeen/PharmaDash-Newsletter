import json

import pytest
from typer.testing import CliRunner

from pharmadash import config, llm, pipeline, screenshots
from pharmadash.cli import app


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    """Runs write into a temp folder; the real history, issue counter and issues folder are never touched."""
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "ISSUES_DIR", tmp_path / "issues")
    monkeypatch.setattr(config, "HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr(screenshots, "available", lambda: False)     # browser test has its own check; keeps this suite fast
    return tmp_path


def dry_state(n=1):
    st = pipeline.new_state("run", dry_run=True, auto=n)
    pipeline.discover_stage(st, print)
    pipeline.make_items(st, list(range(1, n + 1)))
    pipeline.save_state(st)
    return st


def test_dry_run_builds_everything_without_touching_history(sandbox):
    st = dry_state(2)
    pipeline.run_items(st, log=lambda s: None)
    assert st.status == "done" and [i.issue for i in st.items] == [config.load_config()["issue_counter"] + k for k in (0, 1)]
    for it in st.items:
        folder = sandbox / "runs" / st.run_id / "issues" / f"issue-{it.issue:02d}_{it.slug}"
        for f in ("article.md", "factcheck_report.md", "sources.md", "claims_ledger.json"):
            assert (folder / f).exists()
        assert list((folder / "dashboards").glob("*.html"))
    assert not (sandbox / "history.json").exists()


def test_failure_saves_progress_and_resume_skips_finished_stages(sandbox, monkeypatch):
    st = dry_state(1)
    calls = {"research": 0}
    real_research, real_write = pipeline.RUNNERS["research"], pipeline.RUNNERS["write"]

    def counting_research(*a, **k):
        calls["research"] += 1
        return real_research(*a, **k)

    def failing_write(*a, **k):
        raise llm.DailyLimitReached("Groq daily token limit reached")

    monkeypatch.setitem(pipeline.RUNNERS, "research", counting_research)
    monkeypatch.setitem(pipeline.RUNNERS, "write", failing_write)
    with pytest.raises(pipeline.StageError) as e:
        pipeline.run_items(st, log=lambda s: None)
    assert "pharmadash run --resume" in e.value.hint and "--dry-run" in e.value.hint
    saved = pipeline.RunState.model_validate_json((sandbox / "runs" / st.run_id / "state.json").read_text(encoding="utf-8"))
    assert saved.status == "failed" and saved.items[0].done == ["research", "dashboards"]

    monkeypatch.setitem(pipeline.RUNNERS, "write", real_write)
    again = pipeline.latest_unfinished(True)
    pipeline.run_items(again, log=lambda s: None)
    assert again.status == "done" and calls["research"] == 1          # research was not repeated


def test_cli_dry_run_and_resume_messages(sandbox):
    r = CliRunner()
    out = r.invoke(app, ["run", "--dry-run", "--auto", "1"])
    assert out.exit_code == 0 and "Nothing has been published" in out.output
    out = r.invoke(app, ["run", "--resume", "--dry-run"])
    assert out.exit_code == 1 and "Nothing to resume" in out.output


def test_cli_rejects_bad_topic_selection():
    out = CliRunner().invoke(app, ["produce", "--dry-run", "--topics", "9"])
    assert out.exit_code == 1 and "between 1 and" in out.output


def test_history_empty():
    out = CliRunner().invoke(app, ["history"])
    assert out.exit_code == 0 and "No issues produced yet" in out.output


def test_run_stops_instead_of_writing_when_research_finds_nothing(sandbox, monkeypatch):
    from pharmadash.claims import Ledger
    monkeypatch.setattr(pipeline, "_fixture_ledger", lambda title: Ledger(topic=title, built="2026-10-28"))
    st = dry_state(1)
    with pytest.raises(pipeline.StageError) as e:
        pipeline.run_items(st, log=lambda s: None)
    assert "usable fact" in e.value.message and "--resume" in e.value.hint
    assert st.items[0].done == [] and st.status == "failed"
    assert not (sandbox / "history.json").exists()
