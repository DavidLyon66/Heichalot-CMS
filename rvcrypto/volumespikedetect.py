#!/usr/bin/env python3
"""
volumespikedetect.py

Ground truth tool for spike detection.

This tool records human-observed spike events and validates them
against the automatic detector (spikedetect.py). It answers:

    1. What spikes did you observe?
    2. Did the auto-detector catch them?
    3. Are there calendar patterns (month-end clustering)?
    4. How accurate is the auto-detector?

Use this tool to build a labeled dataset of spike events. The labels
serve as ground truth for validating and tuning spikedetect.py.


Usage
-----

Add a labeled spike:

    python3 volumespikedetect.py MMT \\
        --add 2026-07-31 --reason "Month-end accounting settlement" \\
        --magnitude "+83%" --source "manual chart review"

Remove a labeled spike:

    python3 volumespikedetect.py MMT --remove 2026-07-31

List all labeled spikes:

    python3 volumespikedetect.py MMT --list

Validate labels against auto-detector:

    python3 volumespikedetect.py MMT --validate

Analyze calendar patterns:

    python3 volumespikedetect.py MMT --calendar

JSON output:

    python3 volumespikedetect.py MMT --validate --json


Workflow
--------

1. Use --add to label spikes as you observe them
2. Use --validate to see how accurate the auto-detector is
3. Use --calendar to check for accounting settlement patterns
4. Add more labels over time to improve the detector's validation


Storage
-------

Labels are stored in data/{ASSET}_{REFERENCE}_spike_labels.json
Separate from market data and auto-detection results.
"""

import argparse
import configparser
import json
import sys
from datetime import datetime
from pathlib import Path


BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.ini"

DEFAULT_REFERENCE = "USDT"


def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def get_reference(config):
    return config.get(
        "market-data", "reference_currency", fallback=DEFAULT_REFERENCE
    ).upper()


def get_data_dir(config):
    path = Path(config.get("storage", "data_dir", fallback="data"))
    if not path.is_absolute():
        path = BASE / path
    return path


def label_file_path(data_dir, asset, reference):
    return data_dir / f"{asset}_{reference}_spike_labels.json"


def load_labels(path):
    if not path.exists():
        return {"spikes": []}

    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if "spikes" not in data:
        data["spikes"] = []

    return data


def save_labels(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def load_ohlcv(data_dir, asset, reference):
    path = data_dir / f"{asset}_{reference}.json"
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)

    return document.get("data", [])


