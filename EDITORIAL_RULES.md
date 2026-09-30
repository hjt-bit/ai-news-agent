# EDITORIAL RULES FOR SIGNAL — apply to every issue

Noted 2026-09-28 from Hasan. Rules 1–9 ENCODED IN CODE as v12.14 (2026-09-30).
Rule 10 (Threads-native format, decided Sep 28 2026) ENCODED as v12.15 (2026-09-30).
Packaging rule: every v12.x change updates BOTH agent.py and agent_v10.py.

## AUDIENCE
Senior leaders in the GCC, especially Saudi Arabia and the UAE: executives,
founders, and heads of marketing, sales, and operations. Most are not engineers.
They read on mobile, on Monday morning, in under five minutes.

## 1. ACCURACY COMES FIRST
- Read the full source article before summarizing it, not just the headline or meta description.
- Get the direction of every deal right: who pays whom, who invests in whom, who gets equity.
  Bad example (#021): "Anthropic's $11.6B investment in Akamai." This was wrong.
  Anthropic is a customer committing to spend $11.6B on Akamai's cloud, and Akamai
  gave Anthropic a warrant for up to ~5% of its stock.
- Do not state any number, name, or claim that isn't in the source.
- Every link must point to the exact page described. Do not construct URLs.
- If you are unsure about a fact, leave it out.

## 2. "WHY YOU CARE" MUST ADD INSIGHT
- Never restate the headline in different words.
  Bad: "Training 30,000 partners means increased capabilities."
- Answer one of these: What does this signal about where AI is heading? What
  changes for a business in the Gulf? What is the non-obvious angle?
  Good (#021 lead): "This is a bet on CPUs, not GPUs: agents running tasks need
  general-purpose compute. It also flips the usual 'supplier invests in AI lab'
  deal. Here the supplier gives the customer equity."
- Keep it to 1–2 sentences.

## 3. "LEADER ACTION" MUST BE REALISTIC FOR THE READER
- The action must be something a non-technical executive could do this week.
- Never tell readers to negotiate with the companies in the story, or to
  "implement" a model, API, or technical tool.
- Good actions: ask your team a specific question, review a specific budget line
  or vendor contract, run a small pilot, brief the board, or watch for a
  specific signal.
- If no realistic action exists, write "Watch:" plus what to monitor instead.

## 4. REGIONAL SECTION (GULF WATCH) — EXPANDED (Sep 28 2026 addendum)
- Bigger Middle East section than today; more Saudi sources.
- Saudi source list (also in GitHub issue #2): official/primary — SDAIA
  (sdaia.gov.sa), CST (cst.gov.sa), SAMA (sama.gov.sa), PIF (pif.gov.sa), MISA
  (misa.gov.sa), Monsha'at (monshaat.gov.sa), NCA (nca.gov.sa), RDIA, Saudi
  Exchange/Tadawul announcements (saudiexchange.sa), SPA English (spa.gov.sa);
  English press — Arab News (arabnews.com), Saudi Gazette (saudigazette.com.sa),
  Asharq Al-Awsat English (english.aawsat.com), Al Arabiya English
  (english.alarabiya.net); MENA funding/enterprise — MAGNiTT, Wamda.
- Include at least one Saudi Arabia item and one UAE item every issue. If none
  qualify, say so honestly rather than padding.
- Use at least two different outlets.
- Exclude vendor-written features, sponsored content, and press releases dressed
  up as news. Prefer government announcements, major deals, regulation, funding,
  and enterprise adoption stories.
- Every item needs a title, a one-line summary, and a correctly formatted
  source link.

## 5. FEWER, BETTER STORIES
- Maximum: 1 lead + 2 strategic stories + 2 regional + 2 consumer. Cut weaker
  stories rather than filling slots.
- Rank stories by their relevance to Gulf leaders, not by how viral they are globally.

## 6. TIP OF THE WEEK
- The tip must involve a feature launched or significantly updated in the last
  30 days, or a technique most leaders would not already know.
- Do not repeat well-known basics (e.g. "create a Custom GPT").
- The link must go to the actual product page or official help article for that feature.

## 7. LEAVE ROOM FOR HASAN'S VOICE
- Add a placeholder at the top: [HASAN'S TAKE: 2–3 sentences on the week's theme].
- Under the lead story, add [HASAN'S ANGLE: optional 1 line].
- Do not write these yourself. Hasan fills them in before publishing.

## 8. LAYOUT AND CTAs
- Use exactly two subscribe blocks: one after the intro and one at the end.
- Use share buttons only once, at the end.
- Verify that the author bio text matches what Hasan has approved. Do not change it.

## 9. SELF-CHECK BEFORE OUTPUT
Before finalizing, confirm each of these and list any failures at the top of the draft:
- Every deal's direction (buyer/seller/investor) matches the source.
- No "Why you care" line restates its headline.
- Every leader action passes the "could an executive do this this week?" test.
- Gulf Watch has both a KSA and a UAE item from different outlets.
- All links resolve to the described page.
- The tip is recent and not basic.
- The draft is marked DRAFT, pending Hasan's review.

## 10. THREADS-NATIVE FORMAT (Sep 28 2026 decision — ENCODED as v12.15)
After the #021 Threads post flopped (~0 reach on a long promo post with a link
preview), SIGNAL posts on Threads in a Threads-native format, generated
deterministically from the verified story analysis every run:
- Hook-first: lead with the most surprising story as a take — NEVER
  "this week's issue is out".
- Thread 3–4 replies, one story each (headline + why-you-care + leader action).
- The newsletter link appears ONLY in the final reply.
- 2 standalone, linkless drip posts for midweek (suggested Wed/Thu).
- Every post body stays within the Threads character limit; URLs are
  URL-sanitized out of every linkless post (fail-closed: the run aborts if a
  URL leaks outside the final reply).
- Posting itself stays manual: Hasan approves each post via threads-cli.
  The generated thread is copy for review in threads_post_YYYY_MM_DD.md.
