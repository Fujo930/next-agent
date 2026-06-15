"""Job Manager — background task execution with exponential backoff.

Inspired by CodeWhale's JobManager. Manages background tasks with:
- State machine: queued → running → completed/failed/cancelled
- Exponential backoff: retry with increasing delays
- Progress tracking: 0-100% with detail messages
- History: chronological state transitions

Used for: long-running sub-agents, batch operations, test suites.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class JobStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobHistory:
    """A state transition in a job's lifecycle."""
    at: float = field(default_factory=time.time)
    status: JobStatus = JobStatus.QUEUED
    detail: str = ""


@dataclass
class Job:
    """A background job."""
    id: str
    name: str
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0  # 0-100
    detail: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    # Retry
    attempts: int = 0
    max_attempts: int = 3
    backoff_base_ms: int = 500  # base delay for exponential backoff
    next_backoff_ms: int = 0
    next_retry_at: float | None = None
    
    # Internal
    _fn: Callable | None = field(default=None, repr=False)
    _result: dict | None = field(default=None, repr=False)
    history: list[JobHistory] = field(default_factory=list)


class JobManager:
    """Manages background jobs with retry and progress tracking."""

    MAX_HISTORY = 64

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._counter = 0
        self._lock = threading.Lock()

    def enqueue(self, name: str, fn: Callable, max_attempts: int = 3) -> str:
        """Create and queue a new job.

        Returns the job ID.
        """
        with self._lock:
            self._counter += 1
            job_id = f"job_{self._counter}"
            job = Job(
                id=job_id,
                name=name,
                max_attempts=max_attempts,
                _fn=fn,
            )
            job.history.append(JobHistory(status=JobStatus.QUEUED, detail="created"))
            self._jobs[job_id] = job
            return job_id

    def run(self, job_id: str) -> Job:
        """Execute a job synchronously with retry."""
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")

        self._transition(job, JobStatus.RUNNING)
        
        while job.attempts < job.max_attempts:
            try:
                result = job._fn()
                job._result = result
                job.progress = 100
                self._transition(job, JobStatus.COMPLETED, detail="success")
                return job
            except Exception as e:
                job.attempts += 1
                if job.attempts >= job.max_attempts:
                    self._transition(job, JobStatus.FAILED, detail=str(e)[:200])
                    return job
                
                # Exponential backoff
                delay_ms = job.backoff_base_ms * (2 ** (job.attempts - 1))
                job.next_backoff_ms = delay_ms
                job.next_retry_at = time.time() + delay_ms / 1000
                self._transition(
                    job, JobStatus.FAILED,
                    detail=f"Attempt {job.attempts} failed: {e}. Retrying in {delay_ms}ms"
                )
                time.sleep(delay_ms / 1000)
                self._transition(job, JobStatus.RUNNING, detail=f"Retry {job.attempts}")

        return job

    def run_async(self, job_id: str) -> threading.Thread:
        """Run a job in a background thread."""
        t = threading.Thread(target=self.run, args=(job_id,), daemon=True)
        t.start()
        return t

    def cancel(self, job_id: str) -> None:
        """Cancel a pending or running job."""
        job = self._jobs.get(job_id)
        if job:
            self._transition(job, JobStatus.CANCELLED, detail="cancelled by user")

    def get(self, job_id: str) -> Job | None:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        """List all jobs, newest first."""
        return sorted(
            self._jobs.values(),
            key=lambda j: j.updated_at,
            reverse=True,
        )

    def progress(self, job_id: str, progress: int, detail: str = "") -> None:
        """Update job progress."""
        job = self._jobs.get(job_id)
        if job:
            job.progress = min(100, max(0, progress))
            job.detail = detail
            job.updated_at = time.time()

    def _transition(self, job: Job, status: JobStatus, detail: str = "") -> None:
        """Record a state transition."""
        job.status = status
        job.updated_at = time.time()
        if detail:
            job.detail = detail
        job.history.append(JobHistory(status=status, detail=detail))
        if len(job.history) > self.MAX_HISTORY:
            job.history = job.history[-self.MAX_HISTORY:]
