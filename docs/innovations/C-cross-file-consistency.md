# C — 跨文件一致性守卫 (Cross-File Consistency Guard)

## 解决的问题

DeepSeek 在多文件重构时的一致性问题：
- 编辑 `auth.py` 添加了 `create_jwt()` 函数
- 但在 `main.py` 中仍然调用不存在的 `old_auth()`
- 改了 `config.py` 的端口号
- 但 `docker-compose.yml` 的端口映射没更新

Reasonix 和 CodeWhale 都是**事后补救**（checkpoint rollback），不是**事前预防**。

## 方案：编辑前建图 + 编辑后验证

```
Phase 1: 编辑前 — 构建文件依赖图
Phase 2: 编辑中 — 正常编辑
Phase 3: 编辑后 — 自动验证跨文件一致性
    ↓
  ✅ 一致 → 继续
  ❌ 不一致 → 自动修复 或 报告给 LLM
```

### 实现

```python
class CrossFileGuard:
    """Tracks file dependencies and validates consistency after edits."""

    def __init__(self, project_root: Path):
        self.root = project_root
        self.pre_state: dict[str, FileSnapshot] = {}  # 编辑前快照
        self.post_state: dict[str, FileSnapshot] = {}  # 编辑后快照
        self.dependency_graph: nx.DiGraph = nx.DiGraph()

    def before_edit(self, files: list[Path]) -> None:
        """Snapshot files before editing."""
        for f in files:
            if f.exists():
                self.pre_state[str(f)] = self._snapshot(f)

    def after_edit(self, files: list[Path]) -> list[ConsistencyIssue]:
        """Validate consistency and report issues."""
        self.dependency_graph.clear()
        
        # Build dependency graph
        for f in files:
            self.post_state[str(f)] = self._snapshot(f)
            self._extract_references(f, self.dependency_graph)

        issues = []
        # Check 1: Import resolution
        issues.extend(self._check_imports())
        
        # Check 2: Function/class definition vs usage
        issues.extend(self._check_symbols())
        
        # Check 3: Config consistency (port numbers, file paths, etc.)
        issues.extend(self._check_configs())

        return issues

    def _check_imports(self) -> list[ConsistencyIssue]:
        """Verify all imports resolve to existing modules."""
        issues = []
        for filepath, snap in self.post_state.items():
            for imp in snap.imports:
                resolved = self.root / imp.module_path
                if not resolved.exists():
                    issues.append(ConsistencyIssue(
                        file=filepath,
                        line=imp.line,
                        severity="error",
                        message=f"Import '{imp.module_path}' not found",
                        fix=self._suggest_import_fix(imp)
                    ))
        return issues

    def _check_symbols(self) -> list[ConsistencyIssue]:
        """Check that referenced symbols exist in their source files."""
        issues = []
        # 1. Collect exports from all files
        exports: dict[str, set[str]] = {}  # file → {symbol names}
        usages: dict[str, list[SymbolUsage]] = {}  # file → [usages]
        
        for filepath, snap in self.post_state.items():
            exports[filepath] = snap.defined_symbols
            usages[filepath] = snap.referenced_symbols

        # 2. For each usage, check if symbol exists in target module
        for filepath, refs in usages.items():
            for ref in refs:
                if ref.module in exports:
                    if ref.symbol not in exports[ref.module]:
                        issues.append(ConsistencyIssue(
                            file=filepath,
                            line=ref.line,
                            severity="error",
                            message=f"'{ref.symbol}' not found in {ref.module}",
                            fix=f"Did you mean: {self._find_similar(ref.symbol, exports[ref.module])}"
                        ))
        return issues
```

## 支持的语言

第一期只支持 Python（用 `ast` 模块）。架构预留了 language plugin 接口：

```python
class LanguagePlugin(ABC):
    """Plugin for parsing a specific language's import/export patterns."""
    @abstractmethod
    def extract_imports(self, file: Path) -> list[Import]:
        ...
    @abstractmethod
    def extract_exports(self, file: Path) -> set[str]:
        ...
    @abstractmethod
    def extract_usages(self, file: Path) -> list[SymbolUsage]:
        ...
```

## 优势

- Python 的 `ast` 模块让 import 分析零依赖
- 只检查**静态可验证**的（import 存在、函数定义匹配），不试图验证业务逻辑
- 在 LLM 的编辑之后自动运行，成本极低
- 发现不一致时可以给 LLM 具体的修复提示

## 风险

- 动态导入 (`importlib.import_module`)、`getattr` 等无法静态分析
- 需要项目有明确的模块结构（不适合单文件脚本）
