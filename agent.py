"""
SIGNAL -- AI Weekly Intelligence Briefing Agent (v2)
----------------------------------------------------
Pipeline:
  1. FETCH      -> pull the last 7 days of articles from trusted RSS feeds
  2. CLUSTER    -> detect the most "viral" story (covered by the most outlets)
  3. SELECT     -> pick top business + everyday + Middle East stories
  4. ANALYZE    -> ask the LLM for a structured, scannable card per story
  5. PUBLISH    -> render a polished HTML newsletter

Built as a learning project for the MIT Applied Agentic course.
"""

import feedparser
import os
import sys
import json
import re
from collections import Counter
from datetime import datetime, timedelta
from time import mktime
from openai import OpenAI

# =========================================================
# CONFIG  -- edit these freely
# =========================================================
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

MODEL = "gpt-4o-mini"
TEMPERATURE = 0.3

TOP_BUSINESS = 3       # stories in Strategic Briefing (excluding the Viral Lead)
TOP_EVERYDAY = 3       # stories in Consumer Signals
TOP_MIDDLE_EAST = 2    # quick bullets in the Middle East section
LOOKBACK_DAYS = 7

# Where to send readers when they click "Subscribe".
SIGNUP_URL = "#"

# Editor-in-Chief Mode: when True the agent pauses for your review/edits before publishing.
# Auto-disabled when running non-interactively (e.g., GitHub Actions has no stdin -> no terminal).
# You can also force it via env var: SIGNAL_INTERACTIVE=1 (on) or 0 (off).
_env_interactive = os.environ.get("SIGNAL_INTERACTIVE")
if _env_interactive is not None:
    INTERACTIVE_MODE = _env_interactive == "1"
else:
    INTERACTIVE_MODE = sys.stdin.isatty()  # auto-detect: on if running in a real terminal

# Also export a LinkedIn-formatted version of the newsletter on each run.
EXPORT_LINKEDIN = True

# Trusted sources (RSS feeds).
SOURCES = {
    # --- Industry / Technical ---
    "MIT Tech Review": "https://www.technologyreview.com/feed/",
    "OpenAI Blog": "https://openai.com/blog/rss.xml",
    "AI News": "https://www.artificialintelligence-news.com/feed/",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/",
    # --- Everyday-user friendly ---
    "The Verge AI": "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "Wired AI": "https://www.wired.com/feed/tag/ai/latest/rss",
    # --- Middle East focus ---
    "The National (Tech)": "https://www.thenationalnews.com/business/technology/rss.xml",
    "Wamda": "https://www.wamda.com/feed",
    "Arab News (Business)": "https://www.arabnews.com/rss.xml",
}

# Sources we treat as "Middle East" for the regional section
MIDDLE_EAST_SOURCES = {"The National (Tech)", "Wamda", "Arab News (Business)"}

# Keywords that flag any article (from any source) as Middle East-relevant
ME_KEYWORDS = [
    "uae", "saudi", "qatar", "kuwait", "bahrain", "oman", "egypt", "jordan",
    "lebanon", "iraq", "iran", "israel", "turkey", "morocco", "tunisia",
    "dubai", "abu dhabi", "riyadh", "doha", "beirut", "cairo", "amman",
    "middle east", "gulf", "gcc", "mena", "g42", "tahweel", "core42",
]

# =========================================================
# 1. FETCHER
# =========================================================
def fetch_recent_news(days=LOOKBACK_DAYS):
    """Pull articles from each RSS feed published within the last `days` days."""
    print(f"Fetching news from the last {days} days...")
    recent = []
    cutoff = datetime.now() - timedelta(days=days)
    for source, url in SOURCES.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                try:
                    pub = datetime.fromtimestamp(mktime(entry.published_parsed))
                    if pub > cutoff:
                        recent.append({
                            "title": entry.title,
                            "link": entry.link,
                            "source": source,
                            "summary": entry.get("summary", "")[:600],
                        })
                except Exception:
                    continue
        except Exception as e:
            print(f"  ! Failed to fetch {source}: {e}")
    print(f"  Found {len(recent)} recent articles.")
    return recent

# =========================================================
# 2. VIRAL DETECTOR
# =========================================================
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "has",
    "have", "been", "will", "say", "says", "said", "its", "your", "you", "into",
    "out", "but", "not", "more", "than", "their", "they", "them", "what",
    "when", "where", "why", "how", "who", "ai", "new", "now", "could", "would",
    "should", "after", "about", "over", "off", "all", "one", "two", "first",
    "year", "week", "day", "today", "tomorrow", "his", "her", "she", "him",
    "our", "use", "uses", "using", "may", "can", "just", "like", "make",
    "makes", "making", "still", "even", "any", "amid",
}

def _tokens(text):
    """Lowercase word tokens, no stopwords, no short junk."""
    return [w for w in re.findall(r"[A-Za-z][A-Za-z\-]{2,}", text.lower())
            if w not in STOPWORDS and len(w) > 3]

def detect_viral_story(articles):
    """
    Find the most-discussed topic across sources.
    Strategy: count keyword frequency across DISTINCT sources, then pick the
    article whose title best matches the top-trending keyword cluster.
    """
    if not articles:
        return None, []

    print("Detecting viral lead story (most-discussed topic of the week)...")

    # Count how many DISTINCT sources mention each keyword
    keyword_sources = {}
    for art in articles:
        text = f"{art['title']} {art['summary']}"
        for kw in set(_tokens(text)):
            keyword_sources.setdefault(kw, set()).add(art["source"])

    if not keyword_sources:
        return None, []

    # Top-N keywords by source diversity
    ranked = sorted(keyword_sources.items(), key=lambda x: len(x[1]), reverse=True)
    top_keywords = [kw for kw, sources in ranked[:8] if len(sources) >= 2]

    if not top_keywords:
        return None, []

    print(f"  Trending keywords: {', '.join(top_keywords[:5])}")

    # Score each article by how many top keywords its title contains
    def score(art):
        title_tokens = set(_tokens(art["title"]))
        return sum(1 for kw in top_keywords if kw in title_tokens)

    scored = sorted(articles, key=score, reverse=True)
    if score(scored[0]) == 0:
        # No clear viral hit; skip the lead
        return None, top_keywords

    viral = scored[0]
    print(f"  Viral lead: {viral['title'][:80]}")
    return viral, top_keywords

