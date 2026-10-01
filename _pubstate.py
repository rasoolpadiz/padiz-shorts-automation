import sys, json
sys.path.insert(0, r"C:\youtube_pipeline")
import check_actions as C
tok = C.github_token()
st = json.load(open(r"C:\youtube_pipeline\longform_out\posted_long.json", encoding="utf-8"))
print("posted:", st.get("posted"))
print("counts:", st.get("counts"))
import analytics as A
rows = A._fetch_stats(A._youtube_client())
longs = [r for r in rows if A._is_long(r["duration"])]
print("long videos on channel:", len(longs))
for r in sorted(longs, key=lambda x: x["published_at"], reverse=True)[:5]:
    print("  ", r["published_at"][:10], r["views"], "views", r["title"][:58])
