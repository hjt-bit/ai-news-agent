# Publishing SIGNAL on LinkedIn

This guide adds a second distribution channel: **LinkedIn Newsletters**. Readers can subscribe right from your LinkedIn profile and get notified every time you publish.

You'll keep doing both:

- **GitHub Actions** -> auto-runs every Monday and produces the styled HTML newsletter (your archive / portfolio).
- **LinkedIn Newsletter** -> you paste the auto-generated Markdown into LinkedIn and click Publish (about 5 minutes per week, builds your audience).

---

## One-time setup (10 minutes)

### 1. Enable LinkedIn Newsletters on your profile

1. On LinkedIn, click **Write article** (top of your feed, near the post box).
2. In the article editor, look for **Manage** -> **Create a newsletter**.
3. Fill it in with the SIGNAL identity below.

### 2. Copy this newsletter identity

| Field | Use this |
|---|---|
| **Newsletter name** | `SIGNAL` |
| **Subtitle / tagline** | `An AI newsletter every Monday summarising the top news in AI.` |
| **Description** | `Curated AI intelligence for leaders and everyday users. Built and delivered by an autonomous agent. One email a week. No noise.` |
| **Cadence** | Weekly |
| **Logo** | Use a square crop of `linkedin_banner.png` (or generate a 300x300 logo with the SIGNAL wordmark on the navy background) |
| **Cover image** | Use `linkedin_banner.png` directly |

### 3. Update your LinkedIn profile

- **Banner**: upload `linkedin_banner.png` to your profile background. The Subscribe call-out on the banner now points people directly to the newsletter on your profile.
- **Headline**: add a line at the end like `| Author of SIGNAL: AI news every Monday`.
- **Featured section**: pin your first SIGNAL article so visitors see it first.

---

## The weekly publish flow (~5 minutes)

Every time the agent runs (manually on your Mac OR via GitHub Actions), it now writes **two files**:

1. `newsletter_YYYY_MM_DD.html` -- the styled HTML version (existing).
2. `linkedin_post_YYYY_MM_DD.md` -- a LinkedIn-ready Markdown version (NEW).

To publish on LinkedIn:

1. Open `linkedin_post_YYYY_MM_DD.md` (TextEdit or any text editor).
2. **Copy everything** (Cmd+A, Cmd+C).
3. On LinkedIn, click **Write article** -> select your **SIGNAL** newsletter.
4. **Paste**. LinkedIn's editor auto-converts the Markdown headings, bold, links, and bullets.
5. Add the cover image (use `linkedin_banner.png` or a story-related image).
6. Click **Publish**. LinkedIn notifies all your subscribers.

That's it. One email a week, distributed both as a hosted HTML newsletter (GitHub Pages-ready) AND as a LinkedIn Newsletter with a built-in subscribe button.

---

## Tips that actually move the needle

- **Pin the first issue** to your profile as a Featured post for the first 30 days.
- **Reply to every commenter** in the first hour after publishing -- LinkedIn's algorithm rewards early engagement.
- **Repost a single insight** from each issue as a standalone LinkedIn post 2-3 days later, linking to the full newsletter. Doubles your reach.
- **Send a personal DM** to 5-10 contacts each week with the issue. This bootstraps your subscriber base faster than anything else.

---

## What about the GitHub-hosted version?

Both work in parallel. The GitHub Actions workflow keeps producing the HTML newsletter every Monday at 08:00 UTC. You can:

- Forward the HTML to specific people via email
- Host it on GitHub Pages (one click in repo Settings -> Pages)
- Link to it from your LinkedIn newsletter as the "rich version"

Future: when you have ~100 subscribers and want a real email list, swap `SIGNUP_URL` in `agent.py` from Tally to a Buttondown / Beehiiv / Substack URL. Everything else stays the same.
