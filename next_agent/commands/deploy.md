---
allowed-tools: read_file, write_file, edit_file, bash, bash_script
description: Deploy the current project
---

## Context
- Current branch: !`git branch --show-current`
- Recent commits: !`git log --oneline -3`
- Project type: check pyproject.toml, package.json, Cargo.toml, Makefile, Dockerfile

## Your Task

1. Identify the project type and deployment method
2. Run the appropriate build and deploy commands:
   - Python: `pip install -e .` or `python -m build`
   - Node: `npm run build` then `npm publish`
   - Rust: `cargo build --release`
   - Docker: `docker build -t app .`
3. Report the build results and any issues

You MUST verify the build succeeds before claiming deployment is complete.
Do not push to production without explicit confirmation.
