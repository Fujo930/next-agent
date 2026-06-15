"""Test: Does DeepSeek output REASONING blocks when prompted?"""
import sys, os
sys.path.insert(0, "src")

from next_agent.llm import LLMConfig, LLMAdapter
from next_agent.reasoning import REASONING_PROMPT

key = os.environ.get("DEEPSEEK_API_KEY", "")
if not key:
    print("❌ DEEPSEEK_API_KEY not set in environment")
    sys.exit(1)

cfg = LLMConfig(model="deepseek-v4-flash", base_url="https://api.deepseek.com/v1", api_key=key)
llm = LLMAdapter(cfg)

# Include the full REASONING_PROMPT in the system message
system = "You are a coding agent. Be concise.\n\n" + REASONING_PROMPT

resp = llm.chat(
    messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": "Read and analyze src/next_agent/tools/files.py for bugs. Call read_file first."},
    ],
    tools=[{
        "type": "function",
        "function": {
            "name": "read_file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    }],
    tool_choice="auto",
    max_tokens=500,
)

content = resp.content or ""
print("=" * 60)
print("CONTENT:")
print(content[:600])
print("=" * 60)

if "REASONING" in content.upper():
    print("\n✅ YES — DeepSeek outputs REASONING blocks!")
    # Show the reasoning
    import re
    m = re.search(r"REASONING:\s*\n?(.*?)(?=\n\n|\n?$)", content, re.DOTALL | re.IGNORECASE)
    if m:
        print(f"\nExtracted reasoning: {m.group(1).strip()[:300]}")
else:
    print("\n❌ NO — DeepSeek did not output a REASONING block")
    print("May need stronger prompt wording or different model")

print(f"\nTool calls: {len(resp.tool_calls)}")
for tc in resp.tool_calls:
    print(f"  → {tc.name}({list(tc.arguments.keys())})")
print(f"Time: {resp.elapsed_ms:.0f}ms")
