"""engine/scorer.py
Core qualitative scoring engine.
Takes a BiotechEvent and produces a full OptionsRating.
"""
import logging
from datetime import date
from typing import Optional, List

from models.event import BiotechEvent, EventType, SentimentTag
from models.rating import (
    OptionsRating, OptionsStrategy, ScoreBreakdown, RatingGrade, score_to_grade
)
from collectors.catalyst_tracker import catalyst_quality_score, competitive_moat_score

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# IV environment heuristics
# ---------------------------------------------------------------------------

def _iv_environment_score(
    event: BiotechEvent,
    iv_rank: Optional[float] = None,
) -> float:
    """
    Score the implied-volatility environment (0-100).

    iv_rank: Implied Volatility Rank (0-100).  Pass None to use heuristic.

    Heuristic (when iv_rank is None):
     - FDA events / clinical readouts tend to have high IV -> IV crush risk
       -> favors straddle/strangle, penalizes naked directional long
     - Earnings: moderate IV
     - Macro: low-medium IV unless FOMC period
    """
    if iv_rank is not None:
        # High IV rank: better for premium sellers, but also juicy for directional
        # Sweet spot: 40-70 IV rank
        if 40 <= iv_rank <= 70:
            return 80.0
        elif 20 <= iv_rank < 40:
            return 65.0
        elif iv_rank > 70:
            return 55.0  # risk of IV crush post-event
        else:
            return 40.0  # IV rank < 20, expensive on relative basis

    # Heuristic fallback
    high_iv_events = {EventType.FDA_PDUFA, EventType.FDA_ADCOM, EventType.CLINICAL_READOUT}
    if event.event_type in high_iv_events:
        return 62.0   # high IV but crush risk -> moderate
    elif event.event_type == EventType.EARNINGS:
        return 68.0
    elif event.event_type == EventType.MACRO_RELEASE:
        return 55.0
    return 60.0


# ---------------------------------------------------------------------------
# Market context scoring
# ---------------------------------------------------------------------------

def _market_context_score(event: BiotechEvent) -> float:
    """
    Score the market/sector environment (0-100) using the
    MarketContext attached to the event.
    """
    ctx = event.market_context
    if ctx is None:
        return 50.0   # unknown -> neutral

    trend_scores = {
        "strong_risk_on":  85,
        "risk_on":         70,
        "neutral":         50,
        "risk_off":        30,
        "strong_risk_off": 15,
    }
    base = trend_scores.get(ctx.sector_trend or "neutral", 50)

    # XBI-specific adjustment for biotech events
    biotech_events = {EventType.FDA_PDUFA, EventType.FDA_ADCOM, EventType.CLINICAL_READOUT}
    if event.event_type in biotech_events and ctx.xbi_5d_return is not None:
        if ctx.xbi_5d_return > 3:
            base = min(base + 10, 100)
        elif ctx.xbi_5d_return < -3:
            base = max(base - 10, 0)

    return float(base)


# ---------------------------------------------------------------------------
# Sentiment alignment scoring
# ---------------------------------------------------------------------------

def _sentiment_alignment_score(event: BiotechEvent) -> float:
    """
    Convert sentiment tag to a directional alignment score (0-100).
    """
    mapping = {
        SentimentTag.STRONG_BUY:  90.0,
        SentimentTag.BUY:         72.0,
        SentimentTag.NEUTRAL:     50.0,
        SentimentTag.SELL:        28.0,
        SentimentTag.STRONG_SELL: 10.0,
    }
    return mapping.get(event.sentiment, 50.0)


# ---------------------------------------------------------------------------
# Historical accuracy scoring
# ---------------------------------------------------------------------------

def _historical_accuracy_score(
    event: BiotechEvent,
    past_events: Optional[List[BiotechEvent]] = None,
) -> float:
    """
    Estimate historical accuracy of similar calls for this ticker.
    Uses resolved past events of the same type for the same ticker.
    Falls back to 50 if no history.
    """
    if not past_events:
        return 50.0

    from models.event import EventOutcome
    same_type = [
        e for e in past_events
        if e.ticker == event.ticker
        and e.event_type == event.event_type
        and e.outcome != EventOutcome.PENDING
    ]
    if not same_type:
        return 50.0

    positives = sum(
        1 for e in same_type
        if e.outcome in (EventOutcome.POSITIVE, EventOutcome.MIXED)
    )
    rate = (positives / len(same_type)) * 100
    return round(rate, 2)


# ---------------------------------------------------------------------------
# Risk-reward scoring
# ---------------------------------------------------------------------------

def _risk_reward_score(event: BiotechEvent) -> float:
    """
    Estimate risk-reward attractiveness (0-100).
    Higher-impact binary events have larger expected moves -> more favorable R/R.
    """
    # Expected move proxy by event type
    expected_move_proxy = {
        EventType.FDA_PDUFA:        85,
        EventType.FDA_ADCOM:        75,
        EventType.CLINICAL_READOUT: 70,
        EventType.PARTNERSHIP:      50,
        EventType.EARNINGS:         45,
        EventType.COMPETITOR_EVENT: 35,
        EventType.MACRO_RELEASE:    30,
        EventType.CONFERENCE_PRES:  25,
        EventType.SEC_FILING:       15,
        EventType.OTHER:            20,
    }
    return float(expected_move_proxy.get(event.event_type, 30))


# ---------------------------------------------------------------------------
# Strategy recommender
# ---------------------------------------------------------------------------

