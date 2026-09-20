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
