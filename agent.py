"""
AI Weekly Reader's Digest Agent
--------------------------------
A simple agent that:
  1. Fetches the latest AI news from trusted RSS feeds (last 7 days)
  2. Asks the LLM to pick the top stories for two audiences (business + everyday)
  3. Asks the LLM to write a tight, structured summary of each story
  4. Renders a polished HTML newsletter you can email or publish

Built as a learning project for the MIT Applied Agentic course.
"""

import feedparser
import os
import json
from datetime import datetime, timedelta
from time import mktime
from openai import OpenAI

# =========================================================
# CONFIG  -- edit these freely
# =========================================================
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Model: gpt-4o-mini is cheap, fast, and perfect for this use case.
MODEL = "gpt-4o-mini"

# Temperature: 0.0 = predictable, 1.0 = creative. 0.3 is a good middle ground.
TEMPERATURE = 0.3

# How many stories to feature in each section
TOP_BUSINESS = 3
TOP_EVERYDAY = 3

# How many days back to look for news
LOOKBACK_DAYS = 7

# Where to send readers when they click "Subscribe".
# Drop in your Substack/Mailchimp/Beehiiv/Tally form URL here.
# Leave as "#" until you have one set up.
SIGNUP_URL = "https://tally.so/r/7R4V7R"

# Trusted sources (RSS feeds). Add or remove as you like!
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
}

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
                    continue  # skip articles with bad/missing dates
        except Exception as e:
            print(f"  ! Failed to fetch {source}: {e}")
    print(f"  Found {len(recent)} recent articles.")
    return recent

# =========================================================
# 2. EDITOR (dual-track selection)
# =========================================================
def select_articles(articles):
    """Use the LLM to pick top stories for business AND everyday audiences."""
    if not articles:
        return {"business": [], "everyday": []}

    print(f"Selecting top {TOP_BUSINESS} business + {TOP_EVERYDAY} everyday stories...")
    listing = "\n".join(
        f"[{i}] {a['title']} ({a['source']}) - {a['summary'][:160]}"
        for i, a in enumerate(articles)
    )

    prompt = f"""You are an editor for a weekly AI newsletter that serves two audiences:
1) Business leaders (strategy, regulation, enterprise AI moves)
2) Everyday users (consumer apps, privacy, jobs, fun creative tools)

Pick the top {TOP_BUSINESS} stories for BUSINESS and top {TOP_EVERYDAY} for EVERYDAY.
Do not pick the same article in both lists.

Return JSON exactly: {{"business": [indices], "everyday": [indices]}}

Articles:
{listing}
"""
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=TEMPERATURE,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    try:
        result = json.loads(resp.choices[0].message.content)
        biz = [articles[i] for i in result.get("business", []) if i < len(articles)][:TOP_BUSINESS]
        eve = [articles[i] for i in result.get("everyday", []) if i < len(articles)][:TOP_EVERYDAY]
        return {"business": biz, "everyday": eve}
    except Exception as e:
        print(f"  ! Parse error: {e}")
        return {
            "business": articles[:TOP_BUSINESS],
            "everyday": articles[TOP_BUSINESS:TOP_BUSINESS + TOP_EVERYDAY],
        }

