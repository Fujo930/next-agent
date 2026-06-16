# NextAgent — Codex Architecture Alignment

## Codex Core Patterns (learned from open-source analysis)

### 1. Separation of Concerns
```
Codex:    Rust agent core ↔ JSON-RPC 2.0 ↔ TypeScript TUI
NextAgent: Python agent core ↔ HTTP API ↔ React (webview)
```
NextAgent already has this separation. Keep it.

### 2. Agent Loop (ToolOrchestrator)
Codex 4-phase pipeline:
```
approval check → sandbox selection → execute → retry with escalation
```
NextAgent currently: validate → execute. Missing: sandbox, retry escalation.

### 3. Context Management
Codex handles quadratic growth with:
- `/compact` — summarises conversation
- Sub-agent delegation — fresh context per sub-agent
- Prefix caching on Responses API

NextAgent has: prefix caching (96%) + progressive compression.
Missing: `/compact` slash command, sub-agent spawning.

### 4. Responses API (not Chat Completions)
Codex exclusively uses `/v1/responses` for:
- 40-80% better cache utilisation
- Parallel tool calls in one response
- Built for agentic loops

NextAgent uses Chat Completions. Consider migrating.

### 5. Memory Pipeline
Codex two-phase:
1. Extract: gpt-5.1-mini scans 5000 threads, 8 concurrent workers
2. Consolidate: gpt-5.3 merges into memory_summary.md (5K token cap)

NextAgent has: MemoryManager + MemoryDB. Good foundation, needs auto-consolidation.

### 6. Permission Modes
Codex: `--suggest` / `--auto-edit` / `--full-auto`
NextAgent: None exposed to user. Needs CLI flags.

### 7. Slash Commands
Codex: `/compact`, `/model`, `/review`, `/context`, `/cost`, `/init`
NextAgent: Basic CommandManager. Needs expansion.

## Priority Action Items

| Priority | Item | Effort |
|----------|------|--------|
| P0 | Fix dialog/output overlap CSS | ✅ Done |
| P1 | `exec` mode + `--json` output | Medium |
| P1 | AGENTS.md loading in core | Small |
| P2 | Permission modes CLI | Medium |
| P2 | Session resume `--continue` | Medium |
| P3 | `/compact` slash command | Small |
| P3 | Responses API migration | Large |