# =========================================================
# 3. EDITOR (selection)
# =========================================================
def select_articles(articles, viral_article=None):
    """Pick top stories for business + everyday + Middle East tracks."""
    if not articles:
        return {"business": [], "everyday": [], "middle_east": []}

    # Pre-filter: exclude the viral article so we don't double up
    pool = [a for a in articles if a is not viral_article]

    # Pre-bucket Middle East candidates so we never miss them
    me_candidates = [
        a for a in pool
        if a["source"] in MIDDLE_EAST_SOURCES
        or any(kw in (a["title"] + " " + a["summary"]).lower() for kw in ME_KEYWORDS)
    ]

    print(f"Selecting top {TOP_BUSINESS} business, {TOP_EVERYDAY} everyday, {TOP_MIDDLE_EAST} Middle East stories...")

    listing = "\n".join(
        f"[{i}] {a['title']} ({a['source']}) - {a['summary'][:160]}"
        for i, a in enumerate(pool)
    )

    prompt = f"""You are the editor of SIGNAL, a weekly AI intelligence briefing.

Pick stories for THREE tracks. Do not repeat any article across tracks.

TRACK 1 -- "Strategic Briefing" for BUSINESS LEADERS ({TOP_BUSINESS} stories):
- Pick stories with DIRECT commercial, operational, or strategic implications.
- Every story must answer "What's in it for me as a leader?"
- AVOID: pure geopolitics, defense procurement, country-vs-country posturing, government press releases, and abstract policy debates UNLESS they have a concrete impact on enterprise AI adoption, costs, talent, or competition.
- PRIORITIZE: enterprise product launches, pricing changes, M&A, hiring/layoffs, regulation directly affecting business, infrastructure costs, model capability shifts that change what businesses can build.

TRACK 2 -- "Consumer Signals" for EVERYDAY USERS ({TOP_EVERYDAY} stories):
- Consumer apps, privacy, jobs, fun creative tools, lifestyle impact.

TRACK 3 -- "From the Region" for MIDDLE EAST coverage ({TOP_MIDDLE_EAST} stories):
- AI developments tied to UAE, Saudi Arabia, Qatar, Egypt, broader MENA, or Gulf-based AI companies.
- If fewer than {TOP_MIDDLE_EAST} qualify, return fewer.

Return JSON exactly:
{{"business": [indices], "everyday": [indices], "middle_east": [indices]}}

Articles:
{listing}
"""
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            temperature=TEMPERATURE,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        result = json.loads(resp.choices[0].message.content)
        biz = [pool[i] for i in result.get("business", []) if i < len(pool)][:TOP_BUSINESS]
        eve = [pool[i] for i in result.get("everyday", []) if i < len(pool)][:TOP_EVERYDAY]
        me  = [pool[i] for i in result.get("middle_east", []) if i < len(pool)][:TOP_MIDDLE_EAST]
    except Exception as e:
        print(f"  ! Selection error: {e} -- falling back to defaults.")
        biz = pool[:TOP_BUSINESS]
        eve = pool[TOP_BUSINESS:TOP_BUSINESS + TOP_EVERYDAY]
        me  = me_candidates[:TOP_MIDDLE_EAST]

    # Guarantee Middle East content if any candidates exist but LLM missed them
    if not me and me_candidates:
        me = me_candidates[:TOP_MIDDLE_EAST]

    # Dedupe across tracks (defensive)
    used_links = set()
    def dedupe(items):
        out = []
        for a in items:
            if a["link"] not in used_links:
                used_links.add(a["link"])
                out.append(a)
        return out
    biz = dedupe(biz)
    eve = dedupe(eve)
    me  = dedupe(me)

    return {"business": biz, "everyday": eve, "middle_east": me}

# =========================================================
# 4. ANALYST (structured cards per story)
# =========================================================
def analyze_article(article, audience="business"):
    """Ask the LLM for a structured, scannable card for one article."""
    print(f"  [{audience}] {article['title'][:70]}...")

    if audience == "business" or audience == "viral":
        schema_hint = """{
  "headline": "punchy 6-10 word headline (no period)",
  "tldr": "ONE crisp sentence summary, max 22 words",
  "what_happened": "max 14 words, no period",
  "why_it_matters": "max 14 words, no period",
  "business_impact": "max 14 words, no period, focus on cost/revenue/competition/risk",
  "leader_action": "max 14 words, action verb first, no period"
}"""
        rules = ("Audience: senior business leaders. No jargon. No acronyms unless universally known. "
                 "Every field must be concrete and answer 'so what for my business?'")
    elif audience == "middle_east":
        schema_hint = """{
  "headline": "punchy 6-10 word headline (no period)",
  "tldr": "ONE sentence, max 26 words, that names the country/company AND ends with a concrete 'so what for a regional business leader' takeaway"
}"""
        rules = ("Audience: regional business leaders in the GCC/MENA. "
                 "Mention the country or company by name. The sentence must convey what is practical or actionable -- "
                 "a deal, a launch, a hire, a fund, a regulation, a partnership -- not just commentary or geopolitics. "
                 "If the article is purely political, focus on the business/AI angle only.")
    else:  # everyday
        schema_hint = """{
  "headline": "fun 6-10 word headline (no period)",
  "tldr": "ONE friendly sentence summary, max 22 words",
  "in_plain_english": "max 14 words, no period",
  "why_you_care": "max 14 words, no period",
  "what_to_do": "max 14 words, action verb first, no period"
}"""
        rules = "Audience: everyday users. Friendly tone. Zero jargon."

    prompt = f"""You write tight, scannable newsletter cards.

{rules}

Return ONLY a JSON object with EXACTLY these keys and length limits:
{schema_hint}

Be brutally concise. Each field is a phrase, NOT a sentence with sub-clauses.

Article: {article['title']}
Source: {article['source']}
Summary: {article['summary']}
"""
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            temperature=TEMPERATURE,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content)
    except Exception:
        return {}

