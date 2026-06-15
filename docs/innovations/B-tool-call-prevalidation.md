# B — 工具调用预验证 (Tool Call Pre-validation)

## 解决的问题

DeepSeek 的 function calling 正确率 ~90%（Claude ~97%）。常见失败模式：
- JSON 解析失败（返回裸字符串、未转义引号）
- 参数名混淆（search_files 的 pattern 写成 query）
- 缺少必填参数（read_file 没有 path）
- 调用不存在的工具名

Reasonix 和 CodeWhale 只做 retry-on-error，不做预验证。

## 方案：执行前校验门

```
LLM 返回 tool_calls
    ↓
[预验证门] — 6 层检查，任何一层失败 → 发回 LLM 重试
    ↓
[执行]
```

### 6 层检查

| 层 | 检查内容 | 失败策略 |
|----|---------|---------|
| 1. JSON | 每个 tool_call.arguments 能否 parse | 尝试修复（加引号、修括号）→ 失败则 retry |
| 2. Schema | 参数名匹配 tool schema 定义 | 模糊匹配参数名 → 失败则 retry |
| 3. Required | 必填参数是否存在 | 补默认值 → 失败则 retry |
| 4. Type | 参数类型是否正确 | 强制转换 → 失败则 retry |
| 5. Safety | 危险操作检查 | BLOCK（不 retry，让用户确认）|
| 6. Duplicate | 是否重复调用（同参数） | 返回缓存结果，不执行 |

### 实现

```python
class ToolValidator:
    """Pre-execution validation pipeline for DeepSeek tool calls."""

    def __init__(self, tool_registry: ToolRegistry, safety_rules: list[SafetyRule]):
        self.registry = tool_registry
        self.safety = safety_rules  # e.g., block "rm -rf /"

    def validate(self, tool_call: ToolCall) -> ValidationResult:
        # 1. JSON parse with error recovery
        try:
            args = json.loads(tool_call.arguments)
        except json.JSONDecodeError:
            args = self._try_recover_json(tool_call.arguments)
            if args is None:
                return ValidationResult.retry(
                    f"Invalid JSON in arguments: {tool_call.arguments}")

        # 2. Schema check — does this tool exist?
        schema = self.registry.get_schema(tool_call.name)
        if not schema:
            nearest = self.registry.find_nearest_tool(tool_call.name)
            return ValidationResult.retry(
                f"Unknown tool '{tool_call.name}'. "
                f"Did you mean '{nearest}'?" if nearest else
                f"Unknown tool '{tool_call.name}'")

        # 3. Required params
        required = schema.get("required", [])
        missing = [p for p in required if p not in args]
        if missing:
            return ValidationResult.retry(
                f"Missing required parameters: {missing}")

        # 4. Type coercion
        coerced = self._coerce_types(args, schema["properties"])
        if coerced.errors:
            return ValidationResult.retry(
                f"Type errors: {coerced.errors}")

        # 5. Safety check
        for rule in self.safety:
            if rule.matches(tool_call.name, coerced.args):
                return ValidationResult.block(
                    f"BLOCKED by safety rule '{rule.name}': {rule.reason}")

        return ValidationResult.ok(coerced.args)

    def _try_recover_json(self, text: str) -> dict | None:
        """Common DeepSeek JSON errors: bare strings, unquoted keys."""
        # Try: "ls -la" → {"command": "ls -la"}
        # ... heuristics for common patterns
        pass

    def _coerce_types(self, args, schema):
        """Force string→int, int→float, etc. based on schema."""
        pass
```

## 安全规则系统

```python
SAFETY_RULES = [
    SafetyRule(
        name="no-rm-rf-root",
        tool="bash",
        pattern=r"rm\s+-rf\s+/",
        reason="Destructive filesystem operation"
    ),
    SafetyRule(
        name="no-system-write",
        tool="write_file",
        path_pattern="/etc/|/System/|C:\\\\Windows\\\\",
        reason="Writing to system directories"
    ),
    SafetyRule(
        name="no-credential-leak",
        tool="write_file",
        content_pattern=r"sk-[a-zA-Z0-9]{20,}",
        reason="API key detected in output"
    ),
]
```

## 优势

- 失败不消耗工具执行时间/副作用
- 模糊匹配工具名 → LLM 更宽容
- 类型强制转换 → 减少不必要的 retry
- 安全规则前置 → 危险操作永远不会执行

## 与其他创新的关系

- 依赖于 H (确定性补丁引擎) 的去重缓存
- 为 A (推理提取) 提供验证数据
