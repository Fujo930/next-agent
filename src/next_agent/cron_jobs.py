"""Cron Scheduler — scheduled autonomous tasks.

Light-weight scheduler for periodic agent runs.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


DB_PATH = Path.home() / ".nextagent" / "cron.db"


@dataclass
class CronJob:
    """A scheduled task."""
    id: str
    name: str
    schedule: str  # "30m", "2h", "0 9 * * *", ISO timestamp
    prompt: str
    model: str = "deepseek-v4-flash"
    enabled: bool = True
    last_run: float = 0.0
    next_run: float = 0.0
    run_count: int = 0
    last_result: str = ""  # JSON


class CronScheduler:
    """Manages scheduled agent tasks."""

    RE_INTERVAL = re.compile(r"^(\d+)(m|h|d)$")
    RE_EVERY = re.compile(r"^every\s+(\d+)\s*(m|h|d)$")

    def __init__(self, agent_factory=None):
        self._agent_factory = agent_factory
        self._running = False
        self._thread: threading.Thread | None = None
        self._init_db()

    def _init_db(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(DB_PATH)) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS cron_jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    schedule TEXT,
                    prompt TEXT,
                    model TEXT DEFAULT 'deepseek-v4-flash',
                    enabled INTEGER DEFAULT 1,
                    last_run REAL DEFAULT 0,
                    next_run REAL DEFAULT 0,
                    run_count INTEGER DEFAULT 0,
                    last_result TEXT DEFAULT ''
                )
            """)

    def add(self, name: str, schedule: str, prompt: str, model: str = "deepseek-v4-flash") -> CronJob:
        """Add a new cron job."""
        import uuid
        job = CronJob(
            id=str(uuid.uuid4())[:8],
            name=name,
            schedule=schedule,
            prompt=prompt,
            model=model,
            next_run=self._parse_schedule(schedule),
        )
        with sqlite3.connect(str(DB_PATH)) as db:
            db.execute(
                "INSERT INTO cron_jobs VALUES (?,?,?,?,?,?,?,?,?)",
                (job.id, job.name, job.schedule, job.prompt,
                 job.model, int(job.enabled), job.last_run,
                 job.next_run, job.run_count, job.last_result),
            )
        return job

    def list(self) -> list[CronJob]:
        """List all jobs."""
        jobs = []
        with sqlite3.connect(str(DB_PATH)) as db:
            rows = db.execute(
                "SELECT id,name,schedule,prompt,model,enabled,last_run,next_run,run_count,last_result FROM cron_jobs ORDER BY name"
            ).fetchall()
        for row in rows:
            jobs.append(CronJob(
                id=row[0], name=row[1], schedule=row[2], prompt=row[3],
                model=row[4], enabled=bool(row[5]), last_run=row[6],
                next_run=row[7], run_count=row[8], last_result=row[9],
            ))
        return jobs

    def toggle(self, job_id: str) -> bool:
        """Toggle enabled state."""
        job = self._get(job_id)
        if job:
            with sqlite3.connect(str(DB_PATH)) as db:
                db.execute(
                    "UPDATE cron_jobs SET enabled=? WHERE id=?",
                    (int(not job.enabled), job_id),
                )
            return True
        return False

    def remove(self, job_id: str) -> bool:
        """Remove a job."""
        with sqlite3.connect(str(DB_PATH)) as db:
            db.execute("DELETE FROM cron_jobs WHERE id=?", (job_id,))
        return True

    def start(self) -> None:
        """Start background scheduler thread."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            self._check_and_run()
            time.sleep(30)

    def _check_and_run(self) -> None:
        now = time.time()
        for job in self.list():
            if job.enabled and job.next_run and job.next_run <= now:
                self._run_job(job)

    def _run_job(self, job: CronJob) -> None:
        try:
            if self._agent_factory:
                agent = self._agent_factory(job.model)
                response = agent.run(job.prompt)
                result = json.dumps({"ok": True, "output": response[:500]})
            else:
                result = json.dumps({"ok": False, "error": "No agent factory configured"})
        except Exception as e:
            result = json.dumps({"ok": False, "error": str(e)[:200]})

        job.run_count += 1
        job.last_run = time.time()
        job.next_run = self._parse_schedule(job.schedule)
        job.last_result = result

        with sqlite3.connect(str(DB_PATH)) as db:
            db.execute(
                "UPDATE cron_jobs SET last_run=?,next_run=?,run_count=?,last_result=? WHERE id=?",
                (job.last_run, job.next_run, job.run_count, job.last_result, job.id),
            )

    def _get(self, job_id: str) -> CronJob | None:
        jobs = self.list()
        for j in jobs:
            if j.id == job_id:
                return j
        return None

    @classmethod
    def _parse_schedule(cls, schedule: str) -> float:
        """Parse schedule string to next run timestamp."""
        now = time.time()

        # ISO timestamp
        if "T" in schedule and "-" in schedule:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(schedule)
                return dt.timestamp()
            except Exception:
                pass

        # Duration: 30m, 2h, 1d
        m = cls.RE_INTERVAL.match(schedule)
        if m:
            value = int(m.group(1))
            unit = m.group(2)
            multipliers = {"m": 60, "h": 3600, "d": 86400}
            return now + value * multipliers.get(unit, 60)

        # "every Xm/h/d"
        m = cls.RE_EVERY.match(schedule)
        if m:
            value = int(m.group(1))
            unit = m.group(2)
            multipliers = {"m": 60, "h": 3600, "d": 86400}
            return now + value * multipliers.get(unit, 60)

        # Cron format: parse conservatively — default to next hour
        return now + 3600
