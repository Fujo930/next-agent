---
allowed-tools: read_file, search_files, bash(git *)
description: Review code changes and suggest improvements
---

## Context
- Current git status: !`git status --short`
- Current changes: !`git diff`

## Your Task

Review the current changes for:
1. **Correctness** — Does the code do what it claims?
2. **Safety** — Any security issues, edge cases, or race conditions?
3. **Style** — Does it match the surrounding code style?
4. **Completeness** — Are tests updated? Documentation?

Provide a concise review. Focus on real issues, not nitpicks.
