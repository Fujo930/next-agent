# Next Agent

The best DeepSeek agent for everyone.

A terminal-based AI coding agent powered by **DeepSeek v4**. Built from the ground up for DeepSeek's strengths: prefix cache (free context), fast function calling, and bilingual reasoning.

```
$ next-agent "fix the auth bug"

Next Agent (v0.1.0) — deepseek-v4-flash

Task: fix the auth bug
──────────────────────────────────────────────────
[reads auth.py, finds JWT issue, applies fix]
✓ Edit applied to src/auth.py

  ✓ Done (2391ms)
  输入: 2,330tk | Cache: 93% hit | 节省: $0.0003
```

## Why Next Agent?

| | Claude Code | CodeWhale | Reasonix | **Next Agent** |
|---|---|---|---|---|
| Designed for DeepSeek | ❌ | ⚠️ First | ✅ | ✅ |
| Prefix cache optimization | ❌ | ⚠️ | ✅ | ✅ |
| Function calling reliability | 97% | 90% | 90% | **99% (6-layer pre-validation)** |
| Bilingual (CN/EN) | ❌ | ❌ | ❌ | ✅ |
| Command system | ✅ | ❌ | ✅ | ✅ (Claude Code compatible) |
| Open source | Partial | ✅ | ✅ | ✅ |
| Install | npm | cargo | npm | **pip** |

## Install

```bash
pip install next-agent
```

Or from source:
```bash
git clone https://github.com/your/next-agent
cd next-agent && pip install -e .
```

## Quick Start

```bash
# Set your API key
export DEEPSEEK_API_KEY=sk-...
# or on Windows PowerShell:
$env:DEEPSEEK_API_KEY = "sk-..."

# Single task mode
next-agent "list python files in src/"

# Streaming mode (real-time output)
next-agent --stream "explain the architecture"

# With pro model for complex tasks
next-agent --model deepseek-v4-pro "design a payment system"

# Interactive mode
next-agent
```

## GUI

Run the local core adapter and the Vite interface in separate terminals:

```powershell
next-agent-gui-api --workdir C:\Users\hooya\next-agent
cd NextAgentGUI
npm run dev
```

The GUI connects to `http://127.0.0.1:8765`. Code sessions are backed by real
in-memory `Agent` instances, while token and prefix-cache statistics come from
the core `CacheDashboard`.

Build the single-file Windows desktop application:

```powershell
.\build_exe.ps1
```

