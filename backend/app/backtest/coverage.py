"""Coverage report for short-side backtests.

When backtesting the SHORT profile, each underlying may or may not have an
inverse ETF with sufficient history. This module defines the structured output
that reports exactly what was and wasn't tested, and why.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TestedEntry:
    underlying: str
    inverse_etf: str
    window_tested_start: str        # ISO date — first bar where both series exist
    window_tested_end: str          # ISO date — last bar where both series exist
    n_trades: int
    skipped_signals_before_etf_launch: int  # signals before ETF had data → not traded


@dataclass
class SkippedInsufficientHistory:
    underlying: str
    inverse_etf: str
    reason: str   # e.g. "only 12 overlapping bars (need ≥ 50)"


@dataclass
class SkippedDataError:
    symbol: str
    error: str


@dataclass
class CoverageReport:
    """Structured result for which underlyings could be tested on the short side."""

    tested: list[TestedEntry] = field(default_factory=list)
    skipped_no_instrument: list[str] = field(default_factory=list)
    skipped_insufficient_history: list[SkippedInsufficientHistory] = field(default_factory=list)
    skipped_data_error: list[SkippedDataError] = field(default_factory=list)

    @property
    def summary(self) -> dict:
        n_testable = len(self.tested)
        universe_size = (
            n_testable
            + len(self.skipped_no_instrument)
            + len(self.skipped_insufficient_history)
            + len(self.skipped_data_error)
        )
        if self.tested:
            window_lengths = []
            for t in self.tested:
                from datetime import date
                try:
                    s = date.fromisoformat(t.window_tested_start)
                    e = date.fromisoformat(t.window_tested_end)
                    window_lengths.append((e - s).days)
                except Exception:
                    pass
            avg_days = round(sum(window_lengths) / len(window_lengths)) if window_lengths else 0
        else:
            avg_days = 0

        pct = round(n_testable / universe_size * 100, 1) if universe_size > 0 else 0.0
        return {
            "universe_size": universe_size,
            "n_testable": n_testable,
            "pct_testable": pct,
            "avg_tested_window_days": avg_days,
        }

    def print_human_readable(self) -> None:
        s = self.summary
        print(
            f"\n=== SHORT-SIDE COVERAGE REPORT ===\n"
            f"Asked to test {s['universe_size']} name(s); "
            f"{s['n_testable']} testable "
            f"({s['pct_testable']}%); "
            f"avg usable window {s['avg_tested_window_days'] / 365:.1f} yrs "
            f"({s['avg_tested_window_days']} days)."
        )
        if self.skipped_no_instrument:
            print(
                f"\nNo inverse-ETF mapping for "
                f"{len(self.skipped_no_instrument)} name(s): "
                + ", ".join(self.skipped_no_instrument[:10])
                + (" …" if len(self.skipped_no_instrument) > 10 else "")
            )
        if self.skipped_insufficient_history:
            print(f"\nInsufficient overlap ({len(self.skipped_insufficient_history)}):")
            for e in self.skipped_insufficient_history:
                print(f"  {e.underlying} → {e.inverse_etf}: {e.reason}")
        if self.skipped_data_error:
            print(f"\nData errors ({len(self.skipped_data_error)}):")
            for e in self.skipped_data_error:
                print(f"  {e.symbol}: {e.error}")
        if self.tested:
            print(f"\nTested ({len(self.tested)}):")
            for t in self.tested:
                skipped_note = (
                    f", {t.skipped_signals_before_etf_launch} signals skipped before ETF launch"
                    if t.skipped_signals_before_etf_launch > 0
                    else ""
                )
                print(
                    f"  {t.underlying} → {t.inverse_etf}: "
                    f"{t.window_tested_start} – {t.window_tested_end} "
                    f"({t.n_trades} trades{skipped_note})"
                )
        print()

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return {
            "tested": [asdict(t) for t in self.tested],
            "skipped_no_instrument": self.skipped_no_instrument,
            "skipped_insufficient_history": [asdict(e) for e in self.skipped_insufficient_history],
            "skipped_data_error": [asdict(e) for e in self.skipped_data_error],
            "summary": self.summary,
        }
