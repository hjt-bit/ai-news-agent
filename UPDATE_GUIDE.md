# Updating SIGNAL to v2.3 — Step-by-Step

Total time: about **10 minutes**, no terminal required.

## What's in v2.3 (so you know what you're shipping)

- **Editor-in-Chief Mode** — when you run the agent locally on your Mac, it now pauses and lets you review/swap stories before publishing. Auto-disabled on GitHub Actions so the Monday auto-run still works.
- **LinkedIn export** — every run now also writes a `linkedin_post_YYYY_MM_DD.md` you can paste straight into a LinkedIn Newsletter article.
- **Polished design** — uniform navy blocks on every story title, and a sharper Tip of the Week with a real working link.
- **LinkedIn assets** — `linkedin_banner.png` for your profile background, plus `LINKEDIN_NEWSLETTER.md` setup guide.

---

## Step 1 — Open the new files

1. Unzip `ai-news-agent.zip` somewhere convenient (Desktop is fine).
2. Inside the unzipped folder you should see these *new or updated* files you'll be uploading:

   | File | What it is |
   |---|---|
   | `agent.py` | The updated agent (new mode + LinkedIn export) |
   | `LINKEDIN_NEWSLETTER.md` | LinkedIn Newsletter setup guide |
   | `UPDATE_GUIDE.md` | This file (optional but useful in the repo) |
   | `linkedin_banner.png` | The banner for your LinkedIn profile |
   | `example_newsletter.html` | Updated visual reference |
   | `example_preview.png` | Updated screenshot |
   | `example_linkedin_post.md` | Sample LinkedIn export |

## Step 2 — Replace `agent.py` on GitHub

1. Open https://github.com/hjt-bit/ai-news-agent in your browser.
2. Click the **`agent.py`** file in the file list.
3. Click the **pencil icon** (top-right of the file viewer) to edit.
4. On your Mac, open the new `agent.py` (from the unzipped folder) in **TextEdit**:
   - Right-click the file -> Open With -> TextEdit
   - If TextEdit shows it as rich text, switch to plain text: *Format -> Make Plain Text*
5. Press **Cmd+A** to select everything, then **Cmd+C** to copy.
6. Back on GitHub, click anywhere in the editor, press **Cmd+A** to select GitHub's existing code, then **Cmd+V** to paste.
7. Scroll to the bottom -> commit message: `v2.3: Editor-in-Chief mode, LinkedIn export, polished design`
8. Make sure **"Commit directly to the main branch"** is selected.
9. Click the green **"Commit changes"** button.

## Step 3 — Add `LINKEDIN_NEWSLETTER.md` to the repo

1. On the main repo page, click **"Add file"** -> **"Create new file"**.
2. In the filename box at the top, type: `LINKEDIN_NEWSLETTER.md`
3. Open the new `LINKEDIN_NEWSLETTER.md` from the zip in TextEdit.
4. Cmd+A -> Cmd+C, then paste into GitHub's editor.
5. Scroll down -> commit message: `Add LinkedIn Newsletter setup guide`
6. Click **"Commit changes"**.

(Optional: repeat the same steps for `UPDATE_GUIDE.md` if you want this guide saved in the repo.)

## Step 4 — Replace the example files (optional but recommended)

These are the visual references in your repo. Updating them keeps the README tidy.

For each of these files in turn (`example_newsletter.html`, `example_preview.png`, `example_linkedin_post.md`):

1. Click the file in GitHub.
2. Click the **trash icon** to delete it -> commit.
3. Back on the repo page, click **"Add file"** -> **"Upload files"**.
4. Drag the new file from your unzipped folder into the upload area.
5. Commit.

(Yes, GitHub will let you "upload" to overwrite directly too — drag the file in, it auto-replaces. Either path works.)

## Step 5 — Trigger the workflow to test

1. In your repo, click the **"Actions"** tab (top of the repo, between *Pull requests* and *Projects*).
2. In the left sidebar, click **"Weekly AI Newsletter"**.
3. On the right side, click **"Run workflow"** -> the dropdown -> the green **"Run workflow"** button.
4. Wait about 60–90 seconds. Refresh the page. You should see a new run with a green checkmark.
5. Click into the run to see the agent's log. You should see lines like:
   ```
   Mode: AUTONOMOUS (no prompts)
   Found 70+ recent articles.
   Tip: <some tip> -> <some URL>
   Success! Saved newsletter_YYYY_MM_DD.html
   LinkedIn post written -> linkedin_post_YYYY_MM_DD.md
   ```
6. Go back to the main repo page -> open the **`newsletters/`** folder. You should see two new files dated today: the `.html` newsletter and the `.md` LinkedIn post.

## Step 6 — Upload the LinkedIn banner

1. Go to your LinkedIn profile.
2. Click the **camera icon** on your background banner (top-right corner of the banner area).
3. Choose **"Change photo"** -> upload `linkedin_banner.png` from the unzipped folder.
4. LinkedIn will let you reposition. Center it. Click **Apply**.

## Step 7 — Set up your LinkedIn Newsletter (when you're ready to launch)

Open `LINKEDIN_NEWSLETTER.md` from the unzipped folder. It's the full step-by-step (about 10 minutes).

**Quick version:** Click "Write article" on LinkedIn -> "Manage" -> "Create a newsletter" -> use the name/tagline/description in the guide -> publish your first issue using the `linkedin_post_YYYY_MM_DD.md` file the agent wrote on the most recent run.

## Step 8 — Try Editor-in-Chief Mode locally (when you have time, optional)

This only matters when you want to override the agent's picks for a given week.

```bash
cd path/to/ai-news-agent
python3 agent.py
```

The agent will pause and show you the proposed lineup with commands like `swap B2 P3`, `drop C1`, `reason V`, and `ok`. Type your edits, then `ok` to publish.

---

## Troubleshooting

**The Actions run failed in red.** Click the run -> click the failing step. Most common cause: an RSS feed timeout. Just re-run the workflow — it usually works the second time.

**No `linkedin_post.md` was created.** Make sure you fully replaced `agent.py` with the new version (line 50 should say `EXPORT_LINKEDIN = True`).

**The agent prints `Mode: EDITOR-IN-CHIEF` on GitHub Actions.** Open `agent.py` -> find the `INTERACTIVE_MODE` block near the top -> the auto-detection should already handle this (`sys.stdin.isatty()` returns False on Actions). If for some reason it doesn't, add `INTERACTIVE_MODE = False` as a hard override on a new line right after the block.

**My banner looks different on mobile.** LinkedIn aggressively crops banners on phones. The `SIGNAL.` wordmark and main tagline are positioned in the safe zone. The waveform and Subscribe pill may get cropped on phones — that's expected.
Add UPDATE_GUIDE.md for v2.3 deployment steps
