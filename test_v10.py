"""
SIGNAL Agent v10 — Test Suite
Hermetic tests for the v10 fail-closed pipeline: review gate, prompt-injection
hardening, fact-check UNVERIFIED/CONTRADICTED, HTML escaping, tip URL
validation, single-analysis, QA enforcement, take placeholder, social
derivatives, and build_index.

No live network calls: Serper/Beehiiv HTTP is monkey-patched out everywhere.
Run: python3 test_v10.py
"""

import copy
import json
import os
import re
import sys
import types
from datetime import date, datetime, timedelta

# ─── Fake OpenAI (stubbed BEFORE importing agent_v10) ─────────────────────────

class FakeMessage:
    def __init__(self, content):
        self.content = content

class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)

class FakeResponse:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]

# Optional per-test overrides for the fake LLM
RAISE_ON = None
REWRITE_OPENER_RESPONSE = "fallback opener"          # set to a prompt substring to simulate an LLM failure
REL_SCORES = {}         # article-index -> relevance score for the relevance filter

class FakeCompletions:
    def create(self, **kwargs):
        # v10: system message is FIRST, user prompt SECOND — scan all messages.
        text = " ".join(m.get("content", "") for m in kwargs.get("messages", []))
        if RAISE_ON and RAISE_ON in text:
            raise RuntimeError("simulated LLM failure")
        if "AI-relevance classifier" in text:
            return FakeResponse(json.dumps(REL_SCORES))
        elif "editorial judgment engine" in text:
            return FakeResponse('{"0": {"financial": 9, "user_impact": 8, "novelty": 9, "brand": 10, "virality": 9, "key_figures": ["$60 billion", "all-stock deal"]}, "1": {"financial": 3, "user_impact": 6, "novelty": 5, "brand": 7, "virality": 4, "key_figures": ["750 million users"]}, "2": {"financial": 6, "user_impact": 7, "novelty": 6, "brand": 8, "virality": 5, "key_figures": ["$5 billion"]}}')
        elif "editor of SIGNAL" in text:
            return FakeResponse('{"business": [0, 1, 2], "everyday": [3, 4, 5], "middle_east": []}')
        elif "tight, scannable newsletter cards" in text:
            return FakeResponse('{"headline": "Test Headline", "why_you_care": "The angle readers care about", "what_happened": "Something happened", "leader_action": "Take this action"}')
        elif "Rewrite ONLY the opener" in text:
            return FakeResponse(json.dumps({"why_you_care": REWRITE_OPENER_RESPONSE}))
        elif "NOVEL, non-obvious AI tip" in text:
            # v10 schema: title/tool_name/url/one_liner/how_to/why_now
            return FakeResponse('{"title": "Test Tip", "tool_name": "TestTool", "url": "https://example.com/tool", "one_liner": "A great tip", "how_to": "Step 1, Step 2", "why_now": "Because reasons"}')
        elif "OUTLINES" in text:
            return FakeResponse(json.dumps({
                "linkedin_post": {"hook": "hook idea", "bullets": ["b1"], "cta": "cta idea"},
                "ig_carousel_outline": {"slides": [{"headline": "s1", "visual": "v1"}]},
                "reel_script_outline": {"hook": "h", "beats": ["b1"], "cta": "c"},
            }))
        elif "TAKE SUGGESTIONS" in text:
            return FakeResponse(json.dumps({
                "suggestions": [
                    {"story": "Test Viral Story",
                     "angles": [
                         {"angle": "Suggested take one", "why_it_matters_regionally": "Regional relevance one",
                          "provocation": "Provocative question one?"},
                         {"angle": "Suggested take two", "why_it_matters_regionally": "Regional relevance two",
                          "provocation": "Provocative statement two."},
                     ]},
                ]
            }))
        else:
            return FakeResponse('{}')

class FakeChat:
    completions = FakeCompletions()

class FakeClient:
    chat = FakeChat()

fake_openai = types.ModuleType("openai")
fake_openai.OpenAI = lambda **kwargs: FakeClient()
sys.modules["openai"] = fake_openai

# Stub feedparser too (sandbox has no network installs; CI installs the real
# package from requirements.txt before running tests)
fake_feedparser = types.ModuleType("feedparser")
fake_feedparser.parse = lambda *a, **k: types.SimpleNamespace(entries=[], feed={})
sys.modules["feedparser"] = fake_feedparser

sys.path.insert(0, os.path.dirname(__file__))
try:
    import agent as agent          # repo live filename (paste target)
except ImportError:
    import agent_v10 as agent      # standalone zip filename

# ─── Test utilities ──────────────────────────────────────────────────────────
passed = 0
failed = 0

def check(condition, label):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}")

def reset_flags():
    for key, val in agent.RUN_FLAGS.items():
        if isinstance(val, bool):
            agent.RUN_FLAGS[key] = False
        elif isinstance(val, int):
            agent.RUN_FLAGS[key] = 0
        else:
            agent.RUN_FLAGS[key] = []

def banner(title):
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)

def mk_article(title, link, source="TestSource", summary="A test summary."):
    return {"title": title, "link": link, "source": source, "summary": summary,
            "published": None, "_score": 70, "_ai_relevance": 8,
            "_magnitude_score": 7.5, "_key_figures": ["$1B"]}

def passing_fixture(confidence="HIGH"):
    """A minimal issue that should pass QA cleanly."""
    viral = mk_article("OpenAI launches new reasoning model", "https://techcrunch.com/ai-model")
    viral["_magnitude_score"] = 9.0
    viral["_fact_check"] = {"confidence": confidence, "claim_searched": "x",
                            "corroborating_sources": ["a", "b", "c"], "contradicting_sources": []}
    biz = [mk_article("Anthropic raises funding round", "https://venturebeat.com/anthropic-funding")]
    biz[0]["_magnitude_score"] = 7.5
    biz[0]["_fact_check"] = {"confidence": "MEDIUM", "claim_searched": "x",
                             "corroborating_sources": ["a"], "contradicting_sources": []}
    eve = [mk_article("New AI gadget for consumers", "https://theverge.com/ai-gadget")]
    eve[0]["_fact_check"] = {"confidence": "MEDIUM", "claim_searched": "x",
                             "corroborating_sources": ["a"], "contradicting_sources": []}
    me = [mk_article("Saudi fund backs AI datacenter", "https://arabnews.com/saudi-ai",
                     source="Arab News")]
    me[0]["_fact_check"] = {"confidence": "MEDIUM", "claim_searched": "x",
                            "corroborating_sources": ["a"], "contradicting_sources": []}
    picks = {"business": biz, "everyday": eve, "middle_east": me}
    tip = {"title": "Prompt chaining tip", "tool_name": "ChatGPT",
           "url": "https://example.com/tool", "one_liner": "x", "how_to": "x", "why_now": "x"}
    return viral, picks, tip

agent.client = FakeClient()

# ─── TEST 1: v10 scaffold — dead code gone, new constants present ────────────
banner("v10 TEST 1 — Scaffold (cleanup + new config)")
reset_flags()
check(not hasattr(agent, "FORCED_LEAD"), "FORCED_LEAD constant removed")
check(not hasattr(agent, "FORCED_ISSUE"), "FORCED_ISSUE constant removed")
check(not hasattr(agent, "TEASER_MODE"), "TEASER_MODE removed")
check(not hasattr(agent, "score_articles"), "dead score_articles() v1 removed")
check(hasattr(agent, "RUN_FLAGS"), "RUN_FLAGS exists")
check(hasattr(agent, "REVIEW_DIR") and agent.REVIEW_DIR == "review", "REVIEW_DIR == 'review'")
check(hasattr(agent, "AUTHOR_NAME"), "AUTHOR_NAME TODO field exists")
check(hasattr(agent, "BEEHIIV_API_KEY"), "BEEHIIV_API_KEY placeholder exists")
check(hasattr(agent, "SYSTEM_GUARD"), "SYSTEM_GUARD prompt-injection guard exists")
check(callable(agent.parse_args), "parse_args() exists")
check(callable(agent.generate_social_derivatives), "generate_social_derivatives() exists")
check(callable(agent.generate_take_suggestions), "generate_take_suggestions() exists")

# ─── TEST 2: CLI args — review mode default, publish opt-in ──────────────────
banner("v10 TEST 2 — CLI args (review-by-default)")
args = agent.parse_args([])
check(args.publish is False, "default run is NOT publish (review mode)")
check(args.force_lead is None, "--force-lead defaults to None")
check(args.force_issue is None, "--force-issue defaults to None")
args = agent.parse_args(["--publish", "--force-lead", "openai", "--force-issue", "21"])
check(args.publish is True, "--publish opt-in works")
check(args.force_lead == "openai", "--force-lead captured")
check(args.force_issue == 21, "--force-issue captured")

# ─── TEST 3: AI-relevance filter — normal + fail-closed ──────────────────────
banner("v10 TEST 3 — Relevance filter (normal + fail-closed)")
reset_flags()
# 12 articles: 11 pass at threshold 6 -> no safety fallback -> run stays clean
mock_articles = [
    {"title": f"AI story number {i}", "link": f"https://example.com/{i}",
     "source": "TechCrunch AI", "summary": "An AI story.", "published": None,
     "_score": 80, "_score_breakdown": {}}
    for i in range(12)
]
REL_SCORES = {str(i): 9 for i in range(11)}
REL_SCORES["11"] = 3  # one weak article, rejected
filtered = agent.filter_ai_relevance(copy.deepcopy(mock_articles))
check(len(filtered) == 11, f"filter removes the one low-relevance article (got {len(filtered)})")
check(agent.RUN_FLAGS["relevance_degraded"] is False, "clean filter run is not flagged")

# Fail-closed: LLM error -> everything marked -1, excluded (even through the
# safety fallback), flag set — unscored articles never pass.
RAISE_ON = "AI-relevance classifier"
reset_flags()
failed_batch = copy.deepcopy(mock_articles)
filtered = agent.filter_ai_relevance(failed_batch)
RAISE_ON = None
check(len(filtered) == 0, "LLM error -> all articles excluded (fail closed, not passed through)")
check(all(a.get("_ai_relevance") == -1 for a in failed_batch), "failed batch marked -1 (cannot pass)")
check(agent.RUN_FLAGS["relevance_degraded"] is True, "LLM error sets relevance_degraded flag")
reset_flags()

# ─── TEST 4: Viral detection — magnitude + explicit force_lead ────────────────
banner("v10 TEST 4 — Viral detection (+ explicit one-off force)")
test_articles = [
    {"title": "OpenAI ChatGPT Health", "link": "https://x.com/1", "source": "A",
     "summary": "Health feature", "_score": 90, "_magnitude_score": 7.1, "_key_figures": []},
    {"title": "SpaceX Acquires Cursor $60B", "link": "https://x.com/2", "source": "B",
     "summary": "Acquisition", "_score": 85, "_magnitude_score": 9.2, "_key_figures": ["$60 billion"]},
]
viral, _ = agent.detect_viral_story(test_articles)
check(viral is not None and "SpaceX" in viral["title"], "auto-detect picks highest magnitude")
reset_flags()
viral2, _ = agent.detect_viral_story(test_articles, force_lead="chatgpt health")
check(viral2 is not None and "Health" in viral2["title"], "explicit force_lead overrides auto-detect")
check(len(agent.RUN_FLAGS["forced_overrides"]) == 1, "forced override recorded in review flags")
reset_flags()
viral3, _ = agent.detect_viral_story(test_articles, force_lead="chatgpt")
check(viral3 is not None and "Health" in viral3["title"], "single-keyword force_lead works")
reset_flags()

# ─── TEST 5: Fact checker — hermetic (no live network) ───────────────────────
banner("v10 TEST 5 — Fact checker (hermetic: real code, stubbed network)")
import urllib.request
from unittest import mock

class _FakeHTTPResp:
    def __init__(self, payload): self._payload = payload
    def read(self): return self._payload.encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *a): return False

