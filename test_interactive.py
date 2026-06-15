"""Quick interactive mode test — sends one message and exits."""
import sys, os
sys.path.insert(0, "src")

from next_agent.agent import Agent, AgentConfig
from next_agent.llm import LLMConfig

key = os.environ.get("DEEPSEEK_API_KEY", "")
if not key:
    print("❌ DEEPSEEK_API_KEY not set")
    sys.exit(1)

agent = Agent(
    config=AgentConfig(
        model="deepseek-v4-flash",
        workdir=".",
        stream=False,  # non-streaming for clean test
    ),
    llm_config=LLMConfig(
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com/v1",
        api_key=key,
    ),
)

print("=== Interactive Mode Test ===\n")

# Test 1: First message (builds prefix)
print("> List the Python files in src/next_agent/")
r1 = agent.chat("List the Python files in src/next_agent/")
print(f"\n{r1[:400]}")
print(f"\n--- State: prefix={agent._prefix_built}, msgs={len(agent.messages)}")

# Test 2: Follow-up (cache should hit)
print("\n\n> What does the agent.py file do?")
r2 = agent.chat("What does the agent.py file do?")
print(f"\n{r2[:400]}")
print(f"\n--- State: msgs={len(agent.messages)}")

# Test 3: Check reasoning
if agent.reasoning.history:
    print(f"\n✅ Reasoning extraction: {len(agent.reasoning.history)} blocks found")
    for rb in agent.reasoning.history:
        print(f"  [{rb.turn}] {rb.content[:120]}...")
else:
    print("\n⚠️ No reasoning blocks detected")

# Cache stats
print(f"\n--- Cache Stats ---")
for i, r in enumerate(agent.cache_dash.rounds):
    print(f"  Round {i+1}: {r.hit_rate:.0%} hit, ${r.saved_cost:.4f} saved, {r.elapsed_ms:.0f}ms")
print(f"  Total saved: ${agent.cache_dash.total_saved:.4f}")