def recommend_strategy(
    event: BiotechEvent,
    sentiment_score: float,
) -> OptionsStrategy:
    """
    Recommend an options strategy based on event type and sentiment.

    Rules:
    - Binary FDA/clinical with strong directional bias -> bull/bear spread
    - Binary FDA/clinical with neutral -> straddle/strangle
    - Earnings with bullish -> bull call spread (defined risk)
    - Earnings neutral -> iron condor (premium capture)
    - Macro events -> calendar spread or iron condor
    """
    binary_events = {EventType.FDA_PDUFA, EventType.FDA_ADCOM, EventType.CLINICAL_READOUT}

    if event.event_type in binary_events:
        if sentiment_score >= 70:
            return OptionsStrategy.BULL_CALL_SPREAD
        elif sentiment_score <= 30:
            return OptionsStrategy.BEAR_PUT_SPREAD
        else:
            return OptionsStrategy.LONG_STRADDLE

    elif event.event_type == EventType.EARNINGS:
        if sentiment_score >= 70:
            return OptionsStrategy.BULL_CALL_SPREAD
        elif sentiment_score <= 30:
            return OptionsStrategy.BEAR_PUT_SPREAD
        else:
            return OptionsStrategy.IRON_CONDOR

    elif event.event_type == EventType.MACRO_RELEASE:
        return OptionsStrategy.CALENDAR_SPREAD

    elif event.event_type == EventType.PARTNERSHIP:
        if sentiment_score >= 65:
            return OptionsStrategy.LONG_CALL
        return OptionsStrategy.BULL_CALL_SPREAD

    return OptionsStrategy.LONG_STRADDLE


# ---------------------------------------------------------------------------
# Main scoring entry point
# ---------------------------------------------------------------------------

def score_event(
    event: BiotechEvent,
    iv_rank: Optional[float] = None,
    past_events: Optional[List[BiotechEvent]] = None,
    custom_weights: Optional[dict] = None,
    confidence_override: Optional[float] = None,
) -> OptionsRating:
    """
    Primary entry point: takes a BiotechEvent and returns a fully
    populated OptionsRating.

    Parameters
    ----------
    event            : The event to score.
    iv_rank          : Current IV Rank (0-100) if known; None for heuristic.
    past_events      : Historical events for this ticker (for accuracy scoring).
    custom_weights   : Override the default ScoreBreakdown weights.
    confidence_override: Manually set confidence (0-100); otherwise auto-computed.
    """
    if event.event_id is None:
        raise ValueError("event.event_id must be set before scoring.")

    # --- Sub-scores ---
    cq  = catalyst_quality_score(event)
    sa  = _sentiment_alignment_score(event)
    mc  = _market_context_score(event)
    iv  = _iv_environment_score(event, iv_rank)
    ha  = _historical_accuracy_score(event, past_events)
    cm  = competitive_moat_score(event)
    rr  = _risk_reward_score(event)

    breakdown = ScoreBreakdown(
        catalyst_quality    = cq,
        sentiment_alignment = sa,
        market_context      = mc,
        iv_environment      = iv,
        historical_accuracy = ha,
        competitive_moat    = cm,
        risk_reward         = rr,
    )

    composite = breakdown.weighted_total(custom_weights)
    grade     = score_to_grade(composite)
    strategy  = recommend_strategy(event, sa)

    # Confidence: average of catalyst_quality and historical_accuracy
    confidence = confidence_override if confidence_override is not None else \
                 round((cq + ha) / 2, 2)

    # Suggested DTE heuristic: binary/FDA = 30-45 DTE, earnings = 14-21 DTE
    binary_events = {EventType.FDA_PDUFA, EventType.FDA_ADCOM, EventType.CLINICAL_READOUT}
    dte = 35 if event.event_type in binary_events else 21

    # Delta heuristic
    if strategy in (OptionsStrategy.LONG_STRADDLE, OptionsStrategy.LONG_STRANGLE,
                    OptionsStrategy.IRON_CONDOR):
        delta = 0.35
    elif strategy in (OptionsStrategy.BULL_CALL_SPREAD, OptionsStrategy.LONG_CALL):
        delta = 0.45
    elif strategy in (OptionsStrategy.BEAR_PUT_SPREAD, OptionsStrategy.LONG_PUT):
        delta = -0.45
    else:
        delta = 0.40

    # Max risk heuristic: cap at 3% of portfolio for A-grade, scale down
    grade_risk = {
        RatingGrade.A_PLUS: 3.0,
        RatingGrade.A:      2.5,
        RatingGrade.B_PLUS: 2.0,
        RatingGrade.B:      1.5,
        RatingGrade.C:      1.0,
        RatingGrade.D:      0.5,
        RatingGrade.F:      0.0,
    }
    max_risk = grade_risk.get(grade, 1.0)

    rating = OptionsRating(
        event_id              = event.event_id,
        ticker                = event.ticker,
        rating_date           = date.today(),
        recommended_strategy  = strategy,
        score_breakdown       = breakdown,
        confidence_pct        = confidence,
        target_expiry_days    = dte,
        suggested_delta       = abs(delta),
        max_risk_pct_port     = max_risk,
        notes                 = (
            f"Auto-scored: {event.event_type.value} | "
            f"{event.pipeline_stage or 'N/A'} | "
            f"sentiment={event.sentiment.value}"
        ),
    )

    logger.info(
        "Scored %s -> %s (%.1f) | Strategy: %s | MaxRisk: %.1f%%",
        event.event_id, grade.value, composite, strategy.value, max_risk
    )
    return rating
