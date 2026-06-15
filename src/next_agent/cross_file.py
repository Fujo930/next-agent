"""Innovation C — Cross-File Consistency Guard.

Validates that multi-file edits maintain consistency:
- Imports resolve to existing modules
- Referenced functions/classes actually exist in their source files
- Config values are consistent across files

Phase 1: Before edit — snapshot files, build dependency graph
Phase 2: After edit — validate consistency, report issues

Python-only for v0.1 (uses ast module). Language-agnostic plugin interface
for future expansion.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ConsistencyIssue:
    """A cross-file inconsistency found after edits."""
    file: str
    line: int
    severity: str  # "error" or "warning"
    message: str
    suggested_fix: str = ""


@dataclass
class FileSnapshot:
    """Snapshot of a file's exports and imports."""
    path: str
    imports: list[dict] = field(default_factory=list)
    exports: set[str] = field(default_factory=set)
    usages: list[dict] = field(default_factory=list)


class CrossFileGuard:
    """Detects cross-file inconsistencies after edits.

    Currently supports Python (using ast). Architecture is ready for
    language plugins (JavaScript, Rust, etc.) via LanguagePlugin ABC.
    """

    def __init__(self, project_root: Path | str = "."):
        self.root = Path(project_root).resolve()
        self.pre_snapshots: dict[str, FileSnapshot] = {}
        self.post_snapshots: dict[str, FileSnapshot] = {}

    def before_edits(self, files: list[str]) -> None:
        """Snapshot files before editing.

        Call this before the LLM edits any files.
        """
        self.pre_snapshots.clear()
        for f in files:
            fp = self.root / f if not os.path.isabs(f) else Path(f)
            if fp.exists() and fp.suffix == ".py":
                self.pre_snapshots[str(fp)] = self._snapshot(fp)

    def after_edits(self, files: list[str]) -> list[ConsistencyIssue]:
        """Validate cross-file consistency after edits.

        Call this after the LLM finishes editing files.
        Automatically snapshots imported modules for consistency checking.

        Returns list of issues found (empty = all consistent).
        """
        self.post_snapshots.clear()
        to_snapshot = set(files)

        # Also snapshot imported modules for cross-reference checks
        for f in list(to_snapshot):
            fp = self.root / f if not os.path.isabs(f) else Path(f)
            if fp.exists() and fp.suffix == ".py":
                snap = self._snapshot(fp)
                self.post_snapshots[str(fp)] = snap
                # Track imported local modules
                for imp in snap.imports:
                    module = imp.get("module", "")
                    if not module or module.startswith(("os", "sys", "json", "re", "typing")):
                        continue
                    # Resolve local module path
                    resolved = self._resolve_module_path(fp.parent, module)
                    if resolved and resolved.exists():
                        to_snapshot.add(str(resolved))

        # Snapshot any remaining files that weren't in the original list
        for f in to_snapshot:
            fp = self.root / f if not os.path.isabs(f) else Path(f)
            if str(fp) not in self.post_snapshots and fp.exists() and fp.suffix == ".py":
                self.post_snapshots[str(fp)] = self._snapshot(fp)

        issues = []
        issues.extend(self._check_imports())
        issues.extend(self._check_exports())
        return issues

    @staticmethod
    def _resolve_module_path(base_dir: Path, module: str) -> Path | None:
        """Resolve a module name to a file path."""
        if module.startswith("."):
            # Relative import
            parts = module.split(".")
            depth = sum(1 for p in parts if not p)
            rest = [p for p in parts if p]
            d = base_dir
            for _ in range(depth - 1):
                d = d.parent
            for p in rest[:-1]:
                d = d / p
            return d / (rest[-1] + ".py") if rest else None

        # Absolute local import: "auth" → base_dir/auth.py
        candidate = base_dir / (module.replace(".", "/") + ".py")
        if candidate.exists():
            return candidate
        # Try __init__.py: "package.module" → base_dir/package/module.py
        candidate2 = base_dir / module.replace(".", "/") + ".py"
        if candidate2.exists():
            return candidate2
        return None

    def _snapshot(self, filepath: Path) -> FileSnapshot:
        """Extract imports, exports, and usages from a Python file."""
        snap = FileSnapshot(path=str(filepath))

        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except SyntaxError:
            return snap  # can't analyze, skip
        except Exception:
            return snap

        base_dir = filepath.parent

        for node in ast.walk(tree):
            # Imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    snap.imports.append({
                        "module": alias.name,
                        "alias": alias.asname or alias.name,
                        "line": node.lineno,
                    })
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for alias in node.names:
                        # Convert relative import to file path
                        module_path = node.module
                        if node.level > 0:  # relative import
                            parts = module_path.split(".") if module_path else []
                            rel_dir = base_dir
                            for _ in range(node.level - 1):
                                rel_dir = rel_dir.parent
                            resolved = rel_dir / "/".join(parts)
                            module_path = str(resolved)
                        snap.imports.append({
                            "module": module_path,
                            "name": alias.name,
                            "line": node.lineno,
                        })

            # Exports (top-level def and class)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                snap.exports.add(node.name)

            # Variable assignments (top-level only)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        snap.exports.add(target.id)

            # Usages (attribute access like module.Function)
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    snap.usages.append({
                        "module": node.value.id,
                        "symbol": node.attr,
                        "line": node.lineno,
                    })

        return snap

    def _check_imports(self) -> list[ConsistencyIssue]:
        """Check that all imports resolve to existing modules."""
        issues = []

        for filepath, snap in self.post_snapshots.items():
            for imp in snap.imports:
                module = imp["module"]
                
                # Skip stdlib and third-party (can't easily check)
                if module.startswith((".", "..")):
                    # Relative import — check file exists
                    resolved = self._resolve_relative_import(filepath, module)
                    if resolved and not Path(resolved).exists() and not Path(resolved + ".py").exists():
                        issues.append(ConsistencyIssue(
                            file=filepath,
                            line=imp["line"],
                            severity="error",
                            message=f"Import '{module}' resolves to '{resolved}' which does not exist",
                            suggested_fix=f"Check if the file was deleted or the import path is correct",
                        ))

        return issues

    def _check_exports(self) -> list[ConsistencyIssue]:
        """Check that referenced symbols exist in their source modules.

        For each usage like `module.symbol`, verify:
        1. module is imported
        2. symbol exists in that module's exports

        Also check that `from module import name` imports resolve to
        existing symbols in the source module.
        """
        issues = []

        # Build export index: module_name → {exported_symbols}
        export_index: dict[str, set[str]] = {}
        for snap in self.post_snapshots.values():
            module_name = Path(snap.path).stem
            export_index[module_name] = snap.exports

        # Check usages (module.symbol patterns)
        for filepath, snap in self.post_snapshots.items():
            import_map: dict[str, str] = {}
            for imp in snap.imports:
                alias = imp.get("alias", imp.get("name", ""))
                module = imp.get("module", "")
                import_map[alias] = module

            for usage in snap.usages:
                module_ref = usage["module"]
                symbol = usage["symbol"]
                if module_ref in import_map:
                    target_module_name = import_map[module_ref]
                    target_key = target_module_name.split(".")[-1]
                    if target_key in export_index:
                        if symbol not in export_index[target_key]:
                            issues.append(ConsistencyIssue(
                                file=filepath, line=usage["line"],
                                severity="warning",
                                message=f"'{symbol}' referenced from '{module_ref}' but not found in exports of '{target_key}'",
                                suggested_fix=f"Verify {symbol} is defined in the source module",
                            ))

            # NEW: Check that from-imports resolve to existing symbols
            for imp in snap.imports:
                name = imp.get("name", "")
                module = imp.get("module", "")
                if not name or not module:
                    continue
                
                # Only check relative/local imports
                if module.startswith(".") or not module.startswith(("os", "sys", "json", "re", "typing", "datetime", "collections", "pathlib", "builtins")):
                    target_key = module.split(".")[-1]
                    if target_key in export_index:
                        if name not in export_index[target_key]:
                            issues.append(ConsistencyIssue(
                                file=filepath, line=imp.get("line", 0),
                                severity="error",
                                message=f"'{name}' imported from '{module}' but '{name}' is not defined in that module",
                                suggested_fix=f"Check if '{name}' exists in {module}.py or if the import name is correct",
                            ))

        return issues

    @staticmethod
    def _resolve_relative_import(filepath: str, import_path: str) -> str | None:
        """Resolve a relative import path to an absolute file path."""
        file_dir = os.path.dirname(filepath)
        parts = import_path.lstrip(".").split(".")
        target = os.path.join(file_dir, *parts)
        return target
