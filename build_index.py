#!/usr/bin/env python3
"""Rebuild the SIGNAL archive index.html by scanning newsletters/newsletter_*.html.

v10: the CI workflow referenced this file but it never existed. Run after a
--publish run (the workflow does this automatically on the publish path):

    python3 build_index.py

Scans newsletters/newsletter_YYYY_MM_DD.html, newest first, and writes
index.html — a simple dark-themed archive grid matching the SIGNAL brand.
Does NOT commit or push; the workflow does that after review.
"""
import glob
import html
import os
import re
from datetime import datetime

NEWSLETTERS_DIR = "newsletters"
INDEX_FILE = "index.html"


def _issue_number_from_date(datestr):
    """Mirror the agent's date-based issue numbering: issue #001 = week of 2026-05-10."""
    try:
        issue_001 = datetime(2026, 5, 10)
        d = datetime.strptime(datestr, "%Y_%m_%d")
        return max(1, ((d - issue_001).days + 3) // 7 + 1)
    except ValueError:
        return None


def _pretty_date(datestr):
    try:
        return datetime.strptime(datestr, "%Y_%m_%d").strftime("%B %d, %Y")
    except ValueError:
        return datestr


def build_index():
    pattern = os.path.join(NEWSLETTERS_DIR, "newsletter_*.html")
    files = sorted(glob.glob(pattern), reverse=True)
    cards = []
    for path in files:
        m = re.search(r"newsletter_(\d{4}_\d{2}_\d{2})\.html$", path)
        if not m:
            continue
        datestr = m.group(1)
        num = _issue_number_from_date(datestr)
        label = f"#{num:03d}" if num else datestr
        cards.append(
            f'    <a class="issue" href="{html.escape(path)}">'
            f'<span class="issue-num">SIGNAL {label}</span>'
            f'<span class="issue-date">{html.escape(_pretty_date(datestr))}</span></a>'
        )
    cards_html = "\n".join(cards) if cards else '    <p class="empty">No issues yet.</p>'

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SIGNAL — AI Intelligence Briefing Archive</title>
<style>
  body {{ background:#0a0e1a; color:#e8eaf0; font-family:-apple-system,'Segoe UI',Roboto,sans-serif;
         margin:0; padding:48px 20px; }}
  .wrap {{ max-width:760px; margin:0 auto; }}
  h1 {{ font-size:34px; margin:0 0 6px; }} h1 .accent {{ color:#00D4FF; }}
  .sub {{ color:#9aa3b2; margin:0 0 28px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:14px; }}
  .issue {{ display:block; background:#11172a; border:1px solid #1e2a45; border-radius:12px;
            padding:18px; text-decoration:none; color:inherit; transition:border-color .15s; }}
  .issue:hover {{ border-color:#00D4FF; }}
  .issue-num {{ display:block; font-weight:700; font-size:16px; }}
  .issue-date {{ display:block; color:#9aa3b2; font-size:13px; margin-top:4px; }}
  .empty {{ color:#9aa3b2; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>SIGN<span class="accent">A</span>L</h1>
  <p class="sub">Weekly AI intelligence briefing — the archive.</p>
  <div class="grid">
{cards_html}
  </div>
</div>
</body>
</html>
"""
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Rebuilt {INDEX_FILE} with {len(cards)} issue(s).")


if __name__ == "__main__":
    build_index()
