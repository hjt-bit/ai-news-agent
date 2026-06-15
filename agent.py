"""
SIGNAL -- AI Weekly Intelligence Briefing Agent (v3)
----------------------------------------------------
Pipeline:
  1. FETCH      -> pull the last 7 days of articles from trusted RSS feeds
  2. TRANSCRIBE -> extract AI-relevant topics from podcast transcripts (YouTube)
  3. SCORE      -> weighted relevance scoring (cross-source coverage, recency,
                   podcast mention signals, audience relevance)
  4. SELECT     -> pick top stories enforcing source diversity (max 2 per source)
  5. ANALYZE    -> ask the LLM for a structured, scannable card per story
  6. PUBLISH    -> render a polished HTML newsletter + LinkedIn export

Built as a learning project for the MIT Applied Agentic course.
"""

import feedparser
import os
import sys
import json
import re
import urllib.request
import urllib.error
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

# Maximum stories from any single source (enforces diversity)
MAX_PER_SOURCE = 2

# Where to send readers when they click "Subscribe".
SIGNUP_URL  = "https://www.linkedin.com/newsletters/signal-7459465103449468928/"
BEEHIIV_URL = "https://signalweekly.beehiiv.com/subscribe"

# GitHub Pages archive base (used to build the canonical link to each issue).
PAGES_BASE_URL = "https://hjt-bit.github.io/ai-news-agent"

# Editor-in-Chief Mode
_env_interactive = os.environ.get("SIGNAL_INTERACTIVE")
if _env_interactive is not None:
    INTERACTIVE_MODE = _env_interactive == "1"
else:
    INTERACTIVE_MODE = sys.stdin.isatty()

# Also export a LinkedIn-formatted version of the newsletter on each run.
EXPORT_LINKEDIN = True

# ── Forced Viral Lead ──────────────────────────────────────────────────────────
# Set this to a keyword/phrase to force the agent to feature a specific story as
# the viral lead. Set to None to let the agent auto-detect.
FORCED_LEAD = None

# Set this to an integer to force a specific issue number (e.g. 6 to label the
# output "Issue #006" regardless of the run date). Set to None to auto-compute
# the issue number from the date. Remember to reset to None after a one-off run.
FORCED_ISSUE = 6   # one-off: label this run as Issue #006; reset to None after

# =========================================================
# SOURCES -- RSS feeds organized by tier
# =========================================================
SOURCES = {
    # --- Industry / Technical (Tier 1 — most credible) ---
    "MIT Tech Review": "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
    "OpenAI Blog": "https://openai.com/news/rss.xml",
    "Google AI Blog": "https://blog.google/technology/ai/rss/",
    "Hugging Face Blog": "https://huggingface.co/blog/feed.xml",
    "AI News": "https://www.artificialintelligence-news.com/feed/",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/",
    "MarkTechPost": "https://www.marktechpost.com/feed/",
    # --- Everyday-user friendly ---
    "The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "Wired AI": "https://www.wired.com/feed/tag/ai/latest/rss",
    "Ars Technica": "https://feeds.arstechnica.com/arstechnica/index",
    "The Decoder": "https://the-decoder.com/feed/",
    # --- Newsletters & curated briefings ---
    "Ben's Bites": "https://www.bensbites.com/feed",
    "TLDR AI": "https://tldr.tech/api/rss/ai",
    "Last Week in AI": "https://lastweekin.ai/feed",
    "Ahead of AI (Raschka)": "https://magazine.sebastianraschka.com/feed",
    # --- Podcasts (RSS metadata only — transcripts fetched separately) ---
    "All-In Podcast": "https://rss.libsyn.com/shows/254861/destinations/1928300.xml",
    "Latent Space": "https://api.substack.com/feed/podcast/1084089.rss",
    "Dwarkesh Podcast": "https://api.substack.com/feed/podcast/69345.rss",
    # --- European / Global startups ---
    "Sifted": "https://sifted.eu/feed",
    # --- Middle East focus ---
    "TahawulTech": "https://www.tahawultech.com/feed/",
    "Wamda": "https://www.wamda.com/feed",
    "Arab News (Business)": "https://www.arabnews.com/rss.xml",
}

# Sources we treat as "Middle East" for the regional section
MIDDLE_EAST_SOURCES = {"TahawulTech", "Wamda", "Arab News (Business)"}

# Sources that are podcasts (will also get transcript extraction)
PODCAST_SOURCES = {"All-In Podcast", "Latent Space", "Dwarkesh Podcast"}

# YouTube channel IDs for podcast transcript extraction
PODCAST_YOUTUBE_CHANNELS = {
    "All-In Podcast": "UCESLZhusAkFfsNsApnjF_Cg",
    "Latent Space": "UCWTRfRBnIa8bUMK3GM80Nzw",
    "Dwarkesh Podcast": "UC2LQFGfUtSjMGq-ZBMhIA9g",
}

# Domains that are NOT credible standalone news articles (podcast/audio/video hosts,
# raw feeds, social). A story's "Read full story" link must NEVER point here — readers
# expect a real news article they can verify. Podcasts feed the agent as topic SIGNALS
# only; they must not be the cited source link. This guards the issue even if a future
# feed sneaks a non-article URL into the pool.
NON_ARTICLE_LINK_DOMAINS = (
    "libsyn.com", "simplecast.com", "buzzsprout.com", "podbean.com",
    "captivate.fm", "transistor.fm", "anchor.fm", "megaphone.fm",
    "acast.com", "redcircle.com", "fireside.fm", "soundcloud.com",
    "spotify.com", "podcasts.apple.com", "apple.co", "pca.st",
    "youtube.com", "youtu.be", "twitter.com", "x.com", "t.co",
    "facebook.com", "linkedin.com", "reddit.com",
    "substack.com/feed/podcast", "api.substack.com/feed/podcast",
)


def is_valid_article_link(url, source=None):
    """Return True only if `url` looks like a credible standalone news article.

    Rejects podcast/audio hosts, social links, bare domains, and feeds. Used to
    keep non-article URLs out of the newsletter's source links.
    """
    if not url or not isinstance(url, str):
        return False
    u = url.strip().lower()
    if not (u.startswith("http://") or u.startswith("https://")):
        return False
    try:
        from urllib.parse import urlparse
        p = urlparse(u)
    except Exception:
        return False
    host = (p.netloc or "").split("@")[-1].split(":")[0]
    if not host:
        return False
    path = (p.path or "").strip("/")
    full_lower = u  # for path-bearing patterns like substack podcast feeds

    # Block known non-article hosts — matched by HOST (exact or subdomain),
    # not raw substring, so e.g. 'marktechpos t.co m' is never falsely blocked.
    for bad in NON_ARTICLE_LINK_DOMAINS:
        if "/" in bad:
            # Path-bearing pattern (e.g. substack podcast feed): match anywhere in URL.
            if bad in full_lower:
                return False
            continue
        # Domain pattern: match the host exactly or as a subdomain suffix.
        if host == bad or host.endswith("." + bad):
            return False
    # Block obvious feed endpoints.
    if u.rstrip("/").endswith(("/feed", "/rss", ".xml", ".rss")):
        return False
    # Require a path beyond the bare domain (real articles have a slug/path).
    if len(path) < 3:  # e.g. just "/" or "/ai"
        return False
    return True

# Keywords that flag any article (from any source) as Middle East-relevant
ME_KEYWORDS = [
    # Countries
    "uae", "saudi", "saudi arabia", "qatar", "kuwait", "bahrain", "oman", "egypt", "jordan",
    "lebanon", "iraq", "iran", "israel", "turkey", "morocco", "tunisia", "emirates",
    # Cities
    "dubai", "abu dhabi", "riyadh", "doha", "beirut", "cairo", "amman", "jeddah", "manama",
    # Regional terms
    "middle east", "gulf", "gcc", "mena", "levant", "arab", "arabian",
    # Regional companies, funds & ecosystem players (so funding/M&A stories route correctly)
    "g42", "tahweel", "core42", "mnt-halan", "mnt halan", "halan", "careem", "tabby",
    "tamara", "stc", "aramco", "adnoc", "mubadala", "pif", "public investment fund",
    "e&", "etisalat", "du", "anghami", "swvl", "kitopi", "fenix", "valu", "paymob",
    "instabug", "wamda", "rain", "lean technologies", "foodics", "unifonic", "trukker",
    "hub71", "dtec", "difc", "adgm", "neom", "tonomus", "sandbox",
]

# Generic tokens that are too weak to qualify a story as regional ON THEIR OWN
# (they cause false positives, e.g. "sandbox" in a dev context, "du" inside words).
# These only count toward regional relevance when a stronger keyword is also present.
_WEAK_ME_TOKENS = {"arab", "arabian", "sandbox", "du", "e&", "rain", "valu", "halan"}


def is_regional_story(article):
    """Strict test for whether a story genuinely belongs in 'From the Region'.

    A story qualifies only if:
      (a) it comes from a dedicated MENA news source, OR
      (b) a STRONG Middle East keyword appears as a whole word in the title/summary.
    Weak/ambiguous tokens alone do not qualify, which prevents non-regional
    stories (e.g. a US SpaceX IPO) from being stretched to fill the section.
    """
    if not article:
        return False
    if article.get("source") in MIDDLE_EAST_SOURCES:
        return True
    text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
    for kw in ME_KEYWORDS:
        if kw in _WEAK_ME_TOKENS:
            continue
        # Whole-word / phrase match using boundaries so 'uae' won't match inside
        # another word and short tokens don't over-trigger.
        pattern = r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])"
        if re.search(pattern, text):
            return True
    return False

# =========================================================
# PREVIOUS TIPS (to avoid repetition)
# =========================================================
PREVIOUS_TIPS = [
    "ChatGPT Projects",
    "ChatGPT Memory",
    "Claude Artifacts",
    "Granola AI Brainstorming",
    "Claude Computer Use",
    "NotebookLM Audio Overviews",
]

