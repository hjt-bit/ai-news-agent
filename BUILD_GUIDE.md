# SIGNAL — Build Guide

A single, copy-paste walkthrough that takes you from zero to a fully autonomous AI newsletter agent running on GitHub. **Estimated time: 25–30 minutes.**

This pack contains everything pre-wired:

| File | Role |
|---|---|
| `agent.py` | The agent (fetcher → editor → writer → publisher) with the new SIGNAL design |
| `requirements.txt` | Python dependencies |
| `.gitignore` | Keeps secrets and clutter out of your repo |
| `.github/workflows/weekly-newsletter.yml` | Tells GitHub to run the agent every Monday |
| `README.md` | Short repo description |
| `diagnose.py` | Troubleshooter for RSS / SSL issues |
| `example_newsletter.html` | A live sample of the SIGNAL design |
| `example_preview.png` | Visual reference |

---

## Phase 1 — Run it once locally (5 min)

This proves the new design works on your machine before we automate it.

### 1. Open Terminal and go to the project folder
```bash
cd path/to/ai-news-agent
```

### 2. Install the libraries (only needed once)
```bash
pip3 install -r requirements.txt
```

### 3. Set your OpenAI key for this terminal session
```bash
export OPENAI_API_KEY="sk-...your-real-key..."
```
*(Get one at https://platform.openai.com/api-keys if you don't have it.)*

### 4. Run the agent
```bash
python3 agent.py
```

You should see progress logs ending with `Success! Saved newsletter_YYYY_MM_DD.html`.

### 5. View the result
Double-click the new `newsletter_YYYY_MM_DD.html` file in Finder. You should see the new light SIGNAL design.

> **If you get an SSL error:** run `/Library/Frameworks/Python.framework/Versions/3.14/Resources/Install\ Certificates.command` (or your version's path).

---

## Phase 2 — Push to GitHub (10 min)

### 1. Confirm Git is set up
```bash
git --version
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

### 2. Create an empty GitHub repository
1. Sign in at https://github.com.
2. Top-right **+** → **New repository**.
3. **Name:** `ai-news-agent`
4. **Visibility:** Public (required for free unlimited GitHub Actions on personal accounts).
5. **Leave all checkboxes unchecked** (no README, no .gitignore, no license).
6. Click **Create repository**.
7. Keep the resulting page open — you'll need the URL it shows you.

### 3. Push your local code
In your terminal (still inside `ai-news-agent`):
```bash
git init
git add .
git commit -m "Initial commit: SIGNAL AI newsletter agent"
git branch -M main
git remote add origin https://github.com/YOURUSERNAME/ai-news-agent.git
git push -u origin main
```

### 4. Authenticate with a Personal Access Token
When `git push` asks for a password, use a token, not your GitHub password.

1. https://github.com/settings/tokens → **Generate new token (classic)**.
2. Name: `ai-news-agent-push`. Expiration: 90 days. Scope: tick **`repo`**.
3. Click **Generate token** and copy it.
4. Back in the terminal, paste your **GitHub username** when asked, and the **token** as the password.

You should see `* [new branch]      main -> main`. Refresh your repo on GitHub — all files should be there, including `.github/workflows/weekly-newsletter.yml`.

---

## Phase 3 — Add your API key as a GitHub secret (3 min)

This is the secure way for the cloud agent to use your key without exposing it in code.

1. On your GitHub repo page, click **Settings** (top tabs).
2. Left sidebar: **Secrets and variables → Actions**.
3. Click **New repository secret**.
4. **Name:** `OPENAI_API_KEY` *(must be exactly this — case-sensitive)*.
5. **Secret:** paste your `sk-...` key.
6. Click **Add secret**.

That's it — GitHub now stores it encrypted and only the workflow can read it.

---

## Phase 4 — Run it on GitHub for the first time (3 min)

### 1. Enable Actions
Click the **Actions** tab on your repo. If you see a banner asking to enable workflows, click **I understand my workflows, go ahead and enable them**.

### 2. Trigger a manual test run
1. In the left sidebar, click **Weekly AI Newsletter**.
2. On the right side click the **Run workflow** dropdown → green **Run workflow** button.
3. Wait ~10 seconds, then refresh — a new yellow run appears at the top.
4. Click the run to watch the live logs. After ~60–90 seconds it should turn green.

### 3. Verify the output
Go back to the **Code** tab of your repo. You should now see a new `newsletters/` folder containing `newsletter_YYYY_MM_DD.html`.

Click the file → click **Raw** → that's your live, automated newsletter. You can also share the URL of that raw file or copy its HTML into Substack/Beehiiv to email it out.

---

## Phase 5 — You're done. The agent now runs every Monday.

The schedule is set in `.github/workflows/weekly-newsletter.yml`:

```yaml
schedule:
  - cron: '0 8 * * 1'   # every Monday at 08:00 UTC
```

Common changes (edit the file in GitHub's web UI, click the pencil, save):
- `'0 13 * * 1'` → every Monday at 13:00 UTC (= 9am ET / 6am PT)
- `'0 6 * * *'` → every day at 06:00 UTC
- `'0 8 * * 1,4'` → every Monday and Thursday at 08:00 UTC

Use https://crontab.guru to design a schedule visually.

---

## Optional — wire up a real Subscribe button

The newsletter has two "Subscribe free" buttons that currently link to `#`. To make them work:

1. Get a sign-up URL from one of these free tools:
   - **Tally** (https://tally.so) — fastest. 3 minutes to a public form URL.
   - **Substack** (https://substack.com) — fastest if you also want to *email* the newsletter.
   - **Beehiiv** (https://beehiiv.com) — modern Substack alternative, 2,500 free subscribers.
2. In `agent.py`, change line near the top:
   ```python
   SIGNUP_URL = "https://tally.so/r/yourform"   # or your Substack/Beehiiv URL
   ```
3. Commit and push:
   ```bash
   git add agent.py
   git commit -m "Add real signup URL"
   git push
   ```
4. Trigger the workflow again from the Actions tab → next newsletter has working buttons.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Workflow run fails with `authentication error` | API key wrong or not added | Re-add the `OPENAI_API_KEY` secret, exact name |
| Workflow run fails with `quota exceeded` | OpenAI account has no balance | Add $5 credit at platform.openai.com → Billing |
| Workflow runs but no newsletter file appears | RSS feeds returned 0 articles | Check the run logs; may be a one-off network issue |
| Push asks for password every time | Token not saved | macOS: `git config --global credential.helper osxkeychain` |
| Can't find `.github` folder in Finder | It's hidden | `Cmd + Shift + .` to toggle hidden files in Finder |

---

## Cost expectations

Per weekly run: under $0.01 in OpenAI credits and 0 GitHub minutes (free tier on public repos is unlimited).
Per year: roughly $0.50 in OpenAI usage.

You're done. Close your laptop. The agent will deliver next Monday morning whether you're awake or not.
