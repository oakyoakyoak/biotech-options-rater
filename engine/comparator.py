"""engine/comparator.py
Compares biotech stock performance against market benchmarks (SPY, XBI)
and generates qualitative return reports for options post-mortems.
"""
import logging
from dataclasses import dataclass
from typing import List, Optional, Dict

from models.event import BiotechEvent, EventOutcome
from models.rating import OptionsRating

logger = logging.getLogger(__name__)


@dataclass
class ReturnComparison:
    """
    Post-event return comparison for a single BiotechEvent.
    """
    event_id:          str
    ticker:            str
    event_type:        str
    outcome:           str
    actual_move_pct:   Optional[float]
    spy_move_pct:      Optional[float]
    xbi_move_pct:      Optional[float]
    relative_to_spy:   Optional[float]   # actual - SPY
    relative_to_xbi:   Optional[float]   # actual - XBI
    iv_crush_pct:      Optional[float]
    rating_grade:      Optional[str]     # grade from OptionsRating, if linked
    rating_score:      Optional[float]

    def to_dict(self) -> dict:
        return {
            "event_id":        self.event_id,
            "ticker":          self.ticker,
            "event_type":      self.event_type,
            "outcome":         self.outcome,
            "actual_move_pct": self.actual_move_pct,
            "spy_move_pct":    self.spy_move_pct,
            "xbi_move_pct":    self.xbi_move_pct,
            "relative_to_spy": self.relative_to_spy,
            "relative_to_xbi": self.relative_to_xbi,
            "iv_crush_pct":    self.iv_crush_pct,
            "rating_grade":    self.rating_grade,
            "rating_score":    self.rating_score,
        }

    def outperformed_market(self) -> Optional[bool]:
        """True if stock outperformed SPY on event day."""
        if self.relative_to_spy is None:
            return None
        return self.relative_to_spy > 0

    def outperformed_sector(self) -> Optional[bool]:
        """True if stock outperformed XBI on event day."""
        if self.relative_to_xbi is None:
            return None
        return self.relative_to_xbi > 0


def build_comparison(
    event: BiotechEvent,
    rating: Optional[OptionsRating] = None,
) -> ReturnComparison:
    """
    Build a ReturnComparison from a resolved BiotechEvent and optional rating.
    """
    rel_spy = event.relative_move()
    rel_xbi = event.xbi_relative_move()

    return ReturnComparison(
        event_id        = event.event_id or "",
        ticker          = event.ticker,
        event_type      = event.event_type.value,
        outcome         = event.outcome.value,
        actual_move_pct = event.actual_move_pct,
        spy_move_pct    = event.spy_move_pct,
        xbi_move_pct    = event.xbi_move_pct,
        relative_to_spy = rel_spy,
        relative_to_xbi = rel_xbi,
        iv_crush_pct    = event.iv_crush_pct,
        rating_grade    = rating.grade.value if rating else None,
        rating_score    = rating.composite_score if rating else None,
    )


def batch_compare(
    events: List[BiotechEvent],
    ratings: Optional[Dict[str, OptionsRating]] = None,
) -> List[ReturnComparison]:
    """
    Build comparisons for all resolved events.
    `ratings` is a dict mapping event_id -> OptionsRating.
    """
    ratings = ratings or {}
    resolved = [
        e for e in events
        if e.outcome != EventOutcome.PENDING and e.actual_move_pct is not None
    ]
    comparisons = [
        build_comparison(e, ratings.get(e.event_id or ""))
        for e in resolved
    ]
    logger.info("Built %d return comparisons from %d events.", len(comparisons), len(events))
    return comparisons


