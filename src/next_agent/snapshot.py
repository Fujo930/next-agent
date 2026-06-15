"""Side-git snapshot system — non-invasive undo for agent edits.

Inspired by CodeWhale's side-git. Creates snapshots of edited files
in a separate .nextagent/snapshots/ directory, keeping the project's
.git untouched.

Features:
- Auto-snapshot before each edit (write_file/edit_file)
- Snapshot only the files being changed (not full project)
- /restore command to rollback
- /snapshots command to list history
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from pathlib import Path


SNAPSHOT_DIR = ".nextagent/snapshots"


def init_snapshots(workdir: Path | str = ".") -> Path:
    """Initialize the snapshot directory."""
    snap_dir = Path(workdir) / SNAPSHOT_DIR
    snap_dir.mkdir(parents=True, exist_ok=True)
    return snap_dir


def snapshot_file(filepath: str | Path, workdir: Path | str = ".") -> str | None:
    """Take a snapshot of a file before editing.

    Args:
        filepath: Path to the file (absolute or relative to workdir)
        workdir: Working directory

    Returns:
        Snapshot ID (timestamp string) or None if file doesn't exist.
    """
    fp = Path(filepath)
    if not fp.is_absolute():
        fp = Path(workdir) / fp

    if not fp.exists():
        return None

    snap_dir = init_snapshots(workdir)
    snap_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    snap_path = snap_dir / snap_id

    # Store the original file
    snap_path.mkdir(parents=True, exist_ok=True)
    relative = fp.relative_to(Path(workdir).resolve())
    dest = snap_path / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fp, dest)

    # Metadata
    meta = {
        "id": snap_id,
        "file": str(relative),
        "original": str(fp),
        "timestamp": time.time(),
        "size": fp.stat().st_size,
    }
    (snap_path / "meta.json").write_text(json.dumps(meta, indent=2))

    return snap_id


def restore_snapshot(snap_id: str, workdir: Path | str = ".") -> bool:
    """Restore a file from a snapshot.

    Returns True if restoration succeeded.
    """
    snap_dir = Path(workdir) / SNAPSHOT_DIR
    snap_path = snap_dir / snap_id

    if not snap_path.exists():
        return False

    meta_path = snap_path / "meta.json"
    if not meta_path.exists():
        return False

    meta = json.loads(meta_path.read_text())
    original = Path(meta["original"])
    backed_up = snap_path / meta["file"]

    if not backed_up.exists():
        return False

    shutil.copy2(backed_up, original)
    return True


def list_snapshots(workdir: Path | str = ".", limit: int = 20) -> list[dict]:
    """List recent snapshots."""
    snap_dir = Path(workdir) / SNAPSHOT_DIR
    if not snap_dir.exists():
        return []

    snapshots = []
    for entry in sorted(snap_dir.iterdir(), reverse=True):
        if entry.is_dir():
            meta_path = entry / "meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                    meta["_id"] = entry.name
                    snapshots.append(meta)
                except Exception:
                    pass

    return snapshots[:limit]


def format_snapshots(snapshots: list[dict]) -> str:
    """Format snapshot list for display."""
    if not snapshots:
        return "No snapshots."
    lines = ["Snapshots:"]
    for s in snapshots:
        ts = datetime.fromtimestamp(s["timestamp"]).strftime("%H:%M:%S")
        lines.append(f"  {s['_id']}  {s['file']}  ({ts}, {s['size']}B)")
    return "\n".join(lines)
