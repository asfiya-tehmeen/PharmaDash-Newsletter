"""The full pipeline behind `produce` and `run`, with saved progress after every stage.

Stages per topic: research -> dashboards -> write+check -> package. Progress lives in output/runs/<run-id>/state.json,
so `--resume` skips everything already done. Nothing here publishes anything.
"""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, Field

from . import config, dashboards as DB, llm, report, screenshots, style, topics as T
from .claims import Ledger

FIXTURES = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "dry"
STAGES = ["research", "dashboards", "write", "package"]


class Item(BaseModel):
    n: int
    title: str
    angle: str = ""
    slug: str
    issue: int
    done: list[str] = Field(default_factory=list)
    dashboards: list[dict] = Field(default_factory=list)       # [{stem, title, path, problems}]
    summary: dict = Field(default_factory=dict)
    folder: str = ""


class RunState(BaseModel):
    run_id: str
    created: str
    command: str = "run"
    dry_run: bool = False
    focus: Optional[str] = None
    custom: Optional[str] = None
    auto: Optional[int] = None
    topics: list[dict] = Field(default_factory=list)
    topics_file: str = ""
    discovered: bool = False
    items: list[Item] = Field(default_factory=list)
    status: str = "running"             # running | failed | done
    failed_stage: str = ""
    error: str = ""
    usage: str = ""


class NotEnoughEvidence(Exception):
    """Research found too few usable facts to write a trustworthy article."""


class StageError(Exception):
    """A stage failed. `hint` tells the user what to do next."""

    def __init__(self, stage: str, message: str, hint: str):
        super().__init__(message)
        self.stage, self.message, self.hint = stage, message, hint


# ------------------------------------------------------------------ state files

def run_dir(run_id: str) -> Path:
    return config.RUNS_DIR / run_id


