---
allowed-tools: bash(git add *), bash(git status *), bash(git commit *)
description: Create a git commit with an auto-generated message
---

## Context
- Current git status: !`git status --short`
- Current changes: !`git diff --stat`
- Recent commits: !`git log --oneline -5`

## Your Task

Create a single git commit with an appropriate message.
Analyze the changes and write a descriptive commit message.
Stage the files and commit in a single message.
Do not use any other tools.
