"""In-process job registry for long-running background tasks (daily runs, backtests)."""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


@dataclass
class Job:
    id: str
    type: str
    status: Literal["running", "done", "error"]
    started_at: str
    finished_at: str = ""
    result: Any = None
    error: str = ""
    meta: dict = field(default_factory=dict)


_store: dict[str, Job] = {}
_lock = threading.Lock()


def create_job(job_type: str, meta: dict | None = None) -> Job:
    job_id = uuid.uuid4().hex[:8]
    job = Job(
        id=job_id,
        type=job_type,
        status="running",
        started_at=datetime.now(timezone.utc).isoformat(),
        meta=meta or {},
    )
    with _lock:
        _store[job_id] = job
    return job


def get_job(job_id: str) -> Job | None:
    with _lock:
        return _store.get(job_id)


def finish_job(job_id: str, result: Any) -> None:
    with _lock:
        job = _store.get(job_id)
        if job:
            job.status = "done"
            job.finished_at = datetime.now(timezone.utc).isoformat()
            job.result = result


def fail_job(job_id: str, error: str) -> None:
    with _lock:
        job = _store.get(job_id)
        if job:
            job.status = "error"
            job.finished_at = datetime.now(timezone.utc).isoformat()
            job.error = error