orig_urlopen = urllib.request.urlopen
FAKE_SERPER_JSON = ""
def _fake_urlopen(req, timeout=10):
    if FAKE_SERPER_JSON == "__RAISE__":
        raise OSError("simulated network failure")
    return _FakeHTTPResp(FAKE_SERPER_JSON)
urllib.request.urlopen = _fake_urlopen
reset_flags()

def _serper_json(results):
    # v11: Serper API shape — {"organic": [{"link":..., "title":...}, ...]}
    return json.dumps({"organic": [{"link": u, "title": t} for u, t in results]})

# 5a: honest corroboration — self-source excluded, irrelevant results ignored.
#     Claim from "OpenAI Blog": reuters corroborates (2+ token overlap);
#     openai.com is the story's own outlet (excluded); recipe blog ignored.
with mock.patch.dict(os.environ, {"SERPER_API_KEY": "test-serper-key"}):
    FAKE_SERPER_JSON = _serper_json([
        ("https://www.reuters.com/tech/openai-model", "OpenAI launches new reasoning model today"),
        ("https://www.bloomberg.com/ai", "OpenAI launches new reasoning model today"),
        ("https://openai.com/blog/new-model", "OpenAI launches new reasoning model today"),
        ("https://recipes.example.com/x", "Best chocolate cake recipe for birthdays"),
    ])
    corr, contra, ok = agent._search_corroboration("OpenAI launches new reasoning model", "OpenAI Blog")
    check(ok is True, "successful search returns search_ok=True")
    check(len(corr) == 2, f"2 independent corroborating sources (self excluded, irrelevant ignored) — got {len(corr)}")
    check(contra == [], "no contradiction signals")
    check(agent.RUN_FLAGS["fact_check_degraded"] is False, "successful search is not flagged")
    v, _ = agent.fact_check_stories(
        mk_article("OpenAI launches new reasoning model", "https://x.com/v", source="OpenAI Blog"),
        {"business": [], "everyday": [], "middle_east": []})
    check(v["_fact_check"]["confidence"] == "MEDIUM", "2 corroborating -> MEDIUM")

    # 5b: contradiction signals -> CONTRADICTED
    FAKE_SERPER_JSON = _serper_json([
        ("https://www.reuters.com/x", "OpenAI model safety claims debunked by researchers"),
    ])
    corr, contra, ok = agent._search_corroboration("OpenAI model safety claims validated", "Some Blog")
    check(ok is True and len(contra) == 1, "contradiction signal detected")
    v, _ = agent.fact_check_stories(
        mk_article("OpenAI model safety claims validated", "https://x.com/v2"),
        {"business": [], "everyday": [], "middle_east": []})
    check(v["_fact_check"]["confidence"] == "CONTRADICTED", "contradiction -> CONTRADICTED")

    # 5c: search failure -> UNVERIFIED (never LOW-pass), run flagged
    FAKE_SERPER_JSON = "__RAISE__"
    reset_flags()
    v, _ = agent.fact_check_stories(
        mk_article("Some AI story", "https://x.com/v3"),
        {"business": [], "everyday": [], "middle_east": []})
    check(v["_fact_check"]["confidence"] == "UNVERIFIED", "search failure -> UNVERIFIED (not LOW)")
    check(agent.RUN_FLAGS["fact_check_degraded"] is True, "search failure flags the run")

# 5d (v11): SERPER_API_KEY unset -> search skipped, UNVERIFIED, never crashes
reset_flags()
_saved_serper = os.environ.pop("SERPER_API_KEY", None)
try:
    corr, contra, ok = agent._search_corroboration("OpenAI launches new model", "Some Blog")
    check(ok is False and corr == [] and contra == [], "no key -> zero sources, search_ok=False")
    check(agent.RUN_FLAGS["fact_check_degraded"] is True, "missing key flags the run (degraded)")
finally:
    if _saved_serper is not None:
        os.environ["SERPER_API_KEY"] = _saved_serper
urllib.request.urlopen = orig_urlopen
reset_flags()

# ─── TEST 6: QA — clean fixture passes ───────────────────────────────────────
banner("v10 TEST 6 — QA passes on a clean issue")
reset_flags()
viral, picks, tip = passing_fixture()
qa_passed, qa_checks = agent.run_qa_checks(viral, picks, tip, [])
msgs = [m for _, m in qa_checks]
check(qa_passed is True, "clean issue passes QA")
check(any("v10 Fact-check" in m for m in msgs), "QA includes v10 fact-check check")
check(any("v10 Analysis" in m for m in msgs), "QA includes v10 analysis check")
check(any("v10 Render" in m for m in msgs), "QA includes v10 render check")
check(any("v10 Relevance" in m for m in msgs), "QA includes v10 relevance check")
reset_flags()

# ─── TEST 7 (v11): QA cull — fact-check failures removed before render ────────
banner("v11 TEST 7 — QA cull replaces per-story fact-check FAILs")
check(agent.FACT_CHECK_MIN_CONFIDENCE == "MEDIUM", "FACT_CHECK_MIN_CONFIDENCE default is MEDIUM (reject unverifiable)")
for conf in ("UNVERIFIED", "CONTRADICTED", "LOW"):
    reset_flags()
    viral, picks, tip = passing_fixture(confidence=conf)  # bad-confidence viral lead
    viral2, picks2, report = agent.cull_unverifiable_stories(viral, picks)
    check(len(report["exclusions"]) == 1, f"{conf} viral lead culled (1 exclusion)")
    check(report["exclusions"][0]["confidence"] == conf, f"exclusion records confidence={conf}")
    check(all(set(e.keys()) >= {"title", "section", "confidence", "reason", "evidence"}
              for e in report["exclusions"]), "exclusion records title/section/confidence/reason/evidence")
    qa_passed, qa_checks = agent.run_qa_checks(viral2, picks2, tip, [], cull_report=report)
    fails = [m for s, m in qa_checks if s == "FAIL"]
    check(not any("Fact-check" in m for m in fails),
          f"no fact-check FAIL after cull ({conf}) — no double counting")
    check(any("v10 QA exclusions (1 story/stories removed before render" in m
              for _, m in qa_checks), "exclusions section present in QA report")
# LOW is kept when the bar is LOW
orig_min = agent.FACT_CHECK_MIN_CONFIDENCE
agent.FACT_CHECK_MIN_CONFIDENCE = "LOW"
reset_flags()
viral, picks, tip = passing_fixture(confidence="LOW")
_, _, report = agent.cull_unverifiable_stories(viral, picks)
agent.FACT_CHECK_MIN_CONFIDENCE = orig_min
check(len(report["exclusions"]) == 0, "FACT_CHECK_MIN_CONFIDENCE=LOW keeps LOW-confidence stories")
reset_flags()
# Legacy path (no cull_report): old per-story FAIL semantics preserved
viral, picks, tip = passing_fixture(confidence="CONTRADICTED")
qa_passed, qa_checks = agent.run_qa_checks(viral, picks, tip, [])
check(qa_passed is False and any("Fact-check: CONTRADICTED" in m for _, m in qa_checks),
      "legacy QA (no cull_report) still FAILs contradicted stories")
reset_flags()

# ─── TEST 8: QA — fail-closed run flags block publish ────────────────────────
banner("v10 TEST 8 — QA fails on degraded run flags")
cases = [("relevance_degraded", True), ("render_hollow", True)]
for flag, val in cases:
    reset_flags()
    agent.RUN_FLAGS[flag] = val
    viral, picks, tip = passing_fixture()
    qa_passed, _ = agent.run_qa_checks(viral, picks, tip, [])
    check(qa_passed is False, f"{flag}=True -> QA FAIL")
reset_flags()
agent.RUN_FLAGS["analysis_failures"] = 2
viral, picks, tip = passing_fixture()
qa_passed, _ = agent.run_qa_checks(viral, picks, tip, [])
check(qa_passed is False, "analysis_failures=2 -> QA FAIL")
reset_flags()

# ─── TEST 9: analyze_article — failure marked, never silent {} ───────────────
banner("v10 TEST 9 — Analysis fail-closed (no silent {})")
reset_flags()
RAISE_ON = "tight, scannable newsletter cards"
data = agent.analyze_article(mk_article("T", "https://x.com/t"), "business")
RAISE_ON = None
check(data.get("_analysis_failed") is True, "LLM failure marks _analysis_failed=True")
check(agent.RUN_FLAGS["analysis_failures"] == 1, "analysis failure increments RUN_FLAGS")
check(data != {}, "never returns a silent empty dict")
reset_flags()

# ─── TEST 10: HTML escaping in renderers ─────────────────────────────────────
banner("v10 TEST 10 — HTML escaping (prompt-injection hardening)")
evil = mk_article('<script>alert("x")</script> Evil Title', "https://x.com/evil")
evil["source"] = 'Evil <b>Source</b>'
evil_data = {"headline": 'Evil <b>headline</b>', "tldr": 'T <img src=x onerror=y>',
             "what_happened": "W", "why_it_matters": "M", "business_impact": "B",
             "leader_action": "A", "link_url": "https://x.com/evil"}
html_out = agent.render_viral_block(evil, evil_data)
check("<script>" not in html_out, "no raw <script> in rendered card")
check("<b>headline</b>" not in html_out, "LLM headline HTML is escaped")
check("<img" not in html_out, "LLM tldr <img> is escaped")
check("&lt;b&gt;Source&lt;/b&gt;" in html_out, "RSS source name is escaped")
# Fallback path: no headline in analysis -> RSS title is rendered (escaped)
no_headline = {k: v for k, v in evil_data.items() if k != "headline"}
html_out2 = agent.render_viral_block(evil, no_headline)
check("<script>" not in html_out2, "fallback RSS title <script> is escaped")
check("&lt;script&gt;" in html_out2, "escaped title entity present in fallback")

# ─── TEST 11: Tip URL validation ─────────────────────────────────────────────
banner("v10 TEST 11 — Tip URL allow-list validation")
check(agent._validate_tip_url("https://openai.com/blog").startswith("https://openai.com"),
      "https URL kept")
check(agent._validate_tip_url("javascript:alert(1)").startswith("https://hjt-bit.github.io"),
      "javascript: URL falls back to safe default")
check(agent._validate_tip_url("not a url").startswith("https://hjt-bit.github.io"),
      "garbage URL falls back to safe default")
check(agent._validate_tip_url("").startswith("https://hjt-bit.github.io"),
      "empty URL falls back to safe default")
evil_tip = {"title": "T", "one_liner": "x", "how_to": "x", "link_url": "javascript:alert(1)"}
tip_html = agent.render_tip_block(evil_tip)
check("javascript:" not in tip_html, "evil tip URL never rendered")

# ─── v12.10: Hasan's Take removed ─────────────────────────────────────────────
banner("v12.10 — Hasan's Take removed from the newsletter")
check(not hasattr(agent, "get_hasan_take"), "get_hasan_take() is gone")
check(not hasattr(agent, "render_take_block"), "render_take_block() is gone")
check(not hasattr(agent, "TAKE_MODE"), "TAKE_MODE constant is gone")
check("{take_block}" not in agent.HTML_TEMPLATE, "web template has no take slot")
check("01b //" not in agent.build_email_html("020", "September 28, 2026"),
      "email build has no take section")
check("Hasan Jad's Take" not in agent.build_email_html("020", "September 28, 2026"),
      "email build has no take copy")
# take suggestions still exist — they now feed the LinkedIn post he writes himself
check(callable(agent.generate_take_suggestions), "generate_take_suggestions() still exists")

# v12.7.1: byline brand line is its own non-wrapping block (never splits mid-phrase on mobile)
check('class="byline-brand"' in agent.HTML_TEMPLATE, "byline brand line is a dedicated element")
check("byline-brand" in agent.HTML_TEMPLATE and "white-space: nowrap" in agent.HTML_TEMPLATE,
      "byline brand line cannot wrap mid-phrase")

# ─── TEST 13: Social derivatives schema ─────────────────────────────────────
banner("v10 TEST 13 — Social derivatives (structured JSON outlines)")
deriv = agent.generate_social_derivatives("SIGNAL #001 — brief text")
check(isinstance(deriv, dict), "returns a dict")
check("linkedin_post" in deriv and "ig_carousel_outline" in deriv and "reel_script_outline" in deriv,
      "has all three derivative keys")
