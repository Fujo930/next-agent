# Q — Cron 定时任务 (Scheduled Autonomous Tasks)

## 借鉴 Hermes

Hermes 有完整的 cron 子系统——定时触发 agent 执行任务、支持 delivery 到多平台、script 前置数据收集、context_from 任务链。

## 方案

轻量版 scheduler，适合 GUI coding agent 的常见场景。

### 使用场景

```
每周五 17:00 → review 本周所有改动，生成周报
每天 09:00  → 检查依赖更新，提交 PR
每 30 分钟  → 监控 CI 状态，有失败就通知
每次 git push → 自动跑 lint + fix
```

### 存储模型

```sql
CREATE TABLE cron_jobs (
    id TEXT PRIMARY KEY,
    name TEXT,
    schedule TEXT,        -- "0 9 * * *" or "30m" or "every monday 9am"
    prompt TEXT,          -- self-contained task prompt
    model TEXT,           -- flash/pro
    enabled INTEGER,
    last_run REAL,
    next_run REAL,
    run_count INTEGER DEFAULT 0,
    last_result TEXT      -- JSON: {ok, output, tokens, elapsed}
);
```

### Scheduler

```python
class CronScheduler:
    """Background thread that checks for due jobs and runs them."""

    def __init__(self, agent_factory: Callable[[], Agent]):
        self._jobs: dict[str, CronJob] = {}
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start background scheduler thread."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while self._running:
            now = time.time()
            for job in self._jobs.values():
                if job.enabled and job.next_run and job.next_run <= now:
                    self._run_job(job)
            time.sleep(30)  # check every 30s

    def _run_job(self, job: CronJob) -> None:
        agent = self._agent_factory()
        try:
            response = agent.run(job.prompt)
            job.last_result = json.dumps({"ok": True, "output": response[:1000]})
        except Exception as e:
            job.last_result = json.dumps({"ok": False, "error": str(e)})
        job.run_count += 1
        job.last_run = time.time()
        job.next_run = self._parse_schedule(job.schedule)
```

### Schedule 语法

```
"30m"              → 每 30 分钟
"2h"               → 每 2 小时
"0 9 * * *"        → 每天 9:00
"0 17 * * 5"       → 每周五 17:00
"2026-06-20T09:00" → 一次性（到时间执行一次然后自动禁用）
```

### GUI 对接

```
GET  /cron            → [{id, name, schedule, enabled, last_run, run_count}]
POST /cron            → body: {name, schedule, prompt, model}
POST /cron/:id/toggle → 启用/暂停
POST /cron/:id/run    → 立即执行一次
DELETE /cron/:id      → 删除
```

### 改动文件

- `src/next_agent/cron.py` — CronJob, CronScheduler
- `src/next_agent/agent.py` — agent_factory 注入
- `~/.nextagent/cron.db` — SQLite 存储
