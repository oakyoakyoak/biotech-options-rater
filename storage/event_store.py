"""storage/event_store.py
JSON-backed persistence layer for BiotechEvents and OptionsRatings.
Data is stored in data/events.json and data/ratings.json.
"""
import json
import os
import logging
from datetime import date
from pathlib import Path
from typing import List, Optional, Dict

from models.event import (
    BiotechEvent, EventType, EventOutcome, SentimentTag, MarketContext
)
from models.rating import (
    OptionsRating, OptionsStrategy, ScoreBreakdown, RatingGrade
)

logger = logging.getLogger(__name__)

DATA_DIR     = Path(os.environ.get("BIOTECH_DATA_DIR", "data"))
EVENTS_FILE  = DATA_DIR / "events.json"
RATINGS_FILE = DATA_DIR / "ratings.json"


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _event_to_dict(event: BiotechEvent) -> dict:
    d = event.to_dict()
    # MarketContext needs special handling
    if event.market_context is not None:
        mc = event.market_context
        d["market_context"] = {
            "spy_5d_return": mc.spy_5d_return,
            "xbi_5d_return": mc.xbi_5d_return,
            "vix_level":     mc.vix_level,
            "sector_trend":  mc.sector_trend,
            "notes":         mc.notes,
        }
    else:
        d["market_context"] = None
    return d


def _dict_to_event(d: dict) -> BiotechEvent:
    mc_data = d.get("market_context")
    market_ctx = None
    if mc_data:
        market_ctx = MarketContext(
            spy_5d_return = mc_data.get("spy_5d_return"),
            xbi_5d_return = mc_data.get("xbi_5d_return"),
            vix_level     = mc_data.get("vix_level"),
            sector_trend  = mc_data.get("sector_trend"),
            notes         = mc_data.get("notes"),
        )

    return BiotechEvent(
        event_id         = d.get("event_id"),
        ticker           = d["ticker"],
        company_name     = d["company_name"],
        event_type       = EventType(d["event_type"]),
        event_date       = date.fromisoformat(d["event_date"]),
        description      = d["description"],
        sentiment        = SentimentTag(d.get("sentiment", "neutral")),
        analyst_notes    = d.get("analyst_notes", ""),
        pipeline_stage   = d.get("pipeline_stage"),
        indication       = d.get("indication"),
        primary_endpoint = d.get("primary_endpoint"),
        competing_drugs  = d.get("competing_drugs", []),
        market_context   = market_ctx,
        outcome          = EventOutcome(d.get("outcome", "pending")),
        actual_move_pct  = d.get("actual_move_pct"),
        spy_move_pct     = d.get("spy_move_pct"),
        xbi_move_pct     = d.get("xbi_move_pct"),
        iv_crush_pct     = d.get("iv_crush_pct"),
        outcome_notes    = d.get("outcome_notes", ""),
        tags             = d.get("tags", []),
    )


def _rating_to_dict(rating: OptionsRating) -> dict:
    return rating.to_dict()


def _dict_to_rating(d: dict) -> OptionsRating:
    bd = d["score_breakdown"]
    breakdown = ScoreBreakdown(
        catalyst_quality    = bd["catalyst_quality"],
        sentiment_alignment = bd["sentiment_alignment"],
        market_context      = bd["market_context"],
        iv_environment      = bd["iv_environment"],
        historical_accuracy = bd["historical_accuracy"],
        competitive_moat    = bd["competitive_moat"],
        risk_reward         = bd["risk_reward"],
    )
    return OptionsRating(
        event_id              = d["event_id"],
        ticker                = d["ticker"],
        rating_date           = date.fromisoformat(d["rating_date"]),
        recommended_strategy  = OptionsStrategy(d["recommended_strategy"]),
        score_breakdown       = breakdown,
        confidence_pct        = d.get("confidence_pct", 0.0),
        target_expiry_days    = d.get("target_expiry_days"),
        suggested_delta       = d.get("suggested_delta"),
        max_risk_pct_port     = d.get("max_risk_pct_port"),
        notes                 = d.get("notes", ""),
        analyst_flags         = d.get("analyst_flags", []),
    )


# ---------------------------------------------------------------------------
# EventStore class
# ---------------------------------------------------------------------------

