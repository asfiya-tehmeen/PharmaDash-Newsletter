"""Browser test at 1060 / 780 / 390 px. Skipped automatically when Playwright or Chromium is not installed."""
from pathlib import Path

import pytest

from pharmadash import dashboards as DB, screenshots

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.skipif(not screenshots.available(), reason="Playwright not installed")
@pytest.mark.parametrize("fixture", ["dash_ma_supercycle.json", "dry/dash_china.json"])
def test_dashboard_has_no_layout_problems_at_three_widths(tmp_path, fixture):
    d = DB.Dash.model_validate_json((FIX / fixture).read_text(encoding="utf-8"))
    page = DB.build(d, tmp_path)
    res = screenshots.shoot(page, tmp_path / "shots")
    if not res.available:
        pytest.skip(res.note)
    assert len(res.files) == 3
    assert res.problems == []
