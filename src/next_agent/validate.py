"""Innovation B — Tool Call Pre-Validation.

Six-layer validation pipeline executed BEFORE any tool runs:

1. JSON parse — Can arguments be parsed?
2. Schema match — Does this tool exist? Is the name correct?
3. Required params — Are all mandatory fields present?
4. Type coercion — Are parameter types correct?
5. Safety check — Is this operation dangerous?
6. Dedup check — Has this exact call already been made?

If any layer fails:
- Recoverable → return retry instruction to LLM
- Unrecoverable (safety) → BLOCK and ask user
- Duplicate → return cached result, skip execution
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    """Result of pre-validating a tool call."""
    ok: bool
    args: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    action: str = ""  # "execute", "retry", "block", "cached"
    cached_result: dict | None = None


class ToolValidator:
    """Pre-execution validation pipeline for DeepSeek tool calls."""

    def __init__(self, tool_schemas: list[dict]):
        self._schemas: dict[str, dict] = {}
        self._safety_rules: list[tuple[re.Pattern, str, str]] = []
        self._result_cache: dict[tuple[str, str], dict] = {}

        # Build schema index
        for tool in tool_schemas:
            fn = tool.get("function", tool)
            name = fn.get("name", "")
            if name:
                self._schemas[name] = fn

        # Safety rules: (pattern, tool_pattern, reason)
        self._safety_rules = [
            (
                re.compile(r"rm\s+-rf\s+/"),
                "bash",
                "rm -rf / (destructive filesystem operation)",
            ),
            (
                re.compile(r">\s*/dev/sd"),
                "bash",
                "overwrite block device",
            ),
            (
                re.compile(r"mkfs\."),
                "bash",
                "format filesystem",
            ),
        ]

    def validate(self, name: str, raw_arguments: str) -> ValidationResult:
        """Run the full validation pipeline.

        Args:
            name: The tool name from the LLM
            raw_arguments: The raw arguments string from the LLM

        Returns:
            ValidationResult with ok=True and corrected args, or an error.
        """
        # Layer 1: JSON parse
        args, json_error = self._parse_json(raw_arguments)
        if json_error:
            return ValidationResult(
                ok=False,
                action="retry",
                error=f"Invalid JSON in arguments: {json_error}\n"
                      f"Raw arguments: {raw_arguments[:200]}\n"
                      f"Please output valid JSON for arguments.",
            )

        # Layer 2: Schema match
        schema = self._find_schema(name)
        if not schema:
            suggestion = self._find_nearest_tool(name)
            msg = f"Unknown tool '{name}'."
            if suggestion:
                msg += f" Did you mean '{suggestion}'?"
            return ValidationResult(
                ok=False,
                action="retry",
                error=msg,
            )

        # Layer 3: Required params
        required = schema.get("parameters", {}).get("required", [])
        missing = [p for p in required if p not in args or args.get(p) is None]
        if missing:
            return ValidationResult(
                ok=False,
                action="retry",
                error=f"Missing required parameters for '{name}': {missing}",
            )

        # Layer 4: Type coercion
        props = schema.get("parameters", {}).get("properties", {})
        for param, value in list(args.items()):
            if param in props and value is not None:
                expected_type = props[param].get("type", "string")
                args[param] = self._coerce(value, expected_type)

        # Layer 5: Safety check
        if name in ("bash", "bash_script"):
            command = args.get("command", "") or args.get("script", "")
            for pattern, tool_pattern, reason in self._safety_rules:
                if name == tool_pattern and pattern.search(command):
                    return ValidationResult(
                        ok=False,
                        action="block",
                        error=f"BLOCKED by safety rule: {reason}",
                    )

        # Layer 6: Dedup
        cache_key = (name, json.dumps(args, sort_keys=True))
        if cache_key in self._result_cache:
            return ValidationResult(
                ok=True,
                args=args,
                action="cached",
                cached_result=self._result_cache[cache_key],
            )

        return ValidationResult(ok=True, args=args, action="execute")

    def cache_result(self, name: str, args: dict, result: dict) -> None:
        """Cache a tool result for dedup."""
        cache_key = (name, json.dumps(args, sort_keys=True))
        self._result_cache[cache_key] = result

    # ── Internal helpers ─────────────────────────────────────

    @staticmethod
    def _parse_json(raw: str) -> tuple[dict, str]:
        """Parse JSON arguments with error recovery."""
        if not raw or not raw.strip():
            return {}, "Empty arguments"

        try:
            return json.loads(raw), ""
        except json.JSONDecodeError as e:
            pass

        # Recovery attempts for common DeepSeek errors
        # 1. Bare string → wrap in default parameter
        cleaned = raw.strip().strip('"').strip("'")
        if cleaned and not cleaned.startswith("{"):
            return {"command": cleaned}, ""  # assume bash command

        # 2. Fix unquoted keys: {name: value} → {"name": value}
        try:
            fixed = re.sub(r'(\w+):', r'"\1":', raw)
            return json.loads(fixed), ""
        except json.JSONDecodeError:
            pass

        # 3. Fix trailing commas
        try:
            fixed = re.sub(r",\s*}", "}", raw)
            fixed = re.sub(r",\s*\]", "]", fixed)
            return json.loads(fixed), ""
        except json.JSONDecodeError:
            pass

        return {}, f"Cannot parse: {raw[:100]}"

    def _find_schema(self, name: str) -> dict | None:
        return self._schemas.get(name)

    def _find_nearest_tool(self, name: str) -> str | None:
        """Fuzzy match tool name for common typos."""
        name_lower = name.lower().replace("_", "").replace("-", "")
        best = None
        best_score = 999

        for schema_name in self._schemas:
            s_lower = schema_name.lower().replace("_", "").replace("-", "")
            if s_lower == name_lower:
                return schema_name
            # Simple edit distance
            score = self._levenshtein(name_lower, s_lower)
            if score < best_score:
                best_score = score
                best = schema_name

        if best and best_score <= 3:
            return best
        return None

    @staticmethod
    def _coerce(value: Any, expected_type: str) -> Any:
        """Coerce a value to the expected type."""
        if expected_type == "integer" and isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return value  # keep original, let tool handle error
        if expected_type == "number" and isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return value
        if expected_type == "boolean" and isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return value

    @staticmethod
    def _levenshtein(a: str, b: str) -> int:
        if len(a) < len(b):
            a, b = b, a
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
            prev = cur
        return prev[-1]
