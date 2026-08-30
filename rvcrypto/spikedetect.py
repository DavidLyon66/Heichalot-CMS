#!/usr/bin/env python3
"""
spikedetect.py

Automatic spike detector and scorer for rvcrypto.

Detects sudden, sharp price movements driven by external factors —
insider trading, accounting settlements, or other non-market events.
The detector identifies spikes by their statistical signature:
volume surge, price range expansion, and calendar clustering.

Typical use:

    python3 spikedetect.py MMT --report
    python3 spikedetect.py MMT --detect
    python3 spikedetect.py MMT --detect --window 14

Scoring is deterministic — same data always produces same result.

Design assumptions (hardcoded, documented here):

    1. Volume surge is the primary spike indicator.
       Spikes from external money show 5-35x normal volume.

    2. Price range expansion accompanies volume surge.
       The high-low range widens during spike events.

    3. Month-end clustering suggests accounting settlements.
       Spikes near month-end get a calendar bonus.

    4. Multi-day spikes show consecutive elevated days.
       A single volatile day is noise; 2-3 elevated days is a spike.

    5. Post-spike pullback is common.
       Most spikes are followed by mean reversion within 2-3 days.

These assumptions are based on analysis of MMT/USDT price history
from 2025-11-04 to 2026-08-25, which showed clear spike patterns
consistent with external money flows (likely accounting settlements).

The detector does NOT attempt to predict future spikes. It scores
how "spike-like" the current market condition is based on historical
patterns.
"""

import argparse
import configparser
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path


BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.ini"

DEFAULT_REFERENCE = "USDT"
DEFAULT_WINDOW = 7
DEFAULT_LOOKBACK = 30

# ---------------------------------------------------------------------------
# Scoring weights — deterministic, based on MMT historical spike analysis
# ---------------------------------------------------------------------------

# How many points each factor contributes to the 0-100 score
WEIGHT_VOLUME = 35
WEIGHT_RANGE = 25
WEIGHT_CALENDAR = 15
WEIGHT_MOMENTUM = 15
WEIGHT_REVERSION = 10

# Volume thresholds — what multiple of normal volume indicates a spike
# Based on MMT: normal days ~2-5M volume, spikes ~20-500M volume
VOLUME_RATIO_HIGH = 5.0
VOLUME_RATIO_MEDIUM = 2.5
VOLUME_RATIO_LOW = 1.5

# Price range thresholds — how much the high-low range expands
# During spikes, the range typically expands 2-5x
RANGE_EXPANSION_HIGH = 2.0
RANGE_EXPANSION_MEDIUM = 1.5
RANGE_EXPANSION_LOW = 1.2

# Calendar proximity — days before/after month-end that count
CALENDAR_PROXIMITY_DAYS = 3

# Momentum — consecutive days of elevated volume
MOMENTUM_DAYS_HIGH = 3
MOMENTUM_DAYS_MEDIUM = 2

# Thresholds for spike assessment
SCORE_SPIKE_ACTIVE = 75
SCORE_SPIKE_LIKELY = 50
SCORE_WATCH = 25


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


def load_ohlcv(data_dir, asset, reference):
    path = data_dir / f"{asset}_{reference}.json"
    if not path.exists():
        raise FileNotFoundError(f"No data file: {path}")

    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)

    rows = document.get("data", [])
    if not rows:
        raise ValueError(f"Empty data file: {path}")

    return rows


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
# Calendar utilities
# ---------------------------------------------------------------------------

def is_month_end(date_str, proximity_days=CALENDAR_PROXIMITY_DAYS):
    date = datetime.strptime(date_str, "%Y-%m-%d")
    next_month = date.month % 12 + 1
    year = date.year + (1 if date.month == 12 else 0)
    month_end = datetime(year, next_month, 1) - timedelta(days=1)
    days_until = (month_end - date).days
    return 0 <= days_until <= proximity_days


def calendar_score(date_str):
    if is_month_end(date_str):
        return 1.0
    return 0.0


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def score_volume(volumes, index, lookback=DEFAULT_LOOKBACK):
    if index < 1:
        return 0.0, 0.0

    current_volume = volumes[index]

    start = max(0, index - lookback)
    recent = volumes[start:index]

    if not recent:
        return 0.0, 0.0

    avg_volume = sum(recent) / len(recent)

    if avg_volume <= 0:
        return 0.0, 0.0

    ratio = current_volume / avg_volume

    if ratio >= VOLUME_RATIO_HIGH:
        score = 1.0
    elif ratio >= VOLUME_RATIO_MEDIUM:
        score = 0.5 + 0.5 * (ratio - VOLUME_RATIO_MEDIUM) / (VOLUME_RATIO_HIGH - VOLUME_RATIO_MEDIUM)
    elif ratio >= VOLUME_RATIO_LOW:
        score = 0.2 + 0.3 * (ratio - VOLUME_RATIO_LOW) / (VOLUME_RATIO_MEDIUM - VOLUME_RATIO_LOW)
    else:
        score = max(0.0, 0.2 * (ratio - 1.0) / (VOLUME_RATIO_LOW - 1.0))

    return score, ratio


