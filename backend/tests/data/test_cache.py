"""Tests for cache.py — hit/miss logic, force refresh, graceful provider failure."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backend.app.data.cache import ParquetCache
from backend.app.data.provider import ProviderError
from backend.tests.data.conftest import make_bars


@pytest.fixture
def tmp_cache(tmp_path):
    """A ParquetCache backed by a real temp dir and a mock provider."""
    provider = MagicMock()
    cache = ParquetCache(provider, cache_dir=tmp_path / "bars")
    return cache, provider


def test_cache_miss_calls_provider(tmp_cache):
    cache, provider = tmp_cache
    bars = make_bars(start=date(2024, 1, 2), n=5)
    provider.get_daily_bars.return_value = bars

    result = cache.get_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 8))

    provider.get_daily_bars.assert_called_once()
    assert len(result) == len(bars)


def test_cache_hit_does_not_call_provider(tmp_cache):
    cache, provider = tmp_cache
    bars = make_bars(start=date(2024, 1, 2), n=10)
    provider.get_daily_bars.return_value = bars

    # Prime the cache.
    cache.get_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 15))
    provider.reset_mock()

    # Second call for the same range — should not hit the provider.
    cache.get_daily_bars("AAPL", date(2024, 1, 3), date(2024, 1, 10))
    provider.get_daily_bars.assert_not_called()


def test_cache_extends_forward_when_end_is_later(tmp_cache):
    cache, provider = tmp_cache
    bars_early = make_bars(start=date(2024, 1, 2), n=5)
    bars_late = make_bars(start=date(2024, 1, 9), n=3)
    provider.get_daily_bars.side_effect = [bars_early, bars_late]

    # First fetch covers Jan 2–8.
    cache.get_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 8))
    assert provider.get_daily_bars.call_count == 1

    # Second fetch extends to Jan 12 — provider called once more for the gap.
    provider.get_daily_bars.side_effect = [bars_late]
    cache.get_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 12))
    assert provider.get_daily_bars.call_count == 2


def test_force_refresh_clears_cache(tmp_cache):
    cache, provider = tmp_cache
    bars = make_bars(start=date(2024, 1, 2), n=5)
    provider.get_daily_bars.return_value = bars

    cache.get_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 8))
    cache.get_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 8), force_refresh=True)

    # Provider should have been called twice.
    assert provider.get_daily_bars.call_count == 2


def test_graceful_failure_when_provider_errors(tmp_cache):
    cache, provider = tmp_cache
    provider.get_daily_bars.side_effect = ProviderError("Network down")

    # A total miss with a failing provider should raise ProviderError.
    with pytest.raises(ProviderError):
        cache.get_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 8))


def test_cache_file_location(tmp_cache, tmp_path):
    cache, provider = tmp_cache
    path = cache.cache_path("aapl")
    assert path.name == "AAPL.parquet"
    assert "bars" in str(path)


def test_cache_persisted_to_disk(tmp_cache, tmp_path):
    cache, provider = tmp_cache
    bars = make_bars(start=date(2024, 1, 2), n=5)
    provider.get_daily_bars.return_value = bars

    cache.get_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 8))
    assert cache.cache_path("AAPL").exists()