check(isinstance(deriv["linkedin_post"], dict), "linkedin_post is an outline object")

# ─── TEST 14: build_index.py ─────────────────────────────────────────────────
banner("v10 TEST 14 — build_index.py")
import subprocess
r = subprocess.run([sys.executable, "-c",
                    "import build_index, tempfile, os; "
                    "os.makedirs('newsletters', exist_ok=True); "
                    "open('newsletters/newsletter_2026_09_14.html','w').write('<html></html>'); "
                    "build_index.build_index(); "
                    "assert 'newsletter_2026_09_14.html' in open('index.html').read(); "
                    "print('index built OK')"],
                   capture_output=True, text=True, cwd=os.path.dirname(__file__))
check(r.returncode == 0, f"build_index.py builds archive index ({r.stderr.strip()[:80]})")

# ─── TEST 15: Take suggestions — schema, markdown, fail-soft ─────────────────
banner("v10 TEST 15 — Take suggestions (schema, markdown, fail-soft)")
reset_flags()
viral_pair = (mk_article("Viral story", "https://x.com/v"),
              {"headline": "Viral Headline", "tldr": "Viral summary",
               "business_impact": "Viral impact"})
biz_pairs = [(mk_article("Biz story", "https://x.com/b"),
              {"headline": "Biz Headline", "tldr": "Biz summary",
               "business_impact": "Biz impact"})]
me_items = [(mk_article("ME story", "https://x.com/m", source="Arab News"),
             {"headline": "ME Headline", "tldr": "ME summary"})]

# 15a: schema — story + exactly 2 complete angles per entry
sugg = agent.generate_take_suggestions(viral_pair, biz_pairs, me_items)
check(isinstance(sugg, dict) and "suggestions" in sugg, "returns a dict with 'suggestions'")
entry = sugg["suggestions"][0]
check(entry.get("story") == "Test Viral Story", "entry carries a story headline")
check(len(entry["angles"]) == 2, "exactly 2 angles per entry")
check(all(set(a.keys()) >= {"angle", "why_it_matters_regionally", "provocation"}
          for a in entry["angles"]),
      "every angle has angle + regional relevance + provocation")
check(agent.RUN_FLAGS["take_suggestions_failed"] is False, "clean run is not flagged")

# 15b: markdown rendering — draft header, angles, provocations
agent._write_take_suggestions_md(sugg, "/tmp/take_suggestions_test.md", "020", "September 20, 2026")
md = open("/tmp/take_suggestions_test.md", encoding="utf-8").read()
check("DRAFT" in md and "Never publish verbatim" in md,
      "markdown header marks output as non-publishable drafts")
check("## 1." in md and "Test Viral Story" in md, "markdown renders story entries")
check("Provocation" in md and "Why it matters regionally" in md,
      "markdown renders angles + provocations")

# 15c: fail-soft — LLM failure sets flag, returns None, placeholder md written
reset_flags()
RAISE_ON = "TAKE SUGGESTIONS"
sugg_fail = agent.generate_take_suggestions(viral_pair, biz_pairs, me_items)
RAISE_ON = None
check(sugg_fail is None, "LLM failure returns None (does not raise)")
check(agent.RUN_FLAGS["take_suggestions_failed"] is True, "LLM failure sets the run flag")
agent._write_take_suggestions_md(sugg_fail, "/tmp/take_suggestions_fail.md", "020", "September 20, 2026")
md_fail = open("/tmp/take_suggestions_fail.md", encoding="utf-8").read()
check("failed" in md_fail.lower(), "placeholder md notes generation failed")
reset_flags()

# ─── TEST 16 (v11): Serper request shape + graceful degradation ───────────────
banner("v11 TEST 16 — Serper API request shape (hermetic)")
import urllib.request as _urlreq
captured = {}
class _SerperResp:
    def read(self): return json.dumps({"organic": []}).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *a): return False
def _capture_urlopen(req, timeout=10):
    captured["url"] = req.full_url
    captured["method"] = req.get_method()
    captured["headers"] = dict(req.header_items())
    captured["data"] = req.data
    return _SerperResp()
with mock.patch.dict(os.environ, {"SERPER_API_KEY": "test-serper-key"}):
    _urlreq.urlopen = _capture_urlopen
    try:
        corr, contra, ok = agent._search_corroboration("Anthropic releases new model", "Some Blog")
    finally:
        _urlreq.urlopen = orig_urlopen
check(captured.get("url") == "https://google.serper.dev/search", "Serper endpoint used")
check(captured.get("method") == "POST", "Serper called with POST")
_hdrs = {k.lower(): v for k, v in captured.get("headers", {}).items()}
check("x-api-key" in _hdrs, "X-API-KEY header sent")
check("test-serper-key" not in json.dumps(captured.get("data", b"").decode("utf-8", errors="ignore")),
      "API key never appears in request body/logs")
_body = json.loads(captured["data"].decode("utf-8"))
check("q" in _body and "Anthropic releases new model" in _body["q"], "claim sent as query")
check(ok is True and corr == [], "empty organic results -> ok with zero sources")

# ─── TEST 17 (v11): markdown tip URLs stripped before validation ──────────────
banner("v11 TEST 17 — Markdown link tip URLs")
check(agent._strip_markdown_link("[NotebookLM](https://notebooklm.google.com/x)") == "https://notebooklm.google.com/x",
      "markdown link -> raw URL extracted")
check(agent._strip_markdown_link("https://openai.com/blog") == "https://openai.com/blog",
      "plain URL unchanged")
check(agent._validate_tip_url("[My Tool](https://github.com/org/tool)").startswith("https://github.com"),
      "markdown-wrapped allow-listed URL passes validation")
check(agent._validate_tip_url("[Evil](javascript:alert(1))").startswith("https://hjt-bit.github.io"),
      "markdown-wrapped evil URL still falls back")

# ─── TEST 18 (v11): Beehiiv draft — draft-only payload, graceful skip ─────────
banner("v11 TEST 18 — Beehiiv draft creation (hermetic, draft-only)")
beehiiv_calls = []
class _BeehiivResp:
    status = 200
    def read(self): return json.dumps({"data": {"id": "post_123", "status": "draft"}}).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *a): return False
def _beehiiv_urlopen(req, timeout=10):
    beehiiv_calls.append(req)
    return _BeehiivResp()
# 18a: skipped gracefully when secrets absent
_saved = (os.environ.pop("BEEHIIV_API_KEY", None), os.environ.pop("BEEHIIV_PUBLICATION_ID", None))
try:
    check(agent.create_beehiiv_draft_post("T", "<p>x</p>") is None, "absent secrets -> None, no crash")
finally:
    if _saved[0] is not None: os.environ["BEEHIIV_API_KEY"] = _saved[0]
    if _saved[1] is not None: os.environ["BEEHIIV_PUBLICATION_ID"] = _saved[1]
# 18b: draft-only payload when secrets present
with mock.patch.dict(os.environ, {"BEEHIIV_API_KEY": "test-beehiiv-key", "BEEHIIV_PUBLICATION_ID": "pub_test123"}):
    _urlreq.urlopen = _beehiiv_urlopen
    try:
        post_id = agent.create_beehiiv_draft_post("SIGNAL #020 — Test", "<p>body</p>", subtitle="sub")
    finally:
        _urlreq.urlopen = orig_urlopen
check(post_id == "post_123", "returns created post id")
check(len(beehiiv_calls) == 1, "exactly one HTTP call made")
_req = beehiiv_calls[0]
check(_req.full_url == "https://api.beehiiv.com/v2/publications/pub_test123/posts", "Beehiiv v2 create-post endpoint")
check(_req.get_method() == "POST", "draft created with POST")
_payload = json.loads(_req.data.decode("utf-8"))
check(_payload.get("status") == "draft", "status is draft")
check(_payload.get("status") != "confirmed", "status is never confirmed")
check("scheduled_at" not in _payload, "no scheduled_at (never auto-scheduled)")
check(_payload.get("title") == "SIGNAL #020 — Test", "title passed through")
check("Authorization" in dict(_req.header_items()) or "Authorization" in _req.headers, "Bearer auth header sent")
# 18c: HTTP failure degrades gracefully, never raises
def _fail_urlopen(req, timeout=10):
    raise urllib.request.HTTPError(req.full_url, 403, "Forbidden", {}, None)
with mock.patch.dict(os.environ, {"BEEHIIV_API_KEY": "k", "BEEHIIV_PUBLICATION_ID": "pub_x"}):
    _urlreq.urlopen = _fail_urlopen
    try:
        check(agent.create_beehiiv_draft_post("T", "<p>x</p>") is None, "HTTP 403 -> None, no crash")
    finally:
        _urlreq.urlopen = orig_urlopen

# ─── TEST 19 (v11): YouTube transcript — version-agnostic, never crashes ─────
banner("v11 TEST 19 — YouTube transcript fetch (hermetic)")
class _Snippet:
    def __init__(self, text): self.text = text
# 1.x style: instance.fetch()
fake_yt1 = types.ModuleType("youtube_transcript_api")
class _API1x:
    def fetch(self, video_id, languages=None):
        return [_Snippet("hello"), _Snippet("world")]
fake_yt1.YouTubeTranscriptApi = _API1x
sys.modules["youtube_transcript_api"] = fake_yt1
try:
    check(agent._fetch_youtube_transcript("abc123") == "hello world", "1.x fetch() API works")
finally:
    del sys.modules["youtube_transcript_api"]
# 0.x style: static get_transcript()
fake_yt0 = types.ModuleType("youtube_transcript_api")
class _API0x:
    @staticmethod
    def get_transcript(video_id, languages=None):
        return [{"text": "legacy"}, {"text": "transcript"}]
fake_yt0.YouTubeTranscriptApi = _API0x
sys.modules["youtube_transcript_api"] = fake_yt0
try:
    check(agent._fetch_youtube_transcript("abc123") == "legacy transcript", "0.x get_transcript() API works")
finally:
    del sys.modules["youtube_transcript_api"]
# failure -> "" with warning, never raises
fake_yt_fail = types.ModuleType("youtube_transcript_api")
class _APIFail:
    def fetch(self, video_id, languages=None):
        raise RuntimeError("no transcript")
fake_yt_fail.YouTubeTranscriptApi = _APIFail
sys.modules["youtube_transcript_api"] = fake_yt_fail
try:
    check(agent._fetch_youtube_transcript("abc123") == "", "fetch failure -> empty string, no crash")
finally:
    del sys.modules["youtube_transcript_api"]
# unknown API shape -> "" , never raises
fake_yt_weird = types.ModuleType("youtube_transcript_api")
class _APIWeird:
    pass
fake_yt_weird.YouTubeTranscriptApi = _APIWeird
sys.modules["youtube_transcript_api"] = fake_yt_weird
try:
    check(agent._fetch_youtube_transcript("abc123") == "", "unknown API shape -> empty string, no crash")
finally:
    del sys.modules["youtube_transcript_api"]

# ─── TEST 20 (v11): headshot wiring — empty URL hides photo, no broken img ────
banner("v11 TEST 20 — Author headshot wiring")
_saved_photo = agent.AUTHOR_PHOTO_URL
try:
    agent.AUTHOR_PHOTO_URL = ""
    ctx = agent._author_context()
    check(ctx["author_photo_html"] == "", "empty URL -> no photo HTML")
    check("<img" not in ctx["author_photo_html"], "no broken <img> when unset")
    agent.AUTHOR_PHOTO_URL = "https://example.com/headshot.jpg"
    ctx2 = agent._author_context()
    check('src="https://example.com/headshot.jpg"' in ctx2["author_photo_html"], "set URL -> img rendered")
finally:
    agent.AUTHOR_PHOTO_URL = _saved_photo


# ─── TEST 21 (v11): QA cull — verify first, build only from survivors ─────────
banner("v11 TEST 21 — QA cull: verify first, build only from survivors")

