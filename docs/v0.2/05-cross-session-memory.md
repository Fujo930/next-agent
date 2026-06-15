# N — 跨会话记忆 (Cross-Session Memory)

## 借鉴 Hermes

Hermes 有可插拔的持久记忆系统——记住用户偏好、环境细节、经验教训。默认用内置 FTS5 引擎，可切换到 Honcho、Mem0 等外部后端。

## 当前状态

Next Agent v0.1 无跨会话记忆。每次新 session agent 对你的项目、偏好、约定一无所知。

## 方案

SQLite + FTS5 全文搜索。三层记忆：

### 记忆类型

```python
class MemoryType(Enum):
    USER_PROFILE = "user"     # "用户叫 hooya, 偏好中文, 喜欢暖色调 UI"
    PROJECT = "project"       # "这个项目用 pytest + xdist"
    PREFERENCE = "pref"      # "不要用 emoji, 用 SVG 图标"
    LESSON = "lesson"        # "PyInstaller 需要 --collect-all 新模块"
    CONVENTION = "convention" # "commit message 用中文"
    ENVIRONMENT = "env"       # "Windows 10, Python 3.11, git-bash"
```

### 存储结构

```sql
CREATE TABLE memories (
    id INTEGER PRIMARY KEY,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    project TEXT,           -- NULL = global
    created_at REAL,
    last_accessed REAL,
    access_count INTEGER DEFAULT 0,
    importance REAL DEFAULT 0.5  -- 0-1, the agent sets this
);

CREATE VIRTUAL TABLE memories_fts USING fts5(content, type, project);
```

### 自动注入

Session 开始，MemoryManager 查询相关记忆，注入 frozen prefix：

```python
def load_for_session(self, project: str, user_input: str) -> str:
    """Return memory context for this session."""
    # 1. Global memories (user profile, preferences)
    # 2. Project-specific memories
    # 3. Memories matching user_input via FTS5
    memories = []
    memories.extend(self._query_global())
    memories.extend(self._query_project(project))
    memories.extend(self._search_relevant(user_input, limit=5))
    
    if memories:
        return "## Agent Memory\n" + "\n".join(
            f"- [{m.type}] {m.content}" for m in memories
        )
    return ""
```

### 自动保存

Agent 通过 `remember` 工具保存记忆（或自动检测）：

```python
# Agent calls: remember("用户不喜欢 emoji, 用 SVG 图标", type="preference")
# Or auto-detect:
# - User says "不要再用..." → save as lesson
# - Agent discovers environment quirk → save as env
# - Agent fixes same bug 3x → save as pattern
```

### 衰减权重

访问频率高的记忆权重上升，不用的自然衰减。Session 注入时按 `importance * log(access_count + 1)` 排序，只取 top 5。

### GUI 对接

```
GET  /memory          → [{id, type, content, project, access_count}]
POST /memory          → body: {"content": "...", "type": "lesson"}
DELETE /memory/:id    → 删除记忆
```

### 改动文件

- `src/next_agent/memory_db.py` — SQLite + FTS5 引擎
- `src/next_agent/memory.py` — MemoryManager 核心
- `src/next_agent/agent.py` — Session 开始时注入
- `~/.nextagent/memory.db` — 数据库文件
