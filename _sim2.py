import sys, importlib
sys.path.insert(0, r"C:\youtube_pipeline")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import run_long_daily as R, longform as L
importlib.reload(R)
topics = L.load_topics()

state = {"posted": {"en_long_money_01": "2026-09-30", "fa_long_money_01": "2026-09-30"}, "counts": {}}
print("=== day 1 (today) ===")
print("  last lang:", R._last_posted_lang(state))
for t in R.pick_topics(topics, state):
    print("  picks:", t["id"], t["lang"])
    day1 = t

state2 = {"posted": dict(state["posted"], **{day1["id"]: "2026-10-01"}), "counts": {}}
print("=== day 2 (tomorrow) ===")
print("  last lang:", R._last_posted_lang(state2))
for t in R.pick_topics(topics, state2):
    print("  picks:", t["id"], t["lang"])

print("=== same-day 2nd catch-up cron must be blocked ===")
print("  posted_today:", R._posted_today(state2))