def fc_article(title, link, confidence, mag=7.0, source="TestSource"):
    a = mk_article(title, link, source=source)
    a["_magnitude_score"] = mag
    a["_fact_check"] = {
        "confidence": confidence, "claim_searched": "x",
        "corroborating_sources": ["ok story (reuters)"] if confidence in ("HIGH", "MEDIUM") else [],
        "contradicting_sources": ["story debunked by experts (reuters)"]
        if confidence == "CONTRADICTED" else [],
    }
    return a

def cull_fixture():
    viral = fc_article("Viral AI breakthrough verified", "https://reuters.com/viral-ai", "HIGH", mag=9.0)
    biz = [
        fc_article("Solid enterprise AI deal", "https://bloomberg.com/ai-deal", "MEDIUM", mag=8.0),
        fc_article("Fake Chinese nuclear AI story", "https://techcrunch.com/fake-nuke", "CONTRADICTED", mag=7.0),
        fc_article("Unverifiable rumor mill story", "https://ft.com/rumor", "LOW", mag=6.0),
    ]
    eve = [fc_article("Consumer AI gadget launch", "https://theverge.com/gadget", "MEDIUM", mag=7.2)]
    me = [fc_article("Gulf AI datacenter opens", "https://arabnews.com/datacenter", "UNVERIFIED",
                     mag=7.4, source="Arab News")]
    picks = {"business": biz, "everyday": eve, "middle_east": me}
    tip = {"title": "Fresh test tip", "tool_name": "X", "url": "https://example.com",
           "one_liner": "x", "how_to": "x", "why_now": "x"}
    return viral, picks, tip

# 21a: cull removes failing stories pre-render; exclusions fully recorded
reset_flags()
viral, picks, tip = cull_fixture()
viral2, picks2, report = agent.cull_unverifiable_stories(viral, picks)
ex = report["exclusions"]
check(len(ex) == 3, f"3 failing stories culled (got {len(ex)})")
check({e["confidence"] for e in ex} == {"CONTRADICTED", "LOW", "UNVERIFIED"},
      "all failing confidences culled")
check(all(set(e.keys()) >= {"title", "section", "confidence", "reason", "evidence"} for e in ex),
      "every exclusion records title/section/confidence/reason/evidence")
check(any(e["section"] == "business" and "contradicted" in e["reason"] for e in ex),
      "contradiction reason recorded")
check(any("debunked" in e["evidence"] for e in ex if e["confidence"] == "CONTRADICTED"),
      "contradicting evidence attached to exclusion")
check([a["title"] for a in picks2["business"]] == ["Solid enterprise AI deal"],
      "business section keeps only the survivor")
check(len(picks2["middle_east"]) == 0, "UNVERIFIED regional story culled (section left short)")
check(viral2["title"] == "Viral AI breakthrough verified", "verified viral lead untouched")
check(report["total_before"] == 6, "total_before counts viral + all sections")
check(report["lead_swapped"] is None, "no lead swap when lead survives")

# 21b: downstream render contains no culled titles
data = {"headline": "H", "tldr": "T", "what_happened": "W", "why_it_matters": "M",
        "business_impact": "B", "leader_action": "A", "link_url": "https://bloomberg.com/ai-deal"}
rendered = "".join(agent.render_business_card(a, data) for a in picks2["business"])
check("Fake Chinese nuclear AI story" not in rendered and "Unverifiable rumor" not in rendered,
      "culled titles absent from rendered business cards")
check("H" in rendered, "survivor's analysis rendered as a card")

# 21c: section counts WARN (not FAIL) after cull shrinkage
qa_passed, qa_checks = agent.run_qa_checks(viral2, picks2, tip, [], cull_report=report)
fails = [m for s, m in qa_checks if s == "FAIL"]
check(not fails, f"no FAILs on a cull-shrunk issue (got {fails})")
check(qa_passed is True, "cull-shrunk issue passes QA")
warns = [m for s, m in qa_checks if s == "WARN"]
check(any("Strategic Briefing has 1 stor(ies) after QA exclusions (was 3)" in m for m in warns),
      "section-count downgraded to WARN with (was N)")
check(any("From the Region is empty after QA exclusions (was 1)" in m for m in warns),
      "emptied-by-cull region section WARNs instead of FAILing")

# 21d: tally line + no double counting
msgs = [m for _, m in qa_checks]
check(any("v10 Fact-check: 6 stories checked, 3 excluded, 3 verified at MEDIUM+" in m for m in msgs),
      "fact-check tally line: checked/excluded/verified")
check(not any("Fake Chinese nuclear" in m or "Unverifiable rumor" in m or "Gulf AI datacenter" in m
              for s, m in qa_checks if s == "FAIL"),
      "culled story never appears as a FAIL (no double counting)")

# 21e: viral lead culled -> highest-magnitude survivor promoted
reset_flags()
v_bad = fc_article("Hallucinated viral scoop", "https://reuters.com/bad-scoop", "CONTRADICTED", mag=9.9)
p_bad = {"business": [fc_article("Enterprise AI deal", "https://bloomberg.com/deal", "MEDIUM", mag=8.2),
                      fc_article("AI chip funding", "https://techcrunch.com/chips", "MEDIUM", mag=7.1)],
         "everyday": [], "middle_east": []}
v_new, p_new, rep = agent.cull_unverifiable_stories(v_bad, p_bad)
check(v_new is not None and v_new["title"] == "Enterprise AI deal",
      "culled lead replaced by highest-magnitude survivor")
check(all(a["title"] != "Enterprise AI deal" for a in p_new["business"]),
      "promoted story removed from its section")
check(rep["lead_swapped"] == {"from": "Hallucinated viral scoop", "to": "Enterprise AI deal"},
      "lead swap recorded in cull report")
qa2_passed, qa2_checks = agent.run_qa_checks(v_new, p_new, tip, [], cull_report=rep)
check(any("Viral lead swapped after cull" in m for _, m in qa2_checks),
      "lead swap noted in QA report")

# 21f: failsafe trips past one-third (strictly greater)
reset_flags()
doms = ["reuters.com", "bloomberg.com", "techcrunch.com", "ft.com", "theverge.com",
        "wired.com", "venturebeat.com", "arstechnica.com", "theguardian.com"]
arts = [fc_article(f"Story {i}", f"https://{doms[i]}/s{i}",
                   "CONTRADICTED" if i < 4 else "MEDIUM", mag=7.0) for i in range(9)]
v_ok = fc_article("Good lead", "https://reuters.com/good-lead", "HIGH", mag=9.0)
p_fs = {"business": arts[:3], "everyday": arts[3:6], "middle_east": arts[6:9]}
_, _, rep_fs = agent.cull_unverifiable_stories(v_ok, p_fs)
check(agent.cull_failsafe_tripped(rep_fs) is True, "4 of 10 excluded (>1/3) trips failsafe")
arts2 = [fc_article(f"Story {i}", f"https://{doms[i]}/t{i}",
                    "CONTRADICTED" if i < 3 else "MEDIUM", mag=7.0) for i in range(9)]
p_ok = {"business": arts2[:3], "everyday": arts2[3:6], "middle_east": arts2[6:9]}
_, _, rep_ok = agent.cull_unverifiable_stories(v_ok, p_ok)
check(agent.cull_failsafe_tripped(rep_ok) is False, "3 of 10 excluded (=1/3) does not trip failsafe")
check(agent.cull_failsafe_tripped({"exclusions": [], "total_before": 0}) is False,
      "empty issue does not trip failsafe")

# 21g: failsafe bundle written, QA FAILs with clear message
import tempfile
cwd = os.getcwd()
tmpd = tempfile.mkdtemp()
try:
    os.chdir(tmpd)
    agent.write_cull_failsafe_bundle(rep_fs, "September 20, 2026")
    # write_cull_failsafe_bundle chdirs into review/ itself
    check(os.path.exists("qa_report.md"), "failsafe writes review/qa_report.md")
    qr = open("qa_report.md", encoding="utf-8").read()
    check("excessive exclusions" in qr and "FAIL" in qr,
          "failsafe QA report FAILs with clear message")
    check("EXCLUDED [CONTRADICTED]" in qr, "exclusion details in failsafe bundle")
    check(os.path.exists("REVIEW_SUMMARY.md"), "failsafe writes review/REVIEW_SUMMARY.md")
finally:
    os.chdir(cwd)

# 21h: stories with no _fact_check metadata are kept (fact-checker disabled path)
reset_flags()
plain = mk_article("Unfactchecked story", "https://reuters.com/plain")
v3, p3, rep3 = agent.cull_unverifiable_stories(
    fc_article("Lead", "https://reuters.com/lead2", "HIGH", mag=9.0),
    {"business": [plain], "everyday": [], "middle_east": []})
check(len(rep3["exclusions"]) == 0 and len(p3["business"]) == 1,
      "story without _fact_check metadata is kept")


# ─── v12.1 TESTS — code-enforced editorial QA (checks 18/19/20/21) ──────────

# 22a: banned phrases detected in the why_you_care opener (v12.4 field)
reset_flags()
art_bp = mk_article("TestCo raises funding", "https://reuters.com/bp1")
data_bp = {"why_you_care": "This could reshape the landscape for startups",
           "leader_action": "Pilot TestCo in one team this quarter",
           "headline": "TestCo raises funding", "what_happened": "TestCo raised $10M"}
_, checks_bp = agent.run_qa_checks(art_bp, {"business": [art_bp], "everyday": [], "middle_east": []},
                                   None, None, analysis_pairs=[(art_bp, data_bp)])
check(any(s == "FAIL" and "banned phrase" in m for s, m in checks_bp),
      "check 18 FAILs on banned phrase in the opener")

# 22b: clean copy passes check 18
reset_flags()
data_clean = {"why_you_care": "Cuts onboarding time by 30 percent",
              "leader_action": "Pilot TestCo in one team this quarter",
              "headline": "TestCo raises funding", "what_happened": "TestCo raised $10M"}
_, checks_clean = agent.run_qa_checks(art_bp, {"business": [art_bp], "everyday": [], "middle_east": []},
                                      None, None, analysis_pairs=[(art_bp, data_clean)])
check(any(s == "PASS" and "no banned" in m for s, m in checks_clean),
      "check 18 PASSes on clean copy")

# 22c: banned leader-action opener detected
reset_flags()
data_opener = {"why_it_matters": "Cuts onboarding time",
               "business_impact": "Revenue impact",
               "leader_action": "Consider piloting TestCo soon",
               "headline": "TestCo raises", "tldr": "Raised money", "what_happened": "Raised $10M"}
_, checks_op = agent.run_qa_checks(art_bp, {"business": [art_bp], "everyday": [], "middle_east": []},
                                   None, None, analysis_pairs=[(art_bp, data_opener)])
check(any(s == "FAIL" and "banned opener" in m for s, m in checks_op),
      "check 19 FAILs on banned leader-action opener")

# 22d: decisive opener passes check 19
reset_flags()
_, checks_op2 = agent.run_qa_checks(art_bp, {"business": [art_bp], "everyday": [], "middle_east": []},
                                    None, None, analysis_pairs=[(art_bp, data_clean)])
check(any(s == "PASS" and "openers decisive" in m for s, m in checks_op2),
      "check 19 PASSes on decisive opener")

# 22e: status upgrade detected (source "in talks", analysis claims "announced") → FAIL
reset_flags()
art_status = mk_article("TestCo in talks to acquire StartupX", "https://reuters.com/st1",
                        summary="TestCo is reportedly in talks to acquire StartupX, sources say.")
data_status = {"why_it_matters": "Consolidation signal",
               "business_impact": "Competitive pressure",
               "leader_action": "Map exposure to StartupX",
               "headline": "TestCo launches acquisition of StartupX",
               "tldr": "TestCo acquired StartupX", "what_happened": "TestCo announced it has closed the deal"}
_, checks_st = agent.run_qa_checks(art_status, {"business": [art_status], "everyday": [], "middle_east": []},
                                   None, None, analysis_pairs=[(art_status, data_status)])
