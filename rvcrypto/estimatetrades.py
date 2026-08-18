#!/usr/bin/env python3
"""
estimatetrades.py <asset> [--channel ACTIVE|label] [--date YYYY-MM-DD] [--stream]

Experimental estimate of how many >=20% trade opportunities may remain
inside a recorded rvcrypto trading channel.

This is deliberately a first-pass heuristic, not a trained model.

Current idea:
- Start with DEFAULT_TRADES=6 (roughly 3 buys + 3 sells).
- Detect completed directional swing legs inside the selected channel.
- Only count a leg if its amplitude is >=20%.
- Adjust the expected total slightly for channel volatility.
- Remaining estimate = expected total - completed qualifying legs.

This needs historical backtesting. The CLI and report format are the
important parts for now; the estimator can later be replaced.

Future work:
1. Train expected opportunity count from named historical channels.
2. Reuse channelswing.py directly instead of maintaining a second swing definition.
3. Separate BUY and SELL opportunity models.
4. Weight by volinfluence.py and channelvolatility.py.
5. Estimate time-left as well as trades-left.
6. Learn per-asset defaults.
7. Compare estimated opportunities against actual executed trades.
"""

import argparse
import configparser
import json
import statistics
from datetime import date
from pathlib import Path

from tools import lan

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.ini"
CHANNEL_FILE = BASE / "data" / "tradingchannels.json"

DEFAULT_QUOTE = "USDT"
DEFAULT_TRADES = 6
MIN_SWING_PCT = 20.0
DEFAULT_TOPIC = "rvcrypto/estimatetrades"


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_config():
    c = configparser.ConfigParser()
    c.read(CONFIG_FILE)
    return c


def reference_currency(config):
    return config.get("market-data", "reference_currency", fallback=DEFAULT_QUOTE).upper()


def data_dir(config):
    p = Path(config.get("storage", "data_dir", fallback="data"))
    return p if p.is_absolute() else BASE / p