def score_range(rows, index, lookback=DEFAULT_LOOKBACK):
    if index < 1:
        return 0.0, 0.0

    current = rows[index]
    current_range = current["high"] - current["low"]
    current_mid = (current["high"] + current["low"]) / 2.0

    if current_mid <= 0:
        return 0.0, 0.0

    range_pct = current_range / current_mid

    start = max(0, index - lookback)
    recent = rows[start:index]

    if not recent:
        return 0.0, 0.0

    recent_ranges = []
    for r in recent:
        mid = (r["high"] + r["low"]) / 2.0
        if mid > 0:
            recent_ranges.append((r["high"] - r["low"]) / mid)

    if not recent_ranges:
        return 0.0, 0.0

    avg_range_pct = sum(recent_ranges) / len(recent_ranges)

    if avg_range_pct <= 0:
        return 0.0, 0.0

    expansion = range_pct / avg_range_pct

    if expansion >= RANGE_EXPANSION_HIGH:
        score = 1.0
    elif expansion >= RANGE_EXPANSION_MEDIUM:
        score = 0.4 + 0.6 * (expansion - RANGE_EXPANSION_MEDIUM) / (RANGE_EXPANSION_HIGH - RANGE_EXPANSION_MEDIUM)
    elif expansion >= RANGE_EXPANSION_LOW:
        score = 0.1 + 0.3 * (expansion - RANGE_EXPANSION_LOW) / (RANGE_EXPANSION_MEDIUM - RANGE_EXPANSION_LOW)
    else:
        score = max(0.0, 0.1 * (expansion - 1.0) / (RANGE_EXPANSION_LOW - 1.0))

    return score, expansion


def score_momentum(volumes, index, lookback=DEFAULT_LOOKBACK):
    if index < 1:
        return 0.0, 0

    current_volume = volumes[index]
    start = max(0, index - lookback)
    recent = volumes[start:index]

    if not recent:
        return 0.0, 0

    avg_volume = sum(recent) / len(recent)

    if avg_volume <= 0:
        return 0.0, 0

    consecutive = 0
    for i in range(index, max(start - 1, 0), -1):
        if volumes[i] > avg_volume * VOLUME_RATIO_LOW:
            consecutive += 1
        else:
            break

    if consecutive >= MOMENTUM_DAYS_HIGH:
        score = 1.0
    elif consecutive >= MOMENTUM_DAYS_MEDIUM:
        score = 0.5 + 0.5 * (consecutive - MOMENTUM_DAYS_MEDIUM) / (MOMENTUM_DAYS_HIGH - MOMENTUM_DAYS_MEDIUM)
    elif consecutive >= 1:
        score = 0.2 + 0.3 * (consecutive - 1) / (MOMENTUM_DAYS_MEDIUM - 1)
    else:
        score = 0.0

    return score, consecutive


def score_reversion(rows, index, window=DEFAULT_WINDOW):
    if index < 1:
        return 0.0, 0.0

    current = rows[index]

    start = max(0, index - window)
    recent = rows[start:index + 1]

    if len(recent) < 2:
        return 0.0, 0.0

    peak_idx = max(range(len(recent)), key=lambda i: recent[i]["high"])
    peak = recent[peak_idx]

    if peak_idx >= len(recent) - 1:
        return 0.0, 0.0

    peak_price = peak["high"]
    current_price = current["close"]

    if peak_price <= 0:
        return 0.0, 0.0

    pullback_pct = (peak_price - current_price) / peak_price

    days_since_peak = len(recent) - 1 - peak_idx

    if days_since_peak == 0:
        return 0.0, 0.0

    if pullback_pct > 0.1 and days_since_peak <= 3:
        score = min(1.0, pullback_pct * 5)
        return score, pullback_pct
    elif pullback_pct > 0.05 and days_since_peak <= 5:
        score = min(0.7, pullback_pct * 5)
        return score, pullback_pct

    return 0.0, pullback_pct


# ---------------------------------------------------------------------------
# Main scoring functions
# ---------------------------------------------------------------------------

