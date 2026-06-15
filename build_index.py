"""
build_index.py
==============

Scans the /newsletters/ folder, extracts metadata from each newsletter HTML,
and writes a styled SIGNAL-branded `index.html` that lists every issue,
newest first.

Run automatically by the GitHub Action after agent.py commits a new newsletter.

Stand-alone -- no external dependencies beyond Python stdlib.

Usage:
    python3 build_index.py
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
NEWSLETTERS_DIR = ROOT / "newsletters"
OUTPUT_PATH = ROOT / "index.html"

# Issue #001 was published Sunday May 10, 2026.
# Subsequent issues land each Sunday/Monday window (8:00 GST Monday auto-run).
LAUNCH_DATE = datetime(2026, 5, 10, tzinfo=timezone.utc)

# Files dated before launch are pre-launch dev/tests and should NOT show on the public archive.
# These are kept in /newsletters/ for posterity but hidden from the listing.
HIDE_FROM_ARCHIVE = {
    "newsletter_2026_05_03.html",  # pre-launch test
    "newsletter_2026_05_04.html",  # pre-launch test
    "newsletter_2026_05_11.html",  # auto-rerun of Issue #001 -- canonical is May 10
}

LINKEDIN_URL = "https://www.linkedin.com/newsletters/signal-7459465103449468928/"
BEEHIIV_URL = "https://signalweekly.beehiiv.com/subscribe"
GITHUB_PAGES_BASE = "https://hjt-bit.github.io/ai-news-agent"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
DATE_FROM_FILENAME = re.compile(r"newsletter_(\d{4})_(\d{2})_(\d{2})\.html$")
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
H2_RE = re.compile(r'<h2[^>]*class="[^"]*viral[^"]*"[^>]*>(.*?)</h2>', re.IGNORECASE | re.DOTALL)
ANY_H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.IGNORECASE | re.DOTALL)
TAG_STRIP_RE = re.compile(r"<[^>]+>")


def issue_number_for(date: datetime) -> int:
    """Compute issue number from launch date.

    Issue #001 = May 10, 2026 (Sunday).
    Each subsequent issue lands ~7 days later. We use a 4-day grace window
    so that an issue published anywhere in the Sunday-Wednesday range
    of week N still maps to issue N. This handles cases where the
    Monday auto-run is supplemented by manual test runs mid-week.
    """
    if date < LAUNCH_DATE:
        return 0  # pre-launch -- caller should suppress these
    delta_days = (date - LAUNCH_DATE).days
    # Round to nearest week: days 0-3 = issue 1, 4-10 = issue 2, 11-17 = issue 3, ...
    # Using +3 shifts the bucket so dates close to the *next* Monday count
    # toward the upcoming issue rather than the previous one.
    return ((delta_days + 3) // 7) + 1


def extract_viral_headline(html: str) -> str | None:
    """Try to pull the lead/viral story headline from the HTML."""
    candidate = None

    # PRIMARY (current template): the viral lead is rendered as
    #   <div class="card viral"> ... <div class="card-title">HEADLINE</div> ...
    viral_card = re.search(
        r'<div[^>]*class="[^"]*\bviral\b[^"]*"[^>]*>(.*?)</div>\s*</div>',
        html, re.IGNORECASE | re.DOTALL,
    )
    if viral_card:
        inner = viral_card.group(1)
        card_title = re.search(
            r'<div[^>]*class="[^"]*card-title[^"]*"[^>]*>(.*?)</div>',
            inner, re.IGNORECASE | re.DOTALL,
        )
        if card_title:
            candidate = card_title.group(1)

    # Looser primary fallback: first .card-title that follows a `viral` class
    if candidate is None:
        loose = re.search(
            r'class="[^"]*\bviral\b[^"]*".*?<div[^>]*class="[^"]*card-title[^"]*"[^>]*>(.*?)</div>',
            html, re.IGNORECASE | re.DOTALL,
        )
        if loose:
            candidate = loose.group(1)

    # LEGACY template fallback: <h2 class="article-headline">
    if candidate is None:
        article_h2 = re.search(
            r'<h2[^>]*class="[^"]*article-headline[^"]*"[^>]*>(.*?)</h2>',
            html, re.IGNORECASE | re.DOTALL,
        )
        if article_h2:
            candidate = article_h2.group(1)

    # LEGACY template fallback: any h2 inside a `.viral` <section>
    if candidate is None:
        viral_block = re.search(
            r'<section[^>]*class="[^"]*viral[^"]*"[^>]*>(.*?)</section>',
            html, re.IGNORECASE | re.DOTALL,
        )
        if viral_block:
            inner = viral_block.group(1)
            inner_h2 = re.search(r"<h2[^>]*>(.*?)</h2>", inner, re.IGNORECASE | re.DOTALL)
            if inner_h2:
                candidate = inner_h2.group(1)

    if candidate is None:
        return None
    # Strip inner anchors & tags
    text = TAG_STRIP_RE.sub("", candidate).strip()
    text = re.sub(r"\s+", " ", text)
    return text or None


def extract_subtitle(html: str) -> str | None:
    """Pull the masthead subtitle (e.g., 'An AI newsletter every Monday...')."""
    m = re.search(
        r'<p[^>]*class="[^"]*subtitle[^"]*"[^>]*>(.*?)</p>',
        html, re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    text = TAG_STRIP_RE.sub("", m.group(1)).strip()
    text = re.sub(r"\s+", " ", text)
    return text or None


def scan_newsletters() -> list[dict]:
    """Return list of issue records, newest first, with pre-launch tests filtered out."""
    if not NEWSLETTERS_DIR.exists():
        return []
    issues = []
    seen_issue_numbers = set()
    candidates = []
    for path in NEWSLETTERS_DIR.iterdir():
        if not path.is_file() or path.suffix.lower() != ".html":
            continue
        if path.name in HIDE_FROM_ARCHIVE:
            continue
        m = DATE_FROM_FILENAME.match(path.name)
        if not m:
            continue
        try:
            year, month, day = (int(p) for p in m.groups())
            date = datetime(year, month, day, tzinfo=timezone.utc)
        except Exception:
            continue
        # Hide anything before launch date even if not in HIDE_FROM_ARCHIVE
        if date < LAUNCH_DATE:
            continue
        try:
            html = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            html = ""
        headline = extract_viral_headline(html)
        candidates.append({
            "filename": path.name,
            "date": date,
            "issue_number": issue_number_for(date),
            "headline": headline,
        })
    # Newest first
    candidates.sort(key=lambda x: x["date"], reverse=True)
    # Dedupe: if multiple files map to the same issue number, keep the latest one only.
    # This handles the case where a manual mid-week test run produces a duplicate of
    # the upcoming Monday's issue (or a re-run on the same Monday).
    for c in candidates:
        if c["issue_number"] in seen_issue_numbers:
            continue
        seen_issue_numbers.add(c["issue_number"])
        issues.append(c)
    return issues


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------
PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SIGNAL // Weekly AI Intelligence Briefing</title>
  <meta name="description" content="A weekly AI intelligence briefing curated for leaders and professionals. The viral story, strategic moves, MENA developments, and one practical tip -- every Monday.">
  <meta property="og:title" content="SIGNAL // Weekly AI Intelligence Briefing">
  <meta property="og:description" content="A weekly AI intelligence briefing curated for leaders. One brief a week. No noise.">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{base}/">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
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
      --brand-navy: #0E1A2B;
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
      -webkit-font-smoothing: antialiased;
    }}
    a {{ color: var(--cyan); }}
    .container {{
      max-width: 760px;
      margin: 0 auto;
      background: var(--paper);
      border: 1px solid var(--line-bright);
      border-radius: 6px;
      box-shadow: 0 30px 60px -30px rgba(5,13,31,0.18);
      overflow: hidden;
    }}
    /* Masthead */
    .masthead {{
      padding: 36px 44px 32px;
      background: linear-gradient(135deg, var(--brand-navy) 0%, #0a1428 100%);
      color: #ffffff;
      border-bottom: 3px solid var(--cyan);
    }}
    .masthead-top {{
      display: flex; justify-content: space-between; align-items: center;
      font-family: "JetBrains Mono", monospace;
      font-size: 10px; letter-spacing: 2.4px;
      color: rgba(255,255,255,0.62);
      text-transform: uppercase; margin-bottom: 22px;
    }}
    .masthead-top .dot {{
      width: 6px; height: 6px; border-radius: 50%;
      background: #00D4FF; display: inline-block; margin-right: 8px;
      vertical-align: middle;
    }}
    .masthead h1 {{
      font-family: "Space Grotesk", sans-serif;
      font-weight: 700; font-size: 54px; line-height: 1; letter-spacing: -1.8px;
      margin: 0 0 14px; color: #ffffff;
    }}
    .masthead h1 .end-dot {{ color: #00D4FF; }}
    .masthead .subtitle {{
      font-size: 15px; color: rgba(255,255,255,0.85); max-width: 480px;
      margin: 0 0 6px; line-height: 1.55;
    }}
    .masthead .meta {{
      font-family: "JetBrains Mono", monospace;
      font-size: 11px; letter-spacing: 1.6px;
      color: rgba(255,255,255,0.55);
      text-transform: uppercase;
    }}
    /* Subscribe strip */
    .subscribe-strip {{
      padding: 18px 44px;
      display: flex; flex-wrap: wrap; align-items: center; gap: 14px;
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
      background: #ffffff; color: var(--ink);
      border: 1.5px solid var(--ink);
    }}
    .subscribe-strip a.cta-mini.alt:hover {{ background: var(--ink); color: #ffffff; }}
    /* Section header (matches newsletter) */
    .section-header {{
      padding: 28px 44px 14px;
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
    /* Intro */
    .intro {{
      padding: 28px 44px 8px;
      font-size: 16px; color: var(--ink-2); line-height: 1.65;
    }}
    .intro p {{ margin: 0 0 12px; }}
    /* Archive list */
    .archive {{
      padding: 14px 44px 32px;
    }}
    .issue-card {{
      display: flex; flex-direction: column;
      padding: 22px 0;
      border-bottom: 1px solid var(--line);
      gap: 8px;
    }}
    .issue-card:last-child {{ border-bottom: none; }}
    .issue-meta {{
      display: flex; align-items: center; gap: 14px;
      font-family: "JetBrains Mono", monospace;
      font-size: 10.5px; letter-spacing: 1.8px;
      text-transform: uppercase; color: var(--muted);
    }}
    .issue-meta .num {{
      display: inline-block;
      padding: 4px 9px;
      border: 1px solid var(--ink);
      background: var(--paper);
      color: var(--ink);
      font-weight: 600;
      letter-spacing: 1.5px;
    }}
    .issue-card h3 {{
      font-family: "Space Grotesk", sans-serif;
      font-weight: 700; font-size: 22px; line-height: 1.32;
      letter-spacing: -0.3px; margin: 4px 0 0;
      color: var(--ink);
    }}
    .issue-card h3 a {{
      color: var(--ink); text-decoration: none;
      border-bottom: 2px solid transparent;
      transition: border-color 0.15s ease, color 0.15s ease;
    }}
    .issue-card h3 a:hover {{
      color: var(--cyan); border-bottom-color: var(--cyan);
    }}
    .issue-card .read-link {{
      display: inline-flex; align-items: center; gap: 8px;
      margin-top: 8px;
      font-family: "JetBrains Mono", monospace;
      font-size: 11px; font-weight: 600; letter-spacing: 1.5px;
      text-transform: uppercase;
      color: var(--cyan); text-decoration: none;
      padding-bottom: 3px; border-bottom: 1px solid var(--cyan);
      align-self: flex-start;
      transition: color 0.2s ease, border-color 0.2s ease;
    }}
    .issue-card .read-link:hover {{
      color: var(--cyan-bright); border-bottom-color: var(--cyan-bright);
    }}
    .issue-card .read-link::after {{ content: "->"; }}
    .archive-empty {{
      padding: 30px 0; color: var(--muted); font-style: italic;
      text-align: center;
    }}
    /* CTA bottom */
    .cta {{
      padding: 36px 44px 40px;
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
    .cta .cta-buttons {{
      display: inline-flex; flex-wrap: wrap; justify-content: center;
      gap: 12px; margin-top: 4px;
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
    .cta a.button.alt {{
      background: #ffffff; color: var(--ink);
      border: 1.5px solid var(--ink);
    }}
    .cta a.button.alt:hover {{ background: var(--ink); color: #ffffff; }}
    /* Colophon */
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
    .colophon p {{
      font-size: 12.5px; color: var(--muted); margin: 0; line-height: 1.55;
    }}
    /* Mobile */
    @media (max-width: 600px) {{
      body {{ padding: 16px 8px; }}
      .masthead {{ padding: 28px 22px 24px; }}
      .masthead h1 {{ font-size: 42px; }}
      .subscribe-strip {{ padding: 16px 22px; }}
      .section-header {{ padding: 24px 22px 12px; }}
      .intro, .archive {{ padding-left: 22px; padding-right: 22px; }}
      .cta {{ padding: 30px 22px 34px; }}
      .colophon {{ padding: 22px 22px 28px; }}
      .issue-card h3 {{ font-size: 19px; }}
    }}
  </style>
</head>
<body>
  <main class="container">
    <header class="masthead">
      <div class="masthead-top">
        <span><span class="dot"></span>SIGNAL // ARCHIVE</span>
        <span>{updated_label}</span>
      </div>
      <h1>SIGNAL<span class="end-dot">.</span></h1>
      <p class="subtitle">A weekly AI intelligence briefing curated for leaders and professionals. One brief a week. Five minutes. No noise.</p>
      <div class="meta">{issue_count_label} . curated by an autonomous agent</div>
    </header>

    <div class="subscribe-strip">
      <div class="copy"><strong>New here?</strong> Get SIGNAL every Monday at 08:00 GST -- on LinkedIn or by email.</div>
      <a class="cta-mini" href="{linkedin_url}">Subscribe on LinkedIn</a>
      <a class="cta-mini alt" href="{beehiiv_url}">Subscribe by email</a>
    </div>

    <div class="section-header">
      <span class="index">00 //</span>
      <h2>What This Is</h2>
      <span class="rule"></span>
    </div>
    <div class="intro">
      <p>Every Monday at 08:00 GST, SIGNAL delivers exactly what matters in AI -- in five minutes. The viral story of the week, three strategic moves for leaders, two MENA developments, three consumer signals, and one practical tip you can use the same day.</p>
      <p>Built by an autonomous agent. Reviewed and shipped each week.</p>
    </div>

    <div class="section-header">
      <span class="index">01 //</span>
      <h2>The Archive</h2>
      <span class="rule"></span>
    </div>
    <div class="archive">
{issue_cards}
    </div>

    <div class="cta">
      <span class="label">// Subscribe</span>
      <h3>Get SIGNAL every Monday.</h3>
      <p>Curated AI intelligence for leaders and professionals. One brief a week. No noise. Unsubscribe anytime.</p>
      <div class="cta-buttons">
        <a class="button" href="{linkedin_url}">Subscribe on LinkedIn</a>
        <a class="button alt" href="{beehiiv_url}">Subscribe by email</a>
      </div>
    </div>

    <footer class="colophon">
      <div class="sig">// SIGNAL // by an autonomous AI agent</div>
      <p>Curated each Monday from RSS feeds across MIT Tech Review, OpenAI, AI News, VentureBeat, TechCrunch, The Verge, Wired, The National, Wamda and Arab News.<br>Represents personal views, not those of any employer.</p>
    </footer>
  </main>
</body>
</html>
"""