# ---------------------------------------------------------------------------
# Aggregate statistics
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkStats:
    """
    Aggregate stats for a set of ReturnComparisons.
    """
    n_events:              int
    avg_actual_move:       Optional[float]
    avg_spy_move:          Optional[float]
    avg_xbi_move:          Optional[float]
    avg_alpha_vs_spy:      Optional[float]
    avg_alpha_vs_xbi:      Optional[float]
    pct_outperform_spy:    Optional[float]
    pct_outperform_xbi:    Optional[float]
    avg_iv_crush:          Optional[float]
    positive_outcome_rate: Optional[float]

    def to_dict(self) -> dict:
        return {
            "n_events":              self.n_events,
            "avg_actual_move":       self.avg_actual_move,
            "avg_spy_move":          self.avg_spy_move,
            "avg_xbi_move":          self.avg_xbi_move,
            "avg_alpha_vs_spy":      self.avg_alpha_vs_spy,
            "avg_alpha_vs_xbi":      self.avg_alpha_vs_xbi,
            "pct_outperform_spy":    self.pct_outperform_spy,
            "pct_outperform_xbi":    self.pct_outperform_xbi,
            "avg_iv_crush":          self.avg_iv_crush,
            "positive_outcome_rate": self.positive_outcome_rate,
        }


def _safe_avg(values: list) -> Optional[float]:
    filtered = [v for v in values if v is not None]
    if not filtered:
        return None
    return round(sum(filtered) / len(filtered), 4)


def compute_stats(
    comparisons: List[ReturnComparison],
    events_for_outcome: Optional[List[BiotechEvent]] = None,
) -> BenchmarkStats:
    """
    Compute aggregate benchmark stats across a list of ReturnComparisons.
    """
    n = len(comparisons)
    if n == 0:
        return BenchmarkStats(
            n_events=0,
            avg_actual_move=None, avg_spy_move=None, avg_xbi_move=None,
            avg_alpha_vs_spy=None, avg_alpha_vs_xbi=None,
            pct_outperform_spy=None, pct_outperform_xbi=None,
            avg_iv_crush=None, positive_outcome_rate=None,
        )

    outperform_spy = [c for c in comparisons if c.outperformed_market() is True]
    outperform_xbi = [c for c in comparisons if c.outperformed_sector() is True]

    positive_rate = None
    if events_for_outcome:
        positives = [
            e for e in events_for_outcome
            if e.outcome in (EventOutcome.POSITIVE, EventOutcome.MIXED)
        ]
        if events_for_outcome:
            positive_rate = round(len(positives) / len(events_for_outcome) * 100, 2)

    return BenchmarkStats(
        n_events              = n,
        avg_actual_move       = _safe_avg([c.actual_move_pct for c in comparisons]),
        avg_spy_move          = _safe_avg([c.spy_move_pct for c in comparisons]),
        avg_xbi_move          = _safe_avg([c.xbi_move_pct for c in comparisons]),
        avg_alpha_vs_spy      = _safe_avg([c.relative_to_spy for c in comparisons]),
        avg_alpha_vs_xbi      = _safe_avg([c.relative_to_xbi for c in comparisons]),
        pct_outperform_spy    = round(len(outperform_spy) / n * 100, 2) if n else None,
        pct_outperform_xbi    = round(len(outperform_xbi) / n * 100, 2) if n else None,
        avg_iv_crush          = _safe_avg([c.iv_crush_pct for c in comparisons]),
        positive_outcome_rate = positive_rate,
    )


def print_comparison_table(comparisons: List[ReturnComparison]) -> None:
    """
    Print a formatted ASCII table of return comparisons.
    """
    header = (
        f"{'Ticker':<8} {'Event Type':<20} {'Outcome':<12} "
        f"{'Move%':>7} {'SPY%':>7} {'XBI%':>7} "
        f"{'Alpha/SPY':>10} {'Alpha/XBI':>10} "
        f"{'Grade':<6} {'Score':>6}"
    )
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)
    for c in comparisons:
        row = (
            f"{c.ticker:<8} {c.event_type:<20} {c.outcome:<12} "
            f"{c.actual_move_pct or 'N/A':>7} "
            f"{c.spy_move_pct or 'N/A':>7} "
            f"{c.xbi_move_pct or 'N/A':>7} "
            f"{c.relative_to_spy or 'N/A':>10} "
            f"{c.relative_to_xbi or 'N/A':>10} "
            f"{c.rating_grade or 'N/A':<6} "
            f"{c.rating_score or 'N/A':>6}"
        )
        print(row)
    print(sep)
