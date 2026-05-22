"""P3 pivot sub-score. Implements spec §4.2."""
from __future__ import annotations

import pandas as pd

from backend.app.config import P3Config


def score_p3(pattern_series: pd.Series, cfg: P3Config) -> pd.Series:
    """Map each bar's P3 pattern to a sub-score in [-100, +100]."""
    scores_map: dict[str, float] = cfg.scores.model_dump()
    return pattern_series.map(lambda p: scores_map.get(p, 0.0)).rename("p3_score")
