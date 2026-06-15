"""OpenAI-compatible LLM adapter with DeepSeek prefix-cache awareness.

Handles:
- Native function calling (tools parameter)
- DeepSeek prefix cache (repeat system prompt across turns)
- Two models: deepseek-v4-flash and deepseek-v4-pro
- Token usage tracking for cache dashboard
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Generator, Literal

from openai import OpenAI


# ── Provider registry ─────────────────────────────────────────

PROVIDERS: dict[str, dict] = {
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
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-sonnet-4-20250514"],
        "env_key": "ANTHROPIC_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["deepseek/deepseek-chat", "anthropic/claude-sonnet-4"],
        "env_key": "OPENROUTER_API_KEY",
    },
    "local": {
        "base_url": "http://localhost:1234/v1",
        "models": ["local-model"],
        "env_key": None,
    },
}


# ── Config ────────────────────────────────────────────────────

@dataclass
class LLMConfig:
    """Configuration for an LLM provider."""
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    temperature: float = 0.0
    max_tokens: int = 8192

    @classmethod
    def from_provider(cls, provider: str, model: str | None = None) -> "LLMConfig":
        """Create config from a named provider."""
        info = PROVIDERS.get(provider, PROVIDERS["deepseek"])
        key = ""
        if info["env_key"]:
            key = os.environ.get(info["env_key"], "")
        return cls(
            provider=provider,
            model=model or info["models"][0],
            base_url=info["base_url"],
            api_key=key,
        )

    @classmethod
    def from_env(cls, model: str | None = None) -> "LLMConfig":
        """Create config from environment variables."""
        provider = os.environ.get("NEXT_PROVIDER", "deepseek")
        info = PROVIDERS.get(provider, PROVIDERS["deepseek"])
        api_key = os.environ.get("NEXT_API_KEY", "")
        if not api_key and info["env_key"]:
            api_key = os.environ.get(info["env_key"], "")
        base_url = os.environ.get("NEXT_BASE_URL", "") or info["base_url"]
        return cls(
            provider=provider,
            model=model or os.environ.get("NEXT_MODEL", info["models"][0]),
            base_url=base_url,
            api_key=api_key,
        )


# ── Data types ────────────────────────────────────────────────

@dataclass
class ToolCall:
    """A single tool call from the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]

    @classmethod
    def from_openai(cls, raw: dict) -> "ToolCall":
        """Parse from OpenAI-compatible tool_call dict."""
        return cls(
            id=raw["id"],
            name=raw["function"]["name"],
            arguments=json.loads(raw["function"]["arguments"]),
        )


@dataclass
class LLMResponse:
    """Response from an LLM call."""
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""
    elapsed_ms: float = 0.0


@dataclass
class StreamChunk:
    """A single chunk from a streaming LLM response."""
    type: Literal["content", "done"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""
    elapsed_ms: float = 0.0


# ── Adapter ───────────────────────────────────────────────────

class LLMAdapter:
    """OpenAI-compatible adapter with DeepSeek optimizations."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.client = OpenAI(
            api_key=config.api_key or "sk-placeholder",
            base_url=config.base_url,
        )

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a chat completion request.

        If tools are provided, uses native function calling.
        The messages list must follow the correct sequencing:
        assistant(tool_calls) → tool → assistant(tool_calls) → tool → ...
        """
        start = time.monotonic()

        kwargs: dict = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        raw = self.client.chat.completions.create(**kwargs)
        choice = raw.choices[0]
        message = choice.message

        # Parse response
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    parsed = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    parsed = {"_raw": tc.function.arguments, "_error": "JSON parse failed"}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=parsed,
                ))

        elapsed = (time.monotonic() - start) * 1000

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage={
                "prompt_tokens": raw.usage.prompt_tokens if raw.usage else 0,
                "completion_tokens": raw.usage.completion_tokens if raw.usage else 0,
                "total_tokens": raw.usage.total_tokens if raw.usage else 0,
                "cache_hit_tokens": getattr(raw.usage, "prompt_cache_hit_tokens", 0),
                "cache_miss_tokens": getattr(raw.usage, "prompt_cache_miss_tokens", 0),
            },
            model=raw.model,
            elapsed_ms=elapsed,
        )

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Generator["StreamChunk", None, None]:
        """Stream a chat completion request, yielding chunks as they arrive.

        Yields StreamChunk objects with type="content" for text deltas
        and a final type="done" chunk with the full accumulated response.
        """
        start = time.monotonic()

        kwargs: dict = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        stream = self.client.chat.completions.create(**kwargs)

        accumulated_content = ""
        accumulated_tool_calls: dict[int, dict] = {}
        finish_reason = ""
        usage: dict[str, int] = {}
        model = ""

        for chunk in stream:
            # Capture usage before skipping (final usage-only chunk has no choices)
            if chunk.usage:
                usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens or 0,
                    "completion_tokens": chunk.usage.completion_tokens or 0,
                    "total_tokens": chunk.usage.total_tokens or 0,
                    "cache_hit_tokens": getattr(chunk.usage, "prompt_cache_hit_tokens", 0),
                    "cache_miss_tokens": getattr(chunk.usage, "prompt_cache_miss_tokens", 0),
                }
                model = chunk.model or model

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # ── Content delta ──
            if delta.content:
                accumulated_content += delta.content
                yield StreamChunk(type="content", content=delta.content)

            # ── Tool call deltas ──
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in accumulated_tool_calls:
                        accumulated_tool_calls[idx] = {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        }

                    entry = accumulated_tool_calls[idx]
                    if tc_delta.id:
                        entry["id"] = tc_delta.id
                    if tc_delta.function and tc_delta.function.name:
                        entry["name"] = tc_delta.function.name
                    if tc_delta.function and tc_delta.function.arguments:
                        entry["arguments"] += tc_delta.function.arguments

            # ── Finish reason (on final chunk) ──
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

        # ── Parse accumulated tool calls ──
        tool_calls: list[ToolCall] = []
        for idx in sorted(accumulated_tool_calls.keys()):
            tc = accumulated_tool_calls[idx]
            try:
                args = json.loads(tc["arguments"])
            except json.JSONDecodeError:
                args = {"_raw": tc["arguments"], "_error": "JSON parse failed"}
            tool_calls.append(ToolCall(
                id=tc["id"],
                name=tc["name"],
                arguments=args,
            ))

        elapsed = (time.monotonic() - start) * 1000

        yield StreamChunk(
            type="done",
            content=accumulated_content,
            tool_calls=tool_calls,
            finish_reason=finish_reason or "stop",
            usage=usage,
            model=model,
            elapsed_ms=elapsed,
        )

    def test_connection(self) -> bool:
        """Quick connection test."""
        try:
            resp = self.chat(
                messages=[{"role": "user", "content": "1+1=?"}],
                max_tokens=10,
            )
            return bool(resp.content or resp.tool_calls)
        except Exception:
            return False
