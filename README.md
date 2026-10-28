# PharmaDash-Newsletter
Pharma Dash is a bi-weekly pharma market intelligence newsletter. Every issue delivers financial performance analysis, drug-level insights, commercial news, and investor signals, all communicated through business intelligence dashboards built from public data.


Link to Newsletter: https://www.linkedin.com/newsletters/pharmadash-7459285177010364416

---

## PharmaDash Agent

One command that researches pharma news, checks every number, writes your newsletter article and builds your dashboards.

**It never publishes anything.** It leaves a folder of drafts. You read the fact-check report, edit the article and post on LinkedIn yourself.

## How it works

1. **Discover**: reads pharma news feeds, SEC filings and FDA data, and proposes ranked topics. You pick which ones to produce (the only pause).
2. **Produce**, for each topic you pick:
   - **Research**: collects numbers into a *claims ledger*. Every number has a source link, an as-of date and a status (verified, single-source, conflict, unverified).
   - **Dashboards**: 1-3 standalone HTML files in your PharmaDash design. Each figure on the page is checked against the ledger. A dashboard with a figure the ledger doesn't have is **rejected, not built**.
   - **Write**: the article in your voice, from the ledger only. Code (not the AI) re-checks every number, percentage, multiplier ("tenfold") and deal-value wording, and sends flagged sentences back for a fix.
   - **Package**: `output/issues/issue-NN_<slug>/` with the article, dashboards, `factcheck_report.md`, `sources.md` and the ledger.

## Quick Start (no programming needed)

You need three things: Python 3.11 or newer, a free Groq key, and an email address to identify yourself to the SEC.

### 1. Install Python
- **Windows:** download from python.org, tick **"Add python.exe to PATH"** in the installer.
- **macOS:** download from python.org (or `brew install python`).

### 2. Open a terminal in this folder
- **Windows:** open the `pharmadash-agent` folder in File Explorer, click the address bar, type `powershell`, press Enter.
- **macOS:** open Terminal, type `cd ` (with a space), drag the `pharmadash-agent` folder into the window, press Enter.

### 3. Install (one time)

Windows (PowerShell):
```
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```
macOS (Terminal):
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```
After a restart of the terminal, run the `activate` line again before using `pharmadash`.

Optional, for the dashboard screenshot test (about 150 MB): `pip install playwright==1.49.0` then `playwright install chromium`. Without it, everything works; the screenshot check is skipped.

### 4. Add your keys
Run `pharmadash init`. It creates a file called `.env`. Open it in Notepad / TextEdit and fill in:
- `GROQ_API_KEY=`: free at https://console.groq.com/keys (no credit card).
- `SEC_USER_AGENT=`: your name and email, for example `PharmaDash Newsletter jane@example.com`. The SEC requires this on its free data service. It is only sent to sec.gov.

Run `pharmadash init` again. Every line should say **OK**.

### 5. Try it without using any quota
```
pharmadash run --dry-run --auto 1
```
This uses built-in test data (no internet, no AI calls) so you can see every step, the summary and the output folder.

### 6. Make a real issue
```
pharmadash run
```
It shows a numbered list of topics. Type the numbers you want (`1,3`), or `all`, or `top3`, and press Enter. Then it works through each topic and prints a summary. Open the folder it names, read **factcheck_report.md first**, then edit **article.md**.

## Commands

| Command | What it does |
|---|---|
| `pharmadash init` | Creates folders and `.env`, checks your keys. |
| `pharmadash discover [--focus "AI in pharma"]` | Proposes ranked topics and saves them in `output/topics/`. |
| `pharmadash produce --topics 1,3` | Produces topics from the latest topics file. `--custom "my topic"` skips discovery. |
| `pharmadash run` | Discover, ask which topics, then produce. `--auto 2` skips the question and takes the top 2. `--custom "..."`, `--focus "..."`, `--dry-run` and `--resume` also work. |
| `pharmadash verify path\to\article.md` | Re-checks an article after you edit it (uses the `claims_ledger.json` next to it). Exit code 2 if something needs attention. |
| `pharmadash dashboard --from-md path\to\article.md` | Builds dashboards from the ledger next to an article. |
| `pharmadash history` | Lists issues produced so far. |

## Free-tier limits and `--resume`

The agent runs on Groq's free tier, so it costs **$0**. The cost line in the summary is only an estimate of what the same tokens would cost on a paid plan.

The free tier allows about 8,000 tokens per minute and 200,000 per day for each model. The agent paces itself, switches to a second free model when one runs out, and stops cleanly when all are used up. **A full issue can need more than one day of quota** (topic discovery alone uses about 100,000 tokens). When it stops you will see a red box saying what to do. Progress is saved after every step, so:

```
pharmadash run --resume
```
continues exactly where it stopped, without redoing finished steps. The daily limit is a rolling window, so waiting a few hours is usually enough.

## What is in an issue folder

```
output/issues/issue-08_<slug>/
  article.md             your draft (700-1,200 words), no tables
  factcheck_report.md    READ THIS FIRST: what needs your attention, then every number checked, then the ledger
  sources.md             every claim with its link, primary sources first
  claims_ledger.json     the raw ledger (used by `verify` and `dashboard`)
  dashboards/            standalone .html files (double-click to open), .data.json, and screenshots/
