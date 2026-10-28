"""Command-line entry point: `pharmadash <command>`."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from . import __version__, config

app = typer.Typer(help="PharmaDash: research, verify and draft your newsletter issue. Never publishes.",
                  no_args_is_help=True, add_completion=False)
console = Console()


def _not_yet(name: str, milestone: int) -> None:
    console.print(f"[yellow]`{name}` is not built yet (milestone {milestone}).[/yellow]")
    raise typer.Exit(1)


@app.command()
def init() -> None:
    """Create folders, check your keys and tools."""
    root = config.ROOT
    for d in [config.CACHE_DIR, config.TOPICS_DIR, config.ISSUES_DIR, config.RUNS_DIR, config.EXAMPLES_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    if not config.CONFIG_PATH.exists():
        console.print("[red]config.yaml is missing from the project folder.[/red]")
        raise typer.Exit(1)
    if not config.HISTORY_PATH.exists():
        config.HISTORY_PATH.write_text('{"issues": []}\n', encoding="utf-8")
    env_file, env_example = root / ".env", root / ".env.example"
    if not env_file.exists() and env_example.exists():
        shutil.copy(env_example, env_file)
        console.print("Created [bold].env[/bold]. Open it and fill in your two values.")

    problems = 0

    def check(ok: bool, good: str, bad: str) -> None:
        nonlocal problems
        console.print(f"[green]OK[/green]   {good}" if ok else f"[red]FIX[/red]  {bad}")
        problems += 0 if ok else 1

    check(bool(config.groq_api_key()), "GROQ_API_KEY is set",
          "GROQ_API_KEY is empty. Add it to the .env file (free key at console.groq.com/keys).")
    ua = config.sec_user_agent()
    check("@" in ua, "SEC_USER_AGENT is set",
          "SEC_USER_AGENT needs your name and email, e.g. PharmaDash Newsletter you@example.com")
    try:
        import playwright  # noqa: F401
        console.print("[green]OK[/green]   Playwright installed (screenshot test enabled)")
    except ImportError:
        console.print("[yellow]NOTE[/yellow] Playwright not installed. Dashboard screenshot test will be skipped. "
                      "Optional: pip install playwright && playwright install chromium")
    cfg = config.load_config()
    console.print(f"Next issue number: [bold]{cfg['issue_counter']:02d}[/bold]. Watchlist: {len(cfg['watchlist'])} companies.")
    console.print("\n[bold]All set.[/bold] Try: pharmadash run --dry-run" if problems == 0
                  else f"\n[bold]{problems} item(s) to fix above, then run `pharmadash init` again.[/bold]")


@app.command()
def discover(focus: Optional[str] = typer.Option(None, help='Optional steer, e.g. "AI in pharma"')) -> None:
    """Step 1: research the news and propose ranked topics."""
    discover_and_show(focus)


def show_topics(ranked: list) -> None:
    from rich.table import Table
    table = Table(title=f"Topic ideas ({len(ranked)})", show_lines=True)
    for col in ("#", "Score", "Headline", "Flags"):
        table.add_column(col, overflow="fold")
    for i, t in enumerate(ranked, 1):
        table.add_row(str(i), f"{t.total_score}", t.headline + (" (evergreen)" if t.evergreen else ""), ", ".join(t.risk_flags) or "-")
    console.print(table)


def discover_and_show(focus: Optional[str]) -> list:
    """Shared by `discover` and `run`: research, save the topics file, print the numbered list."""
    from . import llm, topics as T
    from .agents import discovery

    try:
        ranked, info = discovery.discover(focus, log=lambda s: console.print(f"[dim]{s}[/dim]"))
    except (llm.BudgetExceeded, llm.DailyLimitReached) as e:
        console.print(f"[red]Stopped:[/red] {e}")
        raise typer.Exit(1)
    path = T.save(ranked, focus, info)
    show_topics(ranked)
    console.print(f"Saved: {path}")
    if info["unreachable"]:
        console.print(f"[yellow]Unreachable sources:[/yellow] {', '.join(info['unreachable'])}")
    cfg = config.load_config()
    console.print(f"[dim]{llm.USAGE.summary(cfg.get('plan', 'free'))}[/dim]")
    return ranked


def _short(folder: str) -> str:
    """Folder path relative to the project when possible."""
    try:
        return str(Path(folder).relative_to(config.ROOT)) if folder else "-"
    except ValueError:
        return folder


def _execute(st) -> None:
    """Run the saved pipeline state to the end, print progress, a clear failure message, or the summary."""
    from rich.panel import Panel
    from rich.table import Table
    from . import config as C, llm, pipeline
    try:
        pipeline.run_items(st, log=lambda s: console.print(f"[dim]  {s}[/dim]"), stage_note=lambda s: console.print(f"[bold cyan]{s}[/bold cyan]"))
    except pipeline.StageError as e:
        console.print(Panel(f"[bold]Stopped at {st.failed_stage}[/bold]\n{e.message}\n\n[bold]What to do:[/bold] {e.hint}",
                            title="Run paused, nothing is lost", border_style="red"))
        raise typer.Exit(1)
    table = Table(title="Run summary", show_lines=True)
    for col in ("Issue", "Topic", "Words", "Facts checked", "Need your attention", "Dashboards"):
        table.add_column(col, overflow="fold")
    for it in st.items:
        sm = it.summary
        table.add_row(f"{it.issue:02d}", it.title[:60], str(sm.get("words", "-")), str(sm.get("checked", "-")),
                      f"[red]{sm.get('attention')}[/red]" if sm.get("attention") else "[green]0[/green]", str(sm.get("dashboards", 0)))
    console.print(table)
    for it in st.items:
        console.print(f"Issue {it.issue:02d} folder: [bold]{_short(it.folder)}[/bold]")
    for it in st.items:
        for b in it.dashboards:
            for p in b["problems"]:
                console.print(f"[yellow]dashboard note:[/yellow] {b['title'][:40]}: {p}")
    console.print(f"[dim]{llm.USAGE.summary(C.load_config().get('plan', 'free'))}[/dim]")
    where = "output/runs/" + st.run_id + "/issues" if st.dry_run else "output/issues"
    console.print(f"\n[bold green]Done.[/bold green] Open each folder in {where}: read [bold]factcheck_report.md[/bold] first, "
                  "then edit [bold]article.md[/bold]. [bold]Nothing has been published.[/bold]")


@app.command()
def produce(topics: Optional[str] = typer.Option(None, help="Topic numbers from the latest topics file, e.g. 1,3 (or all / top3)"),
            custom: Optional[str] = typer.Option(None, help="Your own topic text; skips discovery"),
            dry_run: bool = typer.Option(False, "--dry-run", help="Use built-in test data, no live calls"),
            resume: bool = typer.Option(False, "--resume", help="Continue the last unfinished produce run")) -> None:
    """Step 2: research, verify, write and build dashboards for chosen topics."""
    from . import pipeline, topics as T
    if resume:
        st = pipeline.latest_unfinished(dry_run)
        if not st:
            console.print("[yellow]Nothing to resume.[/yellow]")
            raise typer.Exit(1)
        console.print(f"Resuming run {st.run_id}")
    else:
        st = pipeline.new_state("produce", dry_run=dry_run, custom=custom)
        if custom:
            pipeline.make_items(st, [])
        else:
            if not topics:
                console.print('[red]Say which topics: --topics 1,3 (numbers from the latest topics file) or --custom "your topic".[/red]')
                raise typer.Exit(1)
            try:
                ranked = pipeline.discover_stage(st, print) if dry_run else T.load_latest()[0]
                picks = T.parse_selection(topics, len(ranked))
            except (FileNotFoundError, ValueError) as e:
                console.print(f"[red]{e}[/red]")
                raise typer.Exit(1)
            st.topics = [t.model_dump() for t in ranked]
            pipeline.make_items(st, picks)
        pipeline.save_state(st)
    _execute(st)


@app.command()
def run(focus: Optional[str] = typer.Option(None, help="Steer discovery"),
        auto: Optional[int] = typer.Option(None, help="Skip the pause; pick the top N topics"),
        custom: Optional[str] = typer.Option(None, help="Your own topic text; skips discovery"),
        dry_run: bool = typer.Option(False, "--dry-run", help="Run everything on built-in test data, no live calls"),
        resume: bool = typer.Option(False, "--resume", help="Continue the last unfinished run")) -> None:
    """The whole pipeline in one command (pauses once to ask which topics)."""
    from . import pipeline, topics as T
    log = lambda s: console.print(f"[dim]{s}[/dim]")     # noqa: E731
    if dry_run:
        console.print("[bold yellow]DRY RUN[/bold yellow]: built-in test data only. No model calls, no internet, no changes to your history or issue counter.")
    if resume:
        st = pipeline.latest_unfinished(dry_run)
        if not st:
            console.print("[yellow]Nothing to resume: no unfinished run found.[/yellow] Start a new one with `pharmadash run`.")
            raise typer.Exit(1)
        console.print(f"Resuming run [bold]{st.run_id}[/bold] (finished steps are skipped).")
    else:
        st = pipeline.new_state("run", dry_run=dry_run, focus=focus, custom=custom, auto=auto)
        pipeline.save_state(st)
    if st.custom and not st.items:
        pipeline.make_items(st, [])
        pipeline.save_state(st)
    elif not st.items:
        if not st.topics:
            try:
                if dry_run:
                    ranked = pipeline.discover_stage(st, log)
                    show_topics(ranked)
                else:
                    ranked = discover_and_show(st.focus)
                    st.topics = [t.model_dump() for t in ranked]
            except typer.Exit:
                st.status, st.failed_stage = "failed", "discover"
                pipeline.save_state(st)
                console.print(f"[bold]Nothing was lost. When ready, run:[/bold] {pipeline.resume_command(st)}")
                raise
            except Exception as e:     # network or parsing trouble in discovery
                st.status, st.failed_stage, st.error = "failed", "discover", str(e)[:300]
                pipeline.save_state(st)
                console.print(f"[red]Discovery stopped:[/red] {type(e).__name__}: {str(e)[:250]}\n[bold]Run:[/bold] {pipeline.resume_command(st)}")
                raise typer.Exit(1)
            pipeline.save_state(st)
        else:
            ranked = [T.Topic.model_validate(t) for t in st.topics]
            show_topics(ranked)
        if st.auto:
            picks = list(range(1, min(st.auto, len(ranked)) + 1))
            console.print(f"--auto {st.auto}: taking topics {picks}")
        else:
            while True:
                try:
                    answer = typer.prompt("\nWhich topics should I produce? Numbers like 1,3 (or 'all', 'top3', 'q' to stop)")
                except typer.Abort:
                    console.print("\nStopped. Run `pharmadash run --resume` to choose again.")
                    raise typer.Exit(0)
                if answer.strip().lower() in ("q", "quit", "exit"):
                    console.print("Stopped. Run `pharmadash run --resume` to choose again.")
                    raise typer.Exit(0)
                try:
                    picks = T.parse_selection(answer, len(ranked))
                    break
                except ValueError as e:
                    console.print(f"[red]{e}[/red]")
        pipeline.make_items(st, picks)
        pipeline.save_state(st)
    _execute(st)


@app.command()
def research(topic: Optional[int] = typer.Option(None, "--topic", help="Topic number from the latest topics file"),
             custom: Optional[str] = typer.Option(None, "--custom", help="Your own topic text")) -> None:
    """Research one topic and write its claims ledger (a building block of `produce`)."""
    from . import llm, orchestrator, topics as T
    if custom:
        subject, slug = custom, T.slug(custom)
    elif topic:
        ranked, _ = T.load_latest()
        subject, slug = ranked[topic - 1], T.slug(ranked[topic - 1].headline)
    else:
        console.print("[red]Give --topic N or --custom \"text\".[/red]")
        raise typer.Exit(1)
    try:
        ledger = orchestrator.research_topic(subject, log=lambda s: console.print(f"[dim]{s}[/dim]"))
    except (llm.BudgetExceeded, llm.DailyLimitReached) as e:
        console.print(f"[red]Stopped:[/red] {e}")
        raise typer.Exit(1)
    path = config.RUNS_DIR / f"research_{slug}" / "claims_ledger.json"
    ledger.save(path)
    counts = {}
    for c in ledger.claims:
        counts[c.status] = counts.get(c.status, 0) + 1
    console.print(f"\n[bold]{len(ledger.claims)} claims[/bold] {counts}. Saved: {path}")
    for n in ledger.notes:
        console.print(f"[yellow]note:[/yellow] {n[:160]}")
    console.print(f"[dim]{llm.USAGE.summary(config.load_config().get('plan', 'free'))}[/dim]")


@app.command()
def write(ledger_path: Path = typer.Argument(..., help="claims_ledger.json to write from"),
          title: str = typer.Option(..., help="Working title"), angle: str = typer.Option("", help="One or two sentences on the angle"),
          out: Optional[Path] = typer.Option(None, help="Output folder (default: next to the ledger)")) -> None:
    """Write an article from a claims ledger, then fact-check it (a building block of `produce`)."""
    from . import llm, orchestrator, report, style, topics as T
    from .claims import Ledger
    from .agents import verifier
    ledger = Ledger.load(ledger_path)
    folder = out or ledger_path.parent
    folder.mkdir(parents=True, exist_ok=True)
    dashes = [("dashboard-1", title)]
    try:
        article = orchestrator.write_and_verify(title, angle, ledger, dashes, log=lambda s: console.print(f"[dim]{s}[/dim]"))
    except (llm.BudgetExceeded, llm.DailyLimitReached) as e:
        console.print(f"[red]Stopped:[/red] {e}")
        raise typer.Exit(1)
    (folder / "article.md").write_text(article, encoding="utf-8")
    ledger.save(folder / "claims_ledger.json")
    (folder / "factcheck_report.md").write_text(report.render(ledger, title), encoding="utf-8")
    bad = verifier.failures(ledger)
    console.print(f"Article: {folder / 'article.md'} ({style.metrics(article)['words']} words). "
                  f"[green]{len(ledger.draft_checks) - len(bad)} fine[/green], [red]{len(bad)} need attention[/red].")
    console.print(f"[dim]{llm.USAGE.summary(config.load_config().get('plan', 'free'))}[/dim]")


@app.command()
def verify(path: Path = typer.Argument(..., help="Path to an article .md")) -> None:
    """Re-run the fact-check on any article (even one you edited). Uses claims_ledger.json next to it if present."""
    from . import llm, report
    from .agents import verifier
    from .claims import Ledger
    if not path.exists():
        console.print(f"[red]File not found:[/red] {path}")
        raise typer.Exit(1)
    ledger_path = path.parent / "claims_ledger.json"
    if ledger_path.exists():
        ledger = Ledger.load(ledger_path)
    else:
        ledger = Ledger(topic=path.stem, built=__import__("datetime").date.today().isoformat())
        console.print("[yellow]No claims_ledger.json next to this file: every number will show as unverified. "
                      "Run `pharmadash research` first, or `produce`.[/yellow]")
    draft = path.read_text(encoding="utf-8")
    try:
        verifier.verify_draft(draft, ledger, log=lambda s: console.print(f"[dim]{s}[/dim]"))
    except (llm.BudgetExceeded, llm.DailyLimitReached) as e:
        console.print(f"[red]Stopped:[/red] {e}")
        raise typer.Exit(1)
    ledger.save(ledger_path)
    out = path.parent / "factcheck_report.md"
    out.write_text(report.render(ledger, path.stem), encoding="utf-8")
    bad = verifier.failures(ledger)
    n = len(ledger.draft_checks)
    console.print(f"Checked [bold]{n}[/bold] items: [green]{n - len(bad)} fine[/green], [red]{len(bad)} need attention[/red].")
    console.print(f"Report: {out}")
    console.print(f"[dim]{llm.USAGE.summary(config.load_config().get('plan', 'free'))}[/dim]")
    if bad:
        raise typer.Exit(2)


@app.command()
def dashboard(from_md: Path = typer.Option(..., "--from-md", help="Article .md to build dashboards for"),
              count: Optional[int] = typer.Option(None, help="How many dashboards (default from config.yaml)")) -> None:
    """Build dashboards for an existing article, from the claims_ledger.json next to it."""
    import re
    from . import llm, screenshots
    from .agents import dashboard as dash_agent
    from .claims import Ledger
    if not from_md.exists():
        console.print(f"[red]File not found:[/red] {from_md}")
        raise typer.Exit(1)
    ledger_path = from_md.parent / "claims_ledger.json"
    if not ledger_path.exists():
        console.print("[red]No claims_ledger.json next to the article.[/red] Dashboards are only built from verified figures. "
                      "Run `pharmadash produce` (or `research` + `write`) first.")
        raise typer.Exit(1)
    text = from_md.read_text(encoding="utf-8")
    m = re.search(r"^#\s+(.+)$", text, re.M)
    title = m.group(1).strip() if m else from_md.stem
    cfg = config.load_config()
    try:
        built = dash_agent.make_dashboards(title, "", Ledger.load(ledger_path), cfg["issue_counter"], from_md.parent / "dashboards", count,
                                          log=lambda s: console.print(f"[dim]{s}[/dim]"))
    except (llm.BudgetExceeded, llm.DailyLimitReached) as e:
        console.print(f"[red]Stopped:[/red] {e}")
        raise typer.Exit(1)
    for b in built:
        if b.path:
            console.print(f"[green]Built[/green] {b.path}")
            shot = screenshots.shoot(Path(b.path), from_md.parent / "dashboards" / "screenshots")
            console.print(f"  screenshots: {len(shot.files)} saved" if shot.files else f"  [yellow]{shot.note}[/yellow]")
            for p in shot.problems + b.problems:
                console.print(f"  [yellow]check:[/yellow] {p}")
        else:
            console.print(f"[red]Not built:[/red] {b.title}")
            for p in b.problems:
                console.print(f"  {p}")
    console.print(f"[dim]{llm.USAGE.summary(cfg.get('plan', 'free'))}[/dim]")


@app.command()
def history() -> None:
    """List past issues and topics covered."""
    import json
    from rich.table import Table
    rows = json.loads(config.HISTORY_PATH.read_text(encoding="utf-8")).get("issues", []) if config.HISTORY_PATH.exists() else []
    if not rows:
        console.print("No issues produced yet. Run `pharmadash run` to make the first one.")
        return
    table = Table(title="Issues produced by PharmaDash (none are published by the agent)", show_lines=True)
    for col in ("Issue", "Date", "Topic", "Words", "Attention", "Folder"):
        table.add_column(col, overflow="fold")
    for h in sorted(rows, key=lambda r: r.get("issue", 0)):
        table.add_row(f"{h.get('issue', 0):02d}", h.get("date", ""), h.get("title", ""), str(h.get("words", "-")),
                      str(h.get("attention", "-")), h.get("folder", ""))
    console.print(table)
    console.print(f"Next issue number: {config.load_config()['issue_counter']:02d}")


@app.command()
def version() -> None:
    """Show the version."""
    console.print(__version__)


if __name__ == "__main__":
    app()
