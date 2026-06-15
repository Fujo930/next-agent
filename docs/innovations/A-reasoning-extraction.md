# A — 推理提取层 (Reasoning Extraction Layer)

## 解决的问题

DeepSeek v4 没有 Claude 的 extended thinking 功能。当 DeepSeek 调用一个错误工具时，你看不到它的推理过程，无法 debug。
Reasonix 和 CodeWhale 都只做 retry，没有试图让 DeepSeek 暴露思考链。

## 方案

在 system prompt 中要求 DeepSeek 在每次工具调用前输出结构化推理块。agent 层拦截推理块并存为 session state。

### 三层设计

```
Layer 1 — Prompt Injection
  system prompt 中加入:
  "Before ANY tool call, output a REASONING block:
   ```
   REASONING:
   - What I know: [current state / file contents / errors]
   - What I need: [what tool to call and why]
   - Expected outcome: [what result I expect]
   ```"

Layer 2 — Output Interception
  agent loop 中解析 LLM 输出:
  if response.content starts with "REASONING:":
      parse reasoning block → store in session.reasoning_history
      continue to tool calls as normal

Layer 3 — Reasoning Validation
  推理内容 vs 实际行为对比:
  if reasoning says "read auth.py" but tool call is write_file("/etc/passwd"):
      → BLOCK with explanation "Your reasoning doesn't match your action"
  if reasoning says "fix import error" but tool call is unrelated refactor:
      → WARN "Detected creative drift — sticking to stated goal"
```

## 实现细节

```python
class ReasoningExtractor:
    """Extracts and validates reasoning blocks from LLM output."""

    PATTERN = r"REASONING:\s*\n(.*?)(?=\nTool call|\nASSISTANT:|\Z)"
    
    def extract(self, text: str) -> tuple[str | None, str]:
        """Returns (reasoning, rest_of_text) or (None, original)."""
        match = re.search(self.PATTERN, text, re.DOTALL)
        if match:
            return match.group(1).strip(), text[match.end():].strip()
        return None, text

    def validate_against_tool_calls(
        self, reasoning: str, tool_calls: list[ToolCall]
    ) -> list[Warning]:
        """Check if tool calls contradict stated reasoning."""
        warnings = []
        mentioned_files = re.findall(r'[\w./]+\.\w+', reasoning)
        for tc in tool_calls:
            if tc.name in ("write_file", "edit_file"):
                path = tc.arguments.get("path", "")
                if path not in mentioned_files:
                    warnings.append(
                        Warning(f"Writing to {path} but reasoning "
                                f"never mentioned this file")
                    )
        return warnings
```

## 优势

- 不需要模型支持 extended thinking
- 纯 prompt 工程 + 文本解析
- 推理链可持久化，后续回合可引用
- 用户可以看到 agent 的思考过程 → 建立信任

## 风险

- 吃上下文（推理块本身占 tokens）
- DeepSeek 可能 format 不对（跳过推理直接调工具）
- 缓解：如果格式不对，优雅降级——不影响正常功能