class EventStore:
    """
    Persistent store for BiotechEvents and OptionsRatings backed by JSON files.

    Usage:
        store = EventStore()
        store.save_event(event)
        events = store.load_events()
        store.save_rating(rating)
        ratings = store.load_ratings()
    """

    def __init__(
        self,
        events_path: Optional[Path] = None,
        ratings_path: Optional[Path] = None,
    ):
        self.events_path  = events_path  or EVENTS_FILE
        self.ratings_path = ratings_path or RATINGS_FILE
        _ensure_data_dir()

    # --- Events ---

    def load_events(self) -> List[BiotechEvent]:
        """Load all events from JSON file."""
        if not self.events_path.exists():
            return []
        try:
            with open(self.events_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            events = [_dict_to_event(d) for d in raw]
            logger.info("Loaded %d events from %s", len(events), self.events_path)
            return events
        except Exception as exc:
            logger.error("Failed to load events: %s", exc)
            return []

    def save_events(self, events: List[BiotechEvent]) -> None:
        """Overwrite the events file with the given list."""
        _ensure_data_dir()
        try:
            with open(self.events_path, "w", encoding="utf-8") as f:
                json.dump([_event_to_dict(e) for e in events], f, indent=2)
            logger.info("Saved %d events to %s", len(events), self.events_path)
        except Exception as exc:
            logger.error("Failed to save events: %s", exc)
            raise

    def save_event(self, event: BiotechEvent) -> None:
        """
        Upsert a single event (insert or update by event_id).
        """
        events = self.load_events()
        idx = next(
            (i for i, e in enumerate(events) if e.event_id == event.event_id),
            None
        )
        if idx is not None:
            events[idx] = event
            logger.info("Updated event %s", event.event_id)
        else:
            events.append(event)
            logger.info("Inserted event %s", event.event_id)
        self.save_events(events)

    def get_event(self, event_id: str) -> Optional[BiotechEvent]:
        """Retrieve a single event by ID."""
        return next(
            (e for e in self.load_events() if e.event_id == event_id), None
        )

    def delete_event(self, event_id: str) -> bool:
        """Delete an event by ID. Returns True if deleted."""
        events = self.load_events()
        new_events = [e for e in events if e.event_id != event_id]
        if len(new_events) == len(events):
            return False
        self.save_events(new_events)
        return True

    # --- Ratings ---

    def load_ratings(self) -> List[OptionsRating]:
        """Load all ratings from JSON file."""
        if not self.ratings_path.exists():
            return []
        try:
            with open(self.ratings_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            ratings = [_dict_to_rating(d) for d in raw]
            logger.info("Loaded %d ratings from %s", len(ratings), self.ratings_path)
            return ratings
        except Exception as exc:
            logger.error("Failed to load ratings: %s", exc)
            return []

    def save_ratings(self, ratings: List[OptionsRating]) -> None:
        """Overwrite the ratings file."""
        _ensure_data_dir()
        try:
            with open(self.ratings_path, "w", encoding="utf-8") as f:
                json.dump([_rating_to_dict(r) for r in ratings], f, indent=2)
            logger.info("Saved %d ratings to %s", len(ratings), self.ratings_path)
        except Exception as exc:
            logger.error("Failed to save ratings: %s", exc)
            raise

    def save_rating(self, rating: OptionsRating) -> None:
        """Upsert a single rating (by event_id)."""
        ratings = self.load_ratings()
        idx = next(
            (i for i, r in enumerate(ratings) if r.event_id == rating.event_id),
            None
        )
        if idx is not None:
            ratings[idx] = rating
        else:
            ratings.append(rating)
        self.save_ratings(ratings)

    def ratings_by_event(self) -> Dict[str, OptionsRating]:
        """Return a dict mapping event_id -> OptionsRating."""
        return {r.event_id: r for r in self.load_ratings()}

    def export_json(
        self,
        output_path: Path,
        include_ratings: bool = True,
    ) -> None:
        """
        Export a combined JSON with all events + ratings for external use
        (e.g., feeding a dashboard or LLM analysis).
        """
        events  = self.load_events()
        ratings = self.ratings_by_event() if include_ratings else {}
        export  = []
        for event in events:
            rec = _event_to_dict(event)
            rating = ratings.get(event.event_id or "")
            rec["rating"] = _rating_to_dict(rating) if rating else None
            export.append(rec)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(export, f, indent=2)
        logger.info("Exported %d records to %s", len(export), output_path)