# =========================================================
# 3. ANALYST (structured JSON, ultra-tight phrasing)
# =========================================================
def analyze_article(article, audience="business"):
    """Ask the LLM for a structured, scannable card for one article."""
    print(f"  [{audience}] {article['title'][:70]}...")

    if audience == "business":
        schema_hint = """{
  "headline": "punchy 6-10 word headline (no period)",
  "tldr": "ONE crisp sentence summary, max 20 words",
  "what_happened": "max 12 words, no period",
  "why_it_matters": "max 12 words, no period",
  "business_impact": "max 12 words, no period",
  "leader_action": "max 12 words, action verb first, no period"
}"""
        rules = "Audience: business leaders. No jargon. No acronyms unless universally known."
    else:
        schema_hint = """{
  "headline": "fun 6-10 word headline (no period)",
  "tldr": "ONE friendly sentence summary, max 20 words",
  "in_plain_english": "max 12 words, no period",
  "why_you_care": "max 12 words, no period",
  "what_to_do": "max 12 words, action verb first, no period"
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
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=TEMPERATURE,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except Exception:
        return {}

# =========================================================
# 4. PUBLISHER -- HTML renderer
# =========================================================
# Premium AI intelligence briefing aesthetic: dark charcoal background,
# electric cyan accents, subtle violet depth, off-white text, minimal futuristic accents.
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SIGNAL // AI Intelligence Briefing - {date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    /* Light editorial palette with deep-navy ink and cyan/violet accents */
    --bg: #f4f6fb;            /* page background, very light cool gray */
    --paper: #ffffff;         /* card/paper surface */
    --panel: #f0f4fa;         /* tinted panel for TL;DR & CTA */
    --line: #e3e8f1;          /* hairline divider */
    --line-bright: #cfd6e4;   /* slightly stronger divider */
    --ink: #0e1628;           /* primary text - deep navy */
    --ink-2: #1f2a44;         /* secondary text */
    --muted: #5b6679;         /* meta/muted */
    --muted-2: #8a93a6;       /* very muted */
    --cyan: #0891b2;          /* accent - deeper cyan that reads on light */
    --cyan-bright: #06b6d4;   /* hover/glow */
    --violet: #7c3aed;        /* secondary accent */
    --violet-soft: #8b5cf6;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: var(--bg);
    background-image:
      radial-gradient(800px 400px at 50% -150px, rgba(8,145,178,0.10), transparent 60%),
      radial-gradient(600px 350px at 95% 5%, rgba(124,58,237,0.07), transparent 65%);
    color: var(--ink);
    padding: 40px 16px;
    line-height: 1.6;
    font-size: 15px;
    font-weight: 400;
    -webkit-font-smoothing: antialiased;
  }}
  .wrap {{
    max-width: 680px;
    margin: 0 auto;
    background: var(--paper);
    border: 1px solid var(--line);
    border-radius: 6px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(14,22,40,0.04), 0 12px 40px rgba(14,22,40,0.06);
  }}
  /* MASTHEAD */
  .masthead {{
    padding: 36px 44px 28px;
    border-bottom: 1px solid var(--line);
    background:
      linear-gradient(180deg, rgba(8,145,178,0.04), transparent 70%);
  }}
  .masthead-top {{
    display: flex; justify-content: space-between; align-items: center;
    font-family: "JetBrains Mono", monospace;
    font-size: 10px; letter-spacing: 2px; color: var(--muted);
    text-transform: uppercase; margin-bottom: 28px;
  }}
  .masthead-top .dot {{
    display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    background: var(--cyan); margin-right: 8px; vertical-align: middle;
    box-shadow: 0 0 8px rgba(8,145,178,0.6);
  }}
  .masthead h1 {{
    font-family: "Space Grotesk", sans-serif;
    font-weight: 700; font-size: 46px; line-height: 1; letter-spacing: -1.5px;
    margin: 0 0 10px; color: var(--ink);
  }}
  .masthead h1 .accent {{ color: var(--cyan); }}
  .masthead .tagline {{
    font-size: 14px; color: var(--ink-2); letter-spacing: 0.1px;
  }}
  /* INLINE SUBSCRIBE STRIP UNDER THE MASTHEAD */
  .subscribe-strip {{
    display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
    justify-content: space-between;
    padding: 14px 44px;
    background: linear-gradient(90deg, rgba(8,145,178,0.07), rgba(124,58,237,0.05));
    border-bottom: 1px solid var(--line);
    font-size: 13px; color: var(--ink-2);
  }}
  .subscribe-strip .copy {{ flex: 1; min-width: 200px; }}
  .subscribe-strip .copy strong {{ color: var(--ink); }}
  .subscribe-strip a.cta-mini {{
    display: inline-flex; align-items: center; gap: 8px;
    font-family: "JetBrains Mono", monospace;
    font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase;
    color: #ffffff; background: var(--cyan);
    padding: 9px 16px; border-radius: 3px; text-decoration: none;
    transition: background 0.15s ease, transform 0.15s ease;
  }}
  .subscribe-strip a.cta-mini:hover {{ background: var(--cyan-bright); transform: translateY(-1px); }}
  .subscribe-strip a.cta-mini::after {{ content: "->"; }}
  /* INTRO / DECK */
  .deck {{
    padding: 28px 44px;
    border-bottom: 1px solid var(--line);
    font-size: 15px; color: var(--ink-2); line-height: 1.65;
  }}
  .deck .label {{
    font-family: "JetBrains Mono", monospace;
    font-size: 10px; letter-spacing: 2px; color: var(--cyan);
    text-transform: uppercase; margin-bottom: 10px; display: block;
  }}
  /* SECTION HEADER */
  .section {{ padding: 0; }}
  .section-header {{
    padding: 36px 44px 18px;
    display: flex; align-items: center; gap: 14px;
    border-bottom: 1px solid var(--line);
  }}
  .section-header .index {{
    font-family: "JetBrains Mono", monospace;
    font-size: 11px; color: var(--cyan); letter-spacing: 1.5px;
  }}
  .section-header h2 {{
    font-family: "Space Grotesk", sans-serif;
    font-weight: 600; font-size: 18px; letter-spacing: 0.3px;
    text-transform: uppercase; color: var(--ink); margin: 0;
  }}
  .section-header .rule {{
    flex: 1; height: 1px;
    background: linear-gradient(90deg, var(--line-bright), transparent);
  }}
  /* ARTICLES */
  .article {{
    padding: 28px 44px;
    border-bottom: 1px solid var(--line);
    position: relative;
  }}
  .article:last-child {{ border-bottom: none; }}
  .article-meta {{
    display: flex; gap: 14px; align-items: center;
    font-family: "JetBrains Mono", monospace;
    font-size: 10px; letter-spacing: 1.8px; text-transform: uppercase;
    color: var(--muted); margin-bottom: 12px;
  }}
  .article-meta .pill {{
    display: inline-block; padding: 3px 8px;
    border: 1px solid var(--cyan); border-radius: 2px;
    color: var(--cyan); letter-spacing: 1.5px; background: rgba(8,145,178,0.06);
  }}
  .article-headline {{
    font-family: "Space Grotesk", sans-serif;
    font-weight: 600; font-size: 23px; line-height: 1.25;
    letter-spacing: -0.4px; margin: 0 0 12px;
  }}
  .article-headline a {{
    color: var(--ink); text-decoration: none;
    transition: color 0.2s ease;
  }}
  .article-headline a:hover {{ color: var(--cyan); }}
  .tldr {{
    font-size: 14px; line-height: 1.6; color: var(--ink-2);
    padding: 12px 14px; margin: 0 0 18px;
    background: var(--panel);
    border-left: 2px solid var(--cyan);
    border-radius: 2px;
  }}
  .points {{
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 16px 28px; margin: 0;
  }}
  .point .label {{
    display: block;
    font-family: "JetBrains Mono", monospace;
    font-size: 9px; font-weight: 600; letter-spacing: 2px;
    text-transform: uppercase; color: var(--violet);
    margin-bottom: 4px;
  }}
  .point .value {{
    display: block; font-size: 13px; line-height: 1.5; color: var(--ink);
  }}
  .read-more {{
    display: inline-flex; align-items: center; gap: 8px;
    margin-top: 18px;
    font-family: "JetBrains Mono", monospace;
    font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase;
    color: var(--cyan); text-decoration: none;
    padding-bottom: 3px; border-bottom: 1px solid rgba(8,145,178,0.35);
    transition: border-color 0.2s ease, color 0.2s ease;
  }}
  .read-more:hover {{ color: var(--cyan-bright); border-bottom-color: var(--cyan-bright); }}
  .read-more::after {{ content: "->"; }}
  /* CTA -- the bottom Sign Up block */
  .cta {{
    margin: 0; padding: 44px 44px;
    text-align: center;
    background:
      linear-gradient(135deg, rgba(8,145,178,0.08), rgba(124,58,237,0.08));
    border-top: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
  }}
  .cta .label {{
    font-family: "JetBrains Mono", monospace;
    font-size: 10px; letter-spacing: 2px; color: var(--cyan);
    text-transform: uppercase; margin-bottom: 12px; display: block;
  }}
  .cta h3 {{
    font-family: "Space Grotesk", sans-serif;
    font-weight: 700; font-size: 26px; color: var(--ink);
    margin: 0 0 12px; letter-spacing: -0.5px;
  }}
  .cta p {{
    font-size: 14px; color: var(--ink-2); margin: 0 auto 22px; line-height: 1.6;
    max-width: 440px;
  }}
  .cta a.button {{
    display: inline-block; padding: 14px 28px;
    font-family: "JetBrains Mono", monospace;
    font-size: 12px; letter-spacing: 2px; text-transform: uppercase;
    color: #ffffff; background: var(--cyan);
    text-decoration: none; border-radius: 3px;
    box-shadow: 0 6px 18px rgba(8,145,178,0.25);
    transition: transform 0.15s ease, background 0.15s ease;
  }}
  .cta a.button:hover {{ transform: translateY(-1px); background: var(--cyan-bright); }}
  .cta .small {{
    margin-top: 14px; font-size: 12px; color: var(--muted);
  }}
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
    .masthead h1 {{ font-size: 34px; }}
    .deck, .article, .cta, .colophon, .subscribe-strip {{ padding-left: 22px; padding-right: 22px; }}
    .section-header {{ padding: 28px 22px 14px; }}
    .points {{ grid-template-columns: 1fr; gap: 14px; }}
    .article-headline {{ font-size: 20px; }}
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
      <div class="tagline">A weekly intelligence briefing on artificial intelligence.</div>
    </header>

    <div class="subscribe-strip">
      <div class="copy"><strong>New here?</strong> Get SIGNAL in your inbox every Monday.</div>
      <a class="cta-mini" href="{signup_url}">Subscribe free</a>
    </div>

    <div class="deck">
      <span class="label">// This Week</span>
      The signals that matter, decoded for leaders building with AI \u2014 and the consumer shifts shaping how the rest of the world experiences it.
    </div>

    <section class="section">
      <div class="section-header">
        <span class="index">01 //</span>
        <h2>Strategic Briefing</h2>
        <span class="rule"></span>
      </div>
      {business_cards}
    </section>

    <section class="section">
      <div class="section-header">
        <span class="index">02 //</span>
        <h2>Consumer Signals</h2>
        <span class="rule"></span>
      </div>
      {everyday_cards}
    </section>

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
        <div class="point"><span class="label">Signal</span><span class="value">{data.get('what_happened', '')}</span></div>
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

# =========================================================
# MAIN
# =========================================================
def generate_newsletter():
    print("Starting AI News Agent...\n")
    articles = fetch_recent_news()
    if not articles:
        print("No articles found. Exiting.")
        return

    picks = select_articles(articles)
    today = datetime.now().strftime("%B %d, %Y")

    print("\nWriting business cards...")
    biz_html = "".join(
        render_business_card(art, analyze_article(art, "business"))
        for art in picks["business"]
    )

    print("\nWriting everyday cards...")
    eve_html = "".join(
        render_everyday_card(art, analyze_article(art, "everyday"))
        for art in picks["everyday"]
    )

    html = HTML_TEMPLATE.format(
        date=today,
        business_cards=biz_html,
        everyday_cards=eve_html,
        signup_url=SIGNUP_URL,
    )

    fname = f"newsletter_{datetime.now().strftime('%Y_%m_%d')}.html"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nSuccess! Saved {fname} -- open it in your browser!")


if __name__ == "__main__":
    generate_newsletter()
