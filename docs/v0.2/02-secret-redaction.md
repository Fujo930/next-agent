# K — Secret Redaction (密钥自动脱敏)

## 借鉴 Hermes

Hermes 的 `security.redact_secrets` 默认开启。所有工具输出（terminal stdout、read_file、web content、subagent summaries）在被注入对话上下文前，扫描并脱敏密钥模式。

## 当前状态

Next Agent v0.1 只在 `list_dir` 和 `workspace.py` 中过滤了 `.api_key` 等文件名。但以下场景仍泄露：

- `read_file(".env")` → 直接读出 `DEEPSEEK_API_KEY=sk-...`
- `bash("cat config.json")` → 可能包含密钥
- `web_search` 结果 → 可能包含落地页的示例密钥
- 子代理输出 → 未经过滤

## 方案

系统级 redactor，在所有工具结果进入 `messages` 前扫描。

### 实现

```python
class SecretRedactor:
    """Scans and redacts secrets from tool output."""

    PATTERNS = [
        # API keys: sk-..., ghp_..., etc.
        (r'(sk|pk|rk)-(?:[a-zA-Z0-9]{4,}-){0,5}[a-zA-Z0-9]{4,}', '[REDACTED_KEY]'),
        # GitHub tokens: ghp_..., gho_..., github_pat_...
        (r'gh[poat]_[a-zA-Z0-9]{16,}', '[REDACTED_GH_TOKEN]'),
        # OpenAI keys: sk-proj-..., sk-admin-...
        (r'sk-(?:proj|admin|org)-[a-zA-Z0-9]{16,}', '[REDACTED_OPENAI_KEY]'),
        # AWS keys: AKIA...
        (r'AKIA[0-9A-Z]{16}', '[REDACTED_AWS_KEY]'),
        # JWT tokens: eyJ...
        (r'eyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{10,}', '[REDACTED_JWT]'),
        # Generic key=value with 'secret' or 'password'
        (r'(?:secret|password|token|api[_-]?key)\s*[:=]\s*\S+', '[REDACTED_CREDENTIAL]'),
        # Private key markers
        (r'-----BEGIN (?:RSA|EC|DSA|OPENSSH) PRIVATE KEY-----', '[REDACTED_PRIVATE_KEY]'),
    ]

    def redact(self, text: str) -> tuple[str, int]:
        """Returns (redacted_text, count_of_redactions)."""
        count = 0
        for pattern, replacement in self.PATTERNS:
            new_text, n = re.subn(pattern, replacement, text, flags=re.IGNORECASE)
            count += n
            text = new_text
        return text, count
```

### 接入点

在 `agent.py` 的 `_execute_tool` 返回前，对所有 tool result 做 redact：

```python
result = tool_dispatch(tc.name, args)
if self.config.enable_redaction:  # default: True
    output = result.get("output", "")
    redacted, count = self.redactor.redact(output)
    if count:
        result["output"] = redacted
        result["_redactions"] = count
```

### 性能

- 正则扫描 8KB 文本 < 1ms
- 不影响工具执行速度
- 对 prefix cache 无影响（只改 tool result，不改 system prompt）

### 改动文件

- `src/next_agent/redact.py` — SecretRedactor 类
- `src/next_agent/agent.py` — _execute_tool 中接入
- `src/next_agent/agent.py` — AgentConfig 加 enable_redaction
