"""Setup wizard — generates ~/.nextagent/config.json."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


CONFIG_DIR = Path.home() / ".nextagent"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "model": "deepseek-v4-flash",
    "provider": "deepseek",
    "max_rounds": 25,
    "cache_report": True,
    "language": "auto",
    "stream": False,
    "enabled_toolsets": ["core", "editing", "shell", "git", "web", "reasoning"],
}


def _mask_key(key: str) -> str:
    if len(key) <= 12:
        return key[:4] + "****" + key[-4:]
    return key[:8] + "****" + key[-4:]


def setup_wizard() -> int:
    """Interactive setup wizard. Returns 0 on success, 1 on failure."""
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║       Next Agent — Setup Wizard          ║")
    print("  ╚══════════════════════════════════════════╝")
    print()
    print("This will create ~/.nextagent/config.json")
    print()

    # 1. Load existing config if any
    existing = {}
    if CONFIG_FILE.exists():
        try:
            existing = json.loads(CONFIG_FILE.read_text())
            print(f"Found existing config: {CONFIG_FILE}")
            print(f"  Model: {existing.get('model', '?')}")
        except Exception:
            pass

    config = {**DEFAULT_CONFIG, **existing}

    # 2. API Key
    print("\n─── API Key ───")
    env_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if env_key:
        print(f"  Using key from environment: {_mask_key(env_key)}")
        print("  (Clear DEEPSEEK_API_KEY env var to set a different key)")
    else:
        key = input("  DeepSeek API key (sk-...): ").strip()
        if not key:
            print("  ⚠ No key provided. Set DEEPSEEK_API_KEY env var or run setup again.")
        elif not key.startswith("sk-"):
            print("  ⚠ Key doesn't look right (should start with 'sk-'). Continuing anyway...")
        # Don't save the key to config — it stays in env var for security

    # 3. Model
    print("\n─── Default Model ───")
    current = config.get("model", "deepseek-v4-flash")
    print(f"  1. deepseek-v4-flash  — fast, cheap ($0.15/M input)")
    print(f"  2. deepseek-v4-pro    — smarter, slower ($2.19/M input)")
    choice = input(f"  Choose [{1 if 'flash' in current else 2}]: ").strip()
    if choice == "2":
        config["model"] = "deepseek-v4-pro"
    elif choice == "1":
        config["model"] = "deepseek-v4-flash"
    # else keep current

    # 4. Max rounds
    print("\n─── Max Rounds ───")
    current_rounds = config.get("max_rounds", 25)
    rounds = input(f"  Max tool-call rounds per task [{current_rounds}]: ").strip()
    if rounds.isdigit():
        config["max_rounds"] = int(rounds)

    # 5. Cache report
    print("\n─── Cache Report ───")
    current_cache = config.get("cache_report", True)
    print(f"  Show cache hit rate and cost savings after each turn?")
    choice = input(f"  [Y/n]: ").strip().lower()
    if choice in ("n", "no"):
        config["cache_report"] = False
    else:
        config["cache_report"] = True

    # 6. Language
    print("\n─── Language ───")
    lang = config.get("language", "auto")
    print(f"  auto — auto-detect Chinese/English")
    print(f"  zh   — force Chinese reasoning")
    print(f"  en   — force English only")
    choice = input(f"  [{lang}]: ").strip()
    if choice in ("zh", "en"):
        config["language"] = choice

    # 7. Streaming default
    print("\n─── Streaming ───")
    stream = config.get("stream", False)
    print(f"  Stream LLM output in real-time by default?")
    choice = input(f"  [{'Y' if stream else 'y'}/{'n' if stream else 'N'}]: ").strip().lower()
    if choice in ("y", "yes") or (stream and not choice):
        config["stream"] = True
    elif choice in ("n", "no"):
        config["stream"] = False

    # 8. Save
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))
    
    print()
    print(f"  ✅ Config saved to {CONFIG_FILE}")
    print(f"     Model: {config['model']}")
    print(f"     Max rounds: {config['max_rounds']}")
    print(f"     Cache report: {'on' if config['cache_report'] else 'off'}")
    print(f"     Language: {config['language']}")
    print(f"     Streaming: {'on' if config['stream'] else 'off'}")
    print()
    print("  Run 'next-agent' to start!")
    
    return 0


def load_config() -> dict:
    """Load config from file, falling back to defaults."""
    if not CONFIG_FILE.exists():
        return dict(DEFAULT_CONFIG)
    
    try:
        config = json.loads(CONFIG_FILE.read_text())
        return {**DEFAULT_CONFIG, **config}
    except Exception:
        return dict(DEFAULT_CONFIG)


# CLI handler for 'next-agent setup'
def main():
    return setup_wizard()


if __name__ == "__main__":
    sys.exit(setup_wizard())
