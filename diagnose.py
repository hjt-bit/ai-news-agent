"""
Diagnostic script.
Run with: python3 diagnose.py
Tells you which feeds work and what dates the articles have.
"""
import feedparser
from datetime import datetime, timedelta
from time import mktime

SOURCES = {
    "MIT Tech Review": "https://www.technologyreview.com/feed/",
    "OpenAI Blog": "https://openai.com/blog/rss.xml",
    "AI News": "https://www.artificialintelligence-news.com/feed/",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/",
    "The Verge AI": "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "Wired AI": "https://www.wired.com/feed/tag/ai/latest/rss",
}

print(f"Your computer's current time: {datetime.now()}\n")

for name, url in SOURCES.items():
    print(f"--- {name} ---")
    try:
        feed = feedparser.parse(url)
        print(f"  Total entries returned: {len(feed.entries)}")
        if not feed.entries:
            print(f"  (no entries - feed might be blocked or down)")
            print(f"  bozo flag: {feed.bozo}, exception: {feed.get('bozo_exception', 'none')}")
            continue
        # Show the 3 most recent entries with their parsed dates
        for entry in feed.entries[:3]:
            title = entry.get("title", "?")[:60]
            pub_raw = entry.get("published", "MISSING")
            pub_parsed = entry.get("published_parsed")
            if pub_parsed:
                dt = datetime.fromtimestamp(mktime(pub_parsed))
                age_days = (datetime.now() - dt).days
                print(f"  [{age_days}d ago] {title}  (raw: {pub_raw})")
            else:
                print(f"  [no date!] {title}  (raw: {pub_raw})")
    except Exception as e:
        print(f"  ERROR: {e}")
    print()
