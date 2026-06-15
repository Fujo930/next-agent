"""v0.1 Comprehensive Test Suite — run from PowerShell with DEEPSEEK_API_KEY set."""
import sys, os, time
sys.path.insert(0, "src")

from next_agent.agent import Agent, AgentConfig
from next_agent.llm import LLMConfig

KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not KEY:
    print("ERROR: DEEPSEEK_API_KEY not set")
    print("Run: $env:DEEPSEEK_API_KEY='sk-...'")
    sys.exit(1)

passed = 0
failed = 0
total_time = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name} — {detail}")
        failed += 1

def make_agent(**kw):
    cfg = AgentConfig(model="deepseek-v4-flash", workdir=".", **kw)
    return Agent(config=cfg, llm_config=LLMConfig(model="deepseek-v4-flash", base_url="https://api.deepseek.com/v1", api_key=KEY))

print("=" * 60)
print("  Next Agent v0.1 — Comprehensive Test Suite")
print("=" * 60)

# ─────────────────────────────────────────────────────
# 1. BASIC CONNECTIVITY
# ─────────────────────────────────────────────────────
print("\n─── 1. Basic Connectivity ───")
t0 = time.time()
agent = make_agent()
resp = agent.chat("Say 'hello' in exactly one word.")
elapsed = time.time() - t0
check("API responds", "hello" in resp.lower() or "hi" in resp.lower() or "ok" in resp.lower(), resp[:50])
check("Prefix built", agent._prefix_built)
check("Cache recorded", len(agent.cache_dash.rounds) == 1, f"rounds={len(agent.cache_dash.rounds)}")

# ─────────────────────────────────────────────────────
# 2. TOOL CALLING
# ─────────────────────────────────────────────────────
print("\n─── 2. Tool Calling ───")
t0 = time.time()
agent2 = make_agent()
resp2 = agent2.chat("List the files in src/next_agent/ — show only Python files.")
elapsed = time.time() - t0
check("Tool call executed", ".py" in resp2, "no Python files in response")
check("Multi-turn OK", len(agent2.messages) >= 2)

# ─────────────────────────────────────────────────────
# 3. STREAMING
# ─────────────────────────────────────────────────────
print("\n─── 3. Streaming ───")
t0 = time.time()
agent3 = make_agent(stream=True)
# Capture streaming output by redirecting
import io
old_stdout = sys.stdout
sys.stdout = io.StringIO()
resp3 = agent3.chat("Count from 1 to 3. One word per line.")
stream_output = sys.stdout.getvalue()
sys.stdout = old_stdout
elapsed = time.time() - t0
check("Stream produces output", len(stream_output) > 0 or len(resp3) > 0, f"stream={len(stream_output)} chars")
check("Agent completes", len(agent3.messages) >= 2)

# ─────────────────────────────────────────────────────
# 4. THINK TOOL (A)
# ─────────────────────────────────────────────────────
print("\n─── 4. Think Tool (A) ───")
agent4 = make_agent()
resp4 = agent4.chat("Read src/next_agent/llm.py, analyze it for potential issues. Use the think tool first.")
check("Think tool used", len(agent4.reasoning.history) > 0, "no reasoning blocks")
think_text = ""
if agent4.reasoning.history:
    think_text = agent4.reasoning.history[0].content
    check("Reasoning has content", len(think_text) > 20)

# ─────────────────────────────────────────────────────
# 5. PREFIX CACHE (D)
# ─────────────────────────────────────────────────────
print("\n─── 5. Cache Dashboard (D) ───")
agent5 = make_agent()
agent5.chat("What is 2+2?")
agent5.chat("What is 3+3?")
rounds = agent5.cache_dash.rounds
check("2 rounds recorded", len(rounds) >= 2, f"{len(rounds)} rounds")
if len(rounds) >= 2:
    r1, r2 = rounds[-2], rounds[-1]
    check("Cache hit rate > 0", r2.hit_rate > 0, f"hit_rate={r2.hit_rate:.1%}")
    check("Cost saved tracked", agent5.cache_dash.total_saved >= 0)

