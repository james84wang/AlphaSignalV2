"""GET /api/about — serves docs/ABOUT.md with git last-updated date."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meta"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ABOUT_MD = _REPO_ROOT / "docs" / "ABOUT.md"


def _git_last_modified(path: Path) -> str | None:
    """Return ISO date of the last git commit that touched `path`, or None."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ci", "--", str(path)],
            capture_output=True, text=True, timeout=5, cwd=str(_REPO_ROOT),
        )
        line = result.stdout.strip()
        if line:
            return line[:10]  # YYYY-MM-DD
    except Exception as exc:
        logger.debug("git log failed: %s", exc)
    return None


@router.get("/api/about")
def get_about() -> JSONResponse:
    if not _ABOUT_MD.exists():
        raise HTTPException(status_code=404, detail="About document not found")
    content = _ABOUT_MD.read_text(encoding="utf-8")
    last_updated = _git_last_modified(_ABOUT_MD) or "unknown"
    return JSONResponse({"content": content, "last_updated": last_updated})