# =========================================================
# 1. FETCHER
# =========================================================
def fetch_recent_news(days=LOOKBACK_DAYS):
    """Pull articles from each RSS feed published within the last `days` days."""
    print(f"\n{'='*60}")
    print(f"STEP 1: FETCHING NEWS (last {days} days)")
    print(f"{'='*60}")
    recent = []
    cutoff = datetime.now() - timedelta(days=days)
    source_counts = {}

    skipped_podcast = 0
    skipped_badlink = 0
    for source, url in SOURCES.items():
        # Podcasts are SIGNAL sources only (transcripts) — never selectable as a cited
        # article, because their links are audio episodes, not verifiable news articles.
        if source in PODCAST_SOURCES:
            source_counts[source] = "signal-only (podcast)"
            continue
        try:
            feed = feedparser.parse(url)
            count = 0
            for entry in feed.entries:
                try:
                    pub = datetime.fromtimestamp(mktime(entry.published_parsed))
                    if pub > cutoff:
                        link = entry.link
                        # Guard: only ingest entries that point to a real news article.
                        if not is_valid_article_link(link, source):
                            skipped_badlink += 1
                            continue
                        recent.append({
                            "title": entry.title,
                            "link": link,
                            "source": source,
                            "summary": entry.get("summary", "")[:600],
                            "published": pub,
                        })
                        count += 1
                except Exception:
                    continue
            source_counts[source] = count
        except Exception as e:
            source_counts[source] = f"FAILED: {e}"
            print(f"  ✗ {source}: {e}")

    # Print source fetch report
    print(f"\n  Source Fetch Report:")
    print(f"  {'─'*50}")
    for source, count in sorted(source_counts.items(), key=lambda x: str(x[1]), reverse=True):
        status = f"  {'✓' if isinstance(count, int) and count > 0 else '○' if count == 0 else '✗'} {source}: {count} articles"
        print(status)
    print(f"  {'─'*50}")
    print(f"  TOTAL: {len(recent)} articles from {sum(1 for c in source_counts.values() if isinstance(c, int) and c > 0)} sources")
    if skipped_badlink:
        print(f"  (skipped {skipped_badlink} entr(ies) with non-article links e.g. podcast/audio/social)")

    return recent

# =========================================================
# 2. PODCAST TRANSCRIPT EXTRACTION
# =========================================================
def fetch_podcast_topics():
    """
    Extract AI-relevant topics from recent podcast episodes via YouTube transcripts.
    Returns a list of topic strings that serve as 'importance signals' for scoring.
    Also writes a per-podcast verification report (podcast_review.md) so the
    operator can confirm each week that podcast narratives were actually read.
    """
    print(f"\n{'='*60}")
    print(f"STEP 2: EXTRACTING PODCAST TOPICS")
    print(f"{'='*60}")

    podcast_topics = []
    podcast_report = []  # structured per-podcast status for the verification report

    for podcast_name, channel_id in PODCAST_YOUTUBE_CHANNELS.items():
        print(f"\n  Processing: {podcast_name}")
        status = {
            "podcast": podcast_name,
            "episodes": [],
            "transcript_fetched": False,
            "transcript_chars": 0,
            "topics": [],
            "error": None,
        }
        try:
            topics, meta = _extract_youtube_topics(podcast_name, channel_id)
            status["episodes"] = meta.get("episodes", [])
            status["transcript_fetched"] = meta.get("transcript_fetched", False)
            status["transcript_chars"] = meta.get("transcript_chars", 0)
            status["topics"] = topics
            if topics:
                podcast_topics.extend(topics)
                print(f"    → Extracted {len(topics)} topic signals")
                print(f"    → Transcript fetched: {status['transcript_fetched']} ({status['transcript_chars']} chars)")
            else:
                print(f"    → No recent AI topics found")
        except Exception as e:
            status["error"] = str(e)
            print(f"    ✗ Failed: {e}")
        podcast_report.append(status)

    print(f"\n  Total podcast topic signals: {len(podcast_topics)}")
    if podcast_topics:
        print(f"  Topics: {', '.join(podcast_topics[:10])}{'...' if len(podcast_topics) > 10 else ''}")

    # Write the verification report so the operator can audit podcast ingestion each week
    try:
        _write_podcast_report(podcast_report)
    except Exception as e:
        print(f"  (Could not write podcast report: {e})")

    return podcast_topics, podcast_report