def detect_spike(rows, index, window=DEFAULT_WINDOW, lookback=DEFAULT_LOOKBACK):
    volumes = [r["volume"] for r in rows]

    vol_score, vol_ratio = score_volume(volumes, index, lookback)
    range_score, range_expansion = score_range(rows, index, lookback)
    momentum_score, consecutive = score_momentum(volumes, index, lookback)
    reversion_score, pullback = score_reversion(rows, index, window)
    cal_score = calendar_score(rows[index]["date"])

    total = (
        vol_score * WEIGHT_VOLUME +
        range_score * WEIGHT_RANGE +
        cal_score * WEIGHT_CALENDAR +
        momentum_score * WEIGHT_MOMENTUM +
        reversion_score * WEIGHT_REVERSION
    )

    return {
        "date": rows[index]["date"],
        "close": rows[index]["close"],
        "volume": rows[index]["volume"],
        "volume_ratio": vol_ratio,
        "volume_score": round(vol_score * WEIGHT_VOLUME),
        "range_expansion": range_expansion,
        "range_score": round(range_score * WEIGHT_RANGE),
        "calendar_score": round(cal_score * WEIGHT_CALENDAR),
        "momentum_days": consecutive,
        "momentum_score": round(momentum_score * WEIGHT_MOMENTUM),
        "pullback_pct": pullback,
        "reversion_score": round(reversion_score * WEIGHT_REVERSION),
        "total_score": round(total),
        "direction": _get_direction(rows, index),
    }


def _get_direction(rows, index):
    if index < 1:
        return "FLAT"

    change = rows[index]["close"] - rows[index - 1]["close"]

    if change > 0:
        return "UP"
    elif change < 0:
        return "DOWN"

    return "FLAT"


def score_assessment(score):
    if score >= SCORE_SPIKE_ACTIVE:
        return "SPIKE ACTIVE"
    elif score >= SCORE_SPIKE_LIKELY:
        return "SPIKE LIKELY"
    elif score >= SCORE_WATCH:
        return "WATCH"
    else:
        return "NO SPIKE"


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(rows, window=DEFAULT_WINDOW, lookback=DEFAULT_LOOKBACK):
    if len(rows) < lookback + 1:
        raise ValueError(
            f"Not enough data: need {lookback + 1} rows, have {len(rows)}"
        )

    scores = []
    for i in range(lookback, len(rows)):
        result = detect_spike(rows, i, window, lookback)
        scores.append(result)

    spike_events = [s for s in scores if s["total_score"] >= SCORE_WATCH]

    latest = scores[-1] if scores else None

    avg_volume = _avg_volume(rows, lookback)

    return {
        "asset": rows[0].get("asset", "?"),
        "period": f"{rows[lookback]['date']} to {rows[-1]['date']}",
        "total_days": len(rows),
        "analysis_days": len(scores),
        "spike_events": spike_events,
        "total_spikes": len(spike_events),
        "latest": latest,
        "avg_daily_volume": avg_volume,
    }


def _avg_volume(rows, lookback):
    recent = rows[-lookback:]
    volumes = [r["volume"] for r in recent]
    return sum(volumes) / len(volumes) if volumes else 0


