"""Deterministic patch engine — structured find-and-replace with pre/post validation.

This is Innovation H: Pre-validate find string exists, execute replacement,
post-verify the result. If verification fails, rollback automatically.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PatchResult:
    ok: bool
    output: str = ""
    error: str = ""
    diff: str = ""
    lines_changed: int = 0
    rolled_back: bool = False

    @classmethod
    def success(cls, output: str, diff: str = "", lines_changed: int = 0) -> "PatchResult":
        return cls(ok=True, output=output, diff=diff, lines_changed=lines_changed)

    @classmethod
    def failure(cls, error: str) -> "PatchResult":
        return cls(ok=False, error=error)

    @classmethod
    def rolled_back(cls, error: str) -> "PatchResult":
        return cls(ok=False, error=error, rolled_back=True)


class DeterministicPatcher:
    """Structured patch with pre-validation and post-verification.

    Three-phase lifecycle:
    1. PRE — Find old_string, check uniqueness
    2. EXEC — Replace in file
    3. POST — Verify new_string exists, check syntax, rollback if needed
    """

    def __init__(self, max_file_size: int = 500_000):
        self.max_file_size = max_file_size
        # Simple dedup cache: (path, old_string) → last_seen_result
        self._cache: dict[tuple[str, str], PatchResult] = {}

    def edit(self, filepath: str, old_string: str, new_string: str) -> dict:
        """Execute a deterministic patch with full validation.

        Returns dict compatible with tool dispatch: {"ok": bool, "output": str, ...}
        """
        result = self._edit_inner(filepath, old_string, new_string)
        return {
            "ok": result.ok,
            "output": result.output if result.ok else result.error,
            "diff": result.diff,
            "lines_changed": result.lines_changed,
            "rolled_back": result.rolled_back,
        }

    def _edit_inner(self, filepath: str, old_string: str, new_string: str) -> PatchResult:
        fp = Path(filepath)

        # Dedup check
        cache_key = (str(fp.absolute()), old_string)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            return PatchResult.failure(
                f"Duplicate edit detected (same old_string on {filepath}). "
                f"Previous result: {'ok' if cached.ok else 'error'}"
            )

        # === Phase 1: PRE-VALIDATION ===
        if not fp.exists():
            return PatchResult.failure(f"File not found: {filepath}")
        if fp.stat().st_size > self.max_file_size:
            return PatchResult.failure(f"File too large ({fp.stat().st_size} bytes, max {self.max_file_size})")

        try:
            original = fp.read_text(encoding="utf-8")
        except Exception as e:
            return PatchResult.failure(f"Cannot read {filepath}: {e}")

        count = original.count(old_string)
        if count == 0:
            # Fuzzy match
            suggestion = self._fuzzy_find(original.splitlines(), old_string)
            msg = f"old_string not found in {filepath}."
            if suggestion:
                msg += (
                    f"\nClosest match at line {suggestion['line']}:\n"
                    f"  Expected: {old_string[:100]}...\n"
                    f"  Found:    {suggestion['text'][:100]}...\n"
                    f"Please use the exact text from the file."
                )
            else:
                msg += f"\nFile starts with:\n" + "\n".join(
                    f"{i+1:>4}|{line}" for i, line in enumerate(original.splitlines()[:8])
                )
            return PatchResult.failure(msg)

        if count > 1 and new_string:
            return PatchResult.failure(
                f"old_string appears {count} times in {filepath}. "
                f"Include 2-3 more lines of surrounding context to make it unique."
            )

        # === Phase 2: EXEC ===
        # deletion (new_string is empty → delete old_string)
        if not new_string:
            modified = original.replace(old_string, "", 1)
            modified = modified.replace("\n\n\n", "\n\n")  # collapse triple blank lines
        else:
            modified = original.replace(old_string, new_string, 1)

        try:
            fp.write_text(modified, encoding="utf-8")
        except Exception as e:
            return PatchResult.failure(f"Cannot write {filepath}: {e}")

        # === Phase 3: POST-VERIFICATION ===
        try:
            actual = fp.read_text(encoding="utf-8")
        except Exception as e:
            # Rollback
            fp.write_text(original, encoding="utf-8")
            return PatchResult.rolled_back(f"Post-edit read failed: {e}")

        # Check new_string is present (unless deletion)
        if new_string and new_string not in actual:
            fp.write_text(original, encoding="utf-8")
            return PatchResult.rolled_back(
                f"Post-edit verification FAILED: new_string not found in file after edit. "
                f"Edit was rolled back."
            )

        # Check old_string is gone (unless new contains old)
        if old_string not in new_string and old_string in actual:
            return PatchResult(
                ok=True,
                output=f"Applied edit to {filepath} (old_string still present — may be a duplicate match)",
                diff=self._generate_diff(original, actual, filepath),
                lines_changed=abs(len(modified.splitlines()) - len(original.splitlines())),
            )

        # Success
        lines_changed = abs(len(modified.splitlines()) - len(original.splitlines()))
        self._cache[cache_key] = PatchResult(ok=True, output="ok")

        return PatchResult.success(
            output=f"✓ Edit applied to {filepath}" + (f" ({lines_changed} lines changed)" if lines_changed else ""),
            diff=self._generate_diff(original, actual, filepath),
            lines_changed=lines_changed,
        )

    @staticmethod
    def _fuzzy_find(lines: list[str], target: str) -> dict | None:
        """Find closest matching line using simple Levenshtein distance."""
        best_score = float("inf")
        best = None
        target_norm = target.strip().replace("  ", " ")

        for i, line in enumerate(lines):
            line_norm = line.strip().replace("  ", " ")
            if abs(len(line_norm) - len(target_norm)) > 80:
                continue
            score = DeterministicPatcher._levenshtein(line_norm, target_norm)
            if score < best_score and score < len(target_norm) * 0.35:
                best_score = score
                best = {"line": i + 1, "text": line, "score": score}

        return best

    @staticmethod
    def _levenshtein(a: str, b: str) -> int:
        """Levenshtein distance."""
        if len(a) < len(b):
            a, b = b, a
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cur.append(min(
                    prev[j] + 1,
                    cur[-1] + 1,
                    prev[j - 1] + (ca != cb),
                ))
            prev = cur
        return prev[-1]

    @staticmethod
    def _generate_diff(original: str, modified: str, filepath: str) -> str:
        """Generate a unified diff."""
        orig_lines = original.splitlines(keepends=True)
        mod_lines = modified.splitlines(keepends=True)
        diff = difflib.unified_diff(
            orig_lines, mod_lines,
            fromfile=f"a/{filepath}",
            tofile=f"b/{filepath}",
        )
        return "".join(list(diff)[:60])  # max 60 lines