def load_history(config, asset, quote, cutoff=None):
    path = data_dir(config) / f"{asset}_{quote}.json"
    doc = load_json(path)
    rows = []
    for r in doc.get("data", []):
        try:
            row = {
                "date": str(r["date"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r.get("volume", 0.0)),
            }
        except (KeyError, TypeError, ValueError):
            continue
        if cutoff is None or row["date"] <= cutoff:
            rows.append(row)
    rows.sort(key=lambda r: r["date"])
    if not rows:
        raise ValueError("No usable market history.")
    return rows


def find_channel(asset, label="ACTIVE", as_of=None):
    doc = load_json(CHANNEL_FILE)
    matches = [
        c for c in doc.get("channels", [])
        if str(c.get("asset", "")).upper() == asset
    ]

    if str(label).upper() == "ACTIVE":
        matches = [c for c in matches if c.get("end_date") is None]
    else:
        matches = [
            c for c in matches
            if str(c.get("label", "")).casefold() == str(label).casefold()
        ]

    if not matches:
        raise ValueError(f'No channel "{label}" found for {asset}.')
    if len(matches) > 1:
        raise ValueError(f'More than one channel "{label}" found for {asset}.')

    channel = dict(matches[0])

    if as_of:
        real_end = channel.get("end_date")
        if real_end is None or real_end > as_of:
            channel["end_date"] = as_of

    return channel


def select_channel_rows(history, channel):
    start = channel.get("start_date")
    end = channel.get("end_date")
    rows = [
        r for r in history
        if r["date"] >= start and (end is None or r["date"] <= end)
    ]
    if not rows:
        raise ValueError("No market data inside selected channel.")
    return rows


def build_swings(rows):
    if len(rows) < 2:
        return []

    swings = []
    current = None

    for i in range(1, len(rows)):
        prev = rows[i - 1]
        row = rows[i]

        if row["close"] > prev["close"]:
            direction = "UP"
        elif row["close"] < prev["close"]:
            direction = "DOWN"
        else:
            continue

        if current is None or current["direction"] != direction:
            if current is not None:
                swings.append(current)
            current = {
                "direction": direction,
                "start_date": prev["date"],
                "end_date": row["date"],
                "start_close": prev["close"],
                "end_close": row["close"],
            }
        else:
            current["end_date"] = row["date"]
            current["end_close"] = row["close"]

    if current is not None:
        swings.append(current)

    for s in swings:
        s["amplitude_pct"] = (s["end_close"] / s["start_close"] - 1.0) * 100.0

    return swings


def intraday_range_pct(row):
    if row["open"] == 0:
        return None
    return (row["high"] - row["low"]) / row["open"] * 100.0


def volatility_budget(rows):
    ranges = [intraday_range_pct(r) for r in rows]
    ranges = [v for v in ranges if v is not None]
    if not ranges:
        return None, 0

    median_range = statistics.median(ranges)

    # Provisional heuristic only. Backtesting should replace these.
    if median_range < 10.0:
        adjustment = -2
    elif median_range < 20.0:
        adjustment = 0
    elif median_range < 30.0:
        adjustment = 2
    else:
        adjustment = 4

    return median_range, adjustment


def estimate(rows, target=DEFAULT_TRADES):
    swings = build_swings(rows)
    qualifying = [
        s for s in swings
        if abs(s["amplitude_pct"]) >= MIN_SWING_PCT
    ]

    median_range, adjustment = volatility_budget(rows)
    expected_total = max(2, target + adjustment)
    completed = len(qualifying)
    remaining = max(0, expected_total - completed)

    return {
        "median_range_pct": median_range,
        "volatility_adjustment": adjustment,
        "expected_total": expected_total,
        "completed": completed,
        "remaining": remaining,
        "buys_remaining": (remaining + 1) // 2,
        "sells_remaining": remaining // 2,
        "qualifying_swings": qualifying,
    }
    

def format_report(asset, quote, channel, rows, result):
    label = channel.get("label") or "(unlabelled)"
    end = channel.get("end_date") or rows[-1]["date"]

    lines = [
        f"{asset}/{quote}",
        f"Channel:                 {label}",
        f"Period:                  {channel['start_date']} -> {end}",
        f"Latest data:             {rows[-1]['date']}",
        "",
        "ESTIMATED TRADES LEFT",
        "---------------------",
        f"Minimum swing counted:   {MIN_SWING_PCT:.0f}%",
        f"Default opportunity set: {DEFAULT_TRADES}",
        "Median channel range:   " + (
            f"{result['median_range_pct']:.1f}%"
            if result["median_range_pct"] is not None else "n/a"
        ),
        f"Volatility adjustment:   {result['volatility_adjustment']:+d}",
        f"Estimated total:         {result['expected_total']}",
        f"Completed >=20% legs:    {result['completed']}",
        "",
        f"ESTIMATED LEFT:          {result['remaining']}",
        f"Approx buys left:        {result['buys_remaining']}",
        f"Approx sells left:       {result['sells_remaining']}",
    ]

    if result["qualifying_swings"]:
        lines += ["", "QUALIFYING COMPLETED SWINGS", "---------------------------"]
        for s in result["qualifying_swings"]:
            lines.append(
                f"{s['direction']:<4} {s['start_date']} -> {s['end_date']} "
                f"{s['amplitude_pct']:+.1f}%"
            )

    lines += [
        "",
        "Note: experimental heuristic only. "
        "This estimate needs historical backtesting/training.",
    ]

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("asset")
    ap.add_argument("--channel", default="ACTIVE")
    ap.add_argument("--date", metavar="YYYY-MM-DD")
    ap.add_argument("--stream", action="store_true")
    ap.add_argument("--target", type=int, default=DEFAULT_TRADES,
        help="Target number of trade opportunities for the channel (default: 6)",
    )
    
    args = ap.parse_args()

    asset = args.asset.upper()

    try:
        if args.date:
            date.fromisoformat(args.date)

        config = load_config()
        quote = reference_currency(config)
        history = load_history(config, asset, quote, cutoff=args.date)
        channel = find_channel(asset, args.channel, as_of=args.date)
        rows = select_channel_rows(history, channel)

        result = estimate(rows, target=args.target)
        report = format_report(asset, quote, channel, rows, result)

        if args.stream:
            topic = config.get(
                "estimatetrades",
                "topic",
                fallback=DEFAULT_TOPIC,
            )
            lan.stream(
                report,
                config=config,
                topic=topic,
            )
        else:
            print(report)

    except (
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        statistics.StatisticsError,
        RuntimeError,
    ) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
