"""GET /api/schedule  and  PUT /api/schedule — scheduler control endpoints."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.scheduler import get_scheduler_status, set_enabled

router = APIRouter(prefix="/api", tags=["schedule"])


class ScheduleUpdate(BaseModel):
    enabled: bool


@router.get("/schedule")
def get_schedule() -> dict:
    """Return current scheduler state: enabled flag, fire time, last/next run."""
    return get_scheduler_status()


@router.put("/schedule")
def update_schedule(body: ScheduleUpdate) -> dict:
    """Enable or disable the daily scheduler. Persists across backend restarts."""
    return set_enabled(body.enabled)
