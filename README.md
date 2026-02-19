# biotech-options-rater

A Python toolkit for **qualitatively tracking biotech stock catalysts** — FDA dates, clinical readouts, earnings, and macro releases — benchmarking returns against SPY and XBI, and generating **letter-grade options trade ratings** for each event.

---

## Overview

Biotech options pricing is driven by binary catalysts (PDUFA dates, Phase 3 readouts, ADCOM meetings) that produce large, asymmetric moves. This system helps you:

1. **Log and track** every catalyst with rich qualitative metadata (pipeline stage, primary endpoint, competing drugs, analyst sentiment)
2. **Auto-fetch market context** — SPY / XBI / VIX snapshots before and after the event
3. **Score each setup** across 7 dimensions into a composite 0–100 rating with a letter grade (A+ through F)
4. **Recommend an options strategy** (straddle, bull call spread, iron condor, etc.) based on event type and sentiment
5. **Compare post-event returns** against SPY and XBI to measure alpha and track historical accuracy
6. **Persist everything** in local JSON files and export for dashboard / LLM analysis

---

## Project Structure

```
biotech-options-rater/
├── models/
│   ├── event.py        # BiotechEvent, EventType, EventOutcome, MarketContext
│   └── rating.py       # OptionsRating, ScoreBreakdown, RatingGrade, OptionsStrategy
├── collectors/
│   ├── market_data.py  # SPY/XBI/VIX fetcher, sector trend classifier, macro calendar
│   └── catalyst_tracker.py  # Event factory, catalyst scoring, resolver, filters
├── engine/
│   ├── scorer.py       # Core qualitative scoring engine -> OptionsRating
│   └── comparator.py   # ReturnComparison, BenchmarkStats, print_comparison_table
├── storage/
│   └── event_store.py  # JSON-backed EventStore (upsert, load, export)
├── data/               # Auto-created: events.json, ratings.json
├── cli.py              # Command-line interface
└── requirements.txt
```

---

## Installation

```bash
git clone https://github.com/oakyoakyoak/biotech-options-rater.git
cd biotech-options-rater
pip install -r requirements.txt
```

Requires Python 3.10+.

---

## CLI Usage

### Add an event

```bash
python cli.py add \
  --ticker MRNA \
  --company "Moderna" \
  --type fda_pdufa \
  --date 2026-04-15 \
  --stage "PDUFA date" \
  --indication "COVID-19 vaccine" \
  --endpoint "Non-inferiority vs approved mRNA-1273" \
  --desc "PDUFA action date for mRNA-1283 next-gen COVID vaccine" \
  --sentiment buy \
  --competing "Pfizer BNT162b2,Novavax NVX-CoV" \
  --no-market
```

> Remove `--no-market` to auto-fetch SPY/XBI/VIX context from yfinance.

### Score an event

```bash
python cli.py score --event-id MRNA_2026-04-15_abcd1234
# Optionally pass current IV Rank:
python cli.py score --event-id MRNA_2026-04-15_abcd1234 --iv-rank 72
```

Example output:
```
============================================================
  MRNA | Moderna
  Type:     fda_pdufa
  Date:     2026-04-15
  Stage:    PDUFA date
  Sentiment:buy
  Outcome:  pending
  Rating:   B+ (72.3/100) -> bull_call_spread
  Confidence: 71.5%  DTE: 35  MaxRisk: 2.0%
============================================================

Score Breakdown:
  catalyst_quality          85.5
  sentiment_alignment       72.0
  market_context            70.0
  iv_environment            55.0
  historical_accuracy       50.0
  competitive_moat          55.0
  risk_reward               85.0
```

### Resolve after the event

```bash
python cli.py resolve \
  --event-id MRNA_2026-04-15_abcd1234 \
  --outcome positive \
  --notes "FDA approved with standard labeling, no REMS" \
  --move 18.4 \
  --iv-crush 42.0
```

### List events

```bash
# All upcoming FDA events
python cli.py list --upcoming --type fda_pdufa

# All events for a ticker
python cli.py list --ticker MRNA
```

### Post-event performance report

```bash
python cli.py report
```

Prints an ASCII comparison table showing each event's actual move vs SPY and XBI alpha, IV crush, and linked rating grade.

### Export all data

```bash
python cli.py export --output my_export.json
```

---

## Scoring Model

Each event receives a **composite score (0–100)** from seven sub-dimensions:

