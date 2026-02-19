"""models/rating.py
Options trade rating derived from scored biotech events.
"""
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional, List


class OptionsStrategy(str, Enum):
    LONG_CALL         = "long_call"
    LONG_PUT          = "long_put"
    LONG_STRADDLE     = "long_straddle"
    LONG_STRANGLE     = "long_strangle"
    BULL_CALL_SPREAD  = "bull_call_spread"
    BEAR_PUT_SPREAD   = "bear_put_spread"
    IRON_CONDOR       = "iron_condor"
    CASH_SECURED_PUT  = "cash_secured_put"
    COVERED_CALL      = "covered_call"
    CALENDAR_SPREAD   = "calendar_spread"
    CUSTOM            = "custom"


class RatingGrade(str, Enum):
    """Letter-grade rating for the options setup."""
    A_PLUS  = "A+"   # 90-100  Highest conviction
    A       = "A"    # 80-89
    B_PLUS  = "B+"   # 70-79
    B       = "B"    # 60-69
    C       = "C"    # 50-59   Average setup
    D       = "D"    # 30-49   Below average
    F       = "F"    # 0-29    Avoid


def score_to_grade(score: float) -> RatingGrade:
    """Map 0-100 composite score to letter grade."""
    if score >= 90:  return RatingGrade.A_PLUS
    if score >= 80:  return RatingGrade.A
    if score >= 70:  return RatingGrade.B_PLUS
    if score >= 60:  return RatingGrade.B
    if score >= 50:  return RatingGrade.C
    if score >= 30:  return RatingGrade.D
    return RatingGrade.F


@dataclass
class ScoreBreakdown:
    """
    Decomposed scoring components (each 0-100).
    Weights are applied by the scoring engine.
    """
    catalyst_quality:      float = 0.0   # event type + pipeline stage strength
    sentiment_alignment:   float = 0.0   # analyst consensus vs market positioning
    market_context:        float = 0.0   # broad market / sector tailwinds
    iv_environment:        float = 0.0   # IV rank / IV percentile favorability
    historical_accuracy:   float = 0.0   # past similar events accuracy for ticker
    competitive_moat:      float = 0.0   # pipeline differentiation vs competitors
    risk_reward:           float = 0.0   # event magnitude vs premium cost estimate

    def weighted_total(self, weights: Optional[dict] = None) -> float:
        """
        Compute composite score using weights dict.
        Default weights sum to 1.0:
          catalyst_quality      0.25
          sentiment_alignment   0.15
          market_context        0.15
          iv_environment        0.15
          historical_accuracy   0.10
          competitive_moat      0.10
          risk_reward           0.10
        """
        default_weights = {
            "catalyst_quality":    0.25,
            "sentiment_alignment": 0.15,
            "market_context":      0.15,
            "iv_environment":      0.15,
            "historical_accuracy": 0.10,
            "competitive_moat":    0.10,
            "risk_reward":         0.10,
        }
        w = weights or default_weights
        total = (
            self.catalyst_quality    * w.get("catalyst_quality", 0) +
            self.sentiment_alignment * w.get("sentiment_alignment", 0) +
            self.market_context      * w.get("market_context", 0) +
            self.iv_environment      * w.get("iv_environment", 0) +
            self.historical_accuracy * w.get("historical_accuracy", 0) +
            self.competitive_moat    * w.get("competitive_moat", 0) +
            self.risk_reward         * w.get("risk_reward", 0)
        )
        return round(min(max(total, 0), 100), 2)

    def to_dict(self) -> dict:
        return {
            "catalyst_quality":    self.catalyst_quality,
            "sentiment_alignment": self.sentiment_alignment,
            "market_context":      self.market_context,
            "iv_environment":      self.iv_environment,
            "historical_accuracy": self.historical_accuracy,
            "competitive_moat":    self.competitive_moat,
            "risk_reward":         self.risk_reward,
        }


@dataclass
class OptionsRating:
    """
    Full options trade rating for a specific BiotechEvent.
    Attach to a BiotechEvent via event_id.
    """
    event_id:          str
    ticker:            str
    rating_date:       date
    recommended_strategy: OptionsStrategy
    score_breakdown:   ScoreBreakdown

    # --- Derived ---
    composite_score:   float        = 0.0
    grade:             RatingGrade  = RatingGrade.F
    confidence_pct:    float        = 0.0   # 0-100, model confidence in rating

    # --- Trade parameters ---
    target_expiry_days: Optional[int]   = None   # DTE at entry
    suggested_delta:    Optional[float] = None   # e.g. 0.40 for directional
    max_risk_pct_port:  Optional[float] = None   # max % of portfolio to risk
    notes:              str             = ""
    analyst_flags:      List[str]       = field(default_factory=list)

    def __post_init__(self):
        self.composite_score = self.score_breakdown.weighted_total()
        self.grade = score_to_grade(self.composite_score)

    def refresh_score(self, weights: Optional[dict] = None):
        """Recompute composite_score and grade (call after editing breakdown)."""
        self.composite_score = self.score_breakdown.weighted_total(weights)
        self.grade = score_to_grade(self.composite_score)

    def to_dict(self) -> dict:
        return {
            "event_id":            self.event_id,
            "ticker":              self.ticker,
            "rating_date":         self.rating_date.isoformat(),
            "recommended_strategy":self.recommended_strategy.value,
            "composite_score":     self.composite_score,
            "grade":               self.grade.value,
            "confidence_pct":      self.confidence_pct,
            "target_expiry_days":  self.target_expiry_days,
            "suggested_delta":     self.suggested_delta,
            "max_risk_pct_port":   self.max_risk_pct_port,
            "score_breakdown":     self.score_breakdown.to_dict(),
            "analyst_flags":       self.analyst_flags,
            "notes":               self.notes,
        }