def render_issue_card(issue: dict) -> str:
    date_label = issue["date"].strftime("%B %d, %Y").upper()
    issue_label = f"ISSUE #{issue['issue_number']:03d}"
    href = f"newsletters/{issue['filename']}"
    headline = issue["headline"]
    if headline:
        h3_html = f'<h3><a href="{escape(href)}">{escape(headline)}</a></h3>'
    else:
        h3_html = f'<h3><a href="{escape(href)}">Read this issue</a></h3>'
    return (
        '      <article class="issue-card">\n'
        '        <div class="issue-meta">\n'
        f'          <span class="num">{issue_label}</span>\n'
        f'          <span>{date_label}</span>\n'
        '        </div>\n'
        f'        {h3_html}\n'
        f'        <a class="read-link" href="{escape(href)}">Read the issue</a>\n'
        '      </article>'
    )


def render_index(issues: list[dict]) -> str:
    if issues:
        cards = "\n".join(render_issue_card(i) for i in issues)
    else:
        cards = '      <div class="archive-empty">First issue lands soon.</div>'
    issue_count_label = f"{len(issues)} issue{'s' if len(issues) != 1 else ''} archived"
    updated_label = "UPDATED " + datetime.now(timezone.utc).strftime("%b %d, %Y").upper()
    return PAGE_TEMPLATE.format(
        issue_cards=cards,
        issue_count_label=issue_count_label,
        updated_label=updated_label,
        linkedin_url=LINKEDIN_URL,
        beehiiv_url=BEEHIIV_URL,
        base=GITHUB_PAGES_BASE,
    )


def main() -> int:
    issues = scan_newsletters()
    if not issues:
        print("[build_index] No newsletters found in ./newsletters/. Writing empty-state index.")
    else:
        print(f"[build_index] Found {len(issues)} issue(s):")
        for i in issues:
            print(f"  - Issue #{i['issue_number']:03d} ({i['date'].date()}): "
                  f"{i['headline'] or '(no headline extracted)'}")
    html = render_index(issues)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"[build_index] Wrote {OUTPUT_PATH} ({len(html)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