# =========================================================
# 4b. TIP OF THE WEEK -- one practical AI tip per issue
# =========================================================
def generate_tip_of_week():
    """Ask the LLM for one NOVEL, non-obvious AI tip + a real resource link to explore."""
    print("\nGenerating Tip of the Week...")
    today = datetime.now().strftime("%B %d, %Y")

    prompt = f"""You are writing the "Tip of the Week" for SIGNAL, a premium weekly AI intelligence newsletter.

Goal: surface ONE genuinely NOVEL, non-obvious AI tip a curious professional can explore this week.
The reader is not a beginner -- they already use ChatGPT daily. Show them something they probably haven't tried.

STRONG PREFERENCES (rotate across these each week, do NOT repeat what most newsletters cover):
- A specific lesser-known feature (e.g., ChatGPT Projects/Memory/Canvas, Claude Artifacts/Computer Use, NotebookLM Audio Overviews, Gemini Deep Research, Perplexity Spaces/Labs)
- A new or fast-rising AI tool worth trying (e.g., Granola, Wispr Flow, Cursor, v0, Krea, Suno, ElevenLabs, Replit Agent, Lovable, Bolt, Manus)
- A specific evaluation or workflow technique (e.g., "prompt the model to grade its own output", multi-model side-by-side, role-prompting with explicit constraints)
- A free high-quality learning resource (a specific course, GitHub repo, prompt library, paper, YouTube channel)
- A clever automation pattern (Zapier+ChatGPT, Notion AI databases, Custom GPTs/Gems for repeated tasks)

FORBIDDEN -- do NOT suggest these (too obvious, everyone already does them):
- "Summarize meeting notes / emails / documents"
- "Write a blog post / social caption with ChatGPT"
- "Use ChatGPT to brainstorm"
- Any vague "prompt better" advice
- Anything that requires API keys or coding

Date context: {today}. Pick something seasonally fresh.

The tip MUST include ONE real, working URL to a tool, course, or resource the reader can click.
Use only well-known, stable URLs you are confident exist (e.g., https://notebooklm.google.com,
https://www.anthropic.com/news, https://openai.com/chatgpt/projects, https://www.granola.ai,
https://learnprompting.org, https://www.deeplearning.ai/short-courses/, https://github.com/anthropics/courses,
https://platform.openai.com/docs/guides/prompt-engineering, https://elevenlabs.io, https://suno.com,
https://www.perplexity.ai/spaces, https://gemini.google.com/app, https://claude.ai/projects,
https://huggingface.co/spaces). If unsure a URL exists, use one of the above instead of guessing.

Return ONLY a JSON object with EXACTLY these keys:
{{
  "title": "short 4-7 word title, title case, no period -- intriguing, not generic",
  "what": "2 sentences, max 45 words. Sentence 1: what the tip is. Sentence 2: why it's useful or surprising.",
  "try_this": "one concrete action in 1-2 short steps, max 50 words. Be specific.",
  "link_url": "a real working URL from the list above or a comparably well-known one",
  "link_label": "3-6 word call to action describing the link, e.g. 'Open NotebookLM' or 'See the prompt library'"
}}
"""
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            temperature=0.85,  # high temp -> more novelty/variety week to week
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        print(f"  Tip: {data.get('title', '')} -> {data.get('link_url', '')}")
        return data
    except Exception as e:
        print(f"  ! Tip generation failed: {e}")
        return {}

