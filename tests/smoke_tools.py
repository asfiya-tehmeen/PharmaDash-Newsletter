"""Live smoke test for the data tools. Run: python tests/smoke_tools.py"""
from datetime import date, timedelta

from pharmadash import config
from pharmadash.tools import clinicaltrials, fetch_utils, news_feeds, openfda, sec_edgar

cfg = config.load_config()
since = (date.today() - timedelta(days=30)).isoformat()

names = [c["name"] for c in cfg["watchlist"]]
news = news_feeds.fetch_news(cfg["news_sources"], 14, names)
print(f"NEWS: {len(news)} items; {sum(1 for n in news if n['matches'])} mention a watchlist company")
for n in news[:3]:
    print("  ", n["published"], n["source"], "|", n["title"][:80], n["matches"])

fda = openfda.recent_approvals(since)
print(f"FDA: {len(fda)} approvals since {since}")
for a in fda[:3]:
    print("  ", a)

ct = clinicaltrials.recent_trials("Eli Lilly and Company", since, 3)
print(f"CT.gov: {len(ct)} Lilly studies updated")
for t in ct:
    print("  ", t["nct_id"], t["phase"], t["status"], t["updated"])

if "@" in config.sec_user_agent():
    for c in cfg["watchlist"]:
        if c["name"] in ("Eli Lilly", "Novo Nordisk", "Pfizer"):
            fil = sec_edgar.recent_filings(c["cik"], since=since)
            rev = sec_edgar.metric_series(c["cik"], "revenue")
            last = rev["points"][-1] if rev["points"] else None
            print(f"SEC {c['name']}: {len(fil)} filings; revenue {rev.get('concept')} last={last and (last['period_end'], last['value'])}")
else:
    print("SEC: SKIPPED (SEC_USER_AGENT not set in .env)")

print("UNREACHABLE:", fetch_utils.UNREACHABLE or "none")
