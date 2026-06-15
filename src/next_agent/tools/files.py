"""File operations: read, write, edit, list, search."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

_SKIP_FILES_EXACT = {
    ".api_key", ".env",
}
_SKIP_FILES_PATTERNS = [
    ".env.*", "*.pem", "*.key", "credentials.json",
    "secrets.yaml", "*.p12", "*.pfx",
]


def _is_secret_file(name: str) -> bool:
    """Check if a filename matches secret file patterns."""
    if name in _SKIP_FILES_EXACT:
        return True
    for pattern in _SKIP_FILES_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def read_file(path: str, offset: int = 1, limit: int = 500) -> dict:
    """Read a text file with line numbers."""
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"File not found: {path}"}
    if p.is_dir():
        return {"ok": False, "error": f"Path is a directory: {path}"}

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "error": f"Failed to read {path}: {e}"}

    lines = content.splitlines()
    total = len(lines)

    # Apply offset (1-indexed)
    if offset < 1:
        offset = 1
    start_idx = offset - 1

    if start_idx >= total:
        return {"ok": True, "output": f"[file has {total} lines, offset {offset} is beyond end]", "total_lines": total}

    end_idx = min(start_idx + limit, total)
    selected = lines[start_idx:end_idx]

    # Format with line numbers
    output_lines = []
    for i, line in enumerate(selected):
        output_lines.append(f"{start_idx + i + 1:>6}|{line}")

    output = "\n".join(output_lines)
    if end_idx < total:
        output += f"\n... [{total - end_idx} more lines, use offset={end_idx + 1}]"

    return {"ok": True, "output": output, "total_lines": total}


def write_file(path: str, content: str) -> dict:
    """Write content to a file, creating dirs as needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    try:
        p.write_text(content, encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"Failed to write {path}: {e}"}

    return {"ok": True, "output": f"Wrote {len(content)} chars to {path}"}


def list_dir(path: str = ".") -> dict:
    """List files and directories."""
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"Directory not found: {path}"}
    if not p.is_dir():
        return {"ok": False, "error": f"Not a directory: {path}"}

    try:
        entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    except PermissionError:
        return {"ok": False, "error": f"Permission denied: {path}"}

    lines = []
    for entry in entries:
        if _is_secret_file(entry.name):
            continue
        marker = "[D]" if entry.is_dir() else "[F]"
        name = entry.name
        try:
            size = entry.stat().st_size if entry.is_file() else 0
            if size > 1_000_000:
                size_str = f"{size / 1_000_000:.1f}M"
            elif size > 1_000:
                size_str = f"{size / 1_000:.1f}K"
            else:
                size_str = str(size)
        except OSError:
            size_str = "?"

        lines.append(f"  {marker} {name}  ({size_str})")

    output = f"{p.absolute()}/\n" + "\n".join(lines)
    if len(lines) > 60:
        output += f"\n... [{len(lines) - 60} more entries]"

    return {"ok": True, "output": output, "count": len(entries)}


def search_files(pattern: str, path: str = ".", file_glob: str | None = None) -> dict:
    """Search file contents with regex."""
    import fnmatch

    p = Path(path)
    matches = []

    def _should_skip(fp: Path) -> bool:
        parts = fp.parts
        return any(skip in parts for skip in (".git", "node_modules", "__pycache__", ".venv", "venv", ".next", "dist", "build", "target"))

    def _matches_glob(fp: Path) -> bool:
        if not file_glob:
            return True
        return fnmatch.fnmatch(fp.name, file_glob) or fnmatch.fnmatch(str(fp), file_glob)

    try:
        compiled = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
    except re.error as e:
        return {"ok": False, "error": f"Invalid regex pattern: {e}"}

    try:
        if p.is_file():
            files = [p]
        else:
            files = [f for f in p.rglob("*") if f.is_file() and not _should_skip(f) and _matches_glob(f)]
    except PermissionError:
        return {"ok": False, "error": f"Permission denied: {path}"}

    for fp in files[:200]:  # cap at 200 files
        try:
            content = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for m in compiled.finditer(content):
            line_num = content[:m.start()].count("\n") + 1
            line = content.splitlines()[line_num - 1] if line_num <= len(content.splitlines()) else ""
            matches.append({
                "file": str(fp),
                "line": line_num,
                "text": line.strip()[:120],
            })
            if len(matches) >= 50:
                break
        if len(matches) >= 50:
            break

    if not matches:
        return {"ok": True, "output": f"No matches for '{pattern}'"}

    output_lines = [f"{m['file']}:{m['line']}: {m['text']}" for m in matches]
    output = "\n".join(output_lines)
    return {"ok": True, "output": output, "matches": len(matches)}


def project_info() -> dict:
    """Get project overview."""
    p = Path.cwd()
    files = []
    dirs = 0
    langs: dict[str, int] = {}

    ext_map = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
        ".rs": "Rust", ".go": "Go", ".java": "Java", ".cpp": "C++",
        ".c": "C", ".h": "C/C++", ".html": "HTML", ".css": "CSS",
        ".json": "JSON", ".yaml": "YAML", ".yml": "YAML",
        ".toml": "TOML", ".md": "Markdown", ".sh": "Shell",
        ".sql": "SQL", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift",
    }

    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".next", "dist", "build", "target"}

    for entry in p.rglob("*"):
        if any(skip in entry.parts for skip in skip_dirs):
            continue
        if entry.is_dir():
            dirs += 1
        else:
            files.append(entry)
            ext = entry.suffix.lower()
            if ext in ext_map:
                langs[ext_map[ext]] = langs.get(ext_map[ext], 0) + 1

    lines = [
        f"Project: {p.absolute()}",
        f"Files: {len(files)}  |  Dirs: {dirs}",
    ]

    if langs:
        sorted_langs = sorted(langs.items(), key=lambda x: x[1], reverse=True)
        lang_line = "  ".join(f"{lang}: {count}" for lang, count in sorted_langs[:8])
        lines.append(f"Languages: {lang_line}")

    return {"ok": True, "output": "\n".join(lines)}
