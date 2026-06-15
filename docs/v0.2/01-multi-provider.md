# J — 多 Provider 支持 (Multi-Provider Support)

## 借鉴 Hermes

Hermes 支持 20+ providers，通过 `config.yaml` 声明式配置。切换 provider 不改变 agent 行为。

## 当前状态

Next Agent v0.1 硬编码 DeepSeek。`llm.py` 用的是 `from openai import OpenAI`，base_url 指向 `https://api.deepseek.com/v1`。

## 方案

LLMAdapter 已经用 OpenAI-compatible 格式。加 provider 就是改 config。

### 支持的 Provider

```python
PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "env_key": "DEEPSEEK_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini"],
        "env_key": "OPENAI_API_KEY",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",  # via compatible gateway
        "models": ["claude-sonnet-4-20250514"],
        "env_key": "ANTHROPIC_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["deepseek/deepseek-chat", "anthropic/claude-sonnet-4"],
        "env_key": "OPENROUTER_API_KEY",
    },
    "local": {
        "base_url": "http://localhost:1234/v1",  # LM Studio / Ollama / vLLM
        "models": ["local-model"],
        "env_key": None,  # no auth needed
    },
}
```

### 实现

```python
class LLMConfig:
    provider: str = "deepseek"  # NEW
    model: str = "deepseek-v4-flash"
    base_url: str = ""  # auto-filled from provider
    api_key: str = ""   # auto-filled from provider

    @classmethod
    def from_provider(cls, provider: str, model: str | None = None):
        info = PROVIDERS.get(provider, PROVIDERS["deepseek"])
        key = os.environ.get(info["env_key"], "") if info["env_key"] else ""
        return cls(
            provider=provider,
            model=model or info["models"][0],
            base_url=info["base_url"],
            api_key=key,
        )
```

### GUI 对接

```
GET /providers → [{name, models, requires_key}]
POST /chat   → body: {"provider": "openai", "model": "gpt-4o", "message": "..."}
```

模型选择器下拉框直接读取 `/providers`。

### 注意事项

- 切换 provider → **prefix cache 失效**（不同 provider 的 system prompt 不同）
- Anthropic 需要通过 OpenAI-compatible gateway（如 OpenRouter 或自定义代理）
- 本地模型 function calling 可能不完整，需要降级处理
- DeepSeek 仍然是默认 + 最优 provider

### 改动文件

- `src/next_agent/llm.py` — 加 PROVIDERS + from_provider()
- `src/next_agent/main.py` — --provider flag
- `~/.nextagent/config.json` — 加 provider 字段
