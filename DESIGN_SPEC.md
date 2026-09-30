# Padiz Studio — Design & Growth Standard (v2)

> Owner directive, 2026-09-30. **This file is the contract.** Every long-form and Short
> produced by this repo must satisfy it. If a pipeline decision contradicts this doc,
> the doc wins — fix the code instead.

## 0. Goal
Grow to **100s → millions of subscribers** as fast as possible, with **maximum revenue**.
That requires three things at once, and none of them is optional:
**retention (views), CTR (click-through), and RPM (money per view).**

## 1. The first 15 seconds decide everything
The opening must hook the viewer within **15 seconds**, and hold them to the last second.
Required pattern for every long-form video:
1. **0:00–0:03 — Cold open.** No logo, no intro, no music swell. The single most
   shocking / most concrete line of the whole video, spoken and on screen at once.
2. **0:03–0:08 — Stakes.** Why this matters to *this* viewer, in one sentence.
3. **0:08–0:15 — Promise.** What they will be able to do by the end (the payoff).
4. **0:15+ — Title card + series branding, then straight into content.**
Never open with: " welcome to my channel", " in this video we will", or a static logo.

## 2. Voice / narration
- **Persian voice must not sound robotic.** Feedback 2026-09-30: the FA narration of
  `fa_long_money_01` sounded lifeless and obviously synthetic. This is a defect, not a taste.
- Requirements: emotional range, natural Persian prosody, varied pacing, real pauses at
  sentence ends, no flat monotone reading of the script.
- Gemini TTS is primary (best FA quality), `edge-tts` stays as the no-quota fallback.
- Delivery must be steered with an explicit style prompt per scene, not left to default.
- **Same standard for English** — the bar does not differ by language.

## 3. Graphics, typography and color
- Current frame (photo blended 66% into a flat color, one rounded box) is **not good enough**.
  Owner verdict: "متن‌ها و گرافیک ما ضعیف باشن" — text and graphics are currently weak.
- Required:
  - **Modern, stylish fonts** (not DejaVu/Arial defaults). Display font for hooks,
    clean sans for body. Bundled in `assets/fonts/` so CI renders identically.
  - **Strong hierarchy**: hook line > scene title > supporting line > brand.
  - **Kinetic text**: words/lines appear on beat with the narration, not static walls of text.
  - **Depth**: gradients, soft shadows, vignette, subtle accent glow — not flat rectangles.
  - **Color psychology**: palette chosen per topic mood (money=navy/gold,
    mystery=dark violet/amber, science=deep blue/cyan, history=sepia/brass),
    never one default look for every video.
  - Motion graphics and transitions between scenes; **no two consecutive scenes identical.**
- Subtitles must stay readable on top of all of the above.

## 4. Visuals — zero repetition
- Every project uses **fresh images**. No photo may repeat across any two videos,
  EN or FA, including the same video in two languages.
- Requires a **global used-image registry** (hashes) committed with the repo, checked
  before every fetch. Current behaviour (EN and FA money videos sharing ~all queries)
  is a defect.

## 5. Thumbnails
- Owner verdict: thumbnails must be **"خیلی شیک و زیبا"** (very beautiful).
- Photo background with real contrast, 2–4 words maximum, huge readable type,
  one accent element, consistent brand system, legible at 210px wide on mobile.

## 6. Titles, captions, hashtags
- Choose per analysis of real search/suggest demand, not guesswork.
- Thumbnail text, title hook and first spoken line must agree with each other.
- Tags/hashtags: niche-appropriate, mixed broad+specific, no spam stuffing.

## 7. Automation contract (unchanged)
- **Long-form: 1 video/day** at 12:00 UTC = 15:30 Tehran.
- **Shorts: 5/day** at 06:00, 10:00, 14:00, 17:00, 20:00 UTC — timing and count stay as-is.
- Long-form publishes one EN then one FA on alternating days; topic comes from the pools
  and never repeats until the pool is exhausted (`posted_long.json`).
- Topic pool is limited to the owner's canonical niche lists (`topics_niches.py`).

## 8. Master checklist before any video is marked done
- [ ] Opens on a hook inside 15s, no intro
- [ ] Voice sounds human (esp. Persian)
- [ ] Fonts modern, hierarchy clear, text animated
- [ ] Palette fits the topic mood
- [ ] Zero reused images across the channel
- [ ] Thumbnail readable at small size
- [ ] ≥ 8:00 duration (mid-roll eligible)
- [ ] Description has chapters + photo credits (HTML-free)
