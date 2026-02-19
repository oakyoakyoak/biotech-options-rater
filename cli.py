#!/usr/bin/env python3
"""cli.py
Command-line interface for the Biotech Options Rater.

Usage examples:
  python cli.py add  --ticker MRNA --company "Moderna" --type fda_pdufa \\
                     --date 2026-04-15 --stage "PDUFA date" \\
                     --desc "PDUFA for mRNA-1283 COVID vaccine" \\
                     --sentiment buy

  python cli.py score  --event-id MRNA_2026-04-15_abcd1234

  python cli.py resolve --event-id MRNA_2026-04-15_abcd1234 \\
                         --outcome positive

  python cli.py list   --upcoming --type fda_pdufa
  python cli.py report
  python cli.py export --output export.json
"""
import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from models.event import EventType, EventOutcome, SentimentTag
from collectors.catalyst_tracker import create_event, resolve_event, filter_upcoming_events
from engine.scorer import score_event
from engine.comparator import batch_compare, compute_stats, print_comparison_table
from storage.event_store import EventStore

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("cli")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date format '{s}'; expected YYYY-MM-DD")


def _print_event_summary(event, rating=None):
    print(f"\n{'='*60}")
    print(f"  {event.ticker} | {event.company_name}")
    print(f"  Type:     {event.event_type.value}")
    print(f"  Date:     {event.event_date}")
    print(f"  Stage:    {event.pipeline_stage or 'N/A'}")
    print(f"  Sentiment:{event.sentiment.value}")
    print(f"  Outcome:  {event.outcome.value}")
    if event.actual_move_pct is not None:
        print(f"  Move:     {event.actual_move_pct:+.2f}% "
              f"(vs SPY {event.spy_move_pct or 0:+.2f}%, "
              f"XBI {event.xbi_move_pct or 0:+.2f}%)")
    if rating:
        print(f"  Rating:   {rating.grade.value} ({rating.composite_score:.1f}/100) "
              f"-> {rating.recommended_strategy.value}")
        print(f"  Confidence: {rating.confidence_pct:.1f}%  "
              f"DTE: {rating.target_expiry_days}  "
              f"MaxRisk: {rating.max_risk_pct_port:.1f}%")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Sub-command handlers
# ---------------------------------------------------------------------------

def cmd_add(args, store: EventStore):
    """Add a new biotech catalyst event."""
    competing = args.competing.split(",") if args.competing else []
    event = create_event(
        ticker            = args.ticker,
        company_name      = args.company,
        event_type        = EventType(args.type),
        event_date        = _parse_date(args.date),
        description       = args.desc,
        sentiment         = SentimentTag(args.sentiment),
        pipeline_stage    = args.stage,
        indication        = args.indication,
        primary_endpoint  = args.endpoint,
        competing_drugs   = competing,
        analyst_notes     = args.notes or "",
        auto_market_context = not args.no_market,
        tags              = args.tags.split(",") if args.tags else [],
    )
    store.save_event(event)
    print(f"[+] Event created: {event.event_id}")
    _print_event_summary(event)


def cmd_score(args, store: EventStore):
    """Score an event and save the rating."""
    event = store.get_event(args.event_id)
    if event is None:
        print(f"[!] Event not found: {args.event_id}", file=sys.stderr)
        sys.exit(1)

    past_events = store.load_events()
    rating = score_event(
        event,
        iv_rank=args.iv_rank,
        past_events=past_events,
    )
    store.save_rating(rating)
    _print_event_summary(event, rating)
    print("\nScore Breakdown:")
    for k, v in rating.score_breakdown.to_dict().items():
        print(f"  {k:<25} {v:>6.1f}")


def cmd_resolve(args, store: EventStore):
    """Mark an event as resolved with outcome."""
    event = store.get_event(args.event_id)
    if event is None:
        print(f"[!] Event not found: {args.event_id}", file=sys.stderr)
        sys.exit(1)

    event = resolve_event(
        event,
        outcome          = EventOutcome(args.outcome),
        outcome_notes    = args.notes or "",
        auto_fetch_moves = not args.no_fetch,
    )
    if args.move is not None:
        event.actual_move_pct = args.move
    if args.iv_crush is not None:
        event.iv_crush_pct = args.iv_crush

    store.save_event(event)
    print(f"[+] Resolved {event.event_id} -> {event.outcome.value}")
    _print_event_summary(event)