def save_state(st: RunState) -> None:
    d = run_dir(st.run_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(st.model_dump_json(indent=2), encoding="utf-8")


def new_state(command: str, **kw) -> RunState:
    now = datetime.now()
    prefix = "dry_" if kw.get("dry_run") else ""
    return RunState(run_id=f"{prefix}{now:%Y-%m-%d_%H%M%S}", created=now.isoformat(timespec="seconds"), command=command, **kw)


def latest_unfinished(dry_run: Optional[bool] = None) -> Optional[RunState]:
    for f in sorted(config.RUNS_DIR.glob("*/state.json"), reverse=True):
        try:
            st = RunState.model_validate_json(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if st.status != "done" and (dry_run is None or st.dry_run == dry_run):
            return st
    return None


def resume_command(st: RunState) -> str:
    return f"pharmadash {st.command} --resume" + (" --dry-run" if st.dry_run else "")


# ------------------------------------------------------------------ helpers

def _fixture_ledger(title: str) -> Ledger:
    led = Ledger.load(FIXTURES.parent / "ledger_china_licensing.json")
    led.topic = f"{title} (DRY RUN: fixture data, nothing live was fetched)"
    return led


def _stage_error(stage: str, e: Exception, st: RunState) -> StageError:
    resume = resume_command(st)
    if isinstance(e, NotEnoughEvidence):
        return StageError(stage, str(e), f"Nothing was written, so nothing can be wrong. Fix the cause above, then run: {resume}  "
                          "(or try a more specific --custom topic)")
    if isinstance(e, llm.DailyLimitReached):
        return StageError(stage, str(e), f"Groq's free daily allowance is used up. Progress is saved. Wait, then run: {resume}")
    if isinstance(e, llm.BudgetExceeded):
        return StageError(stage, str(e), f"The token cap in config.yaml (usage_limits) was reached. Raise it if you want, then run: {resume}")
    if isinstance(e, (llm.RequestTooLarge, ValueError)):
        return StageError(stage, f"The model could not complete this step cleanly ({str(e)[:200]}).", f"Run it again: {resume}")
    name = type(e).__name__
    if "Connection" in name or "Timeout" in name or "Network" in name:
        return StageError(stage, f"Network problem ({name}).", f"Check your internet connection, then run: {resume}")
    return StageError(stage, f"{name}: {str(e)[:300]}", f"Progress is saved. Run: {resume}  (if it keeps failing, send me this message)")


# ------------------------------------------------------------------ stages

def discover_stage(st: RunState, log: Callable[[str], None]) -> list[T.Topic]:
    if st.custom:
        return []
    if st.dry_run:
        topics = [T.Topic.model_validate(t) for t in json.loads((FIXTURES / "topics.json").read_text(encoding="utf-8"))]
        st.topics = [t.model_dump() for t in topics]
        return topics
    from .agents import discovery
    ranked, info = discovery.discover(st.focus, log=log)
    st.topics_file = str(T.save(ranked, st.focus, info))
    st.topics = [t.model_dump() for t in ranked]
    return ranked


def make_items(st: RunState, picks: list[int]) -> None:
    """Fix topic -> issue number now, so a resumed run builds the same dashboards and filenames."""
    cfg = config.load_config()
    base = cfg["issue_counter"]
    if st.custom:
        specs = [(st.custom, "", T.slug(st.custom))]
    else:
        specs = [(st.topics[i - 1]["headline"], st.topics[i - 1]["angle"], T.slug(st.topics[i - 1]["headline"])) for i in picks]
    st.items = [Item(n=k, title=t, angle=a, slug=s, issue=base + k - 1) for k, (t, a, s) in enumerate(specs, 1)]


def research_stage(st: RunState, it: Item, folder: Path, log: Callable[[str], None]) -> None:
    if st.dry_run:
        led = _fixture_ledger(it.title)
    else:
        from . import orchestrator
        subject = st.custom if st.custom else T.Topic.model_validate(st.topics[_topic_index(st, it)])
        led = orchestrator.research_topic(subject, log=log)
    led.save(folder / "claims_ledger.json")
    need = config.load_config().get("min_claims", 5)
    usable = sum(1 for c in led.claims if c.status != "unverified")
    if usable < need:
        why = []
        if not config.sec_user_agent():
            why.append("SEC_USER_AGENT is empty in .env, so company financials were skipped")
        blocked = len(led.pages_blocked)
        if blocked:
            why.append(f"{blocked} source page(s) could not be read")
        if any("daily" in n.lower() or "limit" in n.lower() for n in led.notes):
            why.append("the Groq free quota ran short during research")
        raise NotEnoughEvidence(f"Research found only {usable} usable fact(s); at least {need} are needed to write without guessing. "
                                + ("Likely causes: " + "; ".join(why) + "." if why else "The sources found had too few checkable numbers.")
                                + f" The ledger is saved at {folder / 'claims_ledger.json'}.")


def _topic_index(st: RunState, it: Item) -> int:
    return next(i for i, t in enumerate(st.topics) if t["headline"] == it.title)


def dashboards_stage(st: RunState, it: Item, folder: Path, log: Callable[[str], None]) -> None:
    out = folder / "dashboards"
    led = Ledger.load(folder / "claims_ledger.json")
    if st.dry_run:
        d = DB.Dash.model_validate_json((FIXTURES / "dash_china.json").read_text(encoding="utf-8"))
        d.issue = it.issue
        d.sources = "Figures from the test ledger (dry run)."
        problems = DB.check_against_ledger(d, led)
        path = DB.build(d, out)
        built = [{"stem": d.file_stem, "title": "China's licensing takeoff, in numbers", "path": str(path), "problems": problems}]
    else:
        from .agents import dashboard as dash_agent
        built = [b.model_dump() for b in dash_agent.make_dashboards(it.title, it.angle, led, it.issue, out, log=log)]
    for b in built:
        if b["path"]:
            shot = screenshots.shoot(Path(b["path"]), out / "screenshots")
            b["problems"] += shot.problems
            b["screenshots"] = len(shot.files)
            if not shot.files and shot.note:
                log(shot.note)
    it.dashboards = built


def write_stage(st: RunState, it: Item, folder: Path, log: Callable[[str], None]) -> None:
    from .agents import verifier, writer
    led = Ledger.load(folder / "claims_ledger.json")
    dashes = [(b["stem"], b["title"]) for b in it.dashboards if b["path"]]
    if st.dry_run:
        body = (FIXTURES / "article_body.md").read_text(encoding="utf-8").rstrip()
        article = style.clean_typography(body) + writer.footer_block(led, config.load_config())
        verifier.verify_draft(article, led, log=log, use_model=False)
        led.notes += [f"STYLE: {i}" for i in style.lint(article, dashboards=[d for d, _ in dashes]) if not i.startswith("(soft)")]
    else:
        from . import orchestrator
        article = orchestrator.write_and_verify(it.title, it.angle, led, dashes, log=log)
    for b in it.dashboards:
        for p in b["problems"]:
            led.notes.append(f"DASHBOARD {b['title'][:50]}: {p}")
    (folder / "article.md").write_text(article, encoding="utf-8")
    led.save(folder / "claims_ledger.json")
    (folder / "factcheck_report.md").write_text(report.render(led, it.title), encoding="utf-8")
    (folder / "sources.md").write_text(report.sources_md(led, it.title), encoding="utf-8")
    bad = verifier.failures(led)
    it.summary = {"words": style.metrics(article)["words"], "checked": len(led.draft_checks), "attention": len(bad),
                  "dashboards": sum(1 for b in it.dashboards if b["path"])}


def package_stage(st: RunState, it: Item, folder: Path, log: Callable[[str], None]) -> None:
    root = run_dir(st.run_id) / "issues" if st.dry_run else config.ISSUES_DIR
    dest = root / f"issue-{it.issue:02d}_{it.slug}"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in ("article.md", "factcheck_report.md", "sources.md", "claims_ledger.json"):
        shutil.copy(folder / name, dest / name)
    if (folder / "dashboards").exists():
        shutil.copytree(folder / "dashboards", dest / "dashboards")
    it.folder = str(dest)
    if st.dry_run:
        return
    hist = json.loads(config.HISTORY_PATH.read_text(encoding="utf-8")) if config.HISTORY_PATH.exists() else {"issues": []}
    hist["issues"] = [h for h in hist["issues"] if h.get("issue") != it.issue]
    hist["issues"].append({"issue": it.issue, "date": date.today().isoformat(), "title": it.title, "slug": it.slug,
                           "folder": str(dest), "published": False, **it.summary,
                           "dashboards_built": [b["stem"] for b in it.dashboards if b["path"]]})
    config.HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.HISTORY_PATH.write_text(json.dumps(hist, indent=2), encoding="utf-8")
    config.save_issue_counter(max(config.load_config()["issue_counter"], it.issue + 1))


RUNNERS = {"research": research_stage, "dashboards": dashboards_stage, "write": write_stage, "package": package_stage}


def run_items(st: RunState, log: Callable[[str], None], stage_note: Callable[[str], None] = lambda s: None) -> None:
    """Run every unfinished stage of every item. Raises StageError at the first failure (state is saved first)."""
    for it in st.items:
        folder = run_dir(st.run_id) / f"topic_{it.n}_{it.slug[:40]}"
        folder.mkdir(parents=True, exist_ok=True)
        for stage in STAGES:
            if stage in it.done:
                continue
            stage_note(f"[topic {it.n}/{len(st.items)}] {stage}: {it.title[:60]}")
            try:
                RUNNERS[stage](st, it, folder, log)
            except Exception as e:     # every failure becomes a saved state plus a plain-English message
                err = _stage_error(stage, e, st)
                st.status, st.failed_stage, st.error = "failed", f"topic {it.n}: {stage}", err.message
                save_state(st)
                raise err from e
            it.done.append(stage)
            st.status, st.failed_stage, st.error = "running", "", ""
            save_state(st)
    st.status = "done"
    st.usage = llm.USAGE.summary(config.load_config().get("plan", "free"))
    save_state(st)