| Dimension | Weight | Description |
|---|---|---|
| `catalyst_quality` | 25% | Event type priority × pipeline stage multiplier + endpoint clarity bonus |
| `sentiment_alignment` | 15% | Analyst consensus (strong_buy=90 → strong_sell=10) |
| `market_context` | 15% | SPY/XBI 5-day trend + VIX level before event |
| `iv_environment` | 15% | IV Rank favorability (sweet spot 40–70 IVR) |
| `historical_accuracy` | 10% | % of past same-type events for ticker that were positive |
| `competitive_moat` | 10% | Pipeline differentiation (fewer competitors = higher score) |
| `risk_reward` | 10% | Expected event-day move magnitude proxy |

### Letter Grades

| Score | Grade | Position sizing |
|---|---|---|
| 90–100 | A+ | Up to 3.0% of portfolio |
| 80–89 | A | Up to 2.5% |
| 70–79 | B+ | Up to 2.0% |
| 60–69 | B | Up to 1.5% |
| 50–59 | C | Up to 1.0% |
| 30–49 | D | Up to 0.5% |
| 0–29 | F | Avoid |

---

## Strategy Recommender

| Event Type | Sentiment | Recommended Strategy |
|---|---|---|
| FDA / Clinical | Strong bullish (≥70) | Bull Call Spread |
| FDA / Clinical | Neutral (30–70) | Long Straddle |
| FDA / Clinical | Strong bearish (≤30) | Bear Put Spread |
| Earnings | Bullish | Bull Call Spread |
| Earnings | Neutral | Iron Condor |
| Macro | Any | Calendar Spread |
| Partnership | Bullish | Long Call / Bull Spread |

---

## Supported Event Types

- `fda_pdufa` — FDA PDUFA target action date
- `fda_adcom` — FDA Advisory Committee meeting
- `clinical_readout` — Phase 2/3 trial data release
- `earnings` — Quarterly earnings report
- `conference_pres` — Medical/investor conference presentation
- `partnership` — Business development deal
- `sec_filing` — 10-Q, 10-K, 8-K filing
- `macro_release` — CPI, FOMC, NFP, PCE, GDP, PPI, JOLTS, PMI, Retail Sales
- `competitor_event` — Rival company catalyst
- `other`

---

## Python API

```python
from datetime import date
from models.event import EventType, SentimentTag
from collectors.catalyst_tracker import create_event
from engine.scorer import score_event
from storage.event_store import EventStore

store = EventStore()

# Create and persist an event
event = create_event(
    ticker          = "BNTX",
    company_name    = "BioNTech",
    event_type      = EventType.CLINICAL_READOUT,
    event_date      = date(2026, 5, 20),
    description     = "Phase 3 mRNA cancer vaccine BNT111 melanoma readout",
    sentiment       = SentimentTag.BUY,
    pipeline_stage  = "Phase 3",
    indication      = "Unresectable / metastatic melanoma",
    primary_endpoint= "Recurrence-free survival improvement vs pembrolizumab",
    competing_drugs = ["Keytruda monotherapy"],
    auto_market_context=True,
)
store.save_event(event)

# Score it
rating = score_event(event, iv_rank=58)
store.save_rating(rating)
print(f"{rating.grade.value} ({rating.composite_score:.1f}) -> {rating.recommended_strategy.value}")
```

---

## Customising Weights

```python
my_weights = {
    "catalyst_quality":    0.35,  # up-weight catalyst
    "sentiment_alignment": 0.10,
    "market_context":      0.10,
    "iv_environment":      0.20,  # up-weight IV env
    "historical_accuracy": 0.10,
    "competitive_moat":    0.05,
    "risk_reward":         0.10,
}
rating = score_event(event, custom_weights=my_weights)
```

---

## Data Storage

All data is written to `data/events.json` and `data/ratings.json` by default.
Override the directory with the `BIOTECH_DATA_DIR` environment variable:

```bash
export BIOTECH_DATA_DIR=/path/to/my/data
python cli.py list
```

---

## Roadmap

- [ ] Notebook-based dashboard with matplotlib charts
- [ ] IV rank integration via Polygon.io or Tradier API
- [ ] Automatic FDA calendar ingestion (BioPharma Catalyst feed)
- [ ] Backtesting mode: replay past events, compare predicted vs actual grades
- [ ] LLM analyst notes summariser (OpenAI / local model)
- [ ] Email/Slack alerts for upcoming high-rated events