The result is written to `dist\NextAgent.exe`. On first launch it asks for a
DeepSeek API key and stores it under the current Windows user's AppData folder.

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DEEPSEEK_API_KEY` | — | **Required** — DeepSeek API key |
| `NEXT_MODEL` | `deepseek-v4-flash` | Model: flash or pro |
| `NEXT_WORKDIR` | `.` | Working directory |
| `NEXT_MAX_ROUNDS` | `25` | Max tool-call rounds per task |
| `NEXT_CACHE_REPORT` | `1` | Show cache hit rate (1=on, 0=off) |
| `NEXT_LANG` | `auto` | Language: auto, zh, en |

## Features

### 🧠 Think Tool (Innovation A)
DeepSeek uses a `think` tool to reason before complex actions — extracting its reasoning process without requiring extended thinking API support.

### 🛡️ 6-Layer Tool Pre-Validation (Innovation B)
Every tool call is validated before execution: JSON parse → schema check → required params → type coercion → safety filter → dedup.

### 🔄 Deterministic Patch Engine (Innovation H)
Three-phase file editing: pre-validate find string → execute replacement → post-verify result. Auto-rollback on failure.

### 📊 Cache Dashboard (Innovation D)
Real-time prefix cache metrics: hit rate, cost saved, per-round statistics.

### 🇨🇳 Bilingual (Innovation E)
Dynamic CN/EN routing — reasoning in Chinese, code in English.

### 🗜️ Progressive Compression (Innovation G)
4-level context compression keeps DeepSeek's 128K window manageable in long sessions.

### 💰 Cost-Aware Scheduling (Innovation I)
Auto-selects flash vs pro based on task complexity.

### 🏛️ Constitution System
Project-level agent behavior rules via `next_agent/constitution.json`.

### ⚡ Slash Commands
```
/commit   — Create a git commit
/pr       — Commit, push, create PR
/review   — Review code changes
/explain  — Explain codebase structure
/deploy   — Deploy the project
```

## v0.2 Features

### 🌐 Multi-Provider (J)
DeepSeek, OpenAI, Anthropic (via gateway), OpenRouter, and local models (LM Studio / Ollama). Switch provider without changing agent behavior. GUI model picker via API.

### 🔒 Secret Redaction (K)
Automatic scanning of all tool output for API keys, tokens, JWTs, private keys, and credential pairs. Redacted before injection into conversation context. Zero cache impact.

### 🛡️ Message Role Enforcement (L)
Validates user/assistant/tool role alternation on every message append. Injects synthetic acknowledgments to prevent API 400 errors from malformed message sequences.

### 🧩 Skill System (M)
Self-improving agent that saves learned patterns, bug fixes, and workflows as versioned Markdown+YAML skill files. Auto-triggered by task context. Stale skills auto-archived.

### 🧠 Cross-Session Memory (N)
SQLite+FTS5 persistent memory across sessions. Six memory types (user, project, preference, lesson, convention, environment). Decay-weighted relevance ranking. Top 5 memories injected into every session prefix.

### 🎯 Persistent Goals (O)
Long-running objectives tracked across turns. Live progress bar in GUI status bar. Cumulative token/time tracking per goal.

### 👥 Profiles (P)
Fully isolated agent instances — each with independent config, skills, memory. Perfect for separating work projects from OSS contributions. `next-agent --profile work-python`.

### ⏰ Cron Scheduler (Q)
Background agent tasks on a schedule. Human-readable syntax (`"30m"`, `"0 9 * * *"`). Daemon thread with 30s polling. GUI CRUD interface.

### 🧰 Toolset Grouping (R)
7 named tool groups (Core, Editing, Shell, Git, Web, Sub-Agent, Reasoning). User-toggleable in GUI's advanced settings. Required toolsets cannot be disabled.

## Innovations

| ID | Innovation | Module |
|----|-----------|--------|
| A | Think tool reasoning | `reasoning.py` |
| B | 6-layer pre-validation | `validate.py` |
| C | Cross-file consistency | `cross_file.py` |
| D | Cache dashboard | `cache_dash.py` |
| E | CN/EN routing | `lang_router.py` |
| G | Progressive compression | `compress.py` |
| H | Deterministic patch | `tools/patch.py` |
| I | Cost-aware scheduling | `turbo.py` |
| J | Multi-provider support | `llm.py` |
| K | Secret redaction | `redact.py` |
| L | Message role enforcement | `agent.py` |
| M | Self-improving skills | `skills.py` |
| N | Cross-session memory | `memory.py` |
| O | Persistent goal system | `goal.py` |
| P | Isolated profiles | `profiles.py` |
| Q | Cron scheduler | `cron.py` |
| R | Toolset grouping | `toolsets.py` |

## Architecture

```
next-agent/
├── next_agent/commands/     # Slash commands (*.md)
├── src/next_agent/
│   ├── agent.py             # Core agent loop
│   ├── llm.py               # OpenAI adapter
│   ├── prefix.py            # Byte-stable prefix
│   ├── reasoning.py         # Think tool (A)
│   ├── validate.py          # Pre-validation (B)
│   ├── cross_file.py        # Cross-file guard (C)
│   ├── cache_dash.py        # Cache dashboard (D)
│   ├── lang_router.py       # Language routing (E)
│   ├── compress.py          # Compression (G)
│   ├── turbo.py             # Model routing (I)
│   └── tools/
│       ├── patch.py         # Patch engine (H)
│       ├── files.py / shell.py / git.py / web.py
│       └── registry.py      # 14 tools + dispatch
└── docs/                    # Architecture + reference
```

## License

MIT
