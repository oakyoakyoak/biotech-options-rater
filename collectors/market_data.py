"""collectors/market_data.py
Fetches market benchmarks (SPY, XBI, VIX) and macro release data
using yfinance and a lightweight FRED-style approach.
"""
import logging
from datetime import date, timedelta
from typing import Optional, Dict, Tuple

try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False

from models.event import MarketContext

logger = logging.getLogger(__name__)

# Qualitative macro release calendar (static baseline; update as needed)
MACRO_EVENTS: Dict[str, str] = {
    "FOMC":   "Federal Open Market Committee rate decision",
    "CPI":    "Consumer Price Index inflation print",
    "NFP":    "Non-Farm Payrolls jobs report",
    "PPI":    "Producer Price Index",
    "GDP":    "Gross Domestic Product estimate",
    "PCE":    "Personal Consumption Expenditures price index",
    "JOLTS":  "Job Openings and Labor Turnover Survey",
    "PMI":    "Purchasing Managers Index (ISM)",
    "RETAIL": "Retail Sales report",
}

# Sector ETF tickers used for benchmark context
BENCHMARK_TICKERS = {
    "market":  "SPY",
    "biotech": "XBI",
    "health":  "XLV",
    "volatility": "^VIX",
}


def _assert_yfinance():
    if not YF_AVAILABLE:
        raise ImportError(
            "yfinance is required for live data. Install it: pip install yfinance"
        )


def fetch_price_return(
    ticker: str,
    end_date: date,
    lookback_days: int = 5,
) -> Optional[float]:
    """
    Fetch the cumulative percentage return for `ticker` over the
    `lookback_days` trading days ending on `end_date`.

    Returns None if data is unavailable.
    """
    _assert_yfinance()
    start = end_date - timedelta(days=lookback_days * 2)  # buffer for holidays
    try:
        df = yf.download(
            ticker,
            start=start.isoformat(),
            end=(end_date + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            progress=False,
        )
        if df.empty or len(df) < 2:
            logger.warning("No price data for %s on %s", ticker, end_date)
            return None
        close = df["Close"].dropna()
        recent = close.iloc[-lookback_days:] if len(close) >= lookback_days else close
        ret = (recent.iloc[-1] / recent.iloc[0] - 1) * 100
        return round(float(ret), 4)
    except Exception as exc:
        logger.error("Error fetching %s: %s", ticker, exc)
        return None


def fetch_vix_level(event_date: date) -> Optional[float]:
    """Return the closing VIX level on or nearest to event_date."""
    _assert_yfinance()
    try:
        df = yf.download(
            "^VIX",
            start=(event_date - timedelta(days=5)).isoformat(),
            end=(event_date + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            progress=False,
        )
        if df.empty:
            return None
        return round(float(df["Close"].dropna().iloc[-1]), 2)
    except Exception as exc:
        logger.error("VIX fetch error: %s", exc)
        return None


def classify_sector_trend(
    spy_return: Optional[float],
    xbi_return: Optional[float],
    vix: Optional[float],
) -> str:
    """
    Qualitative sector-trend label based on SPY, XBI, and VIX.

    Returns one of: 'strong_risk_on', 'risk_on', 'neutral',
                    'risk_off', 'strong_risk_off'.
    """
    if spy_return is None:
        return "neutral"
    bullish_score = 0
    if spy_return > 1.5:  bullish_score += 2
    elif spy_return > 0:  bullish_score += 1
    elif spy_return < -1.5: bullish_score -= 2
    elif spy_return < 0:    bullish_score -= 1

    if xbi_return is not None:
        if xbi_return > 2:   bullish_score += 1
        elif xbi_return < -2: bullish_score -= 1

    if vix is not None:
        if vix < 15:  bullish_score += 1
        elif vix > 25: bullish_score -= 1
        elif vix > 35: bullish_score -= 2

    if bullish_score >= 3:   return "strong_risk_on"
    if bullish_score >= 1:   return "risk_on"
    if bullish_score <= -3:  return "strong_risk_off"
    if bullish_score <= -1:  return "risk_off"
    return "neutral"


def build_market_context(
    event_date: date,
    lookback_days: int = 5,
) -> MarketContext:
    """
    Build a MarketContext for a given event_date by fetching live
    SPY, XBI, and VIX data.
    """
    spy_ret  = fetch_price_return("SPY",  event_date, lookback_days)
    xbi_ret  = fetch_price_return("XBI",  event_date, lookback_days)
    vix_lvl  = fetch_vix_level(event_date)
    trend    = classify_sector_trend(spy_ret, xbi_ret, vix_lvl)

    return MarketContext(
        spy_5d_return=spy_ret,
        xbi_5d_return=xbi_ret,
        vix_level=vix_lvl,
        sector_trend=trend,
        notes=(
            f"Auto-generated context for {event_date}: "
            f"SPY {spy_ret}%, XBI {xbi_ret}%, VIX {vix_lvl}"
        ),
    )


def fetch_post_event_moves(
    ticker: str,
    event_date: date,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Fetch single-day % moves for ticker, SPY, and XBI on event_date.
    Returns (ticker_move, spy_move, xbi_move).
    """
    def _day_return(t: str) -> Optional[float]:
        return fetch_price_return(t, event_date, lookback_days=1)

    return (
        _day_return(ticker),
        _day_return("SPY"),
        _day_return("XBI"),
    )


def get_macro_calendar() -> Dict[str, str]:
    """Return the static macro release calendar dict."""
    return dict(MACRO_EVENTS)


def describe_macro_event(code: str) -> str:
    """Human-readable description for a macro release code."""
    return MACRO_EVENTS.get(code.upper(), f"Unknown macro release: {code}")