check(any(s == "FAIL" and "Status precision" in m for s, m in checks_st),
      "check 20 FAILs on status upgrade (in talks -> announced)")

# 22f: matching status passes check 20
reset_flags()
data_status_ok = {"why_it_matters": "Consolidation signal",
                  "business_impact": "Competitive pressure",
                  "leader_action": "Map exposure to StartupX",
                  "headline": "TestCo in talks to acquire StartupX",
                  "tldr": "TestCo reportedly considering StartupX deal",
                  "what_happened": "TestCo is in talks to acquire StartupX per sources"}
_, checks_st2 = agent.run_qa_checks(art_status, {"business": [art_status], "everyday": [], "middle_east": []},
                                    None, None, analysis_pairs=[(art_status, data_status_ok)])
check(any(s == "PASS" and "no status upgrades" in m for s, m in checks_st2),
      "check 20 PASSes when analysis matches source status")

# 22i: module constants contain all approved banned phrases/openers
check(len(agent.BANNED_OPENER_PHRASES) == 16,
      "16 banned opener phrases in module constant")
check(len(agent.BANNED_LEADER_ACTION_OPENERS) == 7,
      "7 banned openers in module constant")
check("could reshape the landscape" in agent.BANNED_OPENER_PHRASES and
      "competitive positioning" in agent.BANNED_OPENER_PHRASES,
      "banned opener constant has expected entries")
check("keep an eye on" in agent.BANNED_LEADER_ACTION_OPENERS,
      "banned opener constant has expected entry")


# ─── v12.1 TESTS — Monday-of-publication issue date + take sentence rule ───

# 23a: _parse_explicit_date accepts a valid Monday
reset_flags()
agent._ISSUE_DATE = None
check(agent._parse_explicit_date("2026-09-28") == date(2026, 9, 28),
      "_parse_explicit_date accepts a valid Monday")

# 23b: _parse_explicit_date rejects malformed dates with a clear error
for bad in ["2026/09/22", "22-09-2026", "not-a-date", "", "2026-13-01", "2026-09-2"]:
    try:
        agent._parse_explicit_date(bad)
        check(False, f"_parse_explicit_date rejects malformed {bad!r}")
    except ValueError as e:
        check("YYYY-MM-DD" in str(e), f"_parse_explicit_date rejects malformed {bad!r}")

# 23c: _parse_explicit_date rejects valid non-Monday dates
for non_mon, day in [("2026-09-29", "Tuesday"), ("2026-09-27", "Sunday"),
                     ("2026-09-26", "Saturday"), ("2026-09-22", "Tuesday")]:
    try:
        agent._parse_explicit_date(non_mon)
        check(False, f"_parse_explicit_date rejects non-Monday {non_mon}")
    except ValueError as e:
        check("Monday" in str(e) and day in str(e),
              f"_parse_explicit_date rejects non-Monday {non_mon} ({day})")

# 23d: explicit PUBLICATION_DATE is preferred, pins reruns, drives formats
reset_flags()
saved_pub = os.environ.pop("PUBLICATION_DATE", None)
try:
    os.environ["PUBLICATION_DATE"] = "2026-09-28"
    agent._ISSUE_DATE = None
    check(agent._issue_date() == date(2026, 9, 28) and agent._issue_date().weekday() == 0,
          "explicit PUBLICATION_DATE Monday becomes the issue date")
    check(agent._issue_date_str() == "2026_09_28",
          "_issue_date_str() is YYYY_MM_DD")
    check(agent._issue_date_display() == "September 28, 2026",
          "_issue_date_display() is 'Month DD, YYYY'")
    # delayed reruns on different run dates keep the same pinned issue date
    for run_day in [datetime(2026, 9, 27), datetime(2026, 10, 4), datetime(2026, 10, 11)]:
        agent._ISSUE_DATE = None
        check(agent._issue_date(now=run_day) == date(2026, 9, 28),
              f"delayed rerun on {run_day.date()} keeps pinned issue date")
    # invalid explicit date fails fast with a clear error
    os.environ["PUBLICATION_DATE"] = "2026-09-29"  # a Tuesday
    agent._ISSUE_DATE = None
    try:
        agent._issue_date()
        check(False, "invalid PUBLICATION_DATE raises on _issue_date()")
    except ValueError as e:
        check("Monday" in str(e), "invalid PUBLICATION_DATE raises clear Monday error")
finally:
    if saved_pub is not None:
        os.environ["PUBLICATION_DATE"] = saved_pub
    else:
        os.environ.pop("PUBLICATION_DATE", None)
    agent._ISSUE_DATE = None

# 23e: without PUBLICATION_DATE, run-day resolution (Sun -> upcoming Mon,
# Mon -> same Mon, Tue-Sat -> most recent Mon). 2026-09-28 is a Monday.
saved_pub = os.environ.pop("PUBLICATION_DATE", None)
try:
    for label, run_dt, expected in [
        ("Sunday", datetime(2026, 9, 27), date(2026, 9, 28)),
        ("Monday", datetime(2026, 9, 28), date(2026, 9, 28)),
        ("Tuesday", datetime(2026, 9, 29), date(2026, 9, 28)),
        ("Wednesday", datetime(2026, 9, 30), date(2026, 9, 28)),
        ("Thursday", datetime(2026, 10, 1), date(2026, 9, 28)),
        ("Friday", datetime(2026, 10, 2), date(2026, 9, 28)),
        ("Saturday", datetime(2026, 10, 3), date(2026, 10, 5)),
    ]:
        agent._ISSUE_DATE = None
        got = agent._issue_date(now=run_dt)
        check(got == expected and got.weekday() == 0,
              f"{label} run resolves to Monday {expected}")
finally:
    if saved_pub is not None:
        os.environ["PUBLICATION_DATE"] = saved_pub
    agent._ISSUE_DATE = None

# 23f: _issue_date accepts a plain date for `now` too
agent._ISSUE_DATE = None
check(agent._issue_date(now=date(2026, 9, 27)) == date(2026, 9, 28),
      "_issue_date(now=date) resolves like datetime input")
agent._ISSUE_DATE = None



# 23i: check 20 does not fire when the analysis status is weaker than the source
reset_flags()
data_weaker = {"why_it_matters": "Consolidation signal",
               "business_impact": "Competitive pressure",
               "leader_action": "Map exposure to StartupX",
               "headline": "TestCo reportedly considering StartupX deal",
               "tldr": "TestCo is in talks per sources",
               "what_happened": "Talks are reportedly ongoing"}
art_announced = mk_article("TestCo announced StartupX acquisition", "https://reuters.com/st2",
                           summary="TestCo announced it will acquire StartupX.")
_, checks_weaker = agent.run_qa_checks(art_announced, {"business": [art_announced], "everyday": [], "middle_east": []},
                                       None, None, analysis_pairs=[(art_announced, data_weaker)])
check(any(s == "PASS" and "no status upgrades" in m for s, m in checks_weaker),
      "check 20 PASSes when analysis status is weaker than source (no false upgrade)")


# ─── TEST 24 (v12.2): Kit broadcast draft — draft-only payload, graceful skip ──
banner("v12.2 TEST 24 — Kit broadcast draft creation (hermetic, draft-only)")
kit_calls = []
class _KitResp:
    status = 201
    def read(self): return json.dumps({"data": {"broadcast": {"id": "bcast_456"}}}).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *a): return False
def _kit_urlopen(req, timeout=10):
    kit_calls.append(req)
    return _KitResp()
# 24a: skipped gracefully when the secret is absent
_kit_saved = os.environ.pop("KIT_API_KEY", None)
try:
    check(agent.create_kit_broadcast_draft("T", "<p>x</p>") is None, "absent KIT_API_KEY -> None, no crash")
finally:
    if _kit_saved is not None: os.environ["KIT_API_KEY"] = _kit_saved
# 24b: draft-only payload when the secret is present
with mock.patch.dict(os.environ, {"KIT_API_KEY": "test-kit-key"}):
    _urlreq.urlopen = _kit_urlopen
    try:
        bcast_id = agent.create_kit_broadcast_draft("SIGNAL #020 — Test", "<p>body</p>", preview_text="prev")
    finally:
        _urlreq.urlopen = orig_urlopen
check(bcast_id == "bcast_456", "returns created broadcast id (nested data.broadcast shape)")
check(len(kit_calls) == 1, "exactly one HTTP call made")
_kreq = kit_calls[0]
check(_kreq.full_url == "https://api.kit.com/v4/broadcasts", "Kit v4 broadcasts endpoint")
check(_kreq.get_method() == "POST", "draft created with POST")
_kpayload = json.loads(_kreq.data.decode("utf-8"))
check(_kpayload.get("send_at") is None, "send_at is null (never scheduled)")
check("scheduled_at" not in _kpayload, "no scheduled_at (never auto-scheduled)")
check(_kpayload.get("public") is False, "public is false (archive stays human-gated)")
check(_kpayload.get("subject") == "SIGNAL #020 — Test", "subject passed through")
check(_kpayload.get("preview_text") == "prev", "preview_text passed through")
_kheaders = {_k.lower(): v for _k, v in _kreq.header_items()}
check(_kheaders.get("x-kit-api-key") == "test-kit-key", "X-Kit-Api-Key header sent")
check("test-kit-key" not in json.dumps(_kpayload), "API key never appears in the payload")
# 24c: HTTP failure degrades gracefully, never raises
def _kit_fail_urlopen(req, timeout=10):
    raise urllib.request.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
with mock.patch.dict(os.environ, {"KIT_API_KEY": "k"}):
    _urlreq.urlopen = _kit_fail_urlopen
    try:
        check(agent.create_kit_broadcast_draft("T", "<p>x</p>") is None, "HTTP 401 -> None, no crash")
    finally:
        _urlreq.urlopen = orig_urlopen


# ─── v12.4 TESTS — zero-redundancy story anatomy ─────────────────────────
# Each line earns its place: headline (WHAT) → bold "Why you care" opener
# (SO WHAT, never restates the headline) → body (details absent from the
# headline) → leader action. The summary-style tldr is retired from
# business/viral cards; the opener unifies with the everyday card's voice.

# 24a: analyzer prompt — why_you_care opener + anti-restatement rule, no tldr
captured_prompts = []
_orig_create = FakeCompletions.create
def _spy_create(self, **kwargs):
    captured_prompts.append(" ".join(m.get("content", "") for m in kwargs.get("messages", [])))
    return _orig_create(self, **kwargs)
FakeCompletions.create = _spy_create
try:
    agent.analyze_article(mk_article("BizCo launches AI suite", "https://x.com/biz"), audience="business")
finally:
    FakeCompletions.create = _orig_create
biz_prompt = next(t for t in captured_prompts if "tight, scannable newsletter cards" in t)
check('"why_you_care"' in biz_prompt,
      "v12.4 analyzer schema requests the why_you_care opener")
check('"tldr"' not in biz_prompt and '"why_it_matters"' not in biz_prompt
      and '"business_impact"' not in biz_prompt,
      "v12.4 analyzer schema drops tldr/why_it_matters/business_impact")
check("NO REPETITION" in biz_prompt,
      "v12.4 analyzer prompt carries the anti-restatement rule")

# 24b: renderer anatomy — opener, body, action; nothing else
card_data = {"headline": "TestCo raises $10M",
             "why_you_care": "Gulf VCs are doubling down on AI infrastructure spend",
             "what_happened": "TestCo closed a $10M round led by Gulf Capital on Tuesday",
             "leader_action": "Shortlist TestCo for your Q4 AI infrastructure pilot"}
art24 = mk_article("TestCo raises $10M", "https://x.com/t24")
vh = agent.render_viral_block(art24, card_data)
check('<p class="card-angle"><strong>Why you care:</strong>' in vh,
      "v12.4 viral card opens with the bold Why-you-care opener")
check('<p class="card-body">TestCo closed a $10M round' in vh,
      "v12.4 viral card renders the body as flowing prose")
check("<strong>Leader action:</strong>" in vh,
      "v12.4 viral card keeps the leader action")