# =========================================================
# 5. PUBLISHER -- HTML renderer
# =========================================================
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SIGNAL // AI Intelligence Briefing - {date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    /* Higher-contrast editorial palette: deep navy ink on warm off-white paper */
    --bg: #eef1f7;
    --paper: #ffffff;
    --panel: #f3f6fb;
    --line: #d9dfe9;
    --line-bright: #b6bfd0;
    --ink: #050d1f;            /* near-black navy for max contrast */
    --ink-2: #1a2438;
    --muted: #4a5468;
    --muted-2: #7b859a;
    --cyan: #0e7490;           /* darker teal-cyan, more authoritative */
    --cyan-bright: #0891b2;
    --violet: #6d28d9;
    --highlight: #fff3a3;      /* soft underline highlight (used sparingly) */
    /* SIGNAL signature brand colors */
    --brand-navy: #0E1A2B;     /* signature deep ink navy -- masthead, viral title */
    --brand-navy-2: #16243a;   /* slightly lifted navy for hover/gradient */
    --title-band: #E8EEF7;     /* soft tinted band behind regular story titles */
    --tip-bg: #FDF6E3;         /* warm sand for Tip of the Week */
    --tip-rule: #C49A2C;       /* amber accent rule for Tip of the Week */
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: var(--bg);
    background-image:
      radial-gradient(800px 400px at 50% -180px, rgba(14,116,144,0.10), transparent 60%),
      radial-gradient(600px 350px at 95% 5%, rgba(109,40,217,0.06), transparent 65%);
    color: var(--ink);
    padding: 40px 16px;
    line-height: 1.6;
    font-size: 15px;
    font-weight: 400;
    -webkit-font-smoothing: antialiased;
  }}
  .wrap {{
    max-width: 700px;
    margin: 0 auto;
    background: var(--paper);
    border: 1px solid var(--line-bright);
    border-radius: 6px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(5,13,31,0.05), 0 16px 50px rgba(5,13,31,0.10);
  }}
  /* MASTHEAD -- signature brand navy block */
  .masthead {{
    padding: 38px 44px 30px;
    border-bottom: 3px solid #00D4FF;
    background: linear-gradient(180deg, var(--brand-navy) 0%, var(--brand-navy-2) 100%);
    color: #ffffff;
    position: relative;
  }}
  .masthead::before {{
    content: ""; position: absolute; inset: 0;
    background:
      radial-gradient(600px 220px at 80% -40px, rgba(0,212,255,0.18), transparent 60%),
      radial-gradient(420px 180px at 0% 100%, rgba(109,40,217,0.14), transparent 70%);
    pointer-events: none;
  }}
  .masthead > * {{ position: relative; z-index: 1; }}
  .masthead-top {{
    display: flex; justify-content: space-between; align-items: center;
    font-family: "JetBrains Mono", monospace;
    font-size: 10px; letter-spacing: 2.4px;
    color: rgba(255,255,255,0.62);
    text-transform: uppercase; margin-bottom: 26px;
  }}
  .masthead-top .dot {{
    display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    background: #00D4FF; margin-right: 8px; vertical-align: middle;
    box-shadow: 0 0 10px rgba(0,212,255,0.8);
  }}
  .masthead h1 {{
    font-family: "Space Grotesk", sans-serif;
    font-weight: 700; font-size: 54px; line-height: 1; letter-spacing: -1.8px;
    margin: 0 0 14px; color: #ffffff;
  }}
  .masthead h1 .accent {{ color: #00D4FF; }}
  .masthead .tagline {{
    font-size: 15.5px; color: rgba(255,255,255,0.92); font-weight: 500;
    line-height: 1.45;
  }}
  .masthead .promise {{
    margin-top: 10px;
    font-size: 12.5px; color: rgba(255,255,255,0.62);
    letter-spacing: 0.2px;
  }}
  /* SUBSCRIBE STRIP */
  .subscribe-strip {{
    display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
    justify-content: space-between;
    padding: 14px 44px;
    background: var(--panel);
    border-bottom: 1px solid var(--line);
    font-size: 13px; color: var(--ink-2);
  }}
  .subscribe-strip .copy {{ flex: 1; min-width: 200px; }}
  .subscribe-strip .copy strong {{ color: var(--ink); }}
  .subscribe-strip a.cta-mini {{
    display: inline-flex; align-items: center; gap: 8px;
    font-family: "JetBrains Mono", monospace;
    font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase;
    color: #ffffff; background: var(--ink);
    padding: 10px 18px; border-radius: 3px; text-decoration: none;
    transition: background 0.15s ease, transform 0.15s ease;
  }}
  .subscribe-strip a.cta-mini:hover {{ background: var(--cyan); transform: translateY(-1px); }}
  .subscribe-strip a.cta-mini::after {{ content: "->"; }}
  /* SECTION HEADER */
  .section-header {{
    padding: 36px 44px 14px;
    display: flex; align-items: center; gap: 14px;
    border-bottom: 1px solid var(--line);
    background: var(--paper);
  }}
  .section-header .index {{
    font-family: "JetBrains Mono", monospace;
    font-weight: 600;
    font-size: 11px; color: var(--cyan); letter-spacing: 1.5px;
  }}
  .section-header h2 {{
    font-family: "Space Grotesk", sans-serif;
    font-weight: 700; font-size: 19px; letter-spacing: 0.5px;
    text-transform: uppercase; color: var(--ink); margin: 0;
  }}
  .section-header .rule {{
    flex: 1; height: 2px;
    background: linear-gradient(90deg, var(--ink), transparent);
  }}
  /* VIRAL LEAD -- first story, prominently styled */
  .viral {{
    padding: 30px 44px 32px;
    border-bottom: 1px solid var(--line);
    background:
      linear-gradient(180deg, rgba(14,116,144,0.06), rgba(255,255,255,0)) ,
      var(--paper);
  }}
  .viral .badge {{
    display: inline-flex; align-items: center; gap: 8px;
    font-family: "JetBrains Mono", monospace;
    font-size: 10px; font-weight: 600; letter-spacing: 2px;
    text-transform: uppercase; color: #ffffff;
    background: var(--ink); padding: 5px 10px; border-radius: 2px;
    margin-bottom: 14px;
  }}
  .viral .badge .pulse {{
    width: 6px; height: 6px; border-radius: 50%; background: var(--cyan);
    box-shadow: 0 0 8px var(--cyan-bright);
    animation: pulse 1.6s ease-in-out infinite;
  }}
  @keyframes pulse {{
    0%, 100% {{ opacity: 1; transform: scale(1); }}
    50% {{ opacity: 0.5; transform: scale(0.85); }}
  }}
  .viral .source-line {{
    font-family: "JetBrains Mono", monospace;
    font-size: 10px; color: var(--muted); letter-spacing: 1.8px;
    text-transform: uppercase; margin-bottom: 12px;
  }}
  /* Viral title gets the BIG dark-navy block treatment */
  .viral h2 {{
    font-family: "Space Grotesk", sans-serif;
    font-weight: 700; font-size: 28px; line-height: 1.22;
    letter-spacing: -0.5px; margin: 0 0 18px; color: #ffffff;
    background: var(--brand-navy);
    padding: 18px 20px 18px 22px;
    border-left: 4px solid #00D4FF;
    border-radius: 2px;
    box-shadow: 0 6px 18px rgba(14,26,43,0.18);
  }}
  .viral h2 a {{ color: #ffffff; text-decoration: none; }}
  .viral h2 a:hover {{ color: #00D4FF; }}
  /* ARTICLES */
  .article {{
    padding: 28px 44px;
    border-bottom: 1px solid var(--line);
  }}
  .article:last-child {{ border-bottom: none; }}
  .article-meta {{
    display: flex; gap: 14px; align-items: center;
    font-family: "JetBrains Mono", monospace;
    font-size: 10px; letter-spacing: 1.8px; text-transform: uppercase;
    color: var(--muted); margin-bottom: 12px;
  }}
  .article-meta .pill {{
    display: inline-block; padding: 4px 9px;
    border: 1px solid var(--ink); border-radius: 2px;
    color: var(--ink); letter-spacing: 1.5px;
    background: var(--paper); font-weight: 600;
  }}
  .article-meta .pill.region {{
    border-color: var(--violet); color: var(--violet);
  }}
  /* Story title -- deep navy block, white text, cyan tick (uniform with viral) */
  .article-headline {{
    font-family: "Space Grotesk", sans-serif;
    font-weight: 700; font-size: 21px; line-height: 1.28;
    letter-spacing: -0.3px; margin: 0 0 16px;
    background: var(--brand-navy);
    padding: 14px 18px 14px 20px;
    border-left: 4px solid #00D4FF;
    border-radius: 2px;
    color: #ffffff;
    box-shadow: 0 4px 14px rgba(14,26,43,0.15);
  }}
  .article-headline a {{
    color: #ffffff; text-decoration: none;
    transition: color 0.2s ease;
  }}
  .article-headline a:hover {{ color: #00D4FF; }}
  .tldr {{
    font-size: 14.5px; line-height: 1.6; color: var(--ink);
    padding: 14px 16px; margin: 0 0 18px;
    background: var(--panel);
    border-left: 3px solid var(--cyan);
    border-radius: 2px;
    font-weight: 500;
  }}
  .points {{
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 18px 28px; margin: 0;
  }}
  .point .label {{
    display: block;
    font-family: "JetBrains Mono", monospace;
    font-size: 9.5px; font-weight: 600; letter-spacing: 2px;
    text-transform: uppercase; color: var(--violet);
    margin-bottom: 5px;
  }}
  .point .value {{
    display: block; font-size: 13.5px; line-height: 1.5; color: var(--ink);
    font-weight: 500;
  }}
  .read-more {{
    display: inline-flex; align-items: center; gap: 8px;
    margin-top: 18px;
    font-family: "JetBrains Mono", monospace;
    font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase;
    color: var(--cyan); text-decoration: none;
    padding-bottom: 3px; border-bottom: 1px solid var(--cyan);
    transition: border-color 0.2s ease, color 0.2s ease;
  }}
  .read-more:hover {{ color: var(--cyan-bright); border-bottom-color: var(--cyan-bright); }}
  .read-more::after {{ content: "->"; }}
  /* MIDDLE EAST -- compact bullet list */
  .me-list {{
    padding: 8px 44px 28px;
  }}
  .me-item {{
    padding: 18px 0; border-bottom: 1px dashed var(--line-bright);
  }}
  .me-item:last-child {{ border-bottom: none; }}
  .me-item .source-line {{
    font-family: "JetBrains Mono", monospace;
    font-size: 10px; color: var(--muted); letter-spacing: 1.6px;
    text-transform: uppercase; margin-bottom: 6px;
  }}
  .me-item h4 {{
    font-family: "Space Grotesk", sans-serif;
    font-weight: 700; font-size: 17px; line-height: 1.3;
    margin: 0 0 10px; letter-spacing: -0.2px;
    background: var(--brand-navy);
    color: #ffffff;
    padding: 10px 14px;
    border-left: 3px solid #00D4FF;
    border-radius: 2px;
    display: block;
  }}
  .me-item h4 a {{ color: #ffffff; text-decoration: none; }}
  .me-item h4 a:hover {{ color: #00D4FF; }}
  .me-item p {{ margin: 0; font-size: 14px; color: var(--ink-2); line-height: 1.55; }}
  .me-empty {{ padding: 18px 44px 28px; color: var(--muted); font-size: 13px; font-style: italic; }}
  /* TIP OF THE WEEK -- warm sand block, distinctly 'do this' not 'read this' */
  .tip {{
    margin: 0; padding: 32px 44px 36px;
    background: var(--tip-bg);
    border-top: 3px solid var(--tip-rule);
    border-bottom: 1px solid var(--line);
    position: relative;
  }}
  .tip .label {{
    display: inline-flex; align-items: center; gap: 8px;
    font-family: "JetBrains Mono", monospace;
    font-size: 10px; font-weight: 600; letter-spacing: 2.2px;
    text-transform: uppercase; color: var(--tip-rule);
    margin-bottom: 12px;
  }}
  .tip .label::before {{
    content: ""; display: inline-block;
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--tip-rule);
  }}
  .tip h3 {{
    font-family: "Space Grotesk", sans-serif;
    font-weight: 700; font-size: 22px; line-height: 1.28;
    color: var(--brand-navy); margin: 0 0 12px;
    letter-spacing: -0.3px;
  }}
  .tip .what {{
    font-size: 14.5px; line-height: 1.6; color: var(--ink-2);
    margin: 0 0 16px;
  }}
  .tip .try {{
    background: #ffffff;
    border-left: 3px solid var(--brand-navy);
    border-radius: 2px;
    padding: 14px 16px;
    font-size: 13.5px; line-height: 1.6; color: var(--ink);
  }}
  .tip .try .try-label {{
    display: block;
    font-family: "JetBrains Mono", monospace;
    font-size: 9.5px; font-weight: 600; letter-spacing: 2px;
    text-transform: uppercase; color: var(--brand-navy);
    margin-bottom: 6px;
  }}
  .tip .tip-link {{
    display: inline-flex; align-items: center; gap: 6px;
    margin-top: 16px;
    padding: 10px 16px;
    background: var(--brand-navy);
    color: #ffffff;
    text-decoration: none;
    font-family: "JetBrains Mono", monospace;
    font-size: 11px; font-weight: 600;
    letter-spacing: 1.5px; text-transform: uppercase;
    border-radius: 2px;
    border-left: 3px solid #00D4FF;
    transition: background 0.15s ease, transform 0.15s ease;
  }}
  .tip .tip-link:hover {{
    background: var(--brand-navy-2); transform: translateY(-1px);
  }}
  /* CTA */
  .cta {{
    margin: 0; padding: 44px 44px;
    text-align: center;
    background: linear-gradient(135deg, rgba(14,116,144,0.10), rgba(109,40,217,0.08));
    border-top: 2px solid var(--ink);
    border-bottom: 1px solid var(--line);
  }}
  .cta .label {{
    font-family: "JetBrains Mono", monospace;
    font-size: 10px; letter-spacing: 2px; color: var(--cyan);
    text-transform: uppercase; margin-bottom: 12px; display: block;
    font-weight: 600;
  }}
  .cta h3 {{
    font-family: "Space Grotesk", sans-serif;
    font-weight: 700; font-size: 27px; color: var(--ink);
    margin: 0 0 12px; letter-spacing: -0.5px;
  }}
  .cta p {{
    font-size: 14.5px; color: var(--ink-2); margin: 0 auto 22px; line-height: 1.6;
    max-width: 460px;
  }}
  .cta a.button {{
    display: inline-block; padding: 14px 30px;
    font-family: "JetBrains Mono", monospace;
    font-size: 12px; font-weight: 600; letter-spacing: 2px; text-transform: uppercase;
    color: #ffffff; background: var(--ink);
    text-decoration: none; border-radius: 3px;
    box-shadow: 0 8px 22px rgba(5,13,31,0.20);
    transition: transform 0.15s ease, background 0.15s ease;
  }}
  .cta a.button:hover {{ transform: translateY(-1px); background: var(--cyan); }}
  .cta .small {{ margin-top: 14px; font-size: 12px; color: var(--muted); }}
  /* FOOTER */
  .colophon {{
    padding: 26px 44px 32px;
    text-align: center;
    background: var(--paper);
  }}
  .colophon .sig {{
    font-family: "JetBrains Mono", monospace;
    font-size: 10px; letter-spacing: 2px; color: var(--muted-2);
    text-transform: uppercase; margin-bottom: 6px;
  }}
  .colophon .text {{
    font-size: 11px; color: var(--muted); line-height: 1.6;
  }}
  @media (max-width: 600px) {{
    body {{ padding: 16px 0; font-size: 14px; }}
    .wrap {{ border-radius: 0; }}
    .masthead {{ padding: 28px 22px 22px; }}
    .masthead h1 {{ font-size: 36px; }}
    .article, .cta, .colophon, .subscribe-strip, .viral, .me-list, .tip {{
      padding-left: 22px; padding-right: 22px;
    }}
    .section-header {{ padding: 28px 22px 12px; }}
    .points {{ grid-template-columns: 1fr; gap: 14px; }}
    .article-headline {{ font-size: 20px; }}
    .viral h2 {{ font-size: 24px; }}
    .subscribe-strip {{ flex-direction: column; align-items: flex-start; gap: 10px; }}
  }}
</style>
</head>
<body>
  <div class="wrap">
    <header class="masthead">
      <div class="masthead-top">
        <span><span class="dot"></span>SIGNAL // VOL. 001</span>
        <span>{date}</span>
      </div>
      <h1>SIGNAL<span class="accent">.</span></h1>
      <div class="tagline">An AI newsletter every Monday summarizing the top news in AI.</div>
      <div class="promise">Curated for leaders. Built by an autonomous agent. No noise.</div>
    </header>

    <div class="subscribe-strip">
      <div class="copy"><strong>New here?</strong> Get SIGNAL in your inbox every Monday.</div>
      <a class="cta-mini" href="{signup_url}">Subscribe free</a>
    </div>

    {viral_block}

    <section class="section">
      <div class="section-header">
        <span class="index">02 //</span>
        <h2>Strategic Briefing</h2>
        <span class="rule"></span>
      </div>
      {business_cards}
    </section>

    <section class="section">
      <div class="section-header">
        <span class="index">03 //</span>
        <h2>From the Region &middot; Middle East</h2>
        <span class="rule"></span>
      </div>
      {middle_east_block}
    </section>

    <section class="section">
      <div class="section-header">
        <span class="index">04 //</span>
        <h2>Consumer Signals</h2>
        <span class="rule"></span>
      </div>
      {everyday_cards}
    </section>

    {tip_block}

    <div class="cta">
      <span class="label">// Subscribe</span>
      <h3>Get SIGNAL in your inbox every Monday.</h3>
      <p>Curated AI intelligence for leaders and professionals. One email a week. No noise. Unsubscribe anytime.</p>
      <a class="button" href="{signup_url}">Subscribe free</a>
      <div class="small">Already a reader? Forward to a colleague.</div>
    </div>

    <footer class="colophon">
      <div class="sig">// END_TRANSMISSION</div>
      <div class="text">SIGNAL is composed each week by an AI agent.<br>{date}</div>
    </footer>
  </div>
</body>
</html>
"""

def render_viral_block(article, data):
    """The lead 'viral' story -- bigger, bolder, with full framework."""
    if not article:
        return ""
    return f"""
    <section class="viral">
      <span class="badge"><span class="pulse"></span>The Story Everyone Is Talking About</span>
      <div class="source-line">{article['source']}</div>
      <h2><a href="{article['link']}">{data.get('headline', article['title'])}</a></h2>
      <p class="tldr">{data.get('tldr', '')}</p>
      <div class="points">
        <div class="point"><span class="label">What happened</span><span class="value">{data.get('what_happened', '')}</span></div>
        <div class="point"><span class="label">Why it matters</span><span class="value">{data.get('why_it_matters', '')}</span></div>
        <div class="point"><span class="label">Business impact</span><span class="value">{data.get('business_impact', '')}</span></div>
        <div class="point"><span class="label">Leader action</span><span class="value">{data.get('leader_action', '')}</span></div>
      </div>
      <a class="read-more" href="{article['link']}">Read the full story</a>
    </section>
    """

def render_business_card(article, data):
    return f"""
    <article class="article">
      <div class="article-meta">
        <span class="pill">Strategic</span>
        <span>{article['source']}</span>
      </div>
      <h3 class="article-headline"><a href="{article['link']}">{data.get('headline', article['title'])}</a></h3>
      <p class="tldr">{data.get('tldr', '')}</p>
      <div class="points">
        <div class="point"><span class="label">What happened</span><span class="value">{data.get('what_happened', '')}</span></div>
        <div class="point"><span class="label">Why it matters</span><span class="value">{data.get('why_it_matters', '')}</span></div>
        <div class="point"><span class="label">Business impact</span><span class="value">{data.get('business_impact', '')}</span></div>
        <div class="point"><span class="label">Leader action</span><span class="value">{data.get('leader_action', '')}</span></div>
      </div>
      <a class="read-more" href="{article['link']}">Read the full story</a>
    </article>
    """

def render_everyday_card(article, data):
    return f"""
    <article class="article">
      <div class="article-meta">
        <span class="pill">Consumer</span>
        <span>{article['source']}</span>
      </div>
      <h3 class="article-headline"><a href="{article['link']}">{data.get('headline', article['title'])}</a></h3>
      <p class="tldr">{data.get('tldr', '')}</p>
      <div class="points">
        <div class="point"><span class="label">In plain English</span><span class="value">{data.get('in_plain_english', '')}</span></div>
        <div class="point"><span class="label">Why you care</span><span class="value">{data.get('why_you_care', '')}</span></div>
        <div class="point" style="grid-column: 1 / -1;"><span class="label">What to do</span><span class="value">{data.get('what_to_do', '')}</span></div>
      </div>
      <a class="read-more" href="{article['link']}">Read the full story</a>
    </article>
    """

def render_tip_block(tip):
    """Render the Tip of the Week section. Returns empty string if generation failed."""
    if not tip or not tip.get("title"):
        return ""
    link_html = ""
    if tip.get("link_url") and tip.get("link_label"):
        link_html = f'<a class="tip-link" href="{tip["link_url"]}" target="_blank" rel="noopener">{tip["link_label"]} &rarr;</a>'
    return f"""
    <section class="tip">
      <span class="label">Tip of the Week / Explore Something New</span>
      <h3>{tip.get('title', '')}</h3>
      <p class="what">{tip.get('what', '')}</p>
      <div class="try">
        <span class="try-label">// Try this</span>
        {tip.get('try_this', '')}
      </div>
      {link_html}
    </section>
    """

def render_middle_east_block(items):
    """Compact bullet list for the regional section."""
    if not items:
        return '<div class="me-empty">No major Middle East AI stories detected this week. Back next Monday.</div>'
    rendered = []
    for article, data in items:
        rendered.append(f"""
        <div class="me-item">
          <div class="source-line">{article['source']}</div>
          <h4><a href="{article['link']}">{data.get('headline', article['title'])}</a></h4>
          <p>{data.get('tldr', '')}</p>
        </div>
        """)
    return f'<div class="me-list">{"".join(rendered)}</div>'

# =========================================================
# 6. EDITOR-IN-CHIEF MODE -- terminal review/edit before publish
# =========================================================
def _print_lineup(viral, picks, pool):
    """Render the proposed lineup and the candidates pool to the terminal."""
    bar = "=" * 60
    print(f"\n{bar}\nEDITOR REVIEW -- proposed lineup\n{bar}")

    print("\nVIRAL LEAD (the most-discussed story this week):")
    if viral:
        print(f"  [V]  {viral['title']}")
        print(f"       Source: {viral['source']}")
    else:
        print("  [V]  -- none detected --")

    print("\nSTRATEGIC BRIEFING (business leaders):")
    for i, a in enumerate(picks["business"], 1):
        print(f"  [B{i}] {a['title']}")
        print(f"       Source: {a['source']}")

    print("\nCONSUMER SIGNALS (everyday users):")
    for i, a in enumerate(picks["everyday"], 1):
        print(f"  [C{i}] {a['title']}")
        print(f"       Source: {a['source']}")

    print("\nFROM THE REGION -- MIDDLE EAST:")
    for i, a in enumerate(picks["middle_east"], 1):
        print(f"  [M{i}] {a['title']}")
        print(f"       Source: {a['source']}")

    print(f"\nCANDIDATES POOL ({min(len(pool), 15)} of {len(pool)} other stories):")
    for i, a in enumerate(pool[:15], 1):
        print(f"  [P{i:>2}] {a['title']}  ({a['source']})")

    print(f"\n{bar}\nYOUR CALL\n{bar}")
    print("  ok               -- approve all and publish")
    print("  swap <slot> <P#> -- e.g. 'swap B2 P3' to replace Strategic #2 with Pool #3")
    print("  swap V <P#>      -- replace the Viral Lead with a pool story")
    print("  drop <slot>      -- e.g. 'drop C3' (slot becomes empty; section shrinks)")
    print("  reason <slot>    -- ask the agent why this story was picked")
    print("  pool             -- show 15 more candidates from the pool")
    print("  show             -- reprint the current lineup")
    print("  quit             -- abort without writing the newsletter")
    print("  Chain commands with ';' e.g.  swap B2 P3; drop C3; ok")


def _explain_pick(article, slot):
    """One-shot LLM call: why is this story in this slot?"""
    audience_map = {
        "V": "viral lead -- the most-discussed AI story of the week across multiple outlets",
        "B": "Strategic Briefing -- senior business leaders who need 'so what for my business?'",
        "C": "Consumer Signals -- everyday users who care about apps, jobs, privacy, lifestyle",
        "M": "From the Region -- regional business leaders in the GCC/MENA",
    }
    audience = audience_map.get(slot[0], "a general newsletter reader")
    prompt = f"""In 2 short sentences (max 50 words), explain why this article belongs in the SIGNAL newsletter slot "{audience}".
Be specific about the angle and the takeaway. No marketing language.

Title: {article['title']}
Source: {article['source']}
Summary: {article['summary'][:400]}
"""
    try:
        resp = client.chat.completions.create(
            model=MODEL, temperature=0.4,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"(could not generate explanation: {e})"


def _resolve_slot(slot, viral, picks):
    """Return ('V'|'B'|'C'|'M', index_or_None) for a slot like 'V', 'B2', 'C3', 'M1'."""
    slot = slot.upper().strip()
    if slot == "V":
        return ("V", None)
    if len(slot) >= 2 and slot[0] in "BCM" and slot[1:].isdigit():
        return (slot[0], int(slot[1:]) - 1)
    return (None, None)


def editor_review_loop(viral, picks, all_articles):
    """Interactive review/edit loop. Returns (viral, picks) or (None, None) if aborted."""
    # Build the candidate pool: every article NOT already in the lineup
    in_lineup = set()
    if viral:
        in_lineup.add(viral["link"])
    for track in ("business", "everyday", "middle_east"):
        for a in picks[track]:
            in_lineup.add(a["link"])
    pool = [a for a in all_articles if a["link"] not in in_lineup]
    pool_offset = 0

    _print_lineup(viral, picks, pool[pool_offset:])

    while True:
        try:
            raw = input("\nEditor> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return None, None
        if not raw:
            continue

        for cmd in [c.strip() for c in raw.split(";") if c.strip()]:
            parts = cmd.lower().split()
            verb = parts[0]

            if verb == "ok":
                return viral, picks

            if verb == "quit":
                return None, None

            if verb == "show":
                _print_lineup(viral, picks, pool[pool_offset:])
                continue

            if verb == "pool":
                pool_offset += 15
                if pool_offset >= len(pool):
                    pool_offset = 0
                    print("  -- end of pool, looping back to top --")
                tail = pool[pool_offset:pool_offset + 15]
                print(f"\nCandidates pool ({pool_offset+1}-{pool_offset+len(tail)} of {len(pool)}):")
                for i, a in enumerate(tail, 1):
                    print(f"  [P{i:>2}] {a['title']}  ({a['source']})")
                continue

            if verb == "reason" and len(parts) == 2:
                slot = parts[1].upper()
                track, idx = _resolve_slot(slot, viral, picks)
                target = None
                if track == "V":
                    target = viral
                elif track == "B" and idx is not None and idx < len(picks["business"]):
                    target = picks["business"][idx]
                elif track == "C" and idx is not None and idx < len(picks["everyday"]):
                    target = picks["everyday"][idx]
                elif track == "M" and idx is not None and idx < len(picks["middle_east"]):
                    target = picks["middle_east"][idx]
                if target:
                    print(f"\nWhy [{slot}] '{target['title'][:70]}':")
                    print("  " + _explain_pick(target, slot).replace("\n", "\n  "))
                else:
                    print(f"  ! Slot '{slot}' not found.")
                continue

            if verb == "drop" and len(parts) == 2:
                slot = parts[1].upper()
                track, idx = _resolve_slot(slot, viral, picks)
                if track == "V":
                    if viral:
                        pool.append(viral)
                        viral = None
                        print("  Viral lead dropped.")
                elif track in ("B", "C", "M"):
                    key = {"B": "business", "C": "everyday", "M": "middle_east"}[track]
                    if idx is not None and idx < len(picks[key]):
                        dropped = picks[key].pop(idx)
                        pool.append(dropped)
                        print(f"  Dropped {slot}: {dropped['title'][:70]}")
                    else:
                        print(f"  ! Slot '{slot}' not found.")
                else:
                    print(f"  ! Could not parse slot '{slot}'.")
                continue

            if verb == "swap" and len(parts) == 3:
                slot, pidx_token = parts[1].upper(), parts[2].upper()
                if not pidx_token.startswith("P") or not pidx_token[1:].isdigit():
                    print(f"  ! Pool reference must look like P1, P2... (got '{pidx_token}')")
                    continue
                pidx = int(pidx_token[1:]) - 1 + pool_offset
                if pidx < 0 or pidx >= len(pool):
                    print(f"  ! Pool index {pidx_token} out of range.")
                    continue
                replacement = pool[pidx]
                track, idx = _resolve_slot(slot, viral, picks)
                if track == "V":
                    if viral:
                        pool.append(viral)
                    viral = replacement
                    pool.pop(pidx)
                    print(f"  Viral lead -> {replacement['title'][:70]}")
                elif track in ("B", "C", "M"):
                    key = {"B": "business", "C": "everyday", "M": "middle_east"}[track]
                    if idx is not None and idx < len(picks[key]):
                        old = picks[key][idx]
                        picks[key][idx] = replacement
                        pool.pop(pidx)
                        pool.append(old)
                        print(f"  {slot}: {old['title'][:50]} -> {replacement['title'][:50]}")
                    else:
                        print(f"  ! Slot '{slot}' not found.")
                else:
                    print(f"  ! Could not parse slot '{slot}'.")
                continue

            print(f"  ! Unknown command '{cmd}'. Type 'show' to see the lineup.")

        # After applying a chained command, fall back to the prompt loop

# =========================================================
# 7. LINKEDIN EXPORT -- copy/paste-ready Markdown for LinkedIn Newsletter
# =========================================================
def export_linkedin_post(date_str, viral_pair, biz_pairs, eve_pairs, me_pairs, tip):
    """Write a linkedin_post.md file you can paste into LinkedIn Newsletter editor.

    LinkedIn's article editor accepts: H1/H2/H3 headings, bold, italic, bullet lists,
    numbered lists, blockquotes, and links. It does NOT accept HTML/CSS color blocks.
    So we render a clean Markdown version with the same content & flow.
    """
    lines = []
    lines.append(f"# SIGNAL // {date_str}")
    lines.append("")
    lines.append("_An AI newsletter every Monday summarizing the top news in AI._")
    lines.append("_Curated for leaders. Built by an autonomous agent. No noise._")
    lines.append("")
    lines.append("---")
    lines.append("")

    if viral_pair:
        art, data = viral_pair
        lines.append("## The Viral Lead")
        lines.append(f"*The story everyone is talking about \u00b7 {art['source']}*")
        lines.append("")
        lines.append(f"### [{data.get('headline', art['title'])}]({art['link']})")
        lines.append("")
        lines.append(f"> **TL;DR:** {data.get('tldr', '')}")
        lines.append("")
        lines.append(f"- **What happened:** {data.get('what_happened', '')}")
        lines.append(f"- **Why it matters:** {data.get('why_it_matters', '')}")
        lines.append(f"- **Business impact:** {data.get('business_impact', '')}")
        lines.append(f"- **Leader action:** {data.get('leader_action', '')}")
        lines.append("")
        lines.append(f"[Read the full story \u2192]({art['link']})")
        lines.append("")
        lines.append("---")
        lines.append("")

    if biz_pairs:
        lines.append("## Strategic Briefing")
        lines.append("_For business leaders._")
        lines.append("")
        for art, data in biz_pairs:
            lines.append(f"### [{data.get('headline', art['title'])}]({art['link']})")
            lines.append(f"*{art['source']}*")
            lines.append("")
            lines.append(f"> {data.get('tldr', '')}")
            lines.append("")
            lines.append(f"- **What happened:** {data.get('what_happened', '')}")
            lines.append(f"- **Why it matters:** {data.get('why_it_matters', '')}")
            lines.append(f"- **Business impact:** {data.get('business_impact', '')}")
            lines.append(f"- **Leader action:** {data.get('leader_action', '')}")
            lines.append("")
            lines.append(f"[Read more \u2192]({art['link']})")
            lines.append("")
        lines.append("---")
        lines.append("")

    if me_pairs:
        lines.append("## From the Region \u00b7 Middle East")
        lines.append("")
        for art, data in me_pairs:
            lines.append(f"**[{data.get('headline', art['title'])}]({art['link']})** \u2014 {art['source']}")
            lines.append(f"{data.get('tldr', '')}")
            lines.append("")
        lines.append("---")
        lines.append("")

    if eve_pairs:
        lines.append("## Consumer Signals")
        lines.append("_For everyday users._")
        lines.append("")
        for art, data in eve_pairs:
            lines.append(f"### [{data.get('headline', art['title'])}]({art['link']})")
            lines.append(f"*{art['source']}*")
            lines.append("")
            lines.append(f"> {data.get('tldr', '')}")
            lines.append("")
            lines.append(f"- **In plain English:** {data.get('in_plain_english', '')}")
            lines.append(f"- **Why you care:** {data.get('why_you_care', '')}")
            lines.append(f"- **What to do:** {data.get('what_to_do', '')}")
            lines.append("")
        lines.append("---")
        lines.append("")

    if tip and tip.get("title"):
        lines.append("## Tip of the Week")
        lines.append(f"### {tip.get('title', '')}")
        lines.append("")
        lines.append(tip.get("what", ""))
        lines.append("")
        lines.append(f"**Try this:** {tip.get('try_this', '')}")
        lines.append("")
        if tip.get("link_url") and tip.get("link_label"):
            lines.append(f"[{tip['link_label']} \u2192]({tip['link_url']})")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("### Subscribe to SIGNAL")
    lines.append("Hit **Subscribe** at the top of this newsletter to get SIGNAL every Monday. One email. No noise.")
    lines.append("")
    lines.append("_SIGNAL is composed each week by an AI agent._")

    fname = f"linkedin_post_{datetime.now().strftime('%Y_%m_%d')}.md"
    with open(fname, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  LinkedIn post written -> {fname}")
    return fname

# =========================================================
# MAIN
# =========================================================
def generate_newsletter():
    print("Starting SIGNAL Agent v2...\n")
    print(f"Mode: {'EDITOR-IN-CHIEF (interactive review)' if INTERACTIVE_MODE else 'AUTONOMOUS (no prompts)'}\n")

    articles = fetch_recent_news()
    if not articles:
        print("No articles found. Exiting.")
        return

    # 1) Detect viral lead
    viral, _ = detect_viral_story(articles)

    # 2) Pick stories for the three tracks (excluding viral)
    picks = select_articles(articles, viral_article=viral)

    # 2b) EDITOR-IN-CHIEF MODE: pause and let the user revise
    if INTERACTIVE_MODE:
        viral, picks = editor_review_loop(viral, picks, articles)
        if picks is None:
            print("Aborted by editor. No newsletter written.")
            return

    today = datetime.now().strftime("%B %d, %Y")

    # 3) Analyze viral story (if found)
    viral_html = ""
    if viral:
        print("\nWriting viral lead...")
        viral_data = analyze_article(viral, "viral")
        viral_html = f"""
        <div class="section-header">
          <span class="index">01 //</span>
          <h2>The Viral Lead</h2>
          <span class="rule"></span>
        </div>
        {render_viral_block(viral, viral_data)}
        """

    # 4) Business cards
    print("\nWriting business cards...")
    biz_html = "".join(
        render_business_card(art, analyze_article(art, "business"))
        for art in picks["business"]
    )

    # 5) Middle East cards
    print("\nWriting Middle East section...")
    me_items = [(art, analyze_article(art, "middle_east")) for art in picks["middle_east"]]
    me_html = render_middle_east_block(me_items)

    # 6) Everyday cards
    print("\nWriting everyday cards...")
    eve_html = "".join(
        render_everyday_card(art, analyze_article(art, "everyday"))
        for art in picks["everyday"]
    )

    # 7) Tip of the Week
    tip = generate_tip_of_week()
    tip_html = render_tip_block(tip)

    html = HTML_TEMPLATE.format(
        date=today,
        business_cards=biz_html,
        everyday_cards=eve_html,
        middle_east_block=me_html,
        viral_block=viral_html,
        tip_block=tip_html,
        signup_url=SIGNUP_URL,
    )

    fname = f"newsletter_{datetime.now().strftime('%Y_%m_%d')}.html"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nSuccess! Saved {fname} -- open it in your browser!")

    # 8) LinkedIn export -- copy/paste-ready Markdown
    if EXPORT_LINKEDIN:
        # Re-pair each article with its analyzed data so the export can reuse the LLM output
        # We re-run analyze for the LinkedIn export only if needed; here we cache from above.
        # (Simpler: regenerate cards for the export. Cheap, ~6 small LLM calls.)
        viral_pair = None
        if viral:
            viral_pair = (viral, viral_data)
        biz_pairs = [(art, analyze_article(art, "business")) for art in picks["business"]]
        eve_pairs = [(art, analyze_article(art, "everyday")) for art in picks["everyday"]]
        export_linkedin_post(today, viral_pair, biz_pairs, eve_pairs, me_items, tip)


if __name__ == "__main__":
    generate_newsletter()
