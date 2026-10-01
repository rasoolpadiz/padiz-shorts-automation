import sys, json
sys.path.insert(0, r"C:\youtube_pipeline")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import importlib
import run_long_daily as R
import longform as L
importlib.reload(R)
topics = L.load_topics()

# Simulate: today the money pair is already posted. Which language runs next?
state = {"posted": {"en_long_money_01": "2026-09-30", "fa_long_money_01": "2026-09-30"}, "counts": {}}
print("last posted lang:", R._last_posted_lang(state))
print("posted today:", R._posted_today(state), "(None = clear to publish)")
picked = R.pick_topics(topics, state)
print("-> picks:", [(t["id"], t["lang"]) for t in picked])

# Simulate the NEXT day (after eto -> ai_mistakes published)
state2 = {"posted": dict(state["posted"], en_long_ai_mistakes_01="2026-10-01"), "counts": {}}
print()
print("day 2 -> last lang:", R._last_posted_lang(state2))
for t in R.pick_topics(topics, state2):
    print("   picks:", t["id"], t["lang"])

# Simulate the SAME day second catch-up cron (must be blocked)
state3 = {"posted": dict(state["posted"], en_long_ai_mistakes_01="2026-10-01"), "counts": {}}
print()
print("same-day catch-up -> posted_today:", R._posted_today(state3), "-> would skip" if R._posted_today(state3) else "-> WOULD PUBLISH (bad!)")
