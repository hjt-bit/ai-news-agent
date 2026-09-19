"""
SIGNAL Agent v10 — Test Suite
Hermetic tests for the v10 fail-closed pipeline: review gate, prompt-injection
hardening, fact-check UNVERIFIED/CONTRADICTED, HTML escaping, tip URL
validation, single-analysis, QA enforcement, take placeholder, social
derivatives, and build_index.

No live network calls: DuckDuckGo search is monkey-patched out everywhere.
Run: python3 test_v10.py
"""

import copy
import json
import os
import sys
import types

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
RAISE_ON = None          # set to a prompt substring to simulate an LLM failure
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
            return FakeResponse('{"headline": "Test Headline", "tldr": "Test summary", "what_happened": "Something happened", "why_it_matters": "It matters because", "business_impact": "Impact on business", "leader_action": "Take this action"}')
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
import agent as agent

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
check(hasattr(agent, "TAKE_MODE"), "TAKE_MODE placeholder config exists")
check(hasattr(agent, "AUTHOR_NAME"), "AUTHOR_NAME TODO field exists")
check(hasattr(agent, "BEEHIIV_API_KEY"), "BEEHIIV_API_KEY placeholder exists")
check(hasattr(agent, "SYSTEM_GUARD"), "SYSTEM_GUARD prompt-injection guard exists")
check(callable(agent.parse_args), "parse_args() exists")
check(callable(agent.get_hasan_take), "get_hasan_take() exists")
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

class _FakeHTTPResp:
    def __init__(self, html): self._html = html
    def read(self): return self._html.encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *a): return False

orig_urlopen = urllib.request.urlopen
FAKE_SEARCH_HTML = ""
def _fake_urlopen(req, timeout=10):
    if FAKE_SEARCH_HTML == "__RAISE__":
        raise OSError("simulated network failure")
    return _FakeHTTPResp(FAKE_SEARCH_HTML)
urllib.request.urlopen = _fake_urlopen
reset_flags()

def _result_div(url, title):
    return f'<div class="result__title"><a href="{url}">{title}</a></div>'

# 5a: honest corroboration — self-source excluded, irrelevant results ignored.
#     Claim from "OpenAI Blog": reuters corroborates (2+ token overlap);
#     openai.com is the story's own outlet (excluded); recipe blog ignored.
FAKE_SEARCH_HTML = (
    _result_div("https://www.reuters.com/tech/openai-model", "OpenAI launches new reasoning model today")
    + _result_div("https://www.bloomberg.com/ai", "OpenAI launches new reasoning model today")
    + _result_div("https://openai.com/blog/new-model", "OpenAI launches new reasoning model today")
    + _result_div("https://recipes.example.com/x", "Best chocolate cake recipe for birthdays")
)
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
FAKE_SEARCH_HTML = _result_div("https://www.reuters.com/x",
                               "OpenAI model safety claims debunked by researchers")
corr, contra, ok = agent._search_corroboration("OpenAI model safety claims validated", "Some Blog")
check(ok is True and len(contra) == 1, "contradiction signal detected")
v, _ = agent.fact_check_stories(
    mk_article("OpenAI model safety claims validated", "https://x.com/v2"),
    {"business": [], "everyday": [], "middle_east": []})
check(v["_fact_check"]["confidence"] == "CONTRADICTED", "contradiction -> CONTRADICTED")

# 5c: search failure -> UNVERIFIED (never LOW-pass), run flagged
FAKE_SEARCH_HTML = "__RAISE__"
reset_flags()
v, _ = agent.fact_check_stories(
    mk_article("Some AI story", "https://x.com/v3"),
    {"business": [], "everyday": [], "middle_east": []})
check(v["_fact_check"]["confidence"] == "UNVERIFIED", "search failure -> UNVERIFIED (not LOW)")
check(agent.RUN_FLAGS["fact_check_degraded"] is True, "search failure flags the run")
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

# ─── TEST 7: QA — fact-check confidence blocks publish ───────────────────────
banner("v10 TEST 7 — QA fact-check enforcement")
check(agent.FACT_CHECK_MIN_CONFIDENCE == "MEDIUM", "FACT_CHECK_MIN_CONFIDENCE default is MEDIUM (reject unverifiable)")
for conf in ("UNVERIFIED", "CONTRADICTED"):
    reset_flags()
    viral, picks, tip = passing_fixture(confidence=conf)
    qa_passed, _ = agent.run_qa_checks(viral, picks, tip, [])
    check(qa_passed is False, f"{conf} always blocks publish")
reset_flags()
viral, picks, tip = passing_fixture(confidence="LOW")
qa_passed, qa_checks = agent.run_qa_checks(viral, picks, tip, [])
check(qa_passed is False, "LOW blocks publish when minimum is MEDIUM")
# The constant is actually enforced: flip it to LOW and LOW only warns.
orig_min = agent.FACT_CHECK_MIN_CONFIDENCE
agent.FACT_CHECK_MIN_CONFIDENCE = "LOW"
reset_flags()
viral, picks, tip = passing_fixture(confidence="LOW")
qa_passed, qa_checks = agent.run_qa_checks(viral, picks, tip, [])
agent.FACT_CHECK_MIN_CONFIDENCE = orig_min
warns = [m for s, m in qa_checks if s == "WARN" and "Fact-check" in m]
check(qa_passed is True and warns, "FACT_CHECK_MIN_CONFIDENCE=LOW makes LOW-confidence only warn")
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

# ─── TEST 12: Take placeholder slot ──────────────────────────────────────────
banner("v10 TEST 12 — Hasan's Take placeholder")
take = agent.get_hasan_take(mk_article("V", "https://x.com/v"), {})
check(take.get("mode") == "placeholder", "default TAKE_MODE is placeholder")
take_html = agent.render_take_block(take)
check("to be written at review" in take_html, "placeholder block rendered after viral lead")
written = {"mode": "written", "text": "My <b>opinion</b> here."}
take_html2 = agent.render_take_block(written)
check("<b>opinion</b>" not in take_html2 and "&lt;b&gt;" in take_html2,
      "written take text is escaped")

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

# ─── SUMMARY ─────────────────────────────────────────────────────────────────
print("=" * 60)
print(f"  RESULT: {passed} passed, {failed} failed")
print("=" * 60)
if failed == 0:
    print("ALL v10 TESTS PASSED")
else:
    print(f"SOME TESTS FAILED ({failed})")
    sys.exit(1)
