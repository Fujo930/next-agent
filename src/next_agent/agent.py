"""Core agent loop with all innovations integrated.

The agent loop orchestrates:
A. Reasoning extraction — extract REASONING blocks before tool calls
B. Tool pre-validation — 6-layer validation pipeline before execution
C. Cross-file guard — consistency checks after file edits
D. Cache dashboard — per-round token/cache tracking
E. Language routing — CN/EN dynamic prompt tuning
G. Progressive compression — multi-level context compaction
H. Deterministic patch — pre/post validated file edits
I. Cost-aware routing — flash/pro model selection

Flow:
1. User input arrives
2. Language router adds language-tuning instructions
3. Command resolver checks for slash commands
4. LLM call with frozen prefix + tools
5. Reasoning extractor parses REASONING blocks
6. Tool validator pre-checks each tool call
7. Tools execute (with patch engine for edits)
8. Cross-file guard validates after edits
9. Cache dashboard records metrics
10. Compression check — compact if context > 50%
11. Response returned to user
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .llm import LLMAdapter, LLMConfig, LLMResponse, ToolCall
from .prefix import PrefixManager
from .tools.registry import ALL_TOOL_SCHEMAS, dispatch as tool_dispatch
from .tools.subagent import SubAgentRunner, set_runner as set_subagent_runner
from .tools import mcp
from .toolsets import get_enabled_tools
from .validate import ToolValidator
from .reasoning import ReasoningExtractor, REASONING_PROMPT
from .cache_dash import CacheDashboard
from .lang_router import LanguageRouter
from .turbo import ModelRouter, ModelSelection
from .compress import ProgressiveCompressor, CompressionLevel
from .cross_file import CrossFileGuard
from .workspace import build_snapshot
from .constitution import Constitution
from .redact import SecretRedactor
from .command import CommandManager
from .snapshot import snapshot_file
from .skills import SkillManager
from .memory import MemoryManager


# ── Utilities ────────────────────────────────────────────────

def _safe_json_dumps(obj: Any) -> str:
    """JSON-serialise any object safely, falling back to str() for non-serialisable types."""
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as e:
        return json.dumps({"error": f"JSON serialisation failed: {e}", "type": str(type(obj))}, ensure_ascii=False)


def _parse_allowed_tools(raw: str) -> dict[str, re.Pattern | None]:
    """Parse 'allowed-tools' spec into a filter dict.

    Format: 'Bash(git add:*), read_file, search_files'
    Returns: {'bash': re.compile('(git add:.*)|(git status:.*)'), 'read_file': None, ...}
    None value means 'allow all invocations of this tool'.
    Multiple patterns for the same tool are OR-combined.
    """
    if not raw or not raw.strip():
        return {}

    allowed: dict[str, list[str]] = {}  # tool_name → [pattern_strings]
    
    # Split on '), ' to separate pattern-based tools
    raw_clean = raw.strip()
    parts_raw = raw_clean.split("), ")
    
    for i, part_raw in enumerate(parts_raw):
        part_raw = part_raw.strip()
        if i < len(parts_raw) - 1:
            part_raw += ")"  # restore closing paren
        
        # Handle plain tools separated by commas within this part
        for sub_part in part_raw.split(", "):
            sub_part = sub_part.strip()
            if not sub_part:
                continue
            
            m = re.match(r"(\w+)\((.+)\)", sub_part)
            if m:
                tool_name = m.group(1).lower()
                pattern_str = m.group(2).strip()
                # Convert glob-like to regex: git add:* → git add:.*
                # Only escape actual regex special chars (not spaces, colons, dashes)
                regex_special = r".^$*+?{}[]\|()"
                def _escape_minimal(s: str) -> str:
                    result = []
                    for ch in s:
                        if ch in regex_special and ch != "*":
                            result.append("\\" + ch)
                        else:
                            result.append(ch)
                    return "".join(result)
                regex_str = ".*".join(_escape_minimal(p) for p in pattern_str.split("*"))
                if tool_name not in allowed:
                    allowed[tool_name] = []
                allowed[tool_name].append(regex_str)
            else:
                # Unrestricted tool
                tool_name = sub_part.lower()
                allowed[tool_name] = []  # empty list = unrestricted
    
    # Compile: multiple patterns → OR-combined; empty list → None (unrestricted)
    compiled: dict[str, re.Pattern | None] = {}
    for name, patterns in allowed.items():
        if not patterns:
            compiled[name] = None  # unrestricted
        elif len(patterns) == 1:
            compiled[name] = re.compile(patterns[0])
        else:
            combined = "|".join(f"({p})" for p in patterns)
            compiled[name] = re.compile(combined)
    
    return compiled


def _filter_tools_for_command(
    all_tools: list[dict],
    allowed: dict[str, re.Pattern | None],
) -> list[dict]:
    """Filter tool schemas to only those allowed by a command.

    Args:
        all_tools: Full list of tool schemas
        allowed: Parsed allowed-tools dict (tool_name → pattern or None)

    Returns:
        Filtered list of tool schemas
    """
    if not allowed:
        return all_tools

    filtered = []
    for tool in all_tools:
        fn = tool.get("function", tool)
        name = fn.get("name", "").lower()
        # Always allow think tool (reasoning)
        if name == "think" or name in allowed:
            filtered.append(tool)
        elif any(name == key for key in allowed):
            filtered.append(tool)

    return filtered


def _is_tool_allowed(
    tool_name: str,
    arguments: dict,
    allowed: dict[str, re.Pattern | None],
) -> bool:
    """Check if a specific tool invocation is allowed by command constraints.

    For tools with a pattern (e.g., bash(git add:*)), also checks that
    the command/arguments match the pattern.
    """
    if not allowed:
        return True

    name_lower = tool_name.lower()
    if name_lower not in allowed:
        return False

    pattern = allowed[name_lower]
    if pattern is None:
        return True  # unrestricted

    # Tools with pattern restrictions: check the primary argument
    # For bash: check 'command' → should match git ... pattern
    # For git: check 'command' → should match the pattern
    primary_arg = ""
    if name_lower in ("bash", "bash_script"):
        primary_arg = arguments.get("command", "") or arguments.get("script", "")
    elif name_lower == "git":
        primary_arg = arguments.get("command", "")
    elif name_lower == "read_file":
        primary_arg = arguments.get("path", "")
    elif name_lower in ("write_file", "edit_file"):
        primary_arg = arguments.get("path", "")

    if primary_arg:
        return bool(pattern.search(primary_arg))
    
    return True  # can't check, allow


# ── Configuration ────────────────────────────────────────────

DEFAULT_SYSTEM_PROMPT = """You are Next Agent — an AI coding agent powered by DeepSeek v4.

