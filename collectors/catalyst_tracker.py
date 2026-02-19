"""collectors/catalyst_tracker.py
Tracks biotech catalysts: adds, updates, and resolves BiotechEvents.
Acts as an in-session manager that wraps the persistent EventStore.
"""
import uuid
import logging
from datetime import date
from typing import List, Optional

from models.event import BiotechEvent, EventType, EventOutcome, SentimentTag, MarketContext
from collectors.market_data import build_market_context, fetch_post_event_moves

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Catalyst priority weights (used in scoring engine)
# Higher = more binary / high-impact catalyst
# ---------------------------------------------------------------------------
CATALYST_PRIORITY: dict = {
    EventType.FDA_PDUFA:        95,
    EventType.FDA_ADCOM:        85,
    EventType.CLINICAL_READOUT: 80,
    EventType.PARTNERSHIP:      55,
    EventType.EARNINGS:         50,
    EventType.CONFERENCE_PRES:  30,
    EventType.COMPETITOR_EVENT: 40,
    EventType.SEC_FILING:       20,
    EventType.MACRO_RELEASE:    35,
    EventType.OTHER:            25,
}

# Pipeline-stage strength multiplier (0-1)
PIPELINE_STAGE_WEIGHT: dict = {
    "Phase 1":      0.45,
    "Phase 1/2":    0.50,
    "Phase 2":      0.65,
    "Phase 2/3":    0.75,
    "Phase 3":      0.90,
    "NDA filed":    0.92,
    "BLA filed":    0.92,
    "PDUFA date":   0.95,
    "Approved":     1.00,
    "Marketed":     1.00,
    "Preclinical":  0.30,
}


def create_event(
    ticker: str,
    company_name: str,
    event_type: EventType,
    event_date: date,
    description: str,
    sentiment: SentimentTag = SentimentTag.NEUTRAL,
    pipeline_stage: Optional[str] = None,
    indication: Optional[str] = None,
    primary_endpoint: Optional[str] = None,
    competing_drugs: Optional[List[str]] = None,
    analyst_notes: str = "",
    auto_market_context: bool = True,
    tags: Optional[List[str]] = None,
) -> BiotechEvent:
    """
    Factory function to create a new BiotechEvent with a generated ID
    and optional auto-fetched market context.
    """
    event_id = f"{ticker.upper()}_{event_date.isoformat()}_{str(uuid.uuid4())[:8]}"
    market_ctx = None
    if auto_market_context:
        try:
            market_ctx = build_market_context(event_date)
            logger.info("Market context built for %s on %s", ticker, event_date)
        except Exception as exc:
            logger.warning("Could not auto-fetch market context: %s", exc)

    event = BiotechEvent(
        event_id=event_id,
        ticker=ticker.upper(),
        company_name=company_name,
        event_type=event_type,
        event_date=event_date,
        description=description,
        sentiment=sentiment,
        pipeline_stage=pipeline_stage,
        indication=indication,
        primary_endpoint=primary_endpoint,
        competing_drugs=competing_drugs or [],
        analyst_notes=analyst_notes,
        market_context=market_ctx,
        tags=tags or [],
    )
    logger.info("Created event %s [%s] for %s", event_id, event_type.value, ticker)
    return event


def resolve_event(
    event: BiotechEvent,
    outcome: EventOutcome,
    outcome_notes: str = "",
    auto_fetch_moves: bool = True,
) -> BiotechEvent:
    """
    Mark an event as resolved by setting outcome + post-event price moves.
    If auto_fetch_moves=True, fetches actual moves from yfinance.
    """
    event.outcome = outcome
    event.outcome_notes = outcome_notes

    if auto_fetch_moves:
        try:
            t_move, spy_move, xbi_move = fetch_post_event_moves(
                event.ticker, event.event_date
            )
            event.actual_move_pct = t_move
            event.spy_move_pct    = spy_move
            event.xbi_move_pct    = xbi_move
            logger.info(
                "Resolved %s: move=%.2f%%, SPY=%.2f%%, XBI=%.2f%%",
                event.event_id,
                t_move or 0,
                spy_move or 0,
                xbi_move or 0,
            )
        except Exception as exc:
            logger.warning("Could not auto-fetch post-event moves: %s", exc)

    return event


def catalyst_quality_score(event: BiotechEvent) -> float:
    """
    Compute the catalyst quality sub-score (0-100) based on event type,
    pipeline stage, primary endpoint clarity, and sentiment.

    This is the primary input for the scoring engine's
    `catalyst_quality` dimension.
    """
    # Base from event type priority
    base = CATALYST_PRIORITY.get(event.event_type, 25)

    # Pipeline stage multiplier (biotech-specific events only)
    stage_mult = 1.0
    if event.pipeline_stage and event.event_type in (
        EventType.FDA_PDUFA,
        EventType.FDA_ADCOM,
        EventType.CLINICAL_READOUT,
    ):
        stage_mult = PIPELINE_STAGE_WEIGHT.get(event.pipeline_stage, 0.70)

    raw = base * stage_mult

    # Bonus: well-defined primary endpoint
    if event.primary_endpoint and len(event.primary_endpoint) > 10:
        raw = min(raw + 5, 100)

    # Sentiment adjustment
    sentiment_adj = {
        SentimentTag.STRONG_BUY:  +8,
        SentimentTag.BUY:         +4,
        SentimentTag.NEUTRAL:      0,
        SentimentTag.SELL:        -4,
        SentimentTag.STRONG_SELL: -8,
    }
    raw += sentiment_adj.get(event.sentiment, 0)

    return round(min(max(raw, 0), 100), 2)


def competitive_moat_score(event: BiotechEvent) -> float:
    """
    Estimate competitive moat / pipeline differentiation (0-100).
    Fewer competitors = higher score.
    """
    n_competitors = len(event.competing_drugs)
    if n_competitors == 0:
        return 85.0
    elif n_competitors == 1:
        return 70.0
    elif n_competitors <= 3:
        return 55.0
    elif n_competitors <= 6:
        return 35.0
    return 20.0


def filter_upcoming_events(
    events: List[BiotechEvent],
    as_of: Optional[date] = None,
    event_types: Optional[List[EventType]] = None,
) -> List[BiotechEvent]:
    """
    Filter events that are upcoming (pending) as of `as_of` date.
    Optionally filter by event type.
    """
    as_of = as_of or date.today()
    results = [
        e for e in events
        if e.outcome == EventOutcome.PENDING and e.event_date >= as_of
    ]
    if event_types:
        results = [e for e in results if e.event_type in event_types]
    return sorted(results, key=lambda e: e.event_date)