# ─────────────────────────────────────────────────────
# 6. SECURITY: ALLOWED-TOOLS
# ─────────────────────────────────────────────────────
print("\n─── 6. Allowed-Tools Enforcement ───")
from next_agent.agent import _parse_allowed_tools, _is_tool_allowed, _filter_tools_for_command
from next_agent.tools.registry import ALL_TOOL_SCHEMAS

allowed = _parse_allowed_tools("bash(git add *), bash(git commit *)")
check("Parse allowed-tools", "bash" in allowed)
check("Allow git add", _is_tool_allowed("bash", {"command": "git add ."}, allowed))
check("Deny rm -rf", not _is_tool_allowed("bash", {"command": "rm -rf /"}, allowed))
check("Deny write_file", not _is_tool_allowed("write_file", {"path": "x.py"}, allowed))
filtered = _filter_tools_for_command(ALL_TOOL_SCHEMAS, allowed)
filtered_names = [t["function"]["name"] for t in filtered]
check("Only bash+think in filtered", set(filtered_names) <= {"bash", "think"}, f"got {filtered_names}")

# ─────────────────────────────────────────────────────
# 7. CROSS-FILE GUARD (C)
# ─────────────────────────────────────────────────────
print("\n─── 7. Cross-File Guard (C) ───")
from next_agent.cross_file import CrossFileGuard
import tempfile, pathlib

with tempfile.TemporaryDirectory() as tmp:
    a = pathlib.Path(tmp) / "a.py"
    b = pathlib.Path(tmp) / "b.py"
    a.write_text("def good(): pass\n")
    b.write_text("from a import bad_function_that_does_not_exist\n")
    guard = CrossFileGuard(tmp)
    guard.before_edits([str(b)])
    issues = guard.after_edits([str(b)])
    check("Detects import mismatch", len(issues) >= 1, f"{len(issues)} issues")
    check("Error severity", any(i.severity == "error" for i in issues) if issues else False)

# ─────────────────────────────────────────────────────
# 8. COMPRESSION (G)
# ─────────────────────────────────────────────────────
print("\n─── 8. Progressive Compression (G) ───")
from next_agent.compress import ProgressiveCompressor, CompressionLevel
comp = ProgressiveCompressor(max_tokens=5000)
check(">50% → Level1", comp.check(3000) == CompressionLevel.LEVEL1)
check(">65% → Level2", comp.check(4000) == CompressionLevel.LEVEL2)
check(">85% → Checkpoint", comp.check(4500) == CompressionLevel.CHECKPOINT)
result = comp._compress_level1('{"ok":true,"output":"42 lines in file.py. Error: something wrong. exit code 1."}')
check("Preserves file names", "file.py" in result)
check("Preserves error", "something wrong" in result)

# ─────────────────────────────────────────────────────
# 9. JOB MANAGER
# ─────────────────────────────────────────────────────
print("\n─── 9. JobManager ───")
from next_agent.jobs import JobManager, JobStatus
mgr = JobManager()
def ok(): return {"ok": True}
jid = mgr.enqueue("test", ok)
j = mgr.run(jid)
check("Job completes", j.status == JobStatus.COMPLETED)
check("Job history", len(j.history) >= 2)

retries = 0
def fail_twice():
    global retries; retries += 1
    if retries < 3: raise RuntimeError("fail")
    return {"ok": True}
jid2 = mgr.enqueue("retry", fail_twice, max_attempts=3)
j2 = mgr.run(jid2)
check("Exponential backoff", j2.attempts == 2 and j2.status == JobStatus.COMPLETED)

# ─────────────────────────────────────────────────────
# 10. COST-AWARE ROUTING (I)
# ─────────────────────────────────────────────────────
print("\n─── 10. Cost-Aware Routing (I) ───")
from next_agent.turbo import ModelRouter
router = ModelRouter()
check("Simple → flash", router.select("fix typo").model == "deepseek-v4-flash")
check("Complex CN → pro", router.select("设计支付系统架构").model == "deepseek-v4-pro")
check("Security → pro", router.select("audit security vulnerabilities").model == "deepseek-v4-pro")

# ─────────────────────────────────────────────────────
print("\n" + "=" * 60)
print(f"  RESULTS: {passed}/{passed+failed} passed")
if failed:
    print(f"  ❌ {failed} tests failed")
else:
    print(f"  ✅ ALL TESTS PASSED")
print("=" * 60)