check("card-tldr" not in vh and "Why it matters" not in vh and "meta-grid" not in vh,
      "v12.4 viral card drops tldr / stake-line / grid remnants")
bh = agent.render_business_card(art24, card_data)
check('<p class="card-angle"><strong>Why you care:</strong>' in bh and "card-tldr" not in bh,
      "v12.4 business card uses the new anatomy")

# 24c: check 18 scans the opener; legacy fields are ignored
reset_flags()
art24b = mk_article("TestCo raises funding", "https://reuters.com/24c")
data_bad_opener = {"why_you_care": "This could reshape the landscape for startups",
                   "why_it_matters": "legacy field, ignored",
                   "headline": "TestCo raises funding", "what_happened": "TestCo raised $10M",
                   "leader_action": "Pilot TestCo in one team this quarter"}
_, checks_bo = agent.run_qa_checks(art24b, {"business": [art24b], "everyday": [], "middle_east": []},
                                   None, None, analysis_pairs=[(art24b, data_bad_opener)])
check(any(s == "FAIL" and "banned phrase" in m for s, m in checks_bo),
      "v12.4 check 18 FAILs on a banned phrase in the opener")
reset_flags()
data_clean_opener = dict(data_bad_opener, why_you_care="Cuts model training costs by a third")
_, checks_co = agent.run_qa_checks(art24b, {"business": [art24b], "everyday": [], "middle_east": []},
                                  None, None, analysis_pairs=[(art24b, data_clean_opener)])
check(any(s == "PASS" and "no banned" in m for s, m in checks_co),
      "v12.4 check 18 PASSes on a clean opener")

# 24d: redundancy WARN — opener restating the headline vs a fresh opener
reset_flags()
art24c = mk_article("Anthropic Signs $11.6 Billion Cloud Deal with Akamai", "https://x.com/24d")
data_repeat = {"why_you_care": "Anthropic signs $11.6 billion cloud deal with Akamai",
               "headline": "Anthropic Signs $11.6 Billion Cloud Deal with Akamai",
               "what_happened": "Seven-year agreement for cloud services",
               "leader_action": "Benchmark cloud renewals this quarter"}
_, checks_rp = agent.run_qa_checks(art24c, {"business": [art24c], "everyday": [], "middle_east": []},
                                  None, None, analysis_pairs=[(art24c, data_repeat)])
check(any(s == "WARN" and "restate" in m for s, m in checks_rp),
      "v12.4 redundancy check WARNs when the opener restates the headline")
reset_flags()
data_fresh = dict(data_repeat,
                  why_you_care="Cloud pricing power is shifting to AI labs — expect tougher renewals")
_, checks_fr = agent.run_qa_checks(art24c, {"business": [art24c], "everyday": [], "middle_east": []},
                                  None, None, analysis_pairs=[(art24c, data_fresh)])
check(any(s == "PASS" and "Redundancy" in m for s, m in checks_fr),
      "v12.4 redundancy check PASSes on a fresh opener")

# 24e: status precision now covers the opener
reset_flags()
art24d = mk_article("TestCo in talks to acquire StartupX", "https://reuters.com/24e",
                    summary="TestCo is reportedly in talks to acquire StartupX, sources say.")
data_up = {"why_you_care": "TestCo launched the acquisition of StartupX",
           "headline": "TestCo in talks to acquire StartupX",
           "what_happened": "TestCo is in talks to acquire StartupX per sources",
           "leader_action": "Map exposure to StartupX"}
_, checks_up = agent.run_qa_checks(art24d, {"business": [art24d], "everyday": [], "middle_east": []},
                                   None, None, analysis_pairs=[(art24d, data_up)])
check(any(s == "FAIL" and "Status precision" in m for s, m in checks_up),
      "v12.4 status precision catches an upgrade inside the opener")


# ─── v12.5 TESTS — concrete openers, no corporate mush ─────────────────
# The opener must carry a concrete anchor (number, named actor, specific
# cost/revenue/risk). Mush phrases FAIL via check 18; abstract nouns WARN
# via the new check 23.

# 25a: prompt carries the concreteness formula
captured_p = []
_oc = FakeCompletions.create
def _spy2(self, **kwargs):
    captured_p.append(" ".join(m.get("content", "") for m in kwargs.get("messages", [])))
    return _oc(self, **kwargs)
FakeCompletions.create = _spy2
try:
    agent.analyze_article(mk_article("BizCo launches AI suite", "https://x.com/biz"), audience="business")
finally:
    FakeCompletions.create = _oc
biz_p = next(t for t in captured_p if "tight, scannable newsletter cards" in t)
check("concrete anchor" in biz_p,
      "v12.5 analyzer prompt requires a concrete anchor in the opener")
check("Formula:" in biz_p and "specific consequence" in biz_p,
      "v12.5 opener spec uses the consequence formula")

# 25b: mush phrases FAIL check 18 (the live Anthropic opener pattern)
reset_flags()
art25 = mk_article("Anthropic Signs $11.6 Billion Cloud Deal with Akamai", "https://x.com/25")
data_mush = {"why_you_care": "This partnership signals a major investment in cloud infrastructure, impacting competitive positioning in AI services",
             "headline": "Anthropic Signs $11.6 Billion Cloud Deal with Akamai",
             "what_happened": "Anthropic will pay Akamai $11.6 billion over seven years",
             "leader_action": "Benchmark your cloud renewals against AI-lab rates before Q4"}
_, checks_mush = agent.run_qa_checks(art25, {"business": [art25], "everyday": [], "middle_east": []},
                                    None, None, analysis_pairs=[(art25, data_mush)])
check(any(s == "FAIL" and "banned phrase" in m for s, m in checks_mush),
      "v12.5 check 18 FAILs on corporate-mush opener")

# 25c: abstract nouns WARN via check 23; anchored opener passes clean
reset_flags()
data_abs = dict(data_mush, why_you_care="The AI ecosystem is entering a new paradigm for enterprises")
_, checks_abs = agent.run_qa_checks(art25, {"business": [art25], "everyday": [], "middle_east": []},
                                   None, None, analysis_pairs=[(art25, data_abs)])
check(any(s == "WARN" and "Concreteness" in m for s, m in checks_abs),
      "v12.5 check 23 WARNs on an abstract-noun opener")
reset_flags()
data_sharp = dict(data_mush,
                  why_you_care="AI labs just became cloud price-setters — Gulf enterprises face tougher Q4 renewals")
_, checks_sharp = agent.run_qa_checks(art25, {"business": [art25], "everyday": [], "middle_east": []},
                                      None, None, analysis_pairs=[(art25, data_sharp)])
check(any(s == "PASS" and "Concreteness" in m for s, m in checks_sharp),
      "v12.5 check 23 PASSes on an anchored opener")
check(not any(s in ("FAIL", "WARN") and ("banned phrase" in m or "restate" in m or "Concreteness" in m)
              for s, m in checks_sharp),
      "v12.5 sharp opener triggers no editorial FAIL/WARN")


# ─── v12.6 TESTS — self-correction loop for mushy openers ─────────────
# A violating opener triggers exactly one surgical rewrite; a still-bad
# rewrite keeps the original so QA flags it for Hasan.

# 26a: violation detector
check(agent._opener_violations({"why_you_care": "This signals a major shift in the industry"}) != [],
      "v12.6 detector flags a banned mush phrase")
check(agent._opener_violations({"why_you_care": "The AI ecosystem enters a new paradigm"}) != [],
      "v12.6 detector flags abstract nouns")
check(agent._opener_violations({"why_you_care": "AI labs just became cloud price-setters for Gulf firms"}) == [],
      "v12.6 detector passes a concrete opener")

# 26b: successful rewrite replaces the opener
reset_flags()
REWRITE_OPENER_RESPONSE = "AI labs just became cloud price-setters — Gulf firms face tougher Q4 renewals"
art26 = mk_article("Anthropic Signs $11.6 Billion Cloud Deal with Akamai", "https://x.com/26")
data26 = {"why_you_care": "This partnership signals a major investment in cloud infrastructure",
          "headline": "Anthropic Signs $11.6 Billion Cloud Deal with Akamai",
          "what_happened": "Anthropic will pay Akamai $11.6 billion over seven years",
          "leader_action": "Benchmark cloud renewals this quarter"}
sharp = agent._sharpen_pair(art26, dict(data26), "business")
check(sharp["why_you_care"] == REWRITE_OPENER_RESPONSE,
      "v12.6 surgical rewrite replaces a mushy opener")
check(agent.RUN_FLAGS["opener_rewrites"] == 1,
      "v12.6 rewrite increments the opener_rewrites flag")
check(sharp["headline"] == data26["headline"] and sharp["leader_action"] == data26["leader_action"],
      "v12.6 rewrite leaves other card fields untouched")

# 26c: still-bad rewrite keeps the original for QA to flag
reset_flags()
REWRITE_OPENER_RESPONSE = "This marks a significant step for the ecosystem"
stuck = agent._sharpen_pair(art26, dict(data26), "business")
check(stuck["why_you_care"] == data26["why_you_care"],
      "v12.6 keeps the original when the rewrite is still unusable")
check(agent.RUN_FLAGS["opener_rewrites"] == 0,
      "v12.6 no rewrite counted when the candidate fails validation")

# 26d: clean openers skip the LLM entirely
reset_flags()
calls = []
_oc3 = FakeCompletions.create
def _spy3(self, **kwargs):
    calls.append(1)
    return _oc3(self, **kwargs)
FakeCompletions.create = _spy3
try:
    agent._sharpen_pair(art26, {"why_you_care": "AI labs just became cloud price-setters for Gulf firms",
                               "headline": "h", "what_happened": "w", "leader_action": "a"}, "business")
finally:
    FakeCompletions.create = _oc3
check(calls == [], "v12.6 no LLM call when the opener is already clean")

# 26e: prompt's banned list matches the constant (no drift)
reset_flags()
captured_q = []
_oc4 = FakeCompletions.create
def _spy4(self, **kwargs):
    captured_q.append(" ".join(m.get("content", "") for m in kwargs.get("messages", [])))
    return _oc4(self, **kwargs)
FakeCompletions.create = _spy4
try:
    agent.analyze_article(mk_article("BizCo launches AI suite", "https://x.com/biz"), audience="business")
finally:
    FakeCompletions.create = _oc4
biz_q = next(t for t in captured_q if "tight, scannable newsletter cards" in t)
check(all(p in biz_q for p in agent.BANNED_OPENER_PHRASES),
      "v12.6 prompt banned list matches the module constant")


# ─── v12.8 TESTS — Gulf Watch (KSA/UAE strip) ─────────────────────────────────
banner("v12.8 TESTS — Gulf Watch (KSA/UAE strip)")

# 1. classifier
ksa_art = mk_article("SDAIA launches new Arabic LLM in Riyadh", "https://x.com/ksa1",
                     summary="Saudi Arabia's data authority unveils the model.")
uae_art = mk_article("MGX backs $2B Dubai AI campus", "https://x.com/uae1",
                     summary="Abu Dhabi fund MGX leads the round.")
egy_art = mk_article("Egyptian fintech raises round", "https://x.com/egy1",
                     summary="Cairo startup closes seed funding.")
both_art = mk_article("Saudi-UAE AI partnership announced", "https://x.com/both1",
                      summary="Riyadh and Dubai join forces on compute.")
check(agent.classify_gulf_country(ksa_art) == "KSA", "classifier tags SDAIA/Riyadh story as KSA")
check(agent.classify_gulf_country(uae_art) == "UAE", "classifier tags MGX/Dubai story as UAE")
check(agent.classify_gulf_country(egy_art) is None, "classifier returns None for non-Gulf regional story")
check(agent.classify_gulf_country(both_art) == "KSA", "classifier tie-breaks to KSA")
check(agent.classify_gulf_country(None) is None, "classifier handles None article")
check(agent.classify_gulf_country(mk_article("Spiffy gadgets review", "https://x.com/n")) is None,
      "classifier word boundaries stop 'pif' matching inside 'spiffy'")

