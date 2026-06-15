"""Profile Manager — isolated agent instances.

Each profile has its own config, skills, memory, and snapshots.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


PROFILES_DIR = Path.home() / ".nextagent" / "profiles"


class ProfileManager:
    """Manages multiple isolated agent profiles."""

    @staticmethod
    def list() -> list[dict]:
        """List all profiles."""
        if not PROFILES_DIR.exists():
            return []
        profiles = []
        for d in sorted(PROFILES_DIR.iterdir()):
            if d.is_dir():
                cfg_file = d / "config.json"
                config = {}
                if cfg_file.exists():
                    try:
                        config = json.loads(cfg_file.read_text())
                    except Exception:
                        pass
                profiles.append({
                    "name": d.name,
                    "model": config.get("model", "?"),
                    "project": config.get("workdir", "?"),
                    "is_default": (d.name == "default"),
                })
        return profiles

    @staticmethod
    def create(name: str, model: str = "deepseek-v4-flash", clone_from: str | None = None) -> bool:
        """Create a new profile directory."""
        profile_dir = PROFILES_DIR / name
        if profile_dir.exists():
            return False

        profile_dir.mkdir(parents=True, exist_ok=True)

        if clone_from:
            src = PROFILES_DIR / clone_from
            if src.exists():
                shutil.copytree(src, profile_dir, dirs_exist_ok=True)
                return True

        # Default config
        config = {
            "model": model,
            "max_rounds": 25,
            "cache_report": True,
            "language": "auto",
        }
        (profile_dir / "config.json").write_text(json.dumps(config, indent=2))
        (profile_dir / "skills").mkdir(exist_ok=True)
        (profile_dir / "snapshots").mkdir(exist_ok=True)
        return True

    @staticmethod
    def delete(name: str) -> bool:
        """Delete a profile."""
        if name == "default":
            return False  # cannot delete default
        profile_dir = PROFILES_DIR / name
        if not profile_dir.exists():
            return False
        shutil.rmtree(profile_dir)
        return True

    @staticmethod
    def get_path(name: str) -> Path:
        """Get the profile directory path."""
        return PROFILES_DIR / name

    @staticmethod
    def load_config(name: str) -> dict:
        """Load config for a specific profile."""
        path = PROFILES_DIR / name / "config.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}

    @staticmethod
    def save_config(name: str, config: dict) -> None:
        """Save config for a specific profile."""
        path = PROFILES_DIR / name / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2))

    @staticmethod
    def resolve_profile(name: str | None = None) -> str:
        """Resolve the effective profile name."""
        if name:
            return name
        # Check for a default override
        default_file = PROFILES_DIR / ".default_profile"
        if default_file.exists():
            return default_file.read_text().strip()
        return "default"

    @staticmethod
    def set_default(name: str) -> None:
        """Set the default profile."""
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        (PROFILES_DIR / ".default_profile").write_text(name)
