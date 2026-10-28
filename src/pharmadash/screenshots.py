"""Optional screenshot test: opens each dashboard in Chromium at three widths and looks for layout problems.

Needs Playwright (`pip install playwright` then `playwright install chromium`). Without it the check is skipped, not failed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

WIDTHS = (1060, 780, 390)

PROBE = """() => {
  const out = {overflow: document.documentElement.scrollWidth - window.innerWidth, empty: [], clipped: []};
  for (const id of ['chart', 'mini']) {
    const s = document.getElementById(id);
    if (s && s.children.length < 3) out.empty.push(id);
  }
  // SVG text that falls outside its own svg box (clipped labels)
  document.querySelectorAll('svg text').forEach(t => {
    const s = t.ownerSVGElement.getBoundingClientRect(), r = t.getBoundingClientRect();
    if (r.width && (r.left < s.left - 2 || r.right > s.right + 2)) out.clipped.push(t.textContent.slice(0, 30));
  });
  return out;
}"""


@dataclass
class ShotResult:
    available: bool
    files: list[Path] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    note: str = ""


def available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def shoot(html_path: Path, out_dir: Path) -> ShotResult:
    if not available():
        return ShotResult(False, note="Playwright is not installed, screenshot test skipped (optional: pip install playwright && playwright install chromium)")
    from playwright.sync_api import sync_playwright
    out_dir.mkdir(parents=True, exist_ok=True)
    res = ShotResult(True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for w in WIDTHS:
                page = browser.new_page(viewport={"width": w, "height": 900}, reduced_motion="reduce")
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(html_path.resolve().as_uri())
                page.wait_for_timeout(400)
                info = page.evaluate(PROBE)
                shot = out_dir / f"{html_path.stem}_{w}.png"
                page.screenshot(path=str(shot), full_page=True)
                res.files.append(shot)
                if info["overflow"] > 1:
                    res.problems.append(f"{w}px: page scrolls sideways by {info['overflow']}px")
                if info["empty"]:
                    res.problems.append(f"{w}px: chart did not draw ({', '.join(info['empty'])})")
                if info["clipped"]:
                    res.problems.append(f"{w}px: labels cut off: {', '.join(sorted(set(info['clipped']))[:5])}")
                for e in errors:
                    res.problems.append(f"{w}px: script error: {e[:120]}")
                page.close()
            browser.close()
    except Exception as e:   # e.g. Chromium not downloaded yet
        res.available = False
        res.note = f"Screenshot test could not run ({str(e).splitlines()[0][:150]}). Try: playwright install chromium"
    return res