def format_report(report):
    lines = []

    lines.append(f"SPIKE REPORT: {report['asset']}/USDT")
    lines.append(f"Period: {report['period']} ({report['total_days']} days)")
    lines.append("")

    events = report["spike_events"]

    if events:
        lines.append("DETECTED SPIKE EVENTS:")
        lines.append("")
        lines.append(
            "  Date        Volume      Vol Ratio   Price Move    Score"
        )
        lines.append(
            "  ----------  ----------  ----------  -----------   -----"
        )

        for event in events:
            vol = event["volume"]
            if vol >= 1_000_000:
                vol_str = f"{vol / 1_000_000:.1f}M"
            elif vol >= 1_000:
                vol_str = f"{vol / 1_000:.1f}K"
            else:
                vol_str = f"{vol:.0f}"

            ratio = event["volume_ratio"]
            direction = event["direction"]
            score = event["total_score"]
            date = event["date"]

            if event.get("pullback_pct", 0) > 0:
                price_move = f"{direction} (pulled back {event['pullback_pct']:.0%})"
            else:
                price_move = direction

            lines.append(
                f"  {date}  {vol_str:>10}  {ratio:>8.1f}x  {price_move:>12}  {score:>4}/100"
            )

        lines.append("")

        month_ends = [e for e in events if is_month_end(e["date"])]
        lines.append(
            f"Month-end spikes: {len(month_ends)} of {len(events)} "
            f"({len(month_ends) / len(events) * 100:.0f}%)" if events else ""
        )

        if events:
            avg_vol_ratio = sum(e["volume_ratio"] for e in events) / len(events)
            lines.append(f"Average spike volume: {avg_vol_ratio:.1f}x normal")

    else:
        lines.append("NO SPIKE EVENTS DETECTED in this period.")

    lines.append("")

    if report["latest"]:
        latest = report["latest"]
        lines.append(f"CURRENT STATE (as of {latest['date']}):")
        lines.append(f"  Close: {latest['close']:.4f}")
        lines.append(f"  Volume: {latest['volume']:.0f}")
        lines.append(f"  Volume ratio: {latest['volume_ratio']:.1f}x")
        lines.append(f"  Score: {latest['total_score']}/100 — {score_assessment(latest['total_score'])}")

    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description="Automatic spike detector and scorer."
    )

    parser.add_argument(
        "asset",
        help="Crypto asset symbol (e.g. MMT, DGB)",
    )

    parser.add_argument(
        "--report",
        action="store_true",
        help="Full historical spike analysis",
    )

    parser.add_argument(
        "--detect",
        action="store_true",
        help="Current spike detection score",
    )

    parser.add_argument(
        "--window",
        type=int,
        default=DEFAULT_WINDOW,
        help=f"Assessment window in days (default: {DEFAULT_WINDOW})",
    )

    parser.add_argument(
        "--lookback",
        type=int,
        default=DEFAULT_LOOKBACK,
        help=f"Historical lookback for baseline (default: {DEFAULT_LOOKBACK})",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Structured JSON output",
    )

    parser.add_argument(
        "--history",
        action="store_true",
        help="Show all spike scores over time",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include detailed scoring breakdown",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    asset = args.asset.upper()

    config = load_config()
    reference = get_reference(config)
    data_dir = get_data_dir(config)

    try:
        rows = load_ohlcv(data_dir, asset, reference)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    parsed = parse_rows(rows)

    min_rows = args.lookback + 1
    if len(parsed) < min_rows:
        print(
            f"Error: need at least {min_rows} rows of data, "
            f"have {len(parsed)}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.report and not args.detect and not args.history:
        args.report = True

    report = generate_report(parsed, args.window, args.lookback)

    if args.json:
        output = {
            "asset": asset,
            "reference_currency": reference,
            "window": args.window,
            "lookback": args.lookback,
            "report": report,
        }

        if args.history:
            output["history"] = [
                detect_spike(parsed, i, args.window, args.lookback)
                for i in range(args.lookback, len(parsed))
            ]

        print(
            json.dumps(
                output,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )
        return

    if args.report:
        print(format_report(report))

    if args.detect:
        latest = report["latest"]
        print(f"SPIKE DETECTION: {asset}/USDT")
        print(f"Window: {args.window} days")
        print("")
        print(
            f"  Volume surge:         {latest['volume_ratio']:.1f}x avg"
            f"     {latest['volume_score']}/{WEIGHT_VOLUME}"
        )
        print(
            f"  Price range expand:   {latest['range_expansion']:.1f}x ATR"
            f"     {latest['range_score']}/{WEIGHT_RANGE}"
        )
        print(
            f"  Calendar proximity:   "
            f"{'month-end' if calendar_score(latest['date']) > 0 else 'not near month-end'}"
            f"     {latest['calendar_score']}/{WEIGHT_CALENDAR}"
        )
        print(
            f"  Momentum buildup:     {latest['momentum_days']} days"
            f"     {latest['momentum_score']}/{WEIGHT_MOMENTUM}"
        )
        print(
            f"  Mean reversion:       {latest['pullback_pct']:.0%} pullback"
            f"     {latest['reversion_score']}/{WEIGHT_REVERSION}"
        )
        print("")
        print(
            f"  SPIKE SCORE: {latest['total_score']}/100"
        )
        print(
            f"  Assessment:  {score_assessment(latest['total_score'])}"
        )
        print("")

    if args.history:
        print(f"SPIKE HISTORY: {asset}/USDT")
        print("")
        print(
            f"  {'Date':<12} {'Close':>10} {'Vol Ratio':>10} "
            f"{'Range':>8} {'Momentum':>10} {'Score':>6} {'Assessment'}"
        )
        print(
            f"  {'-'*12} {'-'*10} {'-'*10} "
            f"{'-'*8} {'-'*10} {'-'*6} {'-'*14}"
        )

        for i in range(args.lookback, len(parsed)):
            result = detect_spike(parsed, i, args.window, args.lookback)
            date = result["date"]
            close = result["close"]
            vol = result["volume_ratio"]
            rng = result["range_expansion"]
            mom = result["momentum_days"]
            score = result["total_score"]
            assessment = score_assessment(score)

            print(
                f"  {date:<12} {close:>10.4f} {vol:>9.1f}x "
                f"{rng:>7.1f}x {mom:>6} days {score:>5}/100 {assessment}"
            )

        print("")


if __name__ == "__main__":
    main()
