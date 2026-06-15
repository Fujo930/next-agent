"""Project workspace snapshot builder.

Builds a bounded project overview injected into the system prompt
on first turn. Gives DeepSeek awareness of project structure before
any tool calls.

Limits: max 120 entries, 14 file previews, 24K chars.
Skips: .git, node_modules, __pycache__, .venv, .next, dist, build,
       secrets (.env, .pem, .key, credentials).
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

MAX_ENTRIES = 120
MAX_FILE_PREVIEWS = 14
MAX_CHARS = 24_000

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".next", "dist", "build", "target", ".idea", ".vscode",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
}

SKIP_FILES = {
    ".api_key",
    ".env", ".env.local", ".env.production",
    "*.pem", "*.key", "*.p12", "*.pfx",
    "credentials.json", "credentials",
    "secrets.yaml", "secrets.yml",
}


def _is_secret_file(name: str) -> bool:
    """Check if a filename matches secret file patterns (including globs)."""
    if name in SKIP_FILES:
        return True
    for pattern in SKIP_FILES:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False

PRIORITY_FILES = [
    "README.md", "README", "pyproject.toml", "Cargo.toml",
    "package.json", "go.mod", "Makefile", "docker-compose.yml",
    "Dockerfile", ".gitignore", "CLAUDE.md", "AGENTS.md",
]


def build_snapshot(workdir: Path | str = ".") -> str:
    """Build a bounded workspace snapshot.

    Returns a markdown string ready for injection into the system prompt.
    """
    root = Path(workdir).resolve()
    if not root.exists():
        return f"[Workspace: {root} does not exist]"

    parts = [f"## Workspace: {root}"]

    # 1. Project overview
    file_count = 0
    dir_count = 0
    languages: dict[str, int] = {}
    all_files = []

    ext_map = {
        ".py": "Python", ".js": "JS", ".ts": "TS", ".rs": "Rust",
        ".go": "Go", ".cpp": "C++", ".c": "C", ".java": "Java",
        ".html": "HTML", ".css": "CSS", ".json": "JSON",
        ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
        ".md": "MD", ".sh": "Shell", ".sql": "SQL",
    }

    try:
        for entry in sorted(root.rglob("*"), key=lambda e: (e.is_file(), e.name.lower())):
            if any(skip in entry.parts for skip in SKIP_DIRS):
                continue
            try:
                if entry.is_dir():
                    dir_count += 1
                else:
                    if _is_secret_file(entry.name):
                        continue
                    file_count += 1
                    if file_count <= MAX_ENTRIES:
                        all_files.append(entry)
                    ext = entry.suffix.lower()
                    if ext in ext_map:
                        languages[ext_map[ext]] = languages.get(ext_map[ext], 0) + 1
            except OSError:
                continue  # skip broken paths/symlinks
    except (PermissionError, OSError):
        parts.append("[Permission error during scan]")
        return "\n".join(parts)

    size = sum(f.stat().st_size for f in all_files[:file_count] if f.exists())

    parts.append(f"Files: {file_count} | Dirs: {dir_count} | Size: {_format_size(size)}")
    if languages:
        top = sorted(languages.items(), key=lambda x: x[1], reverse=True)[:6]
        parts.append(f"Languages: {', '.join(f'{l}:{c}' for l, c in top)}")

    # 2. Directory tree (top-level)
    try:
        top_entries = sorted(root.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    except PermissionError:
        top_entries = []

    tree_lines = []
    for entry in top_entries[:30]:
        if entry.name in SKIP_DIRS:
            continue
        if entry.is_file() and _is_secret_file(entry.name):
            continue
        marker = "/" if entry.is_dir() else ""
        tree_lines.append(f"  {entry.name}{marker}")
    if len(top_entries) > 30:
        tree_lines.append(f"  ... ({len(top_entries) - 30} more)")

    if tree_lines:
        parts.append("\n### Top-level\n" + "\n".join(tree_lines))

    # 3. Priority file previews
    previews = []
    for pf in PRIORITY_FILES:
        fp = root / pf
        if fp.exists() and fp.is_file():
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")[:2000]
                previews.append(f"### {pf}\n```\n{content}\n```")
            except Exception:
                pass

    if previews:
        parts.append("\n### Key Files\n" + "\n\n".join(previews[:3]))

    result = "\n".join(parts)
    if len(result) > MAX_CHARS:
        result = result[:MAX_CHARS] + "\n... [truncated]"

    return result


def _format_size(size_bytes: int) -> str:
    if size_bytes > 1_000_000_000:
        return f"{size_bytes / 1_000_000_000:.1f} GB"
    if size_bytes > 1_000_000:
        return f"{size_bytes / 1_000_000:.1f} MB"
    if size_bytes > 1_000:
        return f"{size_bytes / 1_000:.1f} KB"
    return f"{size_bytes} B"
