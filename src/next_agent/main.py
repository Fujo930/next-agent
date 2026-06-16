"""CLI entry point — interactive and single-task modes.

Usage:
    next-agent                          # interactive mode
    next-agent "fix the auth bug"       # single-task mode
    next-agent run "add tests"          # single-task mode (explicit)
    next-agent --model pro "review"     # specify model
    next-agent --workdir /path/to/proj  # specify workspace

Interactive commands:
    /exit       — quit
    /clear      — reset conversation (keep cache prefix)
    /stats      — show cache stats
    /model      — show current model
    /snapshots  — list file snapshots
    /restore ID — restore a snapshot
    /help       — show help
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .agent import Agent, AgentConfig
from .llm import LLMConfig
from .setup import load_config
from .snapshot import list_snapshots, restore_snapshot, format_snapshots


def _parse_toolsets(args, file_config: dict) -> set[str]:
    """Parse enabled toolsets from CLI args, env, or config file."""
    raw = args.toolsets
    if not raw:
        raw = os.environ.get("NEXT_TOOLSETS", "")
    if not raw:
        raw_list = file_config.get("enabled_toolsets", [])
        return set(raw_list) if raw_list else set()
    return {t.strip() for t in raw.split(",") if t.strip()}


def _print_banner():
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║          Next Agent v0.2.3                ║")
    print("  ║    The best DeepSeek agent for everyone   ║")
    print("  ╚══════════════════════════════════════════╝")
    print()


def _interactive_loop(agent: Agent):
    """Interactive readline-based REPL."""
    _print_banner()

    # Set up readline (Windows needs pyreadline3)
    try:
        import readline
        readline.parse_and_bind("tab: complete")
    except ImportError:
        try:
            import pyreadline3 as readline
        except ImportError:
            pass  # degraded but works

    print("Type /help for commands, or just type your request.\n")

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not line:
            continue

        # ── Slash commands ──
        if line.startswith("/"):
            parts = line[1:].split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            match cmd:
                case "exit" | "quit" | "q":
                    print("Goodbye!")
                    break

                case "clear":
                    agent.reset()
                    print("[Conversation cleared. Cache prefix preserved.]")

                case "stats":
                    print(agent.cache_dash.format_session())

                case "model":
                    print(f"Model: {agent.config.model} | "
                          f"Streaming: {'on' if agent.config.stream else 'off'}")

                case "stream":
                    agent.config.stream = not agent.config.stream
                    print(f"Streaming: {'ON' if agent.config.stream else 'OFF'}")

                case "snapshots":
                    snaps = list_snapshots(agent.config.workdir)
                    print(format_snapshots(snaps))

                case "restore":
                    if not arg:
                        print("Usage: /restore <snapshot_id>")
                    elif restore_snapshot(arg, agent.config.workdir):
                        print(f"Restored snapshot {arg}")
                    else:
                        print(f"Snapshot {arg} not found")

                case "help" | "?":
                    print("""
  Commands:
    /exit, /quit    — exit
    /clear          — reset conversation (keeps cache)
    /stats          — show cache statistics
    /model          — show current model and settings
    /stream         — toggle streaming on/off
    /snapshots      — list file snapshots
    /restore <id>   — restore a snapshot
    /help           — this help

  Or just type your request. The agent will figure out what to do.
                    """.strip())

                case _:
                    print(f"Unknown command: /{cmd}. Try /help")
            continue

        # ── Normal chat ──
        print()
        try:
            response = agent.chat(line)
            print(f"\n{response}")
        except Exception as e:
            print(f"\n[Error: {e}]")


def _single_task(agent: Agent, task: str):
    """Run a single task and exit."""
    print(f"\nNext Agent (v0.2.3) — {agent.config.model}\n")
    print(f"Task: {task}\n")
    print("─" * 50)

    try:
        response = agent.run(task)
        print(f"\n{response}")
    except Exception as e:
        print(f"\n[Error: {e}]")
        sys.exit(1)


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Next Agent — The best DeepSeek agent for everyone.",
    )
    parser.add_argument(
        "task", nargs="?", default=None,
        help="Task to run (single-task mode). Use 'setup' to run the setup wizard.",
    )
    parser.add_argument(
        "--model", "-m", default=None,
        help="Model: deepseek-v4-flash or deepseek-v4-pro",
    )
    parser.add_argument(
        "--provider", "-p", default=None,
        help="LLM provider: deepseek, openai, anthropic, openrouter, local",
    )
    parser.add_argument(
        "--toolsets", "-t", default=None,
        help="Comma-separated toolsets to enable (default: core,editing,shell,git,web,reasoning)",
    )
    parser.add_argument(
        "--workdir", "-w", default=os.getcwd(),
        help="Working directory",
    )
    parser.add_argument(
        "--no-reasoning", action="store_true",
        help="Disable reasoning extraction (A)",
    )
    parser.add_argument(
        "--no-validation", action="store_true",
        help="Disable tool pre-validation (B)",
    )
    parser.add_argument(
        "--no-cross-file", action="store_true",
        help="Disable cross-file guard (C)",
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Disable cache dashboard (D)",
    )
    parser.add_argument(
        "--no-lang", action="store_true",
        help="Disable language routing (E)",
    )
    parser.add_argument(
        "--no-compression", action="store_true",
        help="Disable progressive compression (G)",
    )
    parser.add_argument(
        "--stream", "-s", action="store_true",
        help="Enable streaming mode — print LLM output as it arrives",
    )
    parser.add_argument(
        "--effort", default="high",
        choices=["low", "medium", "high", "max"],
        help="Effort level: low/medium/high/max (affects temperature, max_tokens, model selection)",
    )
    parser.add_argument(
        "--version", "-v", action="store_true",
        help="Show version",
    )

    args = parser.parse_args()

    if args.version:
        print("Next Agent v0.2.3")
        sys.exit(0)

    # ── Setup mode ──
    if args.task == "setup":
        from .setup import setup_wizard
        sys.exit(setup_wizard())

    # Load config file (env vars take priority)
    file_config = load_config()

    # Config: CLI args > env vars > config file > defaults
    agent_config = AgentConfig(
        model=args.model or os.environ.get("NEXT_MODEL", file_config.get("model", "deepseek-v4-flash")),
        workdir=args.workdir or os.environ.get("NEXT_WORKDIR", os.getcwd()),
        max_rounds=int(os.environ.get("NEXT_MAX_ROUNDS", str(file_config.get("max_rounds", 25)))),
        enabled_toolsets=_parse_toolsets(args, file_config),
        enable_reasoning=not args.no_reasoning,
        enable_validation=not args.no_validation,
        enable_cross_file=not args.no_cross_file,
        enable_cache_dash=not args.no_cache and os.environ.get("NEXT_CACHE_REPORT", str(int(file_config.get("cache_report", True)))) == "1",
        enable_lang_router=not args.no_lang and os.environ.get("NEXT_LANG", file_config.get("language", "auto")) != "en",
        enable_compression=not args.no_compression,
        stream=args.stream or file_config.get("stream", False),
        effort=args.effort,
    )

    llm_config = LLMConfig.from_provider(
        args.provider or file_config.get("provider", "deepseek"),
        model=agent_config.model,
    )
    agent = Agent(config=agent_config, llm_config=llm_config)

    if args.task:
        _single_task(agent, args.task)
    else:
        _interactive_loop(agent)


if __name__ == "__main__":
    main()