You read codebases, edit files, run commands, and handle git workflows.
Always verify your work. Never claim an edit succeeded without checking.

IMPORTANT: Before any complex action (file edits, shell execution, git commits,
multi-file changes), use the 'think' tool to reason through your plan.
The think tool lets you analyze the situation before acting.
For simple reads (read_file, list_dir), you can skip thinking.
"""

# Turn limit (DeepSeek sometimes loops)
MAX_ROUNDS = 25


@dataclass
class AgentConfig:
    """Runtime configuration for an agent session."""
    model: str = "deepseek-v4-flash"
    workdir: str = "."
    max_rounds: int = MAX_ROUNDS
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    enabled_toolsets: set[str] = field(default_factory=set)
    enable_reasoning: bool = True
    enable_validation: bool = True
    enable_cross_file: bool = True
    enable_cache_dash: bool = True
    enable_lang_router: bool = True
    enable_compression: bool = True
    enable_snapshots: bool = True
    enable_redaction: bool = True
    stream: bool = False


# ── Agent ─────────────────────────────────────────────────────

class Agent:
    """Next Agent — the best DeepSeek agent for everyone."""

    def __init__(
        self,
        config: AgentConfig | None = None,
        llm_config: LLMConfig | None = None,
    ):
        self.config = config or AgentConfig()

        # LLM
        if llm_config is None:
            llm_config = LLMConfig.from_env(self.config.model)
        self.llm = LLMAdapter(llm_config)

        # Prefix (frozen after first build)
        self.prefix = PrefixManager()

        # M — Skill system (loaded once at session start)
        self.skills = SkillManager()

        # N — Cross-session memory (loaded once at session start)
        self.memory = MemoryManager()

        # Innovation modules
        self.validator = ToolValidator(ALL_TOOL_SCHEMAS)
        self.reasoning = ReasoningExtractor()
        self.cache_dash = CacheDashboard(model=self.config.model)
        self.compressor = ProgressiveCompressor()
        self.cross_file = CrossFileGuard(self.config.workdir)
        self.redactor = SecretRedactor()
        self.model_router = ModelRouter()
        self.commands = CommandManager()
        self.commands.load()

        # Sub-agent runner
        import next_agent.tools.registry as reg
        self.subagent = SubAgentRunner(self.llm, reg)
        set_subagent_runner(self.subagent)

        # Conversation state
        self.messages: list[dict] = []
        self.turn_count = 0
        self._prefix_built = False
        self._active_command: dict | None = None

    # ── Public API ──────────────────────────────────────────

    def run(self, user_input: str) -> str:
        """Run the agent on a single user request (single-task mode).

        Args:
            user_input: The user's request

        Returns:
            The agent's final response.
        """
        return self._run_loop(user_input)

    def chat(self, user_input: str) -> str:
        """Handle one turn in interactive mode.

        Args:
            user_input: The user's message

        Returns:
            The agent's response for this turn.
        """
        return self._run_loop(user_input)

    # ── Internal: agent loop ───────────────────────────────

    def _run_loop(self, user_input: str) -> str:
        """Core agent loop."""
        self.turn_count += 1

        # ── E: Language routing ──
        lang_extension = ""
        if self.config.enable_lang_router:
            decision = LanguageRouter.route(user_input)
            lang_extension = decision.prompt_extension

        # ── Command resolution ──
        cmd, resolved_input = self.commands.resolve(user_input)
        user_prompt = resolved_input if cmd else user_input
        if cmd:
            # Special handling for /skills — inject actual skill list
            if cmd["name"] == "skills":
                skill_list = self.skills.list_skills()
                if skill_list:
                    lines = [
                        f"## Available Skills ({len(skill_list)} total)\n",
                        "| Name | Description | Trigger | Created By | Use Count |",
                        "|------|-------------|---------|------------|-----------|",
                    ]
                    for s in skill_list:
                        lines.append(
                            f"| {s['name']} | {s['description']} | {s['trigger']} | "
                            f"{s['created_by']} | {s['use_count']} |"
                        )
                    skills_table = "\n".join(lines)
                    user_prompt = (
                        f"[Command: /skills]\n"
                        f"{skills_table}\n\n"
                        f"Summarize these skills for the user in a helpful way. "
                        f"Explain what skills are and how they work."
                    )
                else:
                    user_prompt = (
                        f"[Command: /skills]\n"
                        f"No skills found. Skills are .md files in ~/.nextagent/skills/ "
                        f"and next_agent/skills/. The agent creates skills automatically "
                        f"when it discovers useful patterns."
                    )
            else:
                user_prompt = f"[Command: /{cmd['name']}]\n{user_prompt}"
            self._active_command = cmd  # store for tool filtering

        # ── Build prefix (once per session) ──
        if not self._prefix_built:
            self._build_prefix(lang_extension, user_input=user_prompt)

        # ── Append user message ──
        self._append_message({"role": "user", "content": user_prompt})

        # ── Agent loop ──
        for round_num in range(self.config.max_rounds):
            # Compose: frozen prefix + conversation
            full_messages = self.prefix.compose(self.messages)
            tools = self.prefix.get_tool_schemas()

            # ── Command tool filtering ──
            cmd_allowed = self._get_command_allowed()
            if cmd_allowed:
                tools = _filter_tools_for_command(tools, cmd_allowed)

            # ── LLM call ──
            if self.config.stream:
                # Streaming mode: yield chunks and print as they arrive
                print()  # blank line before streaming output
                final_chunk = None
                for chunk in self.llm.chat_stream(
                    messages=full_messages,
                    tools=tools,
                    tool_choice="auto",
                ):
                    if chunk.type == "content":
                        print(chunk.content, end="", flush=True)
                    elif chunk.type == "done":
                        final_chunk = chunk
                        if chunk.tool_calls:
                            print()  # newline after content
                            for tc in chunk.tool_calls:
                                args_preview = _safe_json_dumps(tc.arguments)
                                if len(args_preview) > 120:
                                    args_preview = args_preview[:117] + "..."
                                print(f"  🔧 {tc.name}({args_preview})")

                if final_chunk is None:
                    return "[Error: No response from streaming LLM]"

                response = LLMResponse(
                    content=final_chunk.content or None if final_chunk.content else None,
                    tool_calls=final_chunk.tool_calls,
                    finish_reason=final_chunk.finish_reason,
                    usage=final_chunk.usage,
                    model=final_chunk.model,
                    elapsed_ms=final_chunk.elapsed_ms,
                )
            else:
                response = self.llm.chat(
                    messages=full_messages,
                    tools=tools,
                    tool_choice="auto",
                )

            # ── D: Record cache metrics ──
            if self.config.enable_cache_dash:
                self.cache_dash.record(response.usage, response.elapsed_ms)

            # ── A: Extract reasoning ──
            if self.config.enable_reasoning and response.content:
                reasoning_text, rest = self.reasoning.extract(
                    response.content, self.turn_count
                )
                if reasoning_text:
                    # Use rest as the "content" and store reasoning separately
                    response_content_for_message = rest or response.content
                else:
                    response_content_for_message = response.content
            else:
                response_content_for_message = response.content

            # ── Tool calls? ──
            if response.tool_calls:
                # Build assistant message
                assistant_msg = {
                    "role": "assistant",
                    "content": response_content_for_message or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": _safe_json_dumps(tc.arguments),
                            },
                        }
                        for tc in response.tool_calls
                    ],
                }
                self._append_message(assistant_msg)

                # Process each tool call
                for tc in response.tool_calls:
                    result = self._execute_tool(tc)
                    self._append_message({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": _safe_json_dumps(result),
                    })

                # ── G: Compression check ──
                if self.config.enable_compression:
                    current_tokens = self._estimate_tokens()
                    level = self.compressor.check(current_tokens)
                    if level == CompressionLevel.CHECKPOINT:
                        # Would checkpoint in production; for now, just log
                        pass
                    elif level != CompressionLevel.NONE:
                        self.messages, _ = self.compressor.compress_messages(
                            self.messages, current_tokens
                        )

                continue  # next loop iteration

            # ── No tool calls → final response ──
            self._append_message({
                "role": "assistant",
                "content": response_content_for_message or "",
            })

            # In streaming mode, content was already printed; just show cache summary
            if self.config.stream:
                if self.config.enable_cache_dash:
                    cache_summary = self.cache_dash.format_round()
                    print(f"\n{cache_summary}")
                return ""  # content already printed during streaming
            else:
                # Format output with cache info
                output = response_content_for_message or ""
                if self.config.enable_cache_dash:
                    cache_summary = self.cache_dash.format_round()
                    output += f"\n\n{cache_summary}"
                return output

        # Max rounds reached
        return (
            f"[Max rounds ({self.config.max_rounds}) reached. "
            f"The agent may be stuck in a loop. Try rephrasing your request.]"
        )

    # ── Internal: tool execution ─────────────────────────────

    def _execute_tool(self, tc: ToolCall) -> dict:
        """Execute a tool call with full validation pipeline."""

        # ── B: Pre-validation ──
        if self.config.enable_validation:
            validation = self.validator.validate(
                tc.name, _safe_json_dumps(tc.arguments)
            )
            if validation.action == "cached":
                return validation.cached_result or {"ok": True, "output": "[cached]"}
            if validation.action == "block":
                return {"ok": False, "error": validation.error}
            if validation.action == "retry":
                return {"ok": False, "error": f"Validation failed: {validation.error}"}
            args = validation.args
        else:
            args = tc.arguments

        # ── Pre-edit snapshots (for file writes/edits) ──
        if self.config.enable_snapshots and tc.name in ("write_file", "edit_file"):
            path = args.get("path", "")
            if path:
                snapshot_file(path, self.config.workdir)

        # ── C: Cross-file pre-snapshot ──
        if self.config.enable_cross_file and tc.name in ("write_file", "edit_file"):
            path = args.get("path", "")
            if path:
                self.cross_file.before_edits([path])

        # ── Execute ──
        result = tool_dispatch(tc.name, args)

        # ── Secret redaction ──
        if self.config.enable_redaction:
            output = result.get("output", "")
            redacted, count = self.redactor.redact(output)
            if count:
                result["output"] = redacted
                result["_redactions"] = count

        # ── Command tool enforcement ──
        cmd_allowed = self._get_command_allowed()
        if cmd_allowed and not _is_tool_allowed(tc.name, args, cmd_allowed):
            return {
                "ok": False,
                "error": f"Tool '{tc.name}' is not allowed by the active command. Allowed: {list(cmd_allowed.keys())}",
            }

        # ── A: Capture think tool as reasoning ──
        if tc.name == "think" and result.get("ok"):
            thought = result.get("_thought", "")
            if thought:
                self.reasoning.history.append(
                    type("ReasoningBlock", (), {
                        "content": thought,
                        "turn": self.turn_count,
                    })()
                )

        # ── Cache result for dedup ──
        if self.config.enable_validation:
            self.validator.cache_result(tc.name, args, result)

        # ── C: Cross-file post-validation ──
        if self.config.enable_cross_file and tc.name in ("write_file", "edit_file"):
            path = args.get("path", "")
            if path:
                issues = self.cross_file.after_edits([path])
                if issues:
                    issue_msgs = [
                        f"[{i.severity}] {i.file}:{i.line} — {i.message}"
                        for i in issues[:5]
                    ]
                    issue_text = "\n⚠ Cross-file issues:\n" + "\n".join(issue_msgs)
                    if result.get("ok"):
                        result["output"] = result.get("output", "") + issue_text
                    else:
                        result["error"] = (result.get("error", "") + issue_text)

        return result

    # ── Internal: prefix building ─────────────────────────────

    def _build_prefix(self, lang_extension: str = "", user_input: str = "") -> None:
        """Build the frozen system prompt prefix (called once per session)."""
        # Load constitution
        constitution = Constitution.load(self.config.workdir)

        # Build workspace snapshot
        snapshot = build_snapshot(self.config.workdir)

        # Assemble system prompt
        system_prompt = self.config.system_prompt

        # Add reasoning instructions (A)
        if self.config.enable_reasoning:
            system_prompt += f"\n\n{REASONING_PROMPT}"

        # Add constitution
        system_prompt += constitution.to_prompt_extension()

        # Add language extension (E)
        if lang_extension:
            system_prompt += f"\n{lang_extension}"

        # ── M: Load skills (once, frozen into prefix) ──
        skill_extension = self.skills.get_prompt_extension(
            user_input=user_input,
            project=self.config.workdir,
        )
        if skill_extension:
            system_prompt += f"\n\n{skill_extension}"

        # ── N: Load cross-session memory (once, frozen into prefix) ──
        memory_extension = self.memory.load_for_session(
            project=self.config.workdir,
            user_input=user_input,
        )

        # Build the frozen prefix
        tool_schemas = get_enabled_tools(self.config.enabled_toolsets)
        tool_schemas += mcp.get_mcp_manager().get_tool_schemas()
        self.prefix.build(
            system_prompt=system_prompt,
            tool_schemas=tool_schemas,
            project_context=snapshot,
            memory=memory_extension,
        )
        self._prefix_built = True

    # ── Internal: helpers ─────────────────────────────────────

    def _estimate_tokens(self) -> int:
        """Rough estimate of current context tokens."""
        raw = json.dumps(self.messages, ensure_ascii=False)
        return self.prefix.estimated_tokens + (len(raw) // 4)

    def _get_command_allowed(self) -> dict[str, re.Pattern | None]:
        """Get parsed allowed-tools for the active command (if any)."""
        if not self._active_command:
            return {}
        raw = self._active_command.get("allowed_tools", "")
        return _parse_allowed_tools(raw) if raw else {}

    def reset(self) -> None:
        """Reset the conversation (keep prefix)."""
        self.messages.clear()
        self.turn_count = 0
        self.reasoning = ReasoningExtractor()
        self.cache_dash = CacheDashboard(model=self.config.model)

    # ── Internal: message role enforcement ──────────────────

    def _append_message(self, msg: dict) -> None:
        """Append a message, enforcing role alternation.

        OpenAI/DeepSeek require strict role alternation — never two
        consecutive messages with the same role (except 'tool' which
        can follow 'tool' in multi-tool-call responses).
        """
        if not self.messages:
            self.messages.append(msg)
            return

        prev_role = self.messages[-1].get("role", "")
        new_role = msg.get("role", "")

        # System messages can appear anywhere
        if new_role == "system":
            self.messages.append(msg)
            return

        # Tool messages must follow an assistant message with tool_calls
        if new_role == "tool":
            prev_has_tool_calls = bool(self.messages[-1].get("tool_calls"))
            if not prev_has_tool_calls and prev_role != "tool":
                # Insert a synthetic assistant acknowledgment
                self.messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [],
                })

        self.messages.append(msg)