def cmd_list(args, store: EventStore):
    """List events, optionally filtered."""
    events = store.load_events()
    ratings = store.ratings_by_event()

    if args.upcoming:
        event_types = [EventType(t) for t in args.type.split(",")] if args.type else None
        events = filter_upcoming_events(events, event_types=event_types)
    elif args.type:
        events = [e for e in events if e.event_type.value == args.type]
    if args.ticker:
        events = [e for e in events if e.ticker.upper() == args.ticker.upper()]

    if not events:
        print("No events found.")
        return

    for ev in events:
        rating = ratings.get(ev.event_id or "")
        grade  = rating.grade.value if rating else "--"
        score  = f"{rating.composite_score:.1f}" if rating else "--"
        print(
            f"{ev.ticker:<8} {ev.event_date}  "
            f"{ev.event_type.value:<22} "
            f"{ev.outcome.value:<12} "
            f"Grade: {grade:<4} Score: {score}"
        )


def cmd_report(args, store: EventStore):
    """Print performance report of resolved events."""
    events  = store.load_events()
    ratings = store.ratings_by_event()
    comparisons = batch_compare(events, ratings)

    if not comparisons:
        print("No resolved events with price data to report.")
        return

    print_comparison_table(comparisons)
    stats = compute_stats(comparisons, events)
    print("\nAggregate Stats:")
    for k, v in stats.to_dict().items():
        val = f"{v:.2f}" if isinstance(v, float) else str(v)
        print(f"  {k:<28} {val}")


def cmd_export(args, store: EventStore):
    """Export all data to a JSON file."""
    out = Path(args.output)
    store.export_json(out)
    print(f"[+] Exported to {out}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="biotech-rater",
        description="Biotech catalyst tracker and options trade rater.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- add ---
    p_add = sub.add_parser("add", help="Add a new catalyst event")
    p_add.add_argument("--ticker",      required=True)
    p_add.add_argument("--company",     required=True)
    p_add.add_argument("--type",        required=True,
                       choices=[e.value for e in EventType])
    p_add.add_argument("--date",        required=True, help="YYYY-MM-DD")
    p_add.add_argument("--desc",        required=True)
    p_add.add_argument("--sentiment",   default="neutral",
                       choices=[s.value for s in SentimentTag])
    p_add.add_argument("--stage",       default=None)
    p_add.add_argument("--indication",  default=None)
    p_add.add_argument("--endpoint",    default=None)
    p_add.add_argument("--competing",   default=None, help="Comma-separated drug names")
    p_add.add_argument("--notes",       default=None)
    p_add.add_argument("--tags",        default=None, help="Comma-separated tags")
    p_add.add_argument("--no-market",   action="store_true",
                       help="Skip auto market context fetch")

    # --- score ---
    p_score = sub.add_parser("score", help="Score an event and generate options rating")
    p_score.add_argument("--event-id",  required=True)
    p_score.add_argument("--iv-rank",   type=float, default=None,
                         help="Current IV Rank 0-100")

    # --- resolve ---
    p_res = sub.add_parser("resolve", help="Mark an event as resolved")
    p_res.add_argument("--event-id",  required=True)
    p_res.add_argument("--outcome",   required=True,
                       choices=[o.value for o in EventOutcome if o != EventOutcome.PENDING])
    p_res.add_argument("--notes",     default=None)
    p_res.add_argument("--move",      type=float, default=None,
                       help="Override actual move pct")
    p_res.add_argument("--iv-crush",  type=float, default=None)
    p_res.add_argument("--no-fetch",  action="store_true",
                       help="Skip auto price fetch")

    # --- list ---
    p_list = sub.add_parser("list", help="List events")
    p_list.add_argument("--upcoming",  action="store_true")
    p_list.add_argument("--type",      default=None)
    p_list.add_argument("--ticker",    default=None)

    # --- report ---
    sub.add_parser("report", help="Print post-event performance report")

    # --- export ---
    p_exp = sub.add_parser("export", help="Export all data to JSON")
    p_exp.add_argument("--output", default="biotech_export.json")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = build_parser()
    args   = parser.parse_args()
    store  = EventStore()

    dispatch = {
        "add":     cmd_add,
        "score":   cmd_score,
        "resolve": cmd_resolve,
        "list":    cmd_list,
        "report":  cmd_report,
        "export":  cmd_export,
    }
    handler = dispatch.get(args.command)
    if handler:
        handler(args, store)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
