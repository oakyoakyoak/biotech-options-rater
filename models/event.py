"""models/event.py
Data models for biotech catalyst events and market releases.
"""
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional, List


class EventType(str, Enum):
    FDA_PDUFA          = "fda_pdufa"          # FDA target action date
    FDA_ADCOM          = "fda_adcom"          # Advisory committee meeting
    CLINICAL_READOUT   = "clinical_readout"   # Phase 2/3 trial data
    EARNINGS           = "earnings"           # Quarterly earnings
    CONFERENCE_PRES    = "conference_pres"    # Medical / investor conference
    PARTNERSHIP        = "partnership"        # Business development deal
    SEC_FILING         = "sec_filing"         # 10-Q, 10-K, 8-K, etc.
    MACRO_RELEASE      = "macro_release"      # CPI, FOMC, NFP, etc.
    COMPETITOR_EVENT   = "competitor_event"   # Rival company catalyst
    OTHER              = "other"


class EventOutcome(str, Enum):
    PENDING   = "pending"
    POSITIVE  = "positive"
    NEGATIVE  = "negative"
    MIXED     = "mixed"
    WITHDRAWN = "withdrawn"


class SentimentTag(str, Enum):
    """Analyst / community sentiment captured qualitatively."""
    STRONG_BUY  = "strong_buy"
    BUY         = "buy"
    NEUTRAL     = "neutral"
    SELL        = "sell"
    STRONG_SELL = "strong_sell"


@dataclass
class MarketContext:
    """Snapshot of broad market conditions around the event date."""
    spy_5d_return: Optional[float] = None   # SPY 5-day return before event
    xbi_5d_return: Optional[float] = None   # XBI biotech ETF 5-day return
    vix_level:     Optional[float] = None   # VIX at event date
    sector_trend:  Optional[str]   = None   # "risk-on", "risk-off", "neutral"
    notes:         Optional[str]   = None


@dataclass
class BiotechEvent:
    """
    Core record for any catalyst or market release being tracked.
    One event per row; ratings are derived in the scoring engine.
    """
    ticker:          str
    company_name:    str
    event_type:      EventType
    event_date:      date
    description:     str

    # --- Qualitative inputs ---
    sentiment:       SentimentTag          = SentimentTag.NEUTRAL
    analyst_notes:   str                   = ""
    pipeline_stage:  Optional[str]         = None  # e.g. "Phase 3", "NDA filed"
    indication:      Optional[str]         = None  # disease / therapeutic area
    primary_endpoint:Optional[str]         = None  # e.g. "OS improvement >= 3mo"
    competing_drugs: List[str]             = field(default_factory=list)
    market_context:  Optional[MarketContext] = None

    # --- Post-event fill-in ---
    outcome:         EventOutcome          = EventOutcome.PENDING
    actual_move_pct: Optional[float]       = None  # stock % move on event day
    spy_move_pct:    Optional[float]       = None  # SPY % move same day
    xbi_move_pct:    Optional[float]       = None  # XBI % move same day
    iv_crush_pct:    Optional[float]       = None  # IV drop post-event (%)
    outcome_notes:   str                   = ""

    # --- Internal bookkeeping ---
    event_id:        Optional[str]         = None  # auto-assigned by tracker
    tags:            List[str]             = field(default_factory=list)

    def relative_move(self) -> Optional[float]:
        """Stock move minus SPY move (alpha vs market)."""
        if self.actual_move_pct is not None and self.spy_move_pct is not None:
            return round(self.actual_move_pct - self.spy_move_pct, 4)
        return None

    def xbi_relative_move(self) -> Optional[float]:
        """Stock move minus XBI move (alpha vs biotech sector)."""
        if self.actual_move_pct is not None and self.xbi_move_pct is not None:
            return round(self.actual_move_pct - self.xbi_move_pct, 4)
        return None

    def to_dict(self) -> dict:
        return {
            "event_id":         self.event_id,
            "ticker":           self.ticker,
            "company_name":     self.company_name,
            "event_type":       self.event_type.value,
            "event_date":       self.event_date.isoformat(),
            "description":      self.description,
            "sentiment":        self.sentiment.value,
            "analyst_notes":    self.analyst_notes,
            "pipeline_stage":   self.pipeline_stage,
            "indication":       self.indication,
            "primary_endpoint": self.primary_endpoint,
            "competing_drugs":  self.competing_drugs,
            "outcome":          self.outcome.value,
            "actual_move_pct":  self.actual_move_pct,
            "spy_move_pct":     self.spy_move_pct,
            "xbi_move_pct":     self.xbi_move_pct,
            "iv_crush_pct":     self.iv_crush_pct,
            "relative_move":    self.relative_move(),
            "xbi_relative_move":self.xbi_relative_move(),
            "outcome_notes":    self.outcome_notes,
            "tags":             self.tags,
        }
