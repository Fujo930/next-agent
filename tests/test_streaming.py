"""Test streaming support for Next Agent LLM adapter.

Runs a real API call to deepseek-v4-flash with streaming enabled.
Prints incremental output as it arrives, confirming streaming works.
"""
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def main():
    # Load API key
    api_key_file = Path(__file__).parent / ".api_key"
    if api_key_file.exists():
        api_key = api_key_file.read_text().strip()
        os.environ["DEEPSEEK_API_KEY"] = api_key
        print(f"✓ Loaded API key from {api_key_file}")
    else:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            print("✗ No API key found. Set DEEPSEEK_API_KEY or create .api_key")
            sys.exit(1)
        print("✓ Using DEEPSEEK_API_KEY from environment")

    from next_agent.llm import LLMAdapter, LLMConfig

    config = LLMConfig.from_env("deepseek-v4-flash")
    if not config.api_key:
        config.api_key = api_key
    adapter = LLMAdapter(config)

    print(f"\n{'='*60}")
    print("Test 1: Non-streaming chat (baseline)")
    print("=" * 60)
    resp = adapter.chat(
        messages=[{"role": "user", "content": "Say hello in exactly 3 words."}],
        max_tokens=50,
    )
    print(f"Response: {resp.content}")
    print(f"Tokens: {resp.usage.get('total_tokens', 'N/A')}")
    print(f"Elapsed: {resp.elapsed_ms:.0f}ms")

    print(f"\n{'='*60}")
    print("Test 2: Streaming chat (incremental output)")
    print("=" * 60)
    print("Streaming: ", end="", flush=True)
    
    final = None
    for chunk in adapter.chat_stream(
        messages=[{"role": "user", "content": "Count from 1 to 5, one per line."}],
        max_tokens=100,
    ):
        if chunk.type == "content":
            print(chunk.content, end="", flush=True)
        elif chunk.type == "done":
            final = chunk
    
    print()  # trailing newline
    if final:
        print(f"Finish reason: {final.finish_reason}")
        print(f"Tokens: {final.usage.get('total_tokens', 'N/A')}")
        print(f"Elapsed: {final.elapsed_ms:.0f}ms")
        print(f"Content length: {len(final.content)} chars")
    
    print(f"\n{'='*60}")
    print("Test 3: Streaming with tool calls (if supported)")
    print("=" * 60)
    tools = [{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"}
                },
                "required": ["city"]
            }
        }
    }]
    
    print("Streaming: ", end="", flush=True)
    final2 = None
    for chunk in adapter.chat_stream(
        messages=[{"role": "user", "content": "What's the weather in Tokyo?"}],
        tools=tools,
        max_tokens=100,
    ):
        if chunk.type == "content":
            print(chunk.content, end="", flush=True)
        elif chunk.type == "done":
            final2 = chunk
    
    print()
    if final2:
        print(f"Finish reason: {final2.finish_reason}")
        print(f"Tool calls: {len(final2.tool_calls)}")
        for tc in final2.tool_calls:
            print(f"  - {tc.name}({tc.arguments})")
        print(f"Content: {final2.content if final2.content else '(none)'}")

    print(f"\n{'='*60}")
    print("✅ All streaming tests completed!")
    print("=" * 60)

if __name__ == "__main__":
    main()
