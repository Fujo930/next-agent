# P — Profiles 多实例 (Isolated Agent Instances)

## 借鉴 Hermes

Hermes 的 profiles 系统允许运行多个完全独立的 agent 实例——各自有独立的配置、skills、记忆、会话。

## 当前状态

Next Agent v0.1 只有一个全局 `~/.nextagent/config.json`。切换项目/用户需要手动改环境变量。

## 方案

每个 profile 是一个独立目录，包含完整的 agent 状态：

```
~/.nextagent/
├── profiles/
│   ├── default/
│   │   ├── config.json
│   │   ├── skills/
│   │   ├── memory.db
│   │   └── snapshots/
│   ├── work-python/
│   │   ├── config.json       # 不同项目，不同模型
│   │   ├── skills/           # 不同项目，不同 skill
│   │   └── memory.db         # 不同项目，不同记忆
│   └── oss-contrib/
│       ├── config.json       # 开源项目，用 flash 省钱
│       └── ...
```

### 配置隔离

每个 profile 的 `config.json` 独立：

```json
// work-python/config.json
{
    "model": "deepseek-v4-pro",    // 工作项目用 pro
    "max_rounds": 30,
    "language": "zh",
    "project": "~/work/backend"
}

// oss-contrib/config.json
{
    "model": "deepseek-v4-flash",  // 开源省成本
    "max_rounds": 15,
    "language": "en",
    "project": "~/oss/fastapi"
}
```

### CLI

```bash
next-agent --profile work-python "fix auth bug"
next-agent --profile oss-contrib "review PR #42"

# 或设置默认
next-agent profile use work-python
next-agent                # 自动用 work-python

# 管理
next-agent profile list
next-agent profile create my-project --model pro
next-agent profile delete old-project
```

### GUI 对接

```
GET  /profiles          → [{name, model, project, is_default}]
POST /profiles/switch   → body: {"name": "work-python"}
POST /profiles/create   → body: {"name": "...", "model": "..."}
```

### 实现要点

- `ProfileManager` 读取 `~/.nextagent/profiles/<name>/` 目录
- Agent 初始化时加载 profile 的 config + skills + memory
- Profile 切换 → 新 session（prefix cache 重建）
- 全局环境变量（DEEPSEEK_API_KEY）所有 profile 共享

### 改动文件

- `src/next_agent/profiles.py` — ProfileManager
- `src/next_agent/main.py` — --profile flag
- `src/next_agent/setup.py` — profile 创建向导
