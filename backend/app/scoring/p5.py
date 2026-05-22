"""P5 pivot sub-score. Implements spec §4.3."""
from __future__ import annotations

import pandas as pd

from backend.app.config import P5Config


def score_p5(pattern_series: pd.Series, cfg: P5Config) -> pd.Series:
    """Map each bar's P5 pattern to a sub-score in [-100, +100]."""
    scores_map: dict[str, float] = cfg.scores.model_dump()
    return pattern_series.map(lambda p: scores_map.get(p, 0.0)).rename("p5_score")