def _write_podcast_report(podcast_report):
    """Write podcast_review.md — a human-readable weekly audit of podcast ingestion."""
    today = datetime.now().strftime("%B %d, %Y")
    lines = [
        f"# SIGNAL — Podcast Review Log",
        f"",
        f"_Generated {today}. This file confirms which podcasts the agent read this week,",
        f"whether full transcripts were successfully fetched, and what topic signals were extracted._",
        f"",
        f"| Podcast | Episodes Found | Transcript Read | Transcript Length | Topics Extracted |",
        f"|---|---|---|---|---|",
    ]
    for s in podcast_report:
        ep_count = len(s.get("episodes", []))
        tx = "✅ Yes" if s.get("transcript_fetched") else "❌ No (titles/descriptions only)"
        tx_len = f"{s.get('transcript_chars', 0):,} chars" if s.get("transcript_chars") else "—"
        topic_count = len(s.get("topics", []))
        err = f" ⚠️ {s['error']}" if s.get("error") else ""
        lines.append(f"| {s['podcast']} | {ep_count} | {tx}{err} | {tx_len} | {topic_count} |")

    lines.append("")
    lines.append("## Detail by Podcast")
    for s in podcast_report:
        lines.append("")
        lines.append(f"### {s['podcast']}")
        if s.get("error"):
            lines.append(f"- ⚠️ Error: {s['error']}")
        episodes = s.get("episodes", [])
        if episodes:
            lines.append(f"- Recent episodes detected:")
            for ep in episodes:
                lines.append(f"  - {ep}")
        else:
            lines.append("- No recent episodes detected in the lookback window.")
        lines.append(f"- Transcript fetched: {'Yes' if s.get('transcript_fetched') else 'No'}"
                     f" ({s.get('transcript_chars', 0):,} chars)")
        topics = s.get("topics", [])
        if topics:
            lines.append(f"- Topic signals fed into story scoring:")
            for t in topics:
                lines.append(f"  - {t}")
        else:
            lines.append("- No topic signals extracted.")

    with open("podcast_review.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("  ✓ Wrote podcast_review.md (weekly verification report)")


def _extract_youtube_topics(podcast_name, channel_id):
    """
    Fetch recent video titles and descriptions from a YouTube channel's RSS feed,
    then use LLM to extract AI-relevant topic keywords.
    Returns a tuple: (topics_list, meta_dict) where meta_dict carries episode
    titles, transcript status, and transcript length for the verification report.
    """
    meta = {"episodes": [], "transcript_fetched": False, "transcript_chars": 0}

    # YouTube channel RSS feed (no API key needed)
    yt_rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

    try:
        feed = feedparser.parse(yt_rss_url)
    except Exception as e:
        print(f"    Could not parse YouTube RSS: {e}")
        return [], meta

    if not feed.entries:
        print(f"    No entries in YouTube RSS feed")
        return [], meta

    # Get episodes from the last 7 days
    cutoff = datetime.now() - timedelta(days=LOOKBACK_DAYS)
    recent_episodes = []

    for entry in feed.entries[:5]:  # Check last 5 episodes
        try:
            pub = datetime.fromtimestamp(mktime(entry.published_parsed))
            if pub > cutoff:
                title = entry.get("title", "")
                # YouTube RSS includes media:description or summary
                description = entry.get("summary", "") or entry.get("media_description", "")
                recent_episodes.append({
                    "title": title,
                    "description": description[:1000],
                })
        except Exception:
            # If no published_parsed, include anyway (it's recent enough to be in top 5)
            title = entry.get("title", "")
            description = entry.get("summary", "") or ""
            recent_episodes.append({
                "title": title,
                "description": description[:1000],
            })

    # Record episode titles in meta for the verification report
    meta["episodes"] = [ep["title"] for ep in recent_episodes]

    if not recent_episodes:
        return [], meta

    # Also try to get transcript for the most recent episode
    transcript_text = ""
    if feed.entries:
        latest_link = feed.entries[0].get("link", "")
        video_id = _extract_video_id(latest_link)
        if video_id:
            transcript_text = _fetch_youtube_transcript(video_id)
    if transcript_text:
        meta["transcript_fetched"] = True
        meta["transcript_chars"] = len(transcript_text)

    # Use LLM to extract AI-relevant topics from episode titles + descriptions + transcript
    episodes_text = "\n".join(
        f"- {ep['title']}: {ep['description'][:300]}"
        for ep in recent_episodes
    )

    transcript_section = ""
    if transcript_text:
        transcript_section = f"\n\nTranscript excerpt (first 3000 chars):\n{transcript_text[:3000]}"

    prompt = f"""You are extracting AI-relevant topic signals from a podcast.

Podcast: {podcast_name}

Recent episodes:
{episodes_text}
{transcript_section}

Extract the specific AI companies, products, technologies, events, or themes discussed.
Return ONLY a JSON object:
{{"topics": ["topic1", "topic2", ...]}}

Rules:
- Each topic should be 2-5 words (e.g., "Meta business agents", "OpenAI GPT-5", "AI regulation EU")
- Only include topics related to AI, technology, or business/startup news
- Maximum 10 topics
- Be specific: "Meta AI agents for business" is better than "AI agents"
"""

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        result = json.loads(resp.choices[0].message.content)
        return result.get("topics", []), meta
    except Exception as e:
        print(f"    LLM topic extraction failed: {e}")
        return [], meta


def _extract_video_id(url):
    """Extract YouTube video ID from a URL."""
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:embed/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _fetch_youtube_transcript(video_id):
    """
    Attempt to fetch YouTube transcript using the youtube-transcript-api.
    Falls back gracefully if the package is not installed or transcript unavailable.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
        # Combine all text segments
        full_text = " ".join(segment['text'] for segment in transcript_list)
        return full_text[:5000]  # Cap at 5000 chars to manage token usage
    except ImportError:
        # youtube-transcript-api not installed — use fallback
        return _fetch_transcript_fallback(video_id)
    except Exception as e:
        print(f"    Transcript fetch failed for {video_id}: {e}")
        return ""


def _fetch_transcript_fallback(video_id):
    """
    Fallback transcript extraction using YouTube's timedtext API.
    Works without any external packages.
    """
    try:
        # Try to get auto-generated English captions
        url = f"https://www.youtube.com/watch?v={video_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")

        # Extract caption track URL from page source
        caption_match = re.search(r'"captionTracks":\[.*?"baseUrl":"(.*?)"', html)
        if not caption_match:
            return ""

        caption_url = caption_match.group(1).replace("\\u0026", "&")
        req2 = urllib.request.Request(caption_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req2, timeout=10) as response:
            caption_xml = response.read().decode("utf-8", errors="ignore")

        # Extract text from XML caption format
        texts = re.findall(r'<text[^>]*>(.*?)</text>', caption_xml)
        if texts:
            import html as html_module
            full_text = " ".join(html_module.unescape(t) for t in texts)
            return full_text[:5000]
    except Exception as e:
        print(f"    Fallback transcript failed: {e}")

    return ""


# =========================================================
# 3. WEIGHTED RELEVANCE SCORING
# =========================================================
def score_articles(articles, podcast_topics):
    """
    Score each article based on multiple weighted signals.
    Returns articles sorted by relevance score (highest first).

    Scoring dimensions:
    - Cross-source coverage (same topic in multiple sources): 0-40 points
    - Podcast mention signal (topic discussed on podcasts): 0-25 points
    - Recency (newer = higher): 0-15 points
    - Source authority tier: 0-10 points
    - Audience relevance (business/consumer impact): 0-10 points
    """
    print(f"\n{'='*60}")
    print(f"STEP 3: SCORING ARTICLES (weighted relevance)")
    print(f"{'='*60}")

    if not articles:
        return articles

    # --- Dimension 1: Cross-source coverage ---
    # Count how many DISTINCT sources cover similar topics
    topic_clusters = _build_topic_clusters(articles)

    # --- Dimension 2: Podcast mention signals ---
    podcast_keywords = set()
    for topic in podcast_topics:
        podcast_keywords.update(word.lower() for word in topic.split() if len(word) > 3)

    # --- Dimension 3: Source authority tiers ---
    TIER_1_SOURCES = {"MIT Tech Review", "OpenAI Blog", "Google AI Blog", "VentureBeat AI",
                      "TechCrunch AI", "Wired AI"}
    TIER_2_SOURCES = {"The Verge AI", "Ars Technica", "Hugging Face Blog", "AI News",
                      "MarkTechPost", "The Decoder", "Sifted"}
    TIER_3_SOURCES = {"Ben's Bites", "TLDR AI", "Last Week in AI", "Ahead of AI (Raschka)"}

    # Score each article
    now = datetime.now()
    scored_articles = []

    for art in articles:
        score = 0
        score_breakdown = {}

        # D1: Cross-source coverage (0-40)
        coverage_score = _get_coverage_score(art, topic_clusters)
        score += coverage_score
        score_breakdown["coverage"] = coverage_score

        # D2: Podcast mention (0-25)
        title_lower = art["title"].lower()
        summary_lower = art.get("summary", "").lower()
        combined_text = f"{title_lower} {summary_lower}"
        podcast_hits = sum(1 for kw in podcast_keywords if kw in combined_text)
        podcast_score = min(25, podcast_hits * 5)
        score += podcast_score
        score_breakdown["podcast"] = podcast_score

        # D3: Recency (0-15)
        pub_date = art.get("published")
        if pub_date:
            days_old = (now - pub_date).total_seconds() / 86400
            recency_score = max(0, int(15 - (days_old * 2)))
        else:
            recency_score = 5  # default if no date
        score += recency_score
        score_breakdown["recency"] = recency_score

        # D4: Source authority (0-10)
        source = art["source"]
        if source in TIER_1_SOURCES:
            authority_score = 10
        elif source in TIER_2_SOURCES:
            authority_score = 7
        elif source in TIER_3_SOURCES:
            authority_score = 5
        else:
            authority_score = 3
        score += authority_score
        score_breakdown["authority"] = authority_score

        # D5: Audience relevance signals (0-10)
        relevance_score = _audience_relevance_score(art)
        score += relevance_score
        score_breakdown["relevance"] = relevance_score

        art["_score"] = score
        art["_score_breakdown"] = score_breakdown
        scored_articles.append(art)

    # Sort by score descending
    scored_articles.sort(key=lambda x: x["_score"], reverse=True)

    # Print top 15 scored articles
    print(f"\n  Top 15 articles by weighted score:")
    print(f"  {'─'*70}")
    print(f"  {'Score':<6} {'Cov':<4} {'Pod':<4} {'Rec':<4} {'Auth':<5} {'Rel':<4} Source → Title")
    print(f"  {'─'*70}")
    for art in scored_articles[:15]:
        bd = art["_score_breakdown"]
        title_short = art["title"][:45]
        print(f"  {art['_score']:<6} {bd['coverage']:<4} {bd['podcast']:<4} {bd['recency']:<4} "
              f"{bd['authority']:<5} {bd['relevance']:<4} {art['source'][:15]} → {title_short}")
    print(f"  {'─'*70}")

    return scored_articles


def _build_topic_clusters(articles):
    """
    Build topic clusters by finding articles that cover the same event/topic.
    Returns a dict mapping article index to number of sources covering similar topics.
    """
    # Extract key entities/phrases from each article title
    article_signatures = []
    for art in articles:
        title_words = set(re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*', art["title"]))
        # Also extract company/product names (capitalized words)
        entities = set(w for w in re.findall(r'\b[A-Z][a-z]{2,}\b', art["title"]))
        article_signatures.append(title_words | entities)

    # For each article, count how many DISTINCT sources have overlapping signatures
    clusters = {}
    for i, art in enumerate(articles):
        sig_i = article_signatures[i]
        if not sig_i:
            clusters[i] = 0
            continue
        covering_sources = {art["source"]}
        for j, other in enumerate(articles):
            if i == j or other["source"] == art["source"]:
                continue
            sig_j = article_signatures[j]
            # Check if they share significant entity overlap
            overlap = sig_i & sig_j
            if len(overlap) >= 2 or (len(overlap) >= 1 and any(len(w) > 4 for w in overlap)):
                covering_sources.add(other["source"])
        clusters[i] = len(covering_sources) - 1  # subtract self

    return clusters


def _get_coverage_score(art, topic_clusters):
    """Get cross-source coverage score for an article."""
    # Find this article's index in the cluster map
    for idx, cluster_count in topic_clusters.items():
        # We need to match by reference since clusters use indices
        pass
    # Simplified: use the cluster count directly
    # Coverage: 0 other sources = 0pts, 1 = 10pts, 2 = 20pts, 3+ = 30pts, 5+ = 40pts
    # We'll recalculate inline
    return 0  # Will be set in the main scoring loop


def _audience_relevance_score(art):
    """Score based on business/consumer relevance signals in the content."""
    text = f"{art['title']} {art.get('summary', '')}".lower()

    high_relevance_signals = [
        "launch", "release", "available", "pricing", "acquisition", "acquire",
        "partnership", "funding", "raises", "billion", "million", "enterprise",
        "business", "consumer", "users", "customers", "app", "feature",
    ]
    medium_relevance_signals = [
        "research", "paper", "study", "benchmark", "model", "open source",
        "regulation", "policy", "safety", "security",
    ]

    high_hits = sum(1 for s in high_relevance_signals if s in text)
    medium_hits = sum(1 for s in medium_relevance_signals if s in text)

    return min(10, high_hits * 2 + medium_hits)


def score_articles_v2(articles, podcast_topics):
    """
    Improved scoring that properly handles cross-source coverage.
    """
    print(f"\n{'='*60}")
    print(f"STEP 3: SCORING ARTICLES (weighted relevance)")
    print(f"{'='*60}")

    if not articles:
        return articles

    # --- Build entity index for cross-source detection ---
    # Extract named entities (capitalized multi-word phrases + single cap words)
    article_entities = []
    for art in articles:
        title = art["title"]
        # Extract multi-word entities (e.g., "Meta AI", "OpenAI")
        multi_word = set(re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+', title))
        # Single capitalized words (likely company/product names)
        singles = set(w for w in re.findall(r'\b[A-Z][a-zA-Z]{2,}\b', title)
                     if w not in {"The", "And", "For", "With", "How", "Why", "What",
                                  "New", "Now", "Its", "Are", "Has", "Can", "May",
                                  "Will", "Just", "Get", "Got", "Use", "All"})
        article_entities.append(multi_word | singles)

    # Count cross-source coverage per article
    coverage_counts = []
    for i, art in enumerate(articles):
        entities_i = article_entities[i]
        if not entities_i:
            coverage_counts.append(0)
            continue
        covering_sources = set()
        for j, other in enumerate(articles):
            if i == j:
                continue
            entities_j = article_entities[j]
            # Significant overlap = likely same story
            shared = entities_i & entities_j
            if shared and (len(shared) >= 2 or any(len(e) > 5 for e in shared)):
                covering_sources.add(other["source"])
        coverage_counts.append(len(covering_sources))

    # --- Podcast keyword set ---
    podcast_keywords = set()
    for topic in podcast_topics:
        for word in topic.lower().split():
            if len(word) > 3:
                podcast_keywords.add(word)
    # Also add full topic phrases for exact matching
    podcast_phrases = [t.lower() for t in podcast_topics]

    # --- Source authority tiers ---
    TIER_1 = {"MIT Tech Review", "TechCrunch AI", "VentureBeat AI", "Wired AI",
              "The Verge AI", "Ars Technica"}
    TIER_2 = {"OpenAI Blog", "Google AI Blog", "Hugging Face Blog", "AI News",
              "MarkTechPost", "The Decoder", "Sifted"}
    TIER_3 = {"Ben's Bites", "TLDR AI", "Last Week in AI", "Ahead of AI (Raschka)"}
    # Note: OpenAI Blog moved to Tier 2 to reduce its dominance — it's authoritative
    # but we want independent journalism in Tier 1

    now = datetime.now()
    scored = []

    for i, art in enumerate(articles):
        score = 0
        bd = {}

        # D1: Cross-source coverage (0-40 pts)
        cov = coverage_counts[i]
        cov_score = min(40, cov * 12)  # 1 source=12, 2=24, 3=36, 4+=40
        score += cov_score
        bd["coverage"] = cov_score

        # D2: Podcast mention (0-25 pts)
        combined = f"{art['title']} {art.get('summary', '')}".lower()
        # Phrase match (stronger signal)
        phrase_hits = sum(1 for p in podcast_phrases if p in combined)
        # Keyword match (weaker signal)
        kw_hits = sum(1 for kw in podcast_keywords if kw in combined)
        pod_score = min(25, phrase_hits * 10 + kw_hits * 3)
        score += pod_score
        bd["podcast"] = pod_score

        # D3: Recency (0-15 pts)
        pub = art.get("published")
        if pub:
            days_old = (now - pub).total_seconds() / 86400
            rec_score = max(0, int(15 - (days_old * 2)))
        else:
            rec_score = 5
        score += rec_score
        bd["recency"] = rec_score

        # D4: Source authority (0-10 pts)
        src = art["source"]
        if src in TIER_1:
            auth = 10
        elif src in TIER_2:
            auth = 7
        elif src in TIER_3:
            auth = 5
        elif src in MIDDLE_EAST_SOURCES:
            auth = 6  # Boost ME sources slightly
        else:
            auth = 3
        score += auth
        bd["authority"] = auth

        # D5: Audience relevance (0-10 pts)
        rel = _audience_relevance_score(art)
        score += rel
        bd["relevance"] = rel

        art["_score"] = score
        art["_score_breakdown"] = bd
        scored.append(art)

    # Sort by score descending
    scored.sort(key=lambda x: x["_score"], reverse=True)

    # Print top 15
    print(f"\n  Top 15 articles by weighted score:")
    print(f"  {'─'*75}")
    print(f"  {'Score':<6} {'Cov':<5} {'Pod':<5} {'Rec':<5} {'Auth':<5} {'Rel':<5} Source → Title")
    print(f"  {'─'*75}")
    for art in scored[:15]:
        bd = art["_score_breakdown"]
        title_short = art["title"][:42]
        src_short = art["source"][:14]
        print(f"  {art['_score']:<6} {bd['coverage']:<5} {bd['podcast']:<5} {bd['recency']:<5} "
              f"{bd['authority']:<5} {bd['relevance']:<5} {src_short} → {title_short}")
    print(f"  {'─'*75}")

    return scored


# =========================================================
# 4. VIRAL DETECTOR (with scoring integration)
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
    Now uses the pre-computed scores — the highest-scored article becomes the viral lead.
    If FORCED_LEAD is set, search for the best-matching article instead.
    """
    if not articles:
        return None, []

    # ── Forced lead override ──────────────────────────────────────────────────
    if FORCED_LEAD:
        print(f"\n  Forced lead active: searching for '{FORCED_LEAD}'...")
        forced_keywords = set(_tokens(FORCED_LEAD))
        if forced_keywords:
            def forced_score(art):
                title_tokens = set(_tokens(art["title"]))
                summary_tokens = set(_tokens(art.get("summary", "")))
                all_tokens = title_tokens | summary_tokens
                # Require at least 60% of forced keywords to match
                matches = sum(1 for kw in forced_keywords if kw in all_tokens)
                return matches

            candidates = sorted(articles, key=forced_score, reverse=True)
            best_score = forced_score(candidates[0])
            # Require at least 2 keyword matches OR >50% of keywords
            threshold = max(2, len(forced_keywords) * 0.5)
            if best_score >= threshold:
                print(f"  → Forced viral lead: {candidates[0]['title'][:80]}")
                return candidates[0], list(forced_keywords)
            else:
                print(f"  ✗ No strong match for '{FORCED_LEAD}' (best={best_score}, need={threshold})")
                print(f"    Falling back to auto-detect (highest scored article).")

    # Auto-detect: use the highest-scored article as viral lead
    # (articles should already be sorted by score from score_articles_v2)
    if articles and articles[0].get("_score", 0) > 0:
        viral = articles[0]
        print(f"\n  Auto-detected viral lead (score={viral['_score']}): {viral['title'][:80]}")
        return viral, []

    return None, []


# =========================================================
# 5. EDITOR (selection with source diversity enforcement)
# =========================================================
def select_articles(articles, viral_article=None):
    """
    Pick top stories for business + everyday + Middle East tracks.
    ENFORCES source diversity: max MAX_PER_SOURCE stories from any single source.
    """
    if not articles:
        return {"business": [], "everyday": [], "middle_east": []}

    # Pre-filter: exclude the viral article
    pool = [a for a in articles if a is not viral_article]

    # Pre-bucket Middle East candidates (STRICT: genuinely regional only)
    me_candidates = [a for a in pool if is_regional_story(a)]

    print(f"\n{'='*60}")
    print(f"STEP 4: SELECTING STORIES (source diversity enforced)")
    print(f"{'='*60}")
    print(f"  Pool size: {len(pool)} articles")
    print(f"  ME candidates: {len(me_candidates)}")
    print(f"  Max per source: {MAX_PER_SOURCE}")

    # Use LLM for selection but with explicit diversity instructions
    top_pool = pool[:50]  # Send top 50 scored articles
    listing = "\n".join(
        f"[{i}] {a['title']} ({a['source']}) [score={a.get('_score', 0)}] - {a['summary'][:120]}"
        for i, a in enumerate(top_pool)
    )

    # Pre-flag which of the listed articles are Middle East-relevant (for the prompt hint)
    me_links = {a['link'] for a in me_candidates}
    me_indices = [i for i, a in enumerate(top_pool) if a['link'] in me_links]
    me_indices = me_indices if me_indices else "(none detected this week)"

    prompt = f"""You are the editor of SIGNAL, a weekly AI intelligence briefing.

Pick stories for THREE tracks. Do not repeat any article across tracks.

CRITICAL RULES:
1. SOURCE DIVERSITY: You MUST NOT pick more than {MAX_PER_SOURCE} stories from the same source across ALL tracks combined. Spread picks across different sources.
2. SCORE PRIORITY: Articles are pre-ranked by relevance score. Higher-scored articles should generally be preferred, but diversity matters more.
3. DUPLICATE DETECTION: Treat two articles as the SAME story if they cover the same event. Pick only one (prefer the higher-scored version).

TRACK 1 -- "Strategic Briefing" for BUSINESS LEADERS ({TOP_BUSINESS} stories):
- Pick stories with DIRECT commercial, operational, or strategic implications.
- Every story must answer "What's in it for me as a leader?"
- PRIORITIZE: enterprise product launches, pricing changes, M&A, hiring/layoffs, regulation directly affecting business, infrastructure costs, model capability shifts.
- AVOID: pure geopolitics, defense procurement, abstract policy debates.

TRACK 2 -- "Consumer Signals" for EVERYDAY USERS ({TOP_EVERYDAY} stories):
- Consumer apps, privacy, jobs, fun creative tools, lifestyle impact.
- Must be accessible to non-technical readers.

TRACK 3 -- "From the Region" for MIDDLE EAST coverage ({TOP_MIDDLE_EAST} stories):
- AI / tech-business developments tied to UAE, Saudi Arabia, Qatar, Egypt, or the broader GCC/MENA region.
- This includes regional funding rounds, valuations, M&A, launches, hires, and partnerships (e.g., an Egyptian or Gulf fintech raising capital qualifies here).
- IMPORTANT: If a story is Middle East-related, place it in THIS track, NOT in Strategic Briefing — even if it has business implications. The region track takes priority for regional stories.
- If fewer than {TOP_MIDDLE_EAST} qualify, return fewer.

The following article indices have been pre-flagged as Middle East-relevant — strongly prefer routing these to Track 3: {me_indices}

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
        print(f"  ✗ Selection error: {e} -- falling back to score-based selection.")
        biz, eve, me = _fallback_selection(pool, me_candidates)

    # POST-SELECTION: Enforce source diversity programmatically
    # (in case the LLM ignored the instruction)
    biz, eve, me = _enforce_source_diversity(biz, eve, me, pool, me_candidates, viral_article)

    # Use genuine regional candidates if the LLM returned none — but NEVER pad with
    # non-regional stories. If there are no real regional stories, the section is left
    # empty (the renderer shows a graceful 'no regional stories this week' message).
    if not me and me_candidates:
        me = me_candidates[:TOP_MIDDLE_EAST]
    # Final safety: drop anything that isn't genuinely regional.
    me = [a for a in me if is_regional_story(a)]

    # Dedupe across tracks
    used_links = set()
    if viral_article is not None:
        used_links.add(viral_article["link"])

    def _dedupe_track(items, label=""):
        out = []
        for a in items:
            if a["link"] not in used_links:
                used_links.add(a["link"])
                out.append(a)
            else:
                print(f"  [dedupe] dropped {label}: {a['title'][:60]}")
        return out

    biz = _dedupe_track(biz, "business")
    me  = _dedupe_track(me, "middle_east")
    eve = _dedupe_track(eve, "everyday")

    # Print final selection
    print(f"\n  Final Selection:")
    print(f"  {'─'*50}")
    for label, items in [("Business", biz), ("Middle East", me), ("Consumer", eve)]:
        for a in items:
            print(f"  [{label}] {a['source']}: {a['title'][:55]}")
    print(f"  {'─'*50}")

    return {"business": biz, "everyday": eve, "middle_east": me}


def _enforce_source_diversity(biz, eve, me, pool, me_candidates, viral_article):
    """
    Programmatically enforce MAX_PER_SOURCE across all tracks.
    If a source exceeds the limit, replace the lowest-scored article from that source
    with the next-best article from a different source.
    """
    # Count source usage (including viral)
    source_count = Counter()
    if viral_article:
        source_count[viral_article["source"]] += 1

    all_selected = []
    for track_name, track_items in [("biz", biz), ("eve", eve), ("me", me)]:
        for art in track_items:
            all_selected.append((track_name, art))
            source_count[art["source"]] += 1

    # Check for violations
    violations = {src: cnt for src, cnt in source_count.items() if cnt > MAX_PER_SOURCE}
    if not violations:
        return biz, eve, me

    print(f"\n  ⚠ Source diversity violations detected: {violations}")

    # Get used links to avoid
    used_links = set(a["link"] for _, a in all_selected)
    if viral_article:
        used_links.add(viral_article["link"])

    # For each violating source, remove excess articles (lowest scored) and replace
    for src, count in violations.items():
        excess = count - MAX_PER_SOURCE
        # Find articles from this source in selection, sorted by score (lowest first)
        src_articles = [(tn, a) for tn, a in all_selected if a["source"] == src]
        src_articles.sort(key=lambda x: x[1].get("_score", 0))

        for _ in range(excess):
            if not src_articles:
                break
            track_name, to_remove = src_articles.pop(0)
            print(f"    Removing (over-represented): [{track_name}] {to_remove['title'][:50]}")

            # Remove from the appropriate track
            if track_name == "biz":
                biz = [a for a in biz if a["link"] != to_remove["link"]]
            elif track_name == "eve":
                eve = [a for a in eve if a["link"] != to_remove["link"]]
            elif track_name == "me":
                me = [a for a in me if a["link"] != to_remove["link"]]

            used_links.discard(to_remove["link"])

            # Find replacement from a different source
            replacement = None
            for candidate in pool:
                if (candidate["link"] not in used_links
                    and candidate["source"] != src
                    and source_count[candidate["source"]] < MAX_PER_SOURCE):
                    # Check if it fits the track
                    if track_name == "me":
                        if candidate in me_candidates:
                            replacement = candidate
                            break
                    else:
                        replacement = candidate
                        break

            if replacement:
                print(f"    Replacing with: [{track_name}] {replacement['source']}: {replacement['title'][:50]}")
                if track_name == "biz":
                    biz.append(replacement)
                elif track_name == "eve":
                    eve.append(replacement)
                elif track_name == "me":
                    me.append(replacement)
                used_links.add(replacement["link"])
                source_count[replacement["source"]] += 1

    return biz, eve, me


def _fallback_selection(pool, me_candidates):
    """Score-based fallback selection when LLM fails."""
    # Use pre-computed scores, enforce diversity
    source_used = Counter()
    biz, eve, me = [], [], []

    # ME first
    for a in me_candidates:
        if len(me) >= TOP_MIDDLE_EAST:
            break
        if source_used[a["source"]] < MAX_PER_SOURCE:
            me.append(a)
            source_used[a["source"]] += 1

    # Business (skip ME candidates)
    me_links = {a["link"] for a in me}
    for a in pool:
        if len(biz) >= TOP_BUSINESS:
            break
        if a["link"] not in me_links and source_used[a["source"]] < MAX_PER_SOURCE:
            biz.append(a)
            source_used[a["source"]] += 1

    # Everyday
    used_links = me_links | {a["link"] for a in biz}
    for a in pool:
        if len(eve) >= TOP_EVERYDAY:
            break
        if a["link"] not in used_links and source_used[a["source"]] < MAX_PER_SOURCE:
            eve.append(a)
            source_used[a["source"]] += 1

    return biz, eve, me


# =========================================================
# 5c. ENTITY-CLUSTER DEDUP (prevents same topic across sections)
# =========================================================
# Generic words that should NEVER count as a distinguishing entity
_ENTITY_STOPWORDS = {
    "The", "And", "For", "With", "How", "Why", "What", "New", "Now", "Its",
    "Are", "Has", "Can", "May", "Will", "Just", "Get", "Got", "Use", "All",
    "AI", "Ai", "Tech", "Data", "Model", "Models", "App", "Apps", "Inc",
    "Launches", "Launch", "Update", "Report", "Says", "Adds", "Plans",
    "Global", "Week", "This", "That", "From", "After", "Over", "Into",
}


def _primary_entities(article):
    """
    Extract the set of *significant* named entities (companies/products) from an
    article's title + first part of summary. These are what we use to detect when
    two differently-worded stories are actually about the same subject.
    """
    text = f"{article['title']} {article.get('summary', '')[:120]}"
    # Multi-word proper nouns (e.g., "Anthropic Fable", "Meta AI")
    multi = set(re.findall(r'[A-Z][a-z]+(?:\s+[A-Z][a-z0-9]+)+', text))
    # Single proper nouns (e.g., "Anthropic", "Fable", "OpenAI")
    singles = set(
        w for w in re.findall(r'\b[A-Z][a-zA-Z0-9]{2,}\b', text)
        if w not in _ENTITY_STOPWORDS
    )
    # Break multi-word entities into their component significant tokens too,
    # so "Anthropic Fable" and "Fable 5" both share the token "Fable".
    tokens = set()
    for phrase in multi:
        for part in phrase.split():
            if part not in _ENTITY_STOPWORDS and len(part) > 2:
                tokens.add(part)
    return {e.lower() for e in (multi | singles | tokens)}


def enforce_entity_dedup(viral_article, picks):
    """
    Prevent the SAME entity/subject (e.g., 'Anthropic Fable') from appearing in
    more than one place across the whole issue, even when the specific angle or
    event differs. The viral lead always wins; conflicting section stories are
    dropped and (where possible) the section is left for QA to backfill.

    Returns the cleaned picks dict and a list of human-readable drop notes.
    """
    notes = []
    claimed = set()  # entities already 'owned' by an earlier (higher-priority) story

    # Priority order: viral lead first, then business, region, consumer.
    if viral_article:
        claimed |= _primary_entities(viral_article)

    def _filter(items, label):
        nonlocal claimed
        kept = []
        for art in items:
            ents = _primary_entities(art)
            # Significant overlap = same subject as something already used
            overlap = ents & claimed
            # Require the overlap to include a 'strong' entity (len>3) to avoid
            # dropping on generic collisions.
            strong_overlap = {e for e in overlap if len(e) > 3}
            if strong_overlap:
                notes.append(
                    f"[entity-dedup] dropped {label} '{art['title'][:55]}' "
                    f"(duplicate subject: {', '.join(sorted(strong_overlap))})"
                )
                continue
            kept.append(art)
            claimed |= ents
        return kept

    picks["business"] = _filter(picks.get("business", []), "business")
    picks["middle_east"] = _filter(picks.get("middle_east", []), "middle_east")
    picks["everyday"] = _filter(picks.get("everyday", []), "consumer")

    if notes:
        print(f"\n  Entity-cluster dedup removed {len(notes)} duplicate-subject stor(ies):")
        for n in notes:
            print(f"    {n}")
    else:
        print("\n  Entity-cluster dedup: no cross-section subject duplicates found. \u2713")

    return picks, notes


def backfill_picks(picks, viral_article, scored_articles, notes):
    """
    After dedup removes stories, refill empty slots from the next-best scored
    articles that (a) are unused, (b) don't reuse a claimed entity, and
    (c) respect source diversity.
    """
    if not notes:
        return picks  # nothing was removed, nothing to backfill

    used_links = set()
    if viral_article:
        used_links.add(viral_article["link"])
    claimed = set(_primary_entities(viral_article)) if viral_article else set()
    source_count = Counter()
    if viral_article:
        source_count[viral_article["source"]] += 1
    for track in ("business", "middle_east", "everyday"):
        for a in picks.get(track, []):
            used_links.add(a["link"])
            claimed |= _primary_entities(a)
            source_count[a["source"]] += 1

    targets = {"business": TOP_BUSINESS, "middle_east": TOP_MIDDLE_EAST, "everyday": TOP_EVERYDAY}
    for track, target in targets.items():
        need = target - len(picks.get(track, []))
        if need <= 0:
            continue
        for art in scored_articles:
            if need <= 0:
                break
            if art["link"] in used_links:
                continue
            if source_count[art["source"]] >= MAX_PER_SOURCE:
                continue
            ents = _primary_entities(art)
            if {e for e in (ents & claimed) if len(e) > 3}:
                continue  # would reintroduce a duplicate subject
            # For the region track, only backfill genuinely regional stories
            if track == "middle_east":
                if not is_regional_story(art):
                    continue
            picks[track].append(art)
            used_links.add(art["link"])
            claimed |= ents
            source_count[art["source"]] += 1
            need -= 1
            print(f"    [backfill] {track}: {art['source']}: {art['title'][:50]}")
    return picks


# =========================================================
# 5d. AUTOMATED QA SELF-CHECK (runs before every publish)
# =========================================================
def run_qa_checks(viral_article, picks, tip, podcast_report):
    """
    Automated pre-publish QA. Validates the assembled issue against a checklist
    and writes qa_report.md. Returns (passed, checks) where `checks` is a list of
    (status, message) tuples. status is 'PASS', 'WARN', or 'FAIL'.
    """
    print(f"\n{'='*60}")
    print(f"STEP 6: QA SELF-CHECK (pre-publish validation)")
    print(f"{'='*60}")

    checks = []
    biz = picks.get("business", [])
    me = picks.get("middle_east", [])
    eve = picks.get("everyday", [])
    all_stories = ([viral_article] if viral_article else []) + biz + me + eve

    # 1) Viral lead exists
    if viral_article:
        checks.append(("PASS", f"Viral lead present: {viral_article['title'][:55]}"))
    else:
        checks.append(("FAIL", "No viral lead selected"))

    # 2) Sections populated
    if biz:
        checks.append(("PASS", f"Strategic Briefing has {len(biz)} stor(ies)"))
    else:
        checks.append(("FAIL", "Strategic Briefing is empty"))
    if me:
        checks.append(("PASS", f"From the Region has {len(me)} stor(ies)"))
    else:
        checks.append(("WARN", "From the Region is empty (no regional stories this week)"))
    if eve:
        checks.append(("PASS", f"Consumer Signals has {len(eve)} stor(ies)"))
    else:
        checks.append(("FAIL", "Consumer Signals is empty"))

    # 3) No duplicate links
    links = [a["link"] for a in all_stories]
    if len(links) == len(set(links)):
        checks.append(("PASS", "No duplicate article links across the issue"))
    else:
        checks.append(("FAIL", "Duplicate article link found across sections"))

    # 4) No duplicate SUBJECT/entity across sections (the Fable problem)
    seen_entities = {}
    dup_subject = []
    section_map = ([("viral", viral_article)] if viral_article else []) + \
                  [("business", a) for a in biz] + \
                  [("region", a) for a in me] + \
                  [("consumer", a) for a in eve]
    for label, art in section_map:
        for ent in {e for e in _primary_entities(art) if len(e) > 3}:
            if ent in seen_entities and seen_entities[ent] != label:
                dup_subject.append((ent, seen_entities[ent], label, art["title"][:45]))
            seen_entities.setdefault(ent, label)
    if not dup_subject:
        checks.append(("PASS", "No repeated subject/entity across sections"))
    else:
        for ent, sec1, sec2, title in dup_subject:
            checks.append(("FAIL", f"Subject '{ent}' appears in both {sec1} and {sec2} ('{title}')"))

    # 5) Source diversity (no source over MAX_PER_SOURCE, viral counted)
    src_counts = Counter(a["source"] for a in all_stories)
    overused = {s: c for s, c in src_counts.items() if c > MAX_PER_SOURCE}
    if not overused:
        checks.append(("PASS", f"Source diversity OK (max {MAX_PER_SOURCE}/source)"))
    else:
        checks.append(("WARN", f"Source(s) over limit: {overused}"))

    # 6) Regional stories correctly placed (none sitting in business track)
    misplaced = []
    for a in biz:
        if is_regional_story(a):
            misplaced.append(a["title"][:45])
    # Also flag any NON-regional story that slipped into the region track.
    nonregional_in_me = [a["title"][:45] for a in me if not is_regional_story(a)]
    if not misplaced:
        checks.append(("PASS", "No regional stories misfiled in Strategic Briefing"))
    else:
        checks.append(("WARN", f"Possible regional stor(ies) in business track: {misplaced}"))
    if nonregional_in_me:
        checks.append(("FAIL", f"Non-regional stor(ies) in 'From the Region': {nonregional_in_me}"))
    else:
        checks.append(("PASS", "All 'From the Region' stories are genuinely regional"))

    # 7) Tip not a repeat of a previously used tip
    tip_name = (tip or {}).get("title", "") if isinstance(tip, dict) else str(tip)
    tip_repeat = any(prev.lower() in tip_name.lower() or tip_name.lower() in prev.lower()
                     for prev in PREVIOUS_TIPS if tip_name)
    if tip_name and not tip_repeat:
        checks.append(("PASS", f"Tip of the Week is fresh: {tip_name}"))
    elif tip_repeat:
        checks.append(("WARN", f"Tip '{tip_name}' may repeat a previous tip"))
    else:
        checks.append(("WARN", "Could not verify Tip of the Week name"))

    # 8) Podcast ingestion happened (transparency tie-in)
    if podcast_report:
        any_tx = any(s.get("transcript_fetched") for s in podcast_report)
        any_ep = any(s.get("episodes") for s in podcast_report)
        if any_tx:
            checks.append(("PASS", "At least one podcast transcript was read this week"))
        elif any_ep:
            checks.append(("WARN", "Podcasts seen but no transcript read (titles/descriptions only)"))
        else:
            checks.append(("WARN", "No podcast episodes were ingested this week"))

    # 9) Every cited source link must be a credible NEWS ARTICLE (no podcast/audio/social).
    #    This is the credibility guard: readers must reach a verifiable article.
    bad_links = []
    for label, art in section_map:
        link = art.get("link", "")
        if not is_valid_article_link(link):
            bad_links.append((label, art.get("title", "")[:45], link))
    if not bad_links:
        checks.append(("PASS", "All source links are credible news articles (no podcast/audio links)"))
    else:
        for label, title, link in bad_links:
            checks.append(("FAIL", f"Non-article link in {label} ('{title}'): {link}"))

    # Tally
    fails = [m for s, m in checks if s == "FAIL"]
    warns = [m for s, m in checks if s == "WARN"]
    passed = len(fails) == 0

    icon = {"PASS": "\u2713", "WARN": "\u26a0", "FAIL": "\u2717"}
    for status, msg in checks:
        print(f"  {icon[status]} [{status}] {msg}")
    print(f"  {'-'*56}")
    print(f"  Result: {'PASS' if passed else 'FAIL'} "
          f"({len(fails)} fail, {len(warns)} warn, "
          f"{len(checks)-len(fails)-len(warns)} pass)")

    _write_qa_report(checks, passed)
    return passed, checks


def _write_qa_report(checks, passed):
    """Write qa_report.md — a human-readable pre-publish QA audit."""
    now = datetime.now().strftime("%B %d, %Y %H:%M")
    icon = {"PASS": "\u2705", "WARN": "\u26a0\ufe0f", "FAIL": "\u274c"}
    overall = "\u2705 PASS" if passed else "\u274c FAIL \u2014 review before sending"
    lines = [
        "# SIGNAL \u2014 Pre-Publish QA Report",
        "",
        f"**Generated:** {now}  ",
        f"**Overall result:** {overall}",
        "",
        "| Status | Check |",
        "|---|---|",
    ]
    for status, msg in checks:
        lines.append(f"| {icon[status]} {status} | {msg} |")
    lines += [
        "",
        "---",
        "",
        "This report is generated automatically by the SIGNAL agent on every run. "
        "FAIL items should be fixed before publishing; WARN items are advisory.",
        "",
    ]
    with open("qa_report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("  \u2713 Wrote qa_report.md (pre-publish QA audit)")


# =========================================================
# 6. ANALYST (structured cards per story)
# =========================================================
def analyze_article(article, audience="business"):
    """Ask the LLM for a structured, scannable card for one article."""
    print(f"  [{audience}] {article['title'][:70]}...")

    if audience == "business" or audience == "viral":
        schema_hint = """{
  "headline": "punchy 6-10 word headline (no period)",
  "tldr": "ONE crisp sentence summary, max 22 words",
  "what_happened": "18-26 words: include the specific WHO, WHAT, and a concrete NUMBER, name, or date if available, no period",
  "why_it_matters": "max 16 words, no period",
  "business_impact": "max 16 words, no period, focus on cost/revenue/competition/risk",
  "leader_action": "max 16 words, action verb first, no period -- MUST be SPECIFIC and UNIQUE to THIS story"
}"""
        rules = ("Audience: senior business leaders. No jargon. No acronyms unless universally known. "
                 "Every field must be concrete and answer 'so what for my business?' "
                 "The what_happened field MUST include specifics (a company name, dollar figure, product name, "
                 "or date) drawn from the article — never a vague summary like 'launched a new initiative'. "
                 "The leader_action field MUST be specific, varied, and tailored to THIS exact story — name the "
                 "actual tool/product to pilot, the precise metric to measure, or a concrete first step. "
                 "NEVER reuse the generic template 'Brief your [X] team' — vary the verb and the action across stories. "
                 "NEVER use generic phrases like 'Evaluate AI tools' or 'Consider implications'.")
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
Published: {article.get('published', 'recent')}

Use the specific facts in the summary above. If the summary contains numbers, names, or dates, you MUST incorporate them.
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
# 6b. TIP OF THE WEEK
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

ALREADY USED IN PREVIOUS ISSUES (do NOT repeat any of these):
{chr(10).join('- ' + t for t in PREVIOUS_TIPS)}

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
            temperature=0.85,
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
# 7. PUBLISHER -- HTML renderer
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
    --bg: #eef1f7;
    --paper: #ffffff;
    --panel: #f3f6fb;
    --line: #d9dfe9;
    --line-bright: #b6bfd0;
    --ink: #050d1f;
    --ink-2: #1a2438;
    --muted: #4a5468;
    --muted-2: #7b859a;
    --cyan: #0e7490;
    --cyan-bright: #0891b2;
    --violet: #6d28d9;
    --highlight: #fff3a3;
    --brand-navy: #0E1A2B;
    --brand-navy-2: #16243a;
    --title-band: #E8EEF7;
    --tip-bg: #FDF6E3;
    --tip-rule: #C49A2C;
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
  .subscribe-strip a.cta-mini.alt {{
    background: var(--cyan);
  }}
  .subscribe-strip a.cta-mini.alt:hover {{ background: var(--violet); }}
  .section-header {{
    display: flex; align-items: center; gap: 14px;
    padding: 28px 44px 10px; border-top: 1px solid var(--line);
  }}
  .section-header .index {{
    font-family: "JetBrains Mono", monospace;
    font-size: 10px; letter-spacing: 2.4px; color: var(--cyan);
    text-transform: uppercase; white-space: nowrap;
  }}
  .section-header h2 {{
    font-family: "Space Grotesk", sans-serif;
    font-size: 20px; font-weight: 700; margin: 0; color: var(--ink);
    letter-spacing: -0.3px;
  }}
  .section-header .rule {{
    flex: 1; height: 1px; background: var(--line);
  }}
  .card {{
    margin: 0 44px 22px; padding: 22px 26px;
    border: 1px solid var(--line); border-radius: 5px;
    background: var(--paper);
    transition: box-shadow 0.15s ease, border-color 0.15s ease;
  }}
  .card:hover {{
    border-color: var(--line-bright);
    box-shadow: 0 2px 12px rgba(14,116,144,0.08);
  }}
  .card .card-title {{
    font-family: "Space Grotesk", sans-serif;
    font-size: 17px; font-weight: 700; color: var(--ink);
    margin: 0 0 10px; line-height: 1.3; letter-spacing: -0.2px;
    padding: 4px 8px; margin-left: -8px;
    background: var(--title-band); border-radius: 3px;
    display: inline-block;
  }}
  .card .card-tldr {{
    font-size: 14px; color: var(--ink-2); margin-bottom: 14px;
    line-height: 1.5; font-weight: 400;
  }}
  .card .meta-grid {{
    display: grid; grid-template-columns: auto 1fr; gap: 4px 12px;
    font-size: 12.5px; line-height: 1.6;
  }}
  .card .meta-grid .label {{
    font-family: "JetBrains Mono", monospace;
    font-size: 9.5px; letter-spacing: 1.5px; text-transform: uppercase;
    color: var(--muted-2); padding-top: 2px;
  }}
  .card .meta-grid .value {{ color: var(--ink-2); }}
  .card .source-link {{
    display: inline-block; margin-top: 12px;
    font-family: "JetBrains Mono", monospace;
    font-size: 10px; letter-spacing: 1px; text-transform: uppercase;
    color: var(--cyan); text-decoration: none;
    border-bottom: 1px dashed var(--cyan);
    padding-bottom: 1px;
  }}
  .card .source-link:hover {{ color: var(--violet); border-color: var(--violet); }}
  /* Viral lead special styling */
  .card.viral {{
    border: 2px solid var(--brand-navy);
    background: linear-gradient(135deg, #f8faff 0%, #ffffff 100%);
    box-shadow: 0 4px 20px rgba(14,26,43,0.10);
  }}
  .card.viral .card-title {{
    font-size: 20px;
    background: var(--brand-navy); color: #ffffff;
    padding: 6px 12px; border-radius: 3px;
  }}
  /* Middle East section */
  .me-block {{
    margin: 0 44px 22px; padding: 18px 24px;
    border: 1px solid var(--line); border-radius: 5px;
    background: var(--panel);
  }}
  .me-block .me-item {{
    margin-bottom: 14px; padding-bottom: 14px;
    border-bottom: 1px solid var(--line);
  }}
  .me-block .me-item:last-child {{ margin-bottom: 0; padding-bottom: 0; border-bottom: none; }}
  .me-block .me-headline {{
    font-family: "Space Grotesk", sans-serif;
    font-size: 15px; font-weight: 600; color: var(--ink); margin: 0 0 4px;
  }}
  .me-block .me-tldr {{
    font-size: 13.5px; color: var(--ink-2); line-height: 1.5; margin: 0;
  }}
  .me-block .me-link {{
    display: inline-block; margin-top: 6px;
    font-family: "JetBrains Mono", monospace;
    font-size: 9.5px; letter-spacing: 1px; text-transform: uppercase;
    color: var(--cyan); text-decoration: none;
  }}
  /* Tip of the Week */
  .tip-block {{
    margin: 0 44px 22px; padding: 22px 26px;
    border: 1px solid var(--tip-rule); border-radius: 5px;
    background: var(--tip-bg);
    border-left: 4px solid var(--tip-rule);
  }}
  .tip-block .tip-title {{
    font-family: "Space Grotesk", sans-serif;
    font-size: 16px; font-weight: 700; color: var(--ink); margin: 0 0 8px;
  }}
  .tip-block .tip-what {{
    font-size: 14px; color: var(--ink-2); margin-bottom: 10px; line-height: 1.5;
  }}
  .tip-block .tip-try {{
    font-size: 13px; color: var(--muted); margin-bottom: 10px;
    padding: 8px 12px; background: rgba(255,255,255,0.7); border-radius: 3px;
  }}
  .tip-block .tip-try strong {{ color: var(--ink-2); }}
  .tip-block .tip-link {{
    display: inline-block;
    font-family: "JetBrains Mono", monospace;
    font-size: 10px; letter-spacing: 1px; text-transform: uppercase;
    color: var(--tip-rule); text-decoration: none;
    border-bottom: 1px dashed var(--tip-rule);
  }}
  /* CTA */
  .cta-section {{
    text-align: center; padding: 36px 44px;
    border-top: 1px solid var(--line);
    background: var(--panel);
  }}
  .cta-section .cta-text {{
    font-size: 14px; color: var(--muted); margin-bottom: 16px;
  }}
  .cta-section .button {{
    display: inline-block;
    font-family: "JetBrains Mono", monospace;
    font-size: 11px; letter-spacing: 2px; text-transform: uppercase;
    color: #ffffff; background: var(--ink);
    padding: 14px 28px; border-radius: 3px; text-decoration: none;
    transition: background 0.15s ease, transform 0.15s ease;
    margin: 4px;
  }}
  .cta-section .button:hover {{ background: var(--cyan); transform: translateY(-1px); }}
  .cta-section .button.alt {{
    background: var(--cyan);
  }}
  .cta-section .button.alt:hover {{ background: var(--violet); }}
  /* Footer */
  .footer {{
    padding: 24px 44px; text-align: center;
    font-size: 11px; color: var(--muted-2);
    border-top: 1px solid var(--line);
  }}
  .footer a {{ color: var(--cyan); text-decoration: none; }}
  @media (max-width: 600px) {{
    body {{ padding: 16px 4px; }}
    .masthead, .subscribe-strip, .section-header, .card, .me-block, .tip-block, .cta-section, .footer {{
      padding-left: 20px; padding-right: 20px;
    }}
    .card {{ margin-left: 12px; margin-right: 12px; }}
    .me-block {{ margin-left: 12px; margin-right: 12px; }}
    .tip-block {{ margin-left: 12px; margin-right: 12px; }}
    .masthead h1 {{ font-size: 38px; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <div class="masthead">
    <div class="masthead-top">
      <span><span class="dot"></span>Issue #{issue_number}</span>
      <span>{date}</span>
    </div>
    <h1>SIGN<span class="accent">A</span>L</h1>
    <p class="tagline">Your weekly AI intelligence briefing — the stories that matter,<br>in five minutes flat.</p>
    <p class="promise">Curated for leaders &amp; curious minds · Every Monday · Dubai 08:00 GST</p>
  </div>
  <div class="subscribe-strip">
    <div class="copy"><strong>Never miss an issue.</strong> Join SIGNAL — free, every Monday.</div>
    <a class="cta-mini" href="{signup_url}" target="_blank" rel="noopener">Subscribe on LinkedIn</a>
    {beehiiv_strip_btn}
  </div>
  {viral_block}
  <div class="section-header">
    <span class="index">02 //</span>
    <h2>Strategic Briefing</h2>
    <span class="rule"></span>
  </div>
  {business_cards}
  <div class="section-header">
    <span class="index">03 //</span>
    <h2>From the Region</h2>
    <span class="rule"></span>
  </div>
  {middle_east_block}
  <div class="section-header">
    <span class="index">04 //</span>
    <h2>Consumer Signals</h2>
    <span class="rule"></span>
  </div>
  {everyday_cards}
  {tip_block}
  <div class="cta-section">
    <p class="cta-text">Enjoyed this issue? Share SIGNAL with a colleague who wants to stay sharp on AI.</p>
    <a class="button" href="{signup_url}" target="_blank" rel="noopener">Subscribe on LinkedIn</a>
    {beehiiv_main_btn}
  </div>
  <div class="footer">
    SIGNAL is composed each week by an autonomous AI agent. Reviewed and published by Hasan.<br>
    <em>Represents my own views and not that of my employer.</em><br><br>
    <a href="{signup_url}">LinkedIn Newsletter</a>
  </div>
</div>
</body>
</html>"""


def render_viral_block(article, data):
    """Render the viral lead card."""
    if not data:
        return ""
    return f"""
    <div class="card viral">
      <div class="card-title">{data.get('headline', article['title'])}</div>
      <div class="card-tldr">{data.get('tldr', '')}</div>
      <div class="meta-grid">
        <span class="label">What happened</span><span class="value">{data.get('what_happened', '')}</span>
        <span class="label">Why it matters</span><span class="value">{data.get('why_it_matters', '')}</span>
        <span class="label">Business impact</span><span class="value">{data.get('business_impact', '')}</span>
        <span class="label">Leader action</span><span class="value">{data.get('leader_action', '')}</span>
      </div>
      <a class="source-link" href="{article['link']}" target="_blank" rel="noopener">Read full story → {article['source']}</a>
    </div>"""


def render_business_card(article, data):
    """Render a business card."""
    if not data:
        return ""
    return f"""
    <div class="card">
      <div class="card-title">{data.get('headline', article['title'])}</div>
      <div class="card-tldr">{data.get('tldr', '')}</div>
      <div class="meta-grid">
        <span class="label">What happened</span><span class="value">{data.get('what_happened', '')}</span>
        <span class="label">Why it matters</span><span class="value">{data.get('why_it_matters', '')}</span>
        <span class="label">Business impact</span><span class="value">{data.get('business_impact', '')}</span>
        <span class="label">Leader action</span><span class="value">{data.get('leader_action', '')}</span>
      </div>
      <a class="source-link" href="{article['link']}" target="_blank" rel="noopener">Read full story → {article['source']}</a>
    </div>"""


def render_everyday_card(article, data):
    """Render an everyday/consumer card."""
    if not data:
        return ""
    return f"""
    <div class="card">
      <div class="card-title">{data.get('headline', article['title'])}</div>
      <div class="card-tldr">{data.get('tldr', '')}</div>
      <div class="meta-grid">
        <span class="label">In plain English</span><span class="value">{data.get('in_plain_english', '')}</span>
        <span class="label">Why you care</span><span class="value">{data.get('why_you_care', '')}</span>
        <span class="label">What to do</span><span class="value">{data.get('what_to_do', '')}</span>
      </div>
      <a class="source-link" href="{article['link']}" target="_blank" rel="noopener">Read full story → {article['source']}</a>
    </div>"""


def render_middle_east_block(me_items):
    """Render the Middle East section."""
    if not me_items:
        return '<div class="me-block"><p style="color:var(--muted);font-size:13px;">No major Middle East AI stories this week.</p></div>'
    items_html = ""
    for art, data in me_items:
        if not data:
            continue
        items_html += f"""
        <div class="me-item">
          <p class="me-headline">{data.get('headline', art['title'])}</p>
          <p class="me-tldr">{data.get('tldr', '')}</p>
          <a class="me-link" href="{art['link']}" target="_blank" rel="noopener">Read more → {art['source']}</a>
        </div>"""
    return f'<div class="me-block">{items_html}</div>'


def render_tip_block(tip):
    """Render the Tip of the Week block."""
    if not tip:
        return ""
    return f"""
    <div class="section-header">
      <span class="index">05 //</span>
      <h2>Tip of the Week</h2>
      <span class="rule"></span>
    </div>
    <div class="tip-block">
      <div class="tip-title">{tip.get('title', 'AI Tip')}</div>
      <div class="tip-what">{tip.get('what', '')}</div>
      <div class="tip-try"><strong>Try this:</strong> {tip.get('try_this', '')}</div>
      <a class="tip-link" href="{tip.get('link_url', '#')}" target="_blank" rel="noopener">{tip.get('link_label', 'Explore')}</a>
    </div>"""


# =========================================================
# 8. LINKEDIN EXPORT
# =========================================================
def export_linkedin_post(date_str, issue_number, viral_pair, biz_pairs, eve_pairs, me_items, tip):
    """Write a LinkedIn-formatted Markdown version of the newsletter."""
    print("\n  Exporting LinkedIn post...")
    lines = []
    lines.append(f"# SIGNAL // Issue #{issue_number}")
    lines.append(f"**{date_str}**")
    lines.append("")
    lines.append("_Your weekly AI intelligence briefing — the stories that matter, in five minutes flat._")
    lines.append("")
    # Canonical link to THIS issue, surfaced at the very top (above the fold).
    issue_url = f"{PAGES_BASE_URL}/newsletters/newsletter_{datetime.now().strftime('%Y_%m_%d')}.html"
    lines.append(f"📩 Read Issue #{issue_number} in full: {issue_url}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Viral lead
    if viral_pair:
        art, data = viral_pair
        lines.append("## 01 // THE VIRAL LEAD")
        lines.append("")
        lines.append(f"### {data.get('headline', art['title'])}")
        lines.append("")
        lines.append(f"**TL;DR:** {data.get('tldr', '')}")
        lines.append("")
        lines.append(f"- **What happened:** {data.get('what_happened', '')}")
        lines.append(f"- **Why it matters:** {data.get('why_it_matters', '')}")
        lines.append(f"- **Business impact:** {data.get('business_impact', '')}")
        lines.append(f"- **Leader action:** {data.get('leader_action', '')}")
        lines.append("")
        lines.append(f"[Read full story → {art['source']}]({art['link']})")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Business
    lines.append("## 02 // STRATEGIC BRIEFING")
    lines.append("")
    for art, data in biz_pairs:
        lines.append(f"### {data.get('headline', art['title'])}")
        lines.append("")
        lines.append(f"**TL;DR:** {data.get('tldr', '')}")
        lines.append("")
        lines.append(f"- **What happened:** {data.get('what_happened', '')}")
        lines.append(f"- **Why it matters:** {data.get('why_it_matters', '')}")
        lines.append(f"- **Business impact:** {data.get('business_impact', '')}")
        lines.append(f"- **Leader action:** {data.get('leader_action', '')}")
        lines.append("")
        lines.append(f"[Read full story → {art['source']}]({art['link']})")
        lines.append("")
    lines.append("---")
    lines.append("")

    # Middle East
    lines.append("## 03 // FROM THE REGION")
    lines.append("")
    for art, data in me_items:
        lines.append(f"**{data.get('headline', art['title'])}**")
        lines.append(f"{data.get('tldr', '')}")
        lines.append(f"[Read more → {art['source']}]({art['link']})")
        lines.append("")
    lines.append("---")
    lines.append("")

    # Consumer
    lines.append("## 04 // CONSUMER SIGNALS")
    lines.append("")
    for art, data in eve_pairs:
        lines.append(f"### {data.get('headline', art['title'])}")
        lines.append("")
        lines.append(f"**TL;DR:** {data.get('tldr', '')}")
        lines.append("")
        lines.append(f"- **In plain English:** {data.get('in_plain_english', '')}")
        lines.append(f"- **Why you care:** {data.get('why_you_care', '')}")
        lines.append(f"- **What to do:** {data.get('what_to_do', '')}")
        lines.append("")
        lines.append(f"[Read full story → {art['source']}]({art['link']})")
        lines.append("")
    lines.append("---")
    lines.append("")

    # Tip
    if tip:
        lines.append("## 05 // TIP OF THE WEEK")
        lines.append("")
        lines.append(f"**{tip.get('title', '')}**")
        lines.append("")
        lines.append(tip.get('what', ''))
        lines.append("")
        lines.append(f"**Try this:** {tip.get('try_this', '')}")
        lines.append("")
        lines.append(f"[{tip.get('link_label', 'Explore')}]({tip.get('link_url', '#')})")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Footer
    next_issue = f"{int(issue_number) + 1:03d}"
    lines.append(f"Issue #{next_issue} lands next Monday at 08:00 GST.")
    lines.append("")
    lines.append(f"📂 Full archive: {PAGES_BASE_URL}/")
    if SIGNUP_URL:
        lines.append(f"🔔 Subscribe on LinkedIn: {SIGNUP_URL}")
    if BEEHIIV_URL:
        lines.append(f"✉️ Prefer email? Subscribe at {BEEHIIV_URL}")
    lines.append("")
    lines.append("— SIGNAL is composed each week by an autonomous AI agent. Reviewed and published by Hasan.")
    lines.append("")
    lines.append("_Represents my own views and not that of my employer._")

    fname = f"linkedin_post_{datetime.now().strftime('%Y_%m_%d')}.md"
    with open(fname, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  LinkedIn post written -> {fname}")
    return fname


# =========================================================
# MAIN
# =========================================================
def generate_newsletter():
    print("=" * 60)
    print("  SIGNAL Agent v6 — Starting...")
    print("=" * 60)
    print(f"  Mode: {'EDITOR-IN-CHIEF (interactive)' if INTERACTIVE_MODE else 'AUTONOMOUS'}")
    print(f"  Model: {MODEL}")
    print(f"  Sources: {len(SOURCES)}")
    print(f"  Max per source: {MAX_PER_SOURCE}")
    print(f"  Forced lead: {FORCED_LEAD or 'None (auto-detect)'}")
    print()

    # 1) Fetch articles from RSS feeds
    articles = fetch_recent_news()
    if not articles:
        print("No articles found. Exiting.")
        return

    # 2) Extract podcast topics (importance signals)
    podcast_topics, podcast_report = fetch_podcast_topics()

    # 3) Score all articles with weighted relevance
    scored_articles = score_articles_v2(articles, podcast_topics)

    # 4) Detect viral lead (uses scores)
    viral, _ = detect_viral_story(scored_articles)

    # 5) Pick stories for the three tracks (with source diversity)
    picks = select_articles(scored_articles, viral_article=viral)

    # 5c) Entity-cluster dedup — stop the same subject appearing in two sections
    #     (e.g. the Issue #006 'Anthropic Fable' viral-lead + consumer-signal bug)
    picks, dedup_notes = enforce_entity_dedup(viral, picks)

    # 5d) Backfill any slots emptied by dedup with the next-best unique stories
    picks = backfill_picks(picks, viral, scored_articles, dedup_notes)

    # 5b) EDITOR-IN-CHIEF MODE
    if INTERACTIVE_MODE:
        # Simple interactive mode — show picks and ask for confirmation
        print("\n\n=== EDITOR REVIEW ===")
        print("Viral:", viral["title"] if viral else "None")
        print("Business:", [a["title"][:50] for a in picks["business"]])
        print("ME:", [a["title"][:50] for a in picks["middle_east"]])
        print("Consumer:", [a["title"][:50] for a in picks["everyday"]])
        confirm = input("\nProceed? (y/n): ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    today = datetime.now().strftime("%B %d, %Y")

    # 5e) Tip of the Week (generated early so QA can verify it isn't a repeat)
    tip = generate_tip_of_week()

    # 5f) Automated pre-publish QA self-check (writes qa_report.md)
    qa_passed, qa_checks = run_qa_checks(viral, picks, tip, podcast_report)
    if not qa_passed:
        print("\n  ⚠ QA reported FAIL item(s) — see qa_report.md. "
              "Continuing to render so the operator can review before publishing.")

    # 6) Analyze viral story
    viral_html = ""
    viral_data = {}
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

    # 7) Business cards
    print("\nWriting business cards...")
    biz_html = "".join(
        render_business_card(art, analyze_article(art, "business"))
        for art in picks["business"]
    )

    # 8) Middle East cards
    print("\nWriting Middle East section...")
    me_items = [(art, analyze_article(art, "middle_east")) for art in picks["middle_east"]]
    me_html = render_middle_east_block(me_items)

    # 9) Everyday cards
    print("\nWriting everyday cards...")
    eve_html = "".join(
        render_everyday_card(art, analyze_article(art, "everyday"))
        for art in picks["everyday"]
    )

    # 10) Tip of the Week (already generated above for QA)
    tip_html = render_tip_block(tip)

    # Compute issue number (date-based) unless an explicit override is set.
    if FORCED_ISSUE is not None:
        issue_number = int(FORCED_ISSUE)
        print(f"  Issue number FORCED to #{issue_number:03d}")
    else:
        ISSUE_001_DATE = datetime(2026, 5, 10)
        delta_days = (datetime.now() - ISSUE_001_DATE).days
        issue_number = max(1, ((delta_days + 3) // 7) + 1)
    issue_number_str = f"{issue_number:03d}"

    # Build Beehiiv buttons
    if BEEHIIV_URL:
        beehiiv_strip_btn = (
            f'<a class="cta-mini alt" href="{BEEHIIV_URL}" '
            f'target="_blank" rel="noopener">Subscribe by email</a>'
        )
        beehiiv_main_btn = (
            f'<a class="button alt" href="{BEEHIIV_URL}" '
            f'target="_blank" rel="noopener">Subscribe by email</a>'
        )
    else:
        beehiiv_strip_btn = ""
        beehiiv_main_btn = ""

    html = HTML_TEMPLATE.format(
        date=today,
        issue_number=issue_number_str,
        business_cards=biz_html,
        everyday_cards=eve_html,
        middle_east_block=me_html,
        viral_block=viral_html,
        tip_block=tip_html,
        signup_url=SIGNUP_URL,
        beehiiv_strip_btn=beehiiv_strip_btn,
        beehiiv_main_btn=beehiiv_main_btn,
    )

    fname = f"newsletter_{datetime.now().strftime('%Y_%m_%d')}.html"
    with open(fname, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n{'='*60}")
    print(f"  SUCCESS! Saved {fname}")
    print(f"{'='*60}")

    # 11) LinkedIn export
    if EXPORT_LINKEDIN:
        viral_pair = (viral, viral_data) if viral else None
        biz_pairs = [(art, analyze_article(art, "business")) for art in picks["business"]]
        eve_pairs = [(art, analyze_article(art, "everyday")) for art in picks["everyday"]]
        export_linkedin_post(today, issue_number_str, viral_pair, biz_pairs, eve_pairs, me_items, tip)


if __name__ == "__main__":
    generate_newsletter()
