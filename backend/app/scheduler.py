"""Daily signal scheduler — APScheduler wrapper.

Fires at 08:00 America/New_York on weekdays (M–F), running both the LONG and
SHORT strategies over the combined universe.

IMPORTANT: this only fires when the Mac is awake and the backend process is
running.  If the backend is started after the scheduled time (e.g. mid-morning
AEST), the catch-up logic runs today's job immediately — once — if it hasn't
already run today.

Settings are persisted to ``data/schedule_settings.json`` so the
enabled/disabled toggle survives backend restarts.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.app.api.jobs import create_job
from backend.app.api.runs import _run_daily_task

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SETTINGS_PATH = _REPO_ROOT.parent / "data" / "schedule_settings.json"
_SCHED_HOUR = 8
_SCHED_MINUTE = 0
_SCHED_TZ = "America/New_York"

# Module-level singleton.
_scheduler: BackgroundScheduler | None = None
_settings_lock = threading.Lock()


# ── Settings persistence ───────────────────────────────────────────────────────

def _default_settings() -> dict:
    return {
        "enabled": False,
        "last_run_date": None,      # "YYYY-MM-DD" of most-recent scheduled run
        "catchup_enabled": True,    # run on startup if today's job was missed
    }


def load_settings() -> dict:
    with _settings_lock:
        if _SETTINGS_PATH.exists():
            try:
                data = json.loads(_SETTINGS_PATH.read_text())
                defaults = _default_settings()
                defaults.update(data)
                return defaults
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not read schedule settings: %s — using defaults", exc)
        return _default_settings()


def save_settings(settings: dict) -> None:
    with _settings_lock:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_PATH.write_text(json.dumps(settings, indent=2))


# ── Scheduled job ─────────────────────────────────────────────────────────────

def _run_both_strategies() -> None:
    """Run long + short signals over the combined universe. Called by APScheduler."""
    today = str(date.today())
    logger.info("[scheduler] Starting scheduled daily run for %s", today)

    for strategy in ("long", "short"):
        try:
            job = create_job(
                "scheduled_daily_run",
                meta={"universe": "combined", "strategy": strategy, "date": today, "source": "scheduler"},
            )
            _run_daily_task(job.id, "combined", strategy, date.today())
            logger.info("[scheduler] Finished %s strategy run (job %s)", strategy, job.id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[scheduler] %s strategy run failed: %s", strategy, exc)

    settings = load_settings()
    settings["last_run_date"] = today
    save_settings(settings)
    logger.info("[scheduler] Scheduled run complete. last_run_date=%s", today)


# ── Catch-up logic ────────────────────────────────────────────────────────────

def _should_catchup(settings: dict) -> bool:
    """Return True if we should run immediately because today's job was missed.

    Conditions:
    - enabled is True
    - catchup_enabled is True
    - last_run_date is not today
    - current ET time is at or past the scheduled fire time (08:00)
    """
    if not settings.get("enabled") or not settings.get("catchup_enabled", True):
        return False
    last = settings.get("last_run_date")
    today = str(date.today())
    if last == today:
        return False
    try:
        import zoneinfo
        et_now = datetime.now(zoneinfo.ZoneInfo(_SCHED_TZ))
        if et_now.hour < _SCHED_HOUR or (et_now.hour == _SCHED_HOUR and et_now.minute < _SCHED_MINUTE):
            return False
    except Exception:  # noqa: BLE001
        pass
    return True


# ── Public API ─────────────────────────────────────────────────────────────────

def init_scheduler() -> BackgroundScheduler:
    """Start the APScheduler instance.  Call once at app startup."""
    global _scheduler  # noqa: PLW0603

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        _run_both_strategies,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=_SCHED_HOUR,
            minute=_SCHED_MINUTE,
            timezone=_SCHED_TZ,
        ),
        id="daily_signal_run",
        replace_existing=True,
        misfire_grace_time=3600,    # allow up to 1h late fire if the scheduler was paused
        coalesce=True,              # collapse multiple missed fires into one
    )
    _scheduler.start()
    logger.info(
        "[scheduler] Started. Job fires at %02d:%02d %s (Mon–Fri).",
        _SCHED_HOUR,
        _SCHED_MINUTE,
        _SCHED_TZ,
    )

    settings = load_settings()
    if _should_catchup(settings):
        logger.info("[scheduler] Catch-up: today's run was missed — starting now.")
        t = threading.Thread(target=_run_both_strategies, daemon=True)
        t.start()

    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler  # noqa: PLW0603
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None


# ── Status helpers (used by the schedule API) ─────────────────────────────────

def get_scheduler_status() -> dict[str, Any]:
    """Return the current scheduler state for the GET /api/schedule response."""
    settings = load_settings()
    next_run_iso: str | None = None

    if _scheduler and _scheduler.running:
        job = _scheduler.get_job("daily_signal_run")
        if job and job.next_run_time:
            next_run_iso = job.next_run_time.astimezone(timezone.utc).isoformat()

    last = settings.get("last_run_date")
    return {
        "enabled": settings.get("enabled", False),
        "time": f"{_SCHED_HOUR:02d}:{_SCHED_MINUTE:02d}",
        "tz": _SCHED_TZ,
        "catchup_enabled": settings.get("catchup_enabled", True),
        "last_run_date": last,
        "next_run": next_run_iso,
        "note": (
            "This run only fires when your Mac is awake and the backend is running "
            f"(~{_SCHED_HOUR + 16:02d}:{_SCHED_MINUTE:02d} AEST in summer / "
            f"~{_SCHED_HOUR + 15:02d}:{_SCHED_MINUTE:02d} AEST in winter, depending on US DST). "
            "If the machine is asleep, the catch-up logic will run once on the next backend start "
            "if today's run hasn't happened yet and catchup_enabled=true."
        ),
    }


def set_enabled(enabled: bool) -> dict[str, Any]:
    """Toggle the scheduler on/off and persist the setting."""
    settings = load_settings()
    settings["enabled"] = enabled
    save_settings(settings)

    if _scheduler and _scheduler.running:
        job = _scheduler.get_job("daily_signal_run")
        if job:
            if enabled:
                job.resume()
            else:
                job.pause()

    return get_scheduler_status()
