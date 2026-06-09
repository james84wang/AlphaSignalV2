"""POST /api/optimize + GET /api/optimize/{job_id} — run & poll the optimiser.

Mirrors the backtest job pattern: a daemon thread runs the Optuna search while
the in-process job store tracks live progress (trials completed + phase). The
done-result carries the in-sample / holdout / walk-forward metrics, the
PASS/FAIL overfit verdict, the anti-overfitting analysis (luck audit, cluster,
perturbation) and the best entry/exit weights.

The winning config is written to ``config.candidate.hidden_div.yaml``; the live
``config.yaml`` is **never** touched by a run. Promotion is an explicit second
call (``POST /{job_id}/promote``) that validates the candidate and copies it
onto the live config.
"""
from __future__ import annotations

import logging
import tempfile
import threading
from datetime import date, timedelta
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from backend.app.api.jobs import create_job, fail_job, finish_job, get_job, update_job_progress
from backend.app.config import AppConfig, load_config, reset_config
from backend.app.data.cache import ParquetCache
from backend.app.data.watchlists import is_valid_universe, resolve_universe
from backend.app.data.yfinance_provider import YFinanceProvider
from backend.app.db.models import config_hash
from backend.app.optimizer.core import OptimiserConfig, run_optimisation, save_candidate_config
from backend.app.optimizer.report import generate_report, write_trials_csv

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/optimize", tags=["optimize"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _REPO_ROOT / "config.yaml"

# Convenience fallback when the watchlist DB is empty (mirrors scripts/optimize.py).
_WATCHLIST_FALLBACK = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
                       "META", "TSLA", "JPM", "V", "UNH"]


class OptimizeRequest(BaseModel):
    universe: str = "watchlist"          # watchlist | wl:<name> | sp500 | … | combined
    start: str | None = None             # YYYY-MM-DD (default: 5y back)
    end: str | None = None               # YYYY-MM-DD (default: today)
    trials: int = 200
    folds: int = 4
    seed: int = 42
    insample_ratio: float = 0.70
    max_drawdown_limit: float = 0.25     # 0–1 hard DD constraint
    include_scoring_tables: bool = False  # also tune the confluence windows
    include_sizing: bool = False          # also tune position sizing


# ── Routes ──────────────────────────────────────────────────────────────────────

@router.post("", status_code=202)
def start_optimize(body: OptimizeRequest) -> dict:
    """Start an optimisation run in the background. Returns a job_id to poll."""
    cfg = load_config(_CONFIG_PATH)

    if not is_valid_universe(body.universe, cfg):
        raise HTTPException(422, detail=f"Unknown universe {body.universe!r}")
    if body.trials < 1:
        raise HTTPException(422, detail="trials must be >= 1")
    if body.folds < 2:
        raise HTTPException(422, detail="folds must be >= 2")
    if not (0.5 <= body.insample_ratio <= 0.95):
        raise HTTPException(422, detail="insample_ratio must be between 0.5 and 0.95")

    end_date = date.fromisoformat(body.end) if body.end else date.today()
    start_date = (
        date.fromisoformat(body.start)
        if body.start
        else end_date - timedelta(days=cfg.backtest.start_years_back * 365)
    )
    if start_date >= end_date:
        raise HTTPException(422, detail="start must be before end")

    job = create_job("optimize", meta={
        "universe": body.universe,
        "start": str(start_date),
        "end": str(end_date),
        "trials": body.trials,
    })

    t = threading.Thread(
        target=_run_optimize_task,
        args=(job.id, body, start_date, end_date),
        daemon=True,
    )
    t.start()

    return {
        "job_id": job.id,
        "status": "running",
        "message": (
            f"Optimisation started: {body.universe} {start_date} → {end_date}, "
            f"{body.trials} trials"
        ),
    }


@router.get("/{job_id}")
def get_optimize_status(job_id: str) -> dict:
    """Poll progress, or retrieve the full result of a completed optimisation."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, detail=f"Unknown job_id: {job_id}")

    base = {"job_id": job.id, "status": job.status, "started_at": job.started_at}
    if job.status == "running":
        return {**base, "n_done": job.n_done, "n_total": job.n_total, "phase": job.phase}
    if job.status == "error":
        return {**base, "finished_at": job.finished_at, "error": job.error}
    return {**base, "finished_at": job.finished_at, **(job.result or {})}


@router.post("/{job_id}/promote")
def promote_candidate(job_id: str) -> dict:
    """Apply a completed run's candidate config onto the live config.yaml.

    This is the one place the optimiser writes the live config — and only when
    the user explicitly asks for it from the UI.
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, detail=f"Unknown job_id: {job_id}")
    if job.status != "done" or not job.result:
        raise HTTPException(409, detail="Job is not complete — nothing to promote")

    candidate_path = Path(job.result.get("candidate_path", ""))
    if not candidate_path.exists():
        raise HTTPException(404, detail="Candidate config file not found on disk")

    cand = yaml.safe_load(candidate_path.read_text())
    try:
        AppConfig.model_validate(cand)  # never write an invalid config
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, detail=f"Candidate config is invalid: {exc}")

    try:
        with open(_CONFIG_PATH, "w") as fh:
            yaml.safe_dump(cand, fh, default_flow_style=False, sort_keys=False)
    except OSError as exc:
        raise HTTPException(500, detail=f"Failed to write config.yaml: {exc}")

    reset_config()
    return {
        "ok": True,
        "promoted_from": candidate_path.name,
        "config_hash": config_hash(_CONFIG_PATH),
    }