```

### Reading the fact-check report
- **OK**: the number is in the ledger and backed by a primary source or two independent sources.
- **1 SOURCE**: matches the ledger, but only one source backs it. Headline and subtitle figures need more than this, so they appear under "Needs your attention".
- **CONFLICT**: sources disagree, or the number does not match arithmetic recomputed in code (for example a wrong "tenfold"). The article should show both figures or fix the sentence.
- **UNVERIFIED**: the number is not in the ledger at all. Remove it, source it yourself, or write "not disclosed".

## Troubleshooting

| What you see | What it means | What to do |
|---|---|---|
| `'pharmadash' is not recognized` / `command not found` | The virtual environment isn't active. | Run the `activate` line from step 3 in this folder. |
| `GROQ_API_KEY is empty` | The key is missing from `.env`. | Add it (free at console.groq.com/keys), save, run `pharmadash init`. |
| `SEC_USER_AGENT needs your name and email` | SEC lookups are skipped. | Add e.g. `PharmaDash Newsletter you@example.com` to `.env`. |
| Red box: "daily allowance is used up" | Groq's free daily tokens ran out. | Wait a few hours, then `pharmadash run --resume`. |
| "Groq rate limit; waiting 40s" | Normal. The free tier has a per-minute cap. | Nothing; it waits and carries on. |
| `Unreachable sources: ...` | Some sites (for example Fierce, Endpoints) block automated readers. | Nothing; the agent doesn't bypass blocks. It uses other sources and says so in the report. |
| "Research found only N usable fact(s)" | Too few checkable numbers were found, so the agent stopped instead of guessing. Usually `SEC_USER_AGENT` is empty, sources were blocked, or the free quota ran short. | Fix the cause it names, then `pharmadash run --resume`. Or try a more specific `--custom` topic. The limit is `min_claims` in `config.yaml`. |
| "Nothing to resume" | The last run finished, or none was started. | Start a new run: `pharmadash run`. |
| Dashboards "Not built" with "REJECTED" | A figure wasn't in the ledger, so it was not allowed on the page. | Expected safety behaviour. Run `pharmadash dashboard --from-md ...` again, or build from a stronger ledger. |
| "Playwright is not installed" | Optional screenshot check is skipped. | Optional: see step 3. |
| Fonts look different when offline | The dashboards load Space Grotesk, Inter and IBM Plex Mono from Google Fonts. | Works with any internet connection; falls back to system fonts offline. |
| Python 2.7 error on Windows | `python` points to an old install. | Use `py -3 ...` as in step 3, or the virtual environment. |

## Weekly schedule

`pharmadash run --auto 2` produces the top 2 topics without asking. Run it from the virtual environment's own copy of the command so no `activate` is needed.

**Windows (Task Scheduler):** Create Basic Task, name `PharmaDash`, trigger Weekly (e.g. Monday 07:00), action Start a program:
- Program: `C:\full\path\to\pharmadash-agent\.venv\Scripts\pharmadash.exe`
- Arguments: `run --auto 2`
- Start in: `C:\full\path\to\pharmadash-agent`

**macOS (cron):** run `crontab -e` and add (use your real folder):
```
0 7 * * 1 cd /full/path/to/pharmadash-agent && .venv/bin/pharmadash run --auto 2 >> output/schedule.log 2>&1
```
A scheduled run may stop at the free daily limit. Check `output/schedule.log`, then run `pharmadash run --resume` by hand. The computer must be awake at the scheduled time.

## Editing the prompts (your voice and rules)

All the instructions the AI follows are plain text files in `src/pharmadash/prompts/`. Open them in any text editor, change the wording, save. No coding.

| File | Controls |
|---|---|
| `discovery.md` | How topics are found and ranked. |
| `researcher.md` | What counts as a claim and a good source. |
| `writer.md` | Your voice, article structure, length. |
| `verifier.md` | How strictly meaning is judged. |
| `dashboard.md` | Dashboard layout rules, KPI style. |

Each file contains a **"hard rule"** about never inventing numbers. Keep it. The code enforces it as well, but the prompt keeps the AI honest at the source.

## Customizing (`config.yaml`)

- `watchlist`: the companies tracked (name, ticker, SEC id).
- `news_sources`: RSS feeds read for discovery.
- `themes` and `scoring_weights`: what makes a topic rank high.
- `article_word_target`, `dashboards_per_issue`, `lookback_days`, `topic_count`.
- `models`: which model does each job. Change them in one place (see https://console.groq.com/docs/models).
- `usage_limits`: stops a run that uses too many tokens or searches.
- `issue_counter`: the next issue number; goes up automatically after each produced issue.

## Dashboards

Each dashboard is one `.html` file, hand-built SVG, no chart libraries, no internet needed except for the Google font. Bar heights are computed from the figure written on the label, so a label and its bar can't disagree. Projected values use hatched bars with a `~`, approximations are dashed, and undisclosed values show `n/d`.

If Playwright is installed, every dashboard is opened at 1060, 780 and 390 px and checked for sideways scrolling, charts that didn't draw, and cut-off labels. Screenshots are saved next to it.

## Quality limits (please read)

- The checker catches numbers that aren't in the ledger, wrong arithmetic, million/billion slips, wrong multipliers and vague deal values. It is **weaker on meaning**: it can miss a sentence that reuses a correct number for the wrong thing, or an unsupported opinion. **Read the article against the report.**
- Writing quality on the free models is more generic and has shorter sentences than your own issues. For better prose, change `models.writer` in `config.yaml` to a stronger model.
- Free sources only. Paywalled and blocking sites are not read. Company filings and press releases are preferred over aggregators.
- Nothing is investment advice, and every article ends with that disclaimer.

## Tests

```
pytest tests -q --ignore=tests/smoke_tools.py --ignore=tests/live_groq.py
```
`tests/smoke_tools.py` and `tests/live_groq.py` call real services and are run by hand.