def parse_rows(rows):
    parsed = []
    for row in rows:
        try:
            parsed.append({
                "date": row["date"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return parsed


# ---------------------------------------------------------------------------
# Spike labeling
# ---------------------------------------------------------------------------

def add_spike(data, date, reason=None, magnitude=None, source=None):
    existing = next(
        (s for s in data["spikes"] if s["date"] == date),
        None,
    )

    if existing:
        raise ValueError(f"Spike already recorded for {date}")

    spike = {
        "date": date,
        "labeled_at": datetime.utcnow().isoformat() + "Z",
    }

    if reason:
        spike["reason"] = reason

    if magnitude:
        spike["magnitude"] = magnitude

    if source:
        spike["source"] = source

    data["spikes"].append(spike)
    data["spikes"].sort(key=lambda s: s["date"])

    return spike


def remove_spike(data, date):
    original = len(data["spikes"])
    data["spikes"] = [s for s in data["spikes"] if s["date"] != date]
    return len(data["spikes"]) < original


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_labels(data, parsed, lookback=30):
    try:
        import sys
        sys.path.insert(0, str(BASE))
        from spikedetect import detect_spike, score_assessment
    except ImportError:
        print("Error: spikedetect.py not found", file=sys.stderr)
        return None

    if len(parsed) < lookback + 1:
        print(
            f"Error: need {lookback + 1} rows, have {len(parsed)}",
            file=sys.stderr,
        )
        return None

    results = []
    for i in range(lookback, len(parsed)):
        result = detect_spike(parsed, i, window=7, lookback=lookback)
        results.append(result)

    labeled_dates = {s["date"] for s in data["spikes"]}
    result_dates = {r["date"]: r for r in results}

    true_positives = []
    false_positives = []
    missed = []

    for date in labeled_dates:
        if date in result_dates:
            result = result_dates[date]
            if result["total_score"] >= 50:
                true_positives.append({
                    "date": date,
                    "score": result["total_score"],
                    "label": next(
                        (s for s in data["spikes"] if s["date"] == date),
                        {},
                    ),
                })
            else:
                missed.append({
                    "date": date,
                    "score": result["total_score"],
                    "label": next(
                        (s for s in data["spikes"] if s["date"] == date),
                        {},
                    ),
                })
        else:
            missed.append({
                "date": date,
                "score": None,
                "label": next(
                    (s for s in data["spikes"] if s["date"] == date),
                    {},
                ),
            })

    for date, result in result_dates.items():
        if date not in labeled_dates and result["total_score"] >= 50:
            false_positives.append({
                "date": date,
                "score": result["total_score"],
            })

    total_labeled = len(labeled_dates)
    total_detected = len(true_positives)
    total_missed = len(missed)
    total_fp = len(false_positives)

    detection_rate = (
        total_detected / total_labeled * 100
        if total_labeled > 0
        else 0
    )
    fp_rate = (
        total_fp / (total_detected + total_fp) * 100
        if (total_detected + total_fp) > 0
        else 0
    )

    return {
        "total_labeled": total_labeled,
        "total_detected": total_detected,
        "total_missed": total_missed,
        "total_false_positives": total_fp,
        "detection_rate": detection_rate,
        "false_positive_rate": fp_rate,
        "true_positives": true_positives,
        "missed": missed,
        "false_positives": false_positives,
    }


# ---------------------------------------------------------------------------
# Calendar analysis
# ---------------------------------------------------------------------------

def calendar_analysis(data, parsed):
    labeled = data["spikes"]

    if not labeled:
        return None

    month_ends = 0
    month_start = 0
    mid_month = 0

    for spike in labeled:
        date = datetime.strptime(spike["date"], "%Y-%m-%d")
        day = date.day
        _, last_day = _month_range(date.year, date.month)

        if day >= last_day - 3:
            month_ends += 1
        elif day <= 3:
            month_start += 1
        else:
            mid_month += 1

    total = len(labeled)

    return {
        "total_spikes": total,
        "month_end": month_ends,
        "month_end_pct": month_ends / total * 100 if total > 0 else 0,
        "month_start": month_start,
        "month_start_pct": month_start / total * 100 if total > 0 else 0,
        "mid_month": mid_month,
        "mid_month_pct": mid_month / total * 100 if total > 0 else 0,
    }


def _month_range(year, month):
    if month == 12:
        next_month = datetime(year + 1, 1, 1)
    else:
        next_month = datetime(year, month + 1, 1)

    last_day = (next_month - __import__("datetime").timedelta(days=1)).day
    return 1, last_day


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def format_list(data):
    spikes = data["spikes"]

    if not spikes:
        print("No labeled spikes.")
        return

    print(f"LABELED SPIKES ({len(spikes)} total)")
    print("-" * 60)
    print(f"  {'Date':<12} {'Reason':<30} {'Magnitude':<10}")
    print(f"  {'-'*12} {'-'*30} {'-'*10}")

    for spike in spikes:
        date = spike["date"]
        reason = spike.get("reason", "")[:30]
        magnitude = spike.get("magnitude", "")

        if magnitude:
            print(f"  {date:<12} {reason:<30} {magnitude:<10}")
        else:
            print(f"  {date:<12} {reason:<30}")

    print()


def format_validation(result):
    if result is None:
        return

    print("VALIDATION REPORT")
    print("=" * 60)
    print()
    print(f"  Labeled spikes:      {result['total_labeled']}")
    print(f"  Detected by auto:    {result['total_detected']}")
    print(f"  Missed by auto:      {result['total_missed']}")
    print(f"  False positives:     {result['total_false_positives']}")
    print()
    print(f"  Detection rate:      {result['detection_rate']:.0f}%")
    print(f"  False positive rate: {result['false_positive_rate']:.0f}%")
    print()

    if result["true_positives"]:
        print("TRUE POSITIVES (auto-detected correctly):")
        print("-" * 60)
        for tp in result["true_positives"]:
            reason = tp["label"].get("reason", "no reason given")
            print(f"  {tp['date']}: score {tp['score']}/100 — {reason}")
        print()

    if result["missed"]:
        print("MISSED (auto-detector missed these):")
        print("-" * 60)
        for m in result["missed"]:
            reason = m["label"].get("reason", "no reason given")
            score = f"score {m['score']}" if m["score"] is not None else "no data"
            print(f"  {m['date']}: {score} — {reason}")
        print()

    if result["false_positives"]:
        print("FALSE POSITIVES (auto-detected but not labeled):")
        print("-" * 60)
        for fp in result["false_positives"]:
            print(f"  {fp['date']}: score {fp['score']}/100")
        print()


def format_calendar(result):
    if result is None:
        print("No labeled spikes for calendar analysis.")
        return

    print("CALENDAR ANALYSIS")
    print("=" * 60)
    print()
    print(f"  Total labeled spikes: {result['total_spikes']}")
    print()
    print(f"  Month-end (day 28+):  {result['month_end']:>3}  ({result['month_end_pct']:.0f}%)")
    print(f"  Month-start (day 1-3): {result['month_start']:>3}  ({result['month_start_pct']:.0f}%)")
    print(f"  Mid-month:            {result['mid_month']:>3}  ({result['mid_month_pct']:.0f}%)")
    print()

    if result["month_end_pct"] > 40:
        print("  OBSERVATION: Spikes cluster near month-end.")
        print("  This supports the accounting settlement hypothesis.")
    elif result["month_start_pct"] > 40:
        print("  OBSERVATION: Spikes cluster near month-start.")
        print("  This may indicate beginning-of-period activity.")
    else:
        print("  OBSERVATION: No strong calendar pattern detected.")

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description="Ground truth tool for spike detection."
    )

    parser.add_argument(
        "asset",
        help="Crypto asset symbol (e.g. MMT, DGB)",
    )

    actions = parser.add_mutually_exclusive_group(required=True)

    actions.add_argument(
        "--add",
        metavar="DATE",
        help="Add a labeled spike (YYYY-MM-DD)",
    )

    actions.add_argument(
        "--remove",
        metavar="DATE",
        help="Remove a labeled spike",
    )

    actions.add_argument(
        "--list",
        action="store_true",
        help="List all labeled spikes",
    )

    actions.add_argument(
        "--validate",
        action="store_true",
        help="Validate labels against auto-detector",
    )

    actions.add_argument(
        "--calendar",
        action="store_true",
        help="Analyze calendar patterns in labeled spikes",
    )

    parser.add_argument(
        "--reason",
        help="Why you think this spike happened",
    )

    parser.add_argument(
        "--magnitude",
        help="Approximate size (e.g. '+30%', '2x normal')",
    )

    parser.add_argument(
        "--source",
        help="How you observed it (e.g. 'manual chart review')",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Structured JSON output",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    asset = args.asset.upper()

    config = load_config()
    reference = get_reference(config)
    data_dir = get_data_dir(config)

    label_path = label_file_path(data_dir, asset, reference)
    data = load_labels(label_path)

    ohlcv = load_ohlcv(data_dir, asset, reference)
    parsed = parse_rows(ohlcv)

    if args.add:
        try:
            datetime.strptime(args.add, "%Y-%m-%d")
        except ValueError:
            parser.error(
                f"Invalid date '{args.add}'. Expected YYYY-MM-DD."
            )

        try:
            spike = add_spike(
                data,
                date=args.add,
                reason=args.reason,
                magnitude=args.magnitude,
                source=args.source,
            )
        except ValueError as exc:
            parser.error(str(exc))

        save_labels(label_path, data)

        print(f"Added labeled spike: {spike['date']}")
        if spike.get("reason"):
            print(f"  Reason: {spike['reason']}")
        if spike.get("magnitude"):
            print(f"  Magnitude: {spike['magnitude']}")
        print(f"Stored in {label_path}")

        return

    if args.remove:
        removed = remove_spike(data, args.remove)

        if not removed:
            print(f"No labeled spike found for {args.remove}.")
            return

        save_labels(label_path, data)
        print(f"Removed labeled spike: {args.remove}")
        print(f"Stored in {label_path}")

        return

    if args.list:
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            format_list(data)

        return

    if args.validate:
        result = validate_labels(data, parsed)

        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            format_validation(result)

        return

    if args.calendar:
        result = calendar_analysis(data, parsed)

        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            format_calendar(result)

        return


if __name__ == "__main__":
    main()