# 2. _select_gulf_watch: skips used links, skips non-Gulf, caps 3/country (v12.14)
cands = [
    mk_article("SDAIA launches Arabic LLM in Riyadh", "https://x.com/k1", source="TahawulTech"),
    mk_article("PIF backs Humain expansion", "https://x.com/k2", source="Arab News (Business)"),
    mk_article("NEOM cognitive city AI zone", "https://x.com/k3", source="Wamda"),
    mk_article("MGX Dubai AI campus", "https://x.com/u1", source="TahawulTech"),
    mk_article("G42 Abu Dhabi supercomputer", "https://x.com/u2", source="Wamda"),
    mk_article("Mubadala AI fund III", "https://x.com/u3", source="Wamda"),
    mk_article("Egyptian fintech raises", "https://x.com/e1", source="Wamda"),
]
used = {"https://x.com/k1"}  # already picked into a track
gw = agent._select_gulf_watch(cands, used)
check([a["link"] for a in gw] == ["https://x.com/k2", "https://x.com/k3",
                                  "https://x.com/u1", "https://x.com/u2", "https://x.com/u3"],
      "select caps 3/country, skips used links and non-Gulf, keeps rank order")
check(all(a["_gulf_country"] in ("KSA", "UAE") for a in gw), "_gulf_country set on all picks")
check("https://x.com/k2" in used and "https://x.com/u2" in used,
      "used_links mutated so tracks can't double-pick")

# 3. render: strip on top when items exist, absent when empty
html = agent.render_middle_east_block([], gw)
check("Gulf Watch" in html and "Saudi Arabia" in html, "strip renders with country columns")
check("&#x1f1f8;&#x1f1e6;" in html and "&#x1f1e6;&#x1f1ea;" in html, "strip has KSA and UAE flags")
check("PIF backs Humain expansion" in html and 'href="https://x.com/k2"' in html,
      "strip one-liner carries headline and source link")
html_none = agent.render_middle_east_block(
    [(mk_article("Riyadh AI summit", "https://x.com/m"),
      {"headline": "Riyadh hosts AI summit", "tldr": "Big regional moment."})], [])
check("nothing padded" in html_none and "No qualifying KSA/UAE" in html_none,
      "v12.14 honest-empty note renders instead of padding")

# 3b. v12.11: empty country columns are hidden (no dangling headers)
uae_only = [a for a in gw if a["_gulf_country"] == "UAE"]
html_uae = agent.render_middle_east_block([], uae_only)
check("Gulf Watch" in html_uae and "UAE" in html_uae,
      "strip renders with only the UAE column when KSA is empty")
check("Saudi Arabia" not in html_uae, "empty KSA column hidden in web render")
email_uae = agent._email_gulf_watch(uae_only)
check("Gulf Watch" in email_uae and "Saudi Arabia" not in email_uae,
      "empty KSA column hidden in email render")
check('width="100%"' in email_uae, "single email column spans full width")
ksa_only = [a for a in gw if a["_gulf_country"] == "KSA"]
html_ksa = agent.render_middle_east_block([], ksa_only)
check("Saudi Arabia" in html_ksa and "&#x1f1e6;&#x1f1ea;" not in html_ksa,
      "strip renders with only the KSA column when UAE is empty")

# 4. QA helper
st, msg = agent._check_gulf_watch({"middle_east": [], "gulf_watch": gw})
check(st == "PASS", f"gulf QA passes clean picks ({msg})")
st, _ = agent._check_gulf_watch({"middle_east": [gw[0]], "gulf_watch": gw})
check(st == "FAIL", "gulf QA fails when a one-liner duplicates the main list")
bad = mk_article("Berlin AI lab opens", "https://x.com/b1")
bad["_gulf_country"] = "KSA"
st, _ = agent._check_gulf_watch({"middle_east": [], "gulf_watch": [bad]})
check(st == "FAIL", "gulf QA fails on a non-KSA/UAE story in the strip")
st, _ = agent._check_gulf_watch({"middle_east": [], "gulf_watch": []})
check(st == "WARN", "v12.14 gulf QA warns (not passes) when the strip is empty")
ksa_solo = [a for a in gw if a["_gulf_country"] == "KSA"]
st, msg = agent._check_gulf_watch({"middle_east": [], "gulf_watch": ksa_solo})
check(st == "FAIL", f"v12.14 gulf QA fails when a country is missing ({msg})")
one_outlet = [dict(a, source="Wamda") for a in gw if a["_gulf_country"] == "KSA"][:1] + \
             [dict(a, source="Wamda") for a in gw if a["_gulf_country"] == "UAE"][:1]
st, msg = agent._check_gulf_watch({"middle_east": [], "gulf_watch": one_outlet})
check(st == "FAIL", f"v12.14 gulf QA fails when all items share one outlet ({msg})")


# ─── v12.9 TESTS — email-safe HTML for Kit ────────────────────────────────────
banner("v12.9 TESTS — email-safe HTML (Kit broadcasts)")

def _email_fixtures():
    v = mk_article("OpenAI launches reasoning model", "https://x.com/v", source="TechCrunch")
    vd = {"headline": "OpenAI's new reasoning model", "why_you_care": "Cheaper agents for you.",
          "what_happened": "OpenAI shipped it.", "leader_action": "Pilot it."}
    b = (mk_article("Anthropic raises", "https://x.com/b", source="Reuters"),
         {"headline": "Anthropic raises $5B", "why_you_care": "More competition.",
          "what_happened": "Round closed.", "leader_action": "Watch pricing."})
    e = (mk_article("New AI photo app", "https://x.com/e", source="The Verge"),
         {"headline": "Photo app goes viral", "tldr": "Fun app",
          "in_plain_english": "It edits photos.", "why_you_care": "Your team will use it.",
          "what_to_do": "Try it."})
    m = (mk_article("Riyadh AI summit", "https://x.com/m", source="TahawulTech"),
         {"headline": "Riyadh hosts AI summit", "tldr": "Big regional moment."})
    g1 = mk_article("SDAIA launches model", "https://x.com/g1", source="Arab News (Business)")
    g1["_gulf_country"] = "KSA"
    g2 = mk_article("MGX Dubai campus", "https://x.com/g2", source="Wamda")
    g2["_gulf_country"] = "UAE"
    tip = {"title": "Use Projects", "what": "Organize chats", "try_this": "Make one today",
           "link_url": "https://chatgpt.com", "link_label": "Open ChatGPT"}
    return v, vd, b, e, m, [g1, g2], tip

_v, _vd, _b, _e, _m, _gw, _tip = _email_fixtures()
_eh = agent.build_email_html("020", "September 28, 2026", viral=_v, viral_data=_vd,
                             biz_pairs=[_b], eve_pairs=[_e], me_items=[_m],
                             gulf_watch=_gw, tip=_tip)
check("SIGNAL" in _eh and "Issue #020" in _eh, "email html has masthead + issue meta")
for section in ["The Viral Lead", "Strategic Briefing", "From the Region",
                "Consumer Signals", "Tip of the Week"]:
    check(section in _eh, f"email html has section: {section}")
check("01b //" not in _eh, "email html has no take section (v12.10)")
check("Gulf Watch" in _eh and "Saudi Arabia" in _eh, "email html has Gulf Watch strip")
check("Use Projects" in _eh and "Make one today" in _eh, "email html has tip content")
check("Big regional moment." in _eh, "email html has regional item tldr")
check("var(--" not in _eh, "email html has no CSS variables")
check("display:flex" not in _eh and "display: flex" not in _eh, "email html has no flexbox")
check("<table" in _eh, "email html is table-based")
check(agent.PAGES_BASE_URL in _eh, "email html links the archive")
check("Was this forwarded to you?" in _eh and agent.KIT_SIGNUP_URL in _eh,
      "email footer has forwarded-reader subscribe line (Kit URL)")

# escaping
_evil = mk_article("<script>alert(1)</script>", "https://x.com/evil", source="Evil")
_evil_data = {"headline": "<script>alert(1)</script>", "why_you_care": "x",
              "what_happened": "y", "leader_action": "z"}
_eh2 = agent.build_email_html("020", "September 28, 2026",
                             biz_pairs=[(_evil, _evil_data)])
check("<script>" not in _eh2 and "&lt;script&gt;" in _eh2, "email html escapes headlines")

# no gulf -> honest-empty note (v12.14: never pad)
_eh3 = agent.build_email_html("020", "September 28, 2026", me_items=[_m])
check("nothing padded" in _eh3, "email honest-empty Gulf Watch note when no Gulf stories")

# wiring: Kit draft receives the email-safe build, not the web HTML
_captured = {}
_orig_kit = agent.create_kit_broadcast_draft
def _fake_kit(subject, html, preview_text=""):
    _captured.update(subject=subject, html=html, preview=preview_text)
    return "bcast-123"
agent.create_kit_broadcast_draft = _fake_kit
try:
    _bid = agent.maybe_create_kit_draft("020", "September 28, 2026", viral=_v,
                                        viral_data=_vd, biz_pairs=[_b],
                                        eve_pairs=[_e], me_items=[_m],
                                        gulf_watch=_gw, tip=_tip)
finally:
    agent.create_kit_broadcast_draft = _orig_kit
check(_bid == "bcast-123", "maybe_create_kit_draft returns the broadcast id")
check("var(--" not in _captured["html"] and "<table" in _captured["html"],
      "Kit draft carries email-safe HTML, not the web template")
check("SIGNAL #020" in _captured["subject"], "Kit draft subject line is correct")


# ─── v12.14 TESTS — editorial rules + expanded Middle East ────────────────────
banner("v12.14 TESTS — editorial rules + expanded Middle East")

# rule 5: story caps
check(agent.TOP_BUSINESS == 2, "v12.14 cap: 2 strategic stories")
check(agent.TOP_EVERYDAY == 2, "v12.14 cap: 2 consumer stories")
check(agent.TOP_MIDDLE_EAST == 2, "v12.14 cap: 2 regional stories")

# rule 7: placeholders exist and are never written by the agent
check(agent.HASAN_TAKE_PLACEHOLDER in agent.HTML_TEMPLATE,
      "v12.14 web template carries the [HASAN'S TAKE] placeholder")
check(agent.HASAN_ANGLE_PLACEHOLDER in agent.HTML_TEMPLATE,
      "v12.14 web template carries the [HASAN'S ANGLE] placeholder")
_eh_take = agent.build_email_html("020", "September 28, 2026",
                                   viral=_v, viral_data=_vd)
check(agent.HASAN_TAKE_PLACEHOLDER in _eh_take,
      "v12.14 email template carries the [HASAN'S TAKE] placeholder")
check(agent.HASAN_ANGLE_PLACEHOLDER in _eh_take,
      "v12.14 email template carries the [HASAN'S ANGLE] placeholder")

# rule 8: exactly two subscribe blocks + share buttons once, at the end
check(agent.HTML_TEMPLATE.count("{email_capture_top}") == 1 and
      agent.HTML_TEMPLATE.count("{email_capture_bottom}") == 1,
      "v12.14 web template has exactly two subscribe blocks (intro + end)")
check(agent.HTML_TEMPLATE.count("{share_bar}") == 1,
      "v12.14 web template renders share buttons once")
check("{signup_url}" not in agent.HTML_TEMPLATE and
      "{beehiiv_strip_btn}" not in agent.HTML_TEMPLATE and
      "{beehiiv_main_btn}" not in agent.HTML_TEMPLATE and
      "{share_bar_bottom}" not in agent.HTML_TEMPLATE and
      "subscribe-strip" not in agent.HTML_TEMPLATE,
      "v12.14 web template drops LinkedIn strip, Beehiiv buttons, extra share bar")

# rule 8: layout checker on synthetic pages
_good_html = ('<div class="email-capture">a</div><div class="email-capture">b</div>'
              '<div class="share-bar">s</div>'
              f'{agent._h(agent.AUTHOR_TAGLINE)}'
              f'{agent.HASAN_TAKE_PLACEHOLDER}{agent.HASAN_ANGLE_PLACEHOLDER}')
