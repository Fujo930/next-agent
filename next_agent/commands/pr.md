---
allowed-tools: bash(git checkout --branch *), bash(git add *), bash(git status *), bash(git push *), bash(git commit *)
description: Commit, push, and create a PR
---

## Context
- Current git status: !`git status --short`
- Current branch: !`git branch --show-current`
- Current changes: !`git diff --stat`

## Your Task

1. Create a new branch if on main
2. Create a single commit with an appropriate message
3. Push the branch to origin
4. Report the branch name and next steps

You MUST do all of the above in a single message.
Do not use any other tools.
