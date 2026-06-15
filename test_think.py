"""Test: Does DeepSeek use the 'think' tool when prompted?"""
import sys, os
sys.path.insert(0, "src")

from next_agent.agent import Agent, AgentConfig
from next_agent.llm import LLMConfig

key = os.environ.get("DEEPSEEK_API_KEY", "")
if not key:
    print("❌ DEEPSEEK_API_KEY not set")
    sys.exit(1)

agent = Agent(
    config=AgentConfig(model="deepseek-v4-flash", workdir=".", stream=False),
    llm_config=LLMConfig(
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com/v1",
        api_key=key,
    ),
)

print("=== Think Tool Test ===\n")
print("Prompt: 'Read compress.py and find any bugs. Think before acting.'\n")

response = agent.chat("Read src/next_agent/compress.py, analyze it for bugs. Use the think tool to plan your analysis before reading.")

print(f"Response: {response[:500]}")
print(f"\n--- Check think tool usage ---")

# Check if think tool was called
think_called = False
for msg in agent.messages:
    if msg.get("role") == "tool":
        content = msg.get("content", "")
        if "Thinking" in content or "_thought" in content:
            think_called = True
            print(f"✅ Think tool was used!")

if not think_called:
    print(f"❌ Think tool was NOT used")

# Check reasoning history
if agent.reasoning.history:
    print(f"\n✅ Reasoning captured: {len(agent.reasoning.history)} blocks")
    for rb in agent.reasoning.history:
        print(f"  [{rb.turn}] {rb.content[:200]}...")
else:
    print(f"\n⚠️ No reasoning blocks in history")

# Cache
print(f"\n--- Cache ---")
for i, r in enumerate(agent.cache_dash.rounds):
    print(f"  R{i+1}: {r.hit_rate:.0%} hit, {r.elapsed_ms:.0f}ms")