_lc = agent._check_rendered_layout(_good_html, _good_html)
check(all(s == "PASS" for s, _ in _lc), "v12.14 layout checker passes a correct page")
_bad_html = '<div class="email-capture">a</div><div class="share-bar">s</div><div class="share-bar">s2</div>'
_lc2 = agent._check_rendered_layout(_bad_html, _bad_html)
check(any(s == "FAIL" and "subscribe" in m for s, m in _lc2),
      "v12.14 layout checker fails one subscribe block")
check(any(s == "FAIL" and "share-bar" in m for s, m in _lc2),
      "v12.14 layout checker fails two share bars")

# rule 3: realism patterns catch negotiate-with-subject / implement-a-tool
check(any(re.search(p, "negotiate better terms with OpenAI") for p in agent.BANNED_LEADER_ACTION_PATTERNS),
      "v12.14 realism: 'negotiate with X' is banned")
check(any(re.search(p, "implement the new API this week".lower()) for p in agent.BANNED_LEADER_ACTION_PATTERNS),
      "v12.14 realism: 'implement the API' is banned")
check(not any(re.search(p, "ask your team what this means for the renewal budget") for p in agent.BANNED_LEADER_ACTION_PATTERNS),
      "v12.14 realism: legitimate executive actions pass")

# rule 1+2+3+4+6+9: the editorial self-check (hermetic: no link liveness)
_sc_v = mk_article("Anthropic invests $11.6B in Akamai cloud", "https://x.com/deal", source="Reuters")
_sc_vd = {"headline": "Anthropic's $11.6B cloud deal",
          "why_you_care": "Anthropic's $11.6B cloud deal shows scale.",
          "what_happened": "Terms signed.", "leader_action": "Negotiate with Akamai for better rates."}
_sc_tip = {"title": "Use Custom GPT for everything", "what": "Create a custom GPT",
           "try_this": "Do it now", "link_url": agent.TIP_URL_FALLBACK,
           "_tip_url_fallback": True}
_sc = agent._editorial_self_check(_sc_v, _sc_vd, [], [], [], _sc_tip,
                                  {"gulf_watch": []}, check_links=False)
_by_label = {label: (status, detail) for status, label, detail in _sc}
check(_by_label["Deal direction matches the source"][0] == "REVIEW",
      "v12.14 self-check flags deal stories for human direction review")
check(_by_label["No 'Why you care' restates its headline"][0] == "FAIL",
      "v12.14 self-check fails an opener that restates the headline")
check(_by_label["Leader actions pass the 'executive could do this this week?' test"][0] == "FAIL",
      "v12.14 self-check fails a negotiate-with-subject action")
check(_by_label["Gulf Watch has KSA + UAE from different outlets"][0] == "REVIEW",
      "v12.14 self-check reviews an empty Gulf Watch")
check(_by_label["Tip is recent and not basic"][0] == "FAIL",
      "v12.14 self-check fails a basic tip with a fallback link")
check(_by_label["Draft marked DRAFT — pending Hasan's review"][0] == "PASS",
      "v12.14 self-check always records the DRAFT marker")
_g1s = mk_article("SDAIA launches", "https://x.com/k9", source="Arab News")
_g1s["_gulf_country"] = "KSA"
_g2s = mk_article("MGX campus", "https://x.com/u9", source="Wamda")
_g2s["_gulf_country"] = "UAE"
_sc_ok = agent._editorial_self_check(
    None, None,
    [(mk_article("Fine story", "https://x.com/ok", source="Reuters"),
      {"headline": "A fine headline", "why_you_care": "The Gulf angle nobody saw.",
       "what_happened": "It happened.", "leader_action": "Watch the renewal pricing."})],
    [], [],
    {"title": "New Copilot feature", "what": "Try the fresh agents mode",
     "try_this": "Open it", "link_url": "https://support.microsoft.com/x"},
    {"gulf_watch": [_g1s, _g2s]}, check_links=False)
check(all(s == "PASS" for s, _, _ in _sc_ok), "v12.14 self-check passes a clean issue")

# rule 9: review summary leads with DRAFT + the self-check
import tempfile
with tempfile.TemporaryDirectory() as _td:
    agent._write_review_summary(out_dir=_td, publish=False, qa_passed=True,
                                qa_checks=[("PASS", "ok")], issue_number_str="022",
                                today="October 5, 2026", viral=None, tip=None,
                                files=[], self_check=_sc)
    _rs = open(os.path.join(_td, "REVIEW_SUMMARY.md"), encoding="utf-8").read()
check("DRAFT" in _rs and "pending Hasan's review" in _rs,
      "v12.14 review summary carries the DRAFT banner")
check("Editorial self-check" in _rs and _rs.index("Editorial self-check") < _rs.index("QA failures"),
      "v12.14 self-check sits at the top of the review summary")
check("FILL HASAN'S VOICE" in _rs and "DEAL DIRECTION" in _rs,
      "v12.14 review summary lists placeholder + deal-direction human actions")

# rule 4: Google News discovery wires Saudi outlets in as Middle East items
class _FakeEntry(dict):
    """Mimics feedparser's FeedParserDict: attribute + item access."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)
_fake_feed = types.SimpleNamespace(entries=[_FakeEntry({
    "title": "SDAIA announces new Arabic model", "link": "https://news.google.com/rss/articles/x",
    "published_parsed": (datetime.now() - timedelta(days=1)).timetuple(),
    "summary": "Riyadh's AI authority launched a model.",
    "source": {"title": "Arab News"}})])
_orig_parse = agent.feedparser.parse
_orig_resolve = agent._resolve_gnews_link
agent.feedparser.parse = lambda url: _fake_feed
agent._resolve_gnews_link = lambda url, timeout=8: "https://www.arabnews.com/node/123"
try:
    _me_found = agent.fetch_gnews_middle_east(days=7)
finally:
    agent.feedparser.parse = _orig_parse
    agent._resolve_gnews_link = _orig_resolve
check(len(_me_found) == 1 and _me_found[0]["source"] == "Arab News" and
      _me_found[0]["link"] == "https://www.arabnews.com/node/123",
      "v12.14 Google News discovery resolves to the publisher's exact article URL")
check(agent.classify_gulf_country(_me_found[0]) == "KSA",
      "v12.14 Saudi-outlet stories classify as KSA for Gulf Watch")
check("Arab News" in agent.MIDDLE_EAST_SOURCES,
      "v12.14 Google News 'Arab News' counts as a MENA source")

# rule 6: tip URL validation flags fallbacks
check(agent._validate_tip_url("https://not-a-real-site.example/x") == agent.TIP_URL_FALLBACK,
      "v12.14 unrecognized tip URL falls back to the archive URL")

# prompts carry the v12.14 editorial rules
import inspect as _inspect
check("DEAL DIRECTION" in _inspect.getsource(agent.analyze_article),
      "v12.14 accuracy/deal-direction rules are in the analysis prompt")
check("RECENCY RULE" in _inspect.getsource(agent.generate_tip_of_week),
      "v12.14 30-day recency rule is in the tip prompt")
check("V12.14" in _inspect.getsource(agent.analyze_article),
      "v12.14 sourcing preference is in the regional prompt")


# ─── v12.15 TESTS — Threads-native format wired into the agent ────────────────
banner("v12.15 TESTS — Threads-native format (Sep 28 2026 decision)")

check(agent.EXPORT_THREADS is True, "v12.15 EXPORT_THREADS flag is on")

_b2 = (mk_article("MGX commits to Stargate", "https://x.com/b2", source="Bloomberg"),
       {"headline": "MGX backs Stargate with $20B", "why_you_care": "Gulf money shapes AI infra.",
        "what_happened": "Commitment signed.", "leader_action": "Watch the partner list."})

_cwd = os.getcwd()
with tempfile.TemporaryDirectory() as _td:
    os.chdir(_td)
    try:
        _tf = agent.export_threads_post("September 28, 2026", "022",
                                        (_v, _vd), [_b, _b2], [_e], [_m], _tip)
        _tt = open(_tf, encoding="utf-8").read()
    finally:
        os.chdir(_cwd)
check(os.path.basename(_tf).startswith("threads_post_") and _tf.endswith(".md"),
      "v12.15 export writes threads_post_<date>.md")

for _h in ["## POST 1", "## POST 2", "## POST 3", "## POST 4", "## POST 5",
           "MIDWEEK DRIP POSTS", "### Drip 1", "### Drip 2"]:
    check(_h in _tt, f"v12.15 thread has section: {_h}")

# hook-first: POST 1 leads with the viral lead's take, linkless, no promo line
_hook_body = _tt.split("## POST 2")[0]
check("Cheaper agents for you" in _hook_body,
      "v12.15 hook leads with the viral story's take")
check("http" not in _hook_body and "issue is out" not in _tt.lower(),
      "v12.15 hook is linkless and never says the issue is out")
check("🧵" in _hook_body, "v12.15 hook marks the thread")

# one story per reply
for _headline in ["Anthropic raises $5B", "Photo app goes viral", "Riyadh hosts AI summit"]:
    check(_headline in _tt, f"v12.15 story reply carries: {_headline}")
check("→ " in _tt, "v12.15 story replies carry the leader action")

# the newsletter URL appears exactly once, and only in the final reply
_post5 = _tt.split("## POST 5")[1]
check(_tt.count("http") == 2,
      "v12.15 file has exactly two URLs (issue link + subscribe)")
check("http" in _post5 and "http" not in _tt.split("## POST 5")[0],
      "v12.15 links live ONLY in the final reply")
check(agent.PAGES_BASE_URL in _post5,
      "v12.15 final reply links the issue archive")

# drip posts are standalone and linkless
_drips = _tt.split("MIDWEEK DRIP POSTS")[1]
check("http" not in _drips, "v12.15 drip posts are linkless")
check("MGX backs Stargate" in _drips, "v12.15 drip posts reuse leftover stories")

# sanitizer strips URLs that slip into story copy (end-to-end)
_evil_data = dict(_vd); _evil_data["why_you_care"] = "See https://evil.example/x for details."
with tempfile.TemporaryDirectory() as _td2:
    os.chdir(_td2)
    try:
        _tf2 = agent.export_threads_post("September 28, 2026", "022",
                                         (_v, _evil_data), [_b], [_e], [_m], _tip)
        _tt2 = open(_tf2, encoding="utf-8").read()
    finally:
        os.chdir(_cwd)
check("evil.example" not in _tt2.split("## POST 5")[0],
      "v12.15 URL sanitizer strips links from linkless posts")

# empty issue: fail-closed, no thread generated
with tempfile.TemporaryDirectory() as _td3:
    os.chdir(_td3)
    try:
        _tf3 = agent.export_threads_post("September 28, 2026", "022",
                                         None, [], [], [], None)
        _tt3 = open(_tf3, encoding="utf-8").read()
    finally:
        os.chdir(_cwd)
check("No stories qualified" in _tt3,
      "v12.15 empty issue writes a skipped-thread note, not a thread")

# helper units: truncation keeps posts within the Threads limit
check(len(agent._threads_trunc("word " * 400)) <= agent.THREADS_POST_MAX and
      agent._threads_trunc("word " * 400).endswith("…"),
      "v12.15 _threads_trunc caps post length safely")

# wiring: the pipeline calls the export
import inspect as _inspect2
check("export_threads_post" in _inspect2.getsource(agent.generate_newsletter),
      "v12.15 generate_newsletter calls export_threads_post")


# ─── SUMMARY ─────────────────────────────────────────────────────────────────
print("=" * 60)
print(f"  RESULT: {passed} passed, {failed} failed")
print("=" * 60)
if failed == 0:
    print("ALL v10 TESTS PASSED")
else:
    print(f"SOME TESTS FAILED ({failed})")
    sys.exit(1)


# ─── pytest bridge ───────────────────────────────────────────────────────────
# The module-level checks above ARE the suite (run by `python test_v10.py`,
# as the CI workflow does). This gives `python -m pytest` a real test to
# collect so it reports a genuine pass instead of "no tests ran".

def test_v11_custom_suite_passed():
    assert failed == 0, f"{failed} check(s) failed in the custom suite"