@router.get("/{job_id}/report", response_class=PlainTextResponse)
def get_optimize_report(job_id: str) -> PlainTextResponse:
    """Return the markdown optimisation report for a completed job."""
    job = get_job(job_id)
    if job is None or job.status != "done" or not job.result:
        raise HTTPException(404, detail="No completed result for this job")
    report_path = Path(job.result.get("report_path", ""))
    if not report_path.exists():
        raise HTTPException(404, detail="Report not found on disk")
    return PlainTextResponse(report_path.read_text(), media_type="text/markdown; charset=utf-8")


# ── Background worker ──────────────────────────────────────────────────────────

def _run_optimize_task(job_id: str, body: OptimizeRequest, start: date, end: date) -> None:
    try:
        cfg = load_config(_CONFIG_PATH)
        symbols = resolve_universe(body.universe, cfg)
        if not symbols and body.universe == "watchlist":
            symbols = list(_WATCHLIST_FALLBACK)
        if not symbols:
            fail_job(job_id, "No symbols resolved for optimisation")
            return

        cache = ParquetCache(YFinanceProvider())

        def fetcher(sym: str, s: date, e: date):
            return cache.get_daily_bars(sym, s, e)

        def _cb(n_done: int, n_total: int, phase: str) -> None:
            update_job_progress(job_id, n_done, n_total, phase)

        # Each UI run gets its own fresh Optuna study so "N trials" means N (the
        # CLI deliberately reuses a per-date study; a UI run should be isolated).
        study_db = Path(tempfile.gettempdir()) / f"alphasignal_study_{job_id}.db"
        study_db.unlink(missing_ok=True)

        opt_cfg = OptimiserConfig(
            strategy="hidden_div",
            insample_ratio=body.insample_ratio,
            max_trials=body.trials,
            n_folds=body.folds,
            max_drawdown_limit=body.max_drawdown_limit,
            seed=body.seed,
            include_scoring_tables=body.include_scoring_tables,
            include_sizing=body.include_sizing,
            study_db_path=study_db,
        )

        result = run_optimisation(
            symbols=symbols, start=start, end=end, base_cfg=cfg,
            data_fetcher=fetcher, opt_cfg=opt_cfg, progress_callback=_cb,
        )

        candidate_path = save_candidate_config(result, "hidden_div", cfg)
        report_path = generate_report(result, "hidden_div", symbols,
                                      candidate_path=candidate_path)
        csv_path = write_trials_csv(result, "hidden_div")

        finish_job(job_id, _build_payload(result, symbols, candidate_path,
                                          report_path, csv_path))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Optimisation failed for job %s", job_id)
        fail_job(job_id, str(exc))


def _f(x) -> float:
    """Coerce a possibly-numpy number to a plain JSON-safe float."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _metrics(d: dict) -> dict:
    """Float-coerce a metrics dict so it is always JSON-serialisable."""
    return {k: _f(v) for k, v in (d or {}).items()}


def _build_payload(result, symbols, candidate_path, report_path, csv_path) -> dict:
    return {
        "universe_size": len(symbols),
        "n_trials": result.n_trials_attempted,
        "wall_clock_seconds": round(_f(result.wall_clock_seconds), 1),
        "insample_start": str(result.insample_start),
        "insample_end": str(result.insample_end),
        "holdout_start": str(result.holdout_start),
        "holdout_end": str(result.holdout_end),
        "pass_verdict": bool(result.pass_verdict),
        "verdict_tier": result.verdict_tier,
        "verdict_notes": list(result.verdict_notes),
        "insample_metrics": _metrics(result.insample_metrics),
        "holdout_metrics": _metrics(result.holdout_metrics),
        "wf_metrics": _metrics(result.wf_metrics),
        "holdout_benchmark_metrics": _metrics(result.holdout_benchmark_metrics),
        "benchmark_vs_spy_metrics": _metrics(result.benchmark_vs_spy_metrics),
        "luck_audit": result.luck_audit,
        "cluster_analysis": result.cluster_analysis,
        "perturbation_results": result.perturbation_results,
        "best_strat": result.best_strat_dict,
        "best_composite_score": round(_f(result.best_composite_score), 4),
        "candidate_path": str(candidate_path),
        "report_path": str(report_path),
        "csv_path": str(csv_path),
    }
