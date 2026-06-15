---
name: python-import-check
description: Before editing Python files, verify imports resolve
trigger: editing .py files in any project
created_by: agent
created_at: 2026-06-14
use_count: 5
---

## Pattern

When editing Python files that change imports (add/remove/rename):

1. Read the target file first
2. Check all imports with `python -c "import ast; ast.parse(open('file').read())"`
3. If imports changed, read the imported module to verify the symbol exists

## Why

DeepSeek sometimes adds imports for symbols that don't exist in the target module.
This skill prevents that by enforcing a pre-edit import check.

## When to Apply

Automatically triggered when:
- Editing `.py` files
- Adding new imports
- Renaming imported symbols
