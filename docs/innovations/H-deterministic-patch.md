# H — 确定性补丁引擎 (Deterministic Patch Engine)

## 解决的问题

DeepSeek 在生成 diff/patch 格式文本时准确率低。全文件重写浪费大量 token。需要一种结构化的编辑方式。

**三种编辑模式，自动选择最优：**

| 模式 | 适用场景 | Token 成本 |
|------|---------|-----------|
| **Patch** (find→replace) | 改动 < 20% 的文件 | 极低 |
| **Surgical** (精确替换) | 单行或多行修改 | 低 |
| **Rewrite** (全文件重写) | 改动 > 50% 或 新文件 | 高 |

## 方案：结构化编辑管线

```
LLM 调用 edit_file(path, old_string, new_string)
    ↓
[Phase 1: PRE — 查找验证]
  - 在文件中找到 old_string 了吗？
  - 它是唯一的吗？
  - 如果找不到 → 模糊匹配（Levenshtein），报告差异
    ↓
[Phase 2: EXEC — 执行替换]
  - 原地替换
  - 记录修改行范围
    ↓
[Phase 3: POST — 结果验证]
  - 读回文件
  - new_string 确实存在了吗？
  - 文件语法仍然有效吗？
  - 旧内容被正确替换了吗？
    ↓
  ✅ 成功 → 返回 diff
  ❌ 失败 → 报告给 LLM，让它修正
```

## 实现

```python
class DeterministicPatch:
    """Structured edit with pre-validation and post-verification."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.original_content = ""
        self.modified_content = ""

    def edit(self, old_string: str, new_string: str) -> PatchResult:
        """Execute a deterministic patch with full lifecycle."""

        # === Phase 1: PRE-VALIDATION ===
        if not os.path.exists(self.filepath):
            return PatchResult.error(f"File not found: {self.filepath}")

        with open(self.filepath, "r", encoding="utf-8") as f:
            self.original_content = f.read()

        # Check if old_string exists
        count = self.original_content.count(old_string)
        if count == 0:
            # Fuzzy match fallback
            lines = self.original_content.splitlines()
            best_match = self._fuzzy_find(lines, old_string)
            if best_match:
                return PatchResult.error(
                    f"Exact match not found. Closest match at "
                    f"line {best_match.line}:\n"
                    f"  Expected: {old_string[:80]}...\n"
                    f"  Found:    {best_match.text[:80]}...\n"
                    f"Please retry with the exact text from the file."
                )
            return PatchResult.error(
                f"String not found in file. First 5 lines:\n"
                + "\n".join(lines[:5])
            )

        if count > 1 and new_string != "":
            return PatchResult.error(
                f"old_string appears {count} times. "
                f"Include more context lines to make it unique."
            )

        # === Phase 2: EXECUTE ===
        self.modified_content = self.original_content.replace(
            old_string, new_string, 1  # replace only first occurrence
        )

        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write(self.modified_content)

        # === Phase 3: POST-VERIFICATION ===
        # Re-read to confirm
        with open(self.filepath, "r", encoding="utf-8") as f:
            actual = f.read()

        # Verify: new string is present
        if new_string and new_string not in actual:
            # Rollback
            with open(self.filepath, "w", encoding="utf-8") as f:
                f.write(self.original_content)
            return PatchResult.error(
                "Post-edit verification failed: new_string not found in file. "
                "Edit was rolled back."
            )

        # Verify: old string is gone (unless new_string contains it)
        if old_string not in new_string and old_string in actual:
            return PatchResult.warning(
                "old_string still present in file (may be duplicate match). "
                "Edit applied but check file."
            )

        # Syntax check (language-aware)
        syntax_ok, syntax_error = self._check_syntax()
        if not syntax_ok:
            return PatchResult.warning(
                f"Edit applied but syntax check failed: {syntax_error}"
            )

        # Success — generate diff
        diff = self._generate_diff()
        return PatchResult.success(
            f"✓ Edit applied at {self._find_line_number(actual, new_string)}",
            diff=diff
        )

    def _fuzzy_find(self, lines: list[str], target: str) -> FuzzyMatch | None:
        """Find closest match using Levenshtein distance."""
        best_score = float("inf")
        best_match = None
        target_normalized = target.strip().replace("  ", " ")

        for i, line in enumerate(lines):
            line_normalized = line.strip().replace("  ", " ")
            if abs(len(line_normalized) - len(target_normalized)) > 50:
                continue
            score = self._levenshtein(line_normalized, target_normalized)
            if score < best_score and score < len(target_normalized) * 0.3:
                best_score = score
                best_match = FuzzyMatch(line=i+1, text=line)

        return best_match
```

## 三种编辑模式的自动选择

```python
class EditStrategy:
    """Selects optimal edit mode based on change size."""

    @classmethod
    def choose(cls, filepath: str, new_content: str) -> str:
        """Returns 'patch', 'surgical', or 'rewrite'."""
        with open(filepath, "r") as f:
            old_content = f.read()

        old_lines = len(old_content.splitlines())
        new_lines = len(new_content.splitlines())

        if not os.path.exists(filepath):
            return "rewrite"  # new file

        ratio = abs(new_lines - old_lines) / max(old_lines, 1)
        
        if ratio < 0.2:
            return "patch"      # < 20% change → targeted edit
        elif ratio < 0.5:
            return "surgical"   # 20-50% → multi-patch
        else:
            return "rewrite"    # > 50% → full rewrite
```

## 优势

- 执行前验证避免了 DeepSeek 的 diff 生成错误
- 模糊匹配让 LLM 更宽容（不需要完美匹配缩进）
- 后置验证 + 自动回滚 → 编辑永远不会损坏文件
- 语法检查跨语言（Python: `ast.parse`, JS: `node -c`, Rust: `rustc --check`）

## 风险

- 大文件全重写仍然费 token — 用 edit_strategy 自动选择模式
- 模糊匹配可能匹配错误的行 — 限制 Levenshtein 距离阈值
