#!/usr/bin/env python3
"""
channelswing.py

Describe day-to-day swing behaviour inside a recorded trading channel.

Typical use:

    python3 channelswing.py MMT
    python3 channelswing.py MMT ACTIVE
    python3 channelswing.py MMT "July Triangle"

The channel date range comes from data/tradingchannels.json and the
market history comes from data/<ASSET>_<REFERENCE>.json.

The default report measures:
    close-to-close move
    intraday high-low range
    close position inside the daily range
    volume relative to a recent rolling average
    daily direction/state
    contiguous up/down swing duration and amplitude

This is deliberately descriptive rather than predictive.
"""

import argparse
import configparser
import json
import statistics
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.ini"
CHANNEL_FILE = BASE_DIR / "data" / "tradingchannels.json"
DEFAULT_REFERENCE_CURRENCY = "USDT"
DEFAULT_VOLUME_WINDOW = 7
DEFAULT_FLAT_THRESHOLD = 0.0


def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def get_reference_currency(config):
    return config.get(
        "market-data",
        "reference_currency",
        fallback=DEFAULT_REFERENCE_CURRENCY,
    ).upper()


def get_data_dir(config):
    value = config.get("storage", "data_dir", fallback="data")
    path = Path(value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def load_json(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def find_channel(asset, label=None):
    if not CHANNEL_FILE.exists():
        raise FileNotFoundError(f"Channel file not found: {CHANNEL_FILE}")

    document = load_json(CHANNEL_FILE)
    channels = document.get("channels", [])
    asset_key = asset.casefold()

    asset_matches = [
        channel
        for channel in channels
        if str(channel.get("asset", "")).casefold() == asset_key
    ]

    active_requested = (
        label is None
        or not str(label).strip()
        or str(label).strip().casefold() == "active"
    )

    if active_requested:
        matches = [
            channel
            for channel in asset_matches
            if channel.get("end_date") is None
        ]
        if not matches:
            raise ValueError(f"No active channel found for {asset}.")
        if len(matches) > 1:
            raise ValueError(
                f"More than one active channel exists for {asset}."
            )
        return matches[0]

    label_key = str(label).strip().casefold()
    matches = [
        channel
        for channel in asset_matches
        if str(channel.get("label", "")).casefold() == label_key
    ]
    if not matches:
        raise ValueError(
            f'No channel labelled "{label}" found for {asset}.'
        )
    if len(matches) > 1:
        raise ValueError(
            f'More than one channel labelled "{label}" exists for {asset}.'
        )
    return matches[0]


def history_path(data_dir, asset, reference_currency):
    return data_dir / f"{asset.upper()}_{reference_currency.upper()}.json"


def load_history(path):
    if not path.exists():
        raise FileNotFoundError(f"Market history not found: {path}")

    document = load_json(path)
    rows = document.get("data")
    if not isinstance(rows, list):
        raise ValueError(f"{path} does not contain a valid 'data' list.")

    usable = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            usable.append({
                "date": str(row["date"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0.0)),
            })
        except (KeyError, TypeError, ValueError):
            continue

    usable.sort(key=lambda row: row["date"])
    if not usable:
        raise ValueError(f"No usable OHLCV rows found in {path}.")
    return usable


def select_channel_rows(history, channel):
    start_date = channel.get("start_date")
    end_date = channel.get("end_date")
    if not start_date:
        raise ValueError("Channel does not contain start_date.")

    selected = [
        row
        for row in history
        if row["date"] >= start_date
        and (end_date is None or row["date"] <= end_date)
    ]
    if not selected:
        raise ValueError("No market data falls inside this channel.")
    return selected


def previous_close_map(history):
    result = {}
    previous = None
    for row in history:
        result[row["date"]] = previous["close"] if previous else None
        previous = row
    return result


def rolling_volume_map(history, window):
    result = {}
    for index, row in enumerate(history):
        start = max(0, index - window)
        preceding = history[start:index]
        result[row["date"]] = (
            statistics.mean(item["volume"] for item in preceding)
            if preceding
            else None
        )
    return result


def classify_state(move_pct, flat_threshold):
    if move_pct is None:
        return "FLAT"
    if move_pct > flat_threshold:
        return "UP"
    if move_pct < -flat_threshold:
        return "DOWN"
    return "FLAT"


def calculate_rows(history, channel_rows, volume_window, flat_threshold):
    previous_closes = previous_close_map(history)
    volume_averages = rolling_volume_map(history, volume_window)
    results = []

    for row in channel_rows:
        previous_close = previous_closes.get(row["date"])
        move_pct = None if previous_close in (None, 0) else (
            (row["close"] / previous_close) - 1.0
        ) * 100.0

        range_pct = None if row["open"] == 0 else (
            (row["high"] - row["low"]) / row["open"] * 100.0
        )

        price_range = row["high"] - row["low"]
        close_position = None if price_range <= 0 else (
            (row["close"] - row["low"]) / price_range * 100.0
        )

        avg_volume = volume_averages.get(row["date"])
        volume_ratio = None if avg_volume in (None, 0) else (
            row["volume"] / avg_volume
        )

        results.append({
            **row,
            "move_pct": move_pct,
            "range_pct": range_pct,
            "close_position_pct": close_position,
            "volume_ratio": volume_ratio,
            "state": classify_state(move_pct, flat_threshold),
        })

    return results


def build_swings(rows):
    swings = []
    current = None

    for index, row in enumerate(rows):
        state = row["state"]

        if state == "FLAT":
            if current:
                swings.append(current)
                current = None
            continue

        if current is None or current["state"] != state:
            if current:
                swings.append(current)

            if index > 0:
                start_price = rows[index - 1]["close"]
            else:
                move = row["move_pct"]
                if move is None or move == -100:
                    start_price = row["open"]
                else:
                    start_price = row["close"] / (1.0 + move / 100.0)

            current = {
                "state": state,
                "start_date": row["date"],
                "end_date": row["date"],
                "days": 1,
                "start_price": start_price,
                "end_price": row["close"],
            }
        else:
            current["end_date"] = row["date"]
            current["days"] += 1
            current["end_price"] = row["close"]

    if current:
        swings.append(current)

    for swing in swings:
        start_price = swing["start_price"]
        swing["amplitude_pct"] = None if start_price in (None, 0) else (
            (swing["end_price"] / start_price) - 1.0
        ) * 100.0

    return swings


def signed(value):
    return "   n/a" if value is None else f"{value:+6.1f}%"


def unsigned(value):
    return "  n/a" if value is None else f"{value:5.1f}%"


def ratio(value):
    return " n/a" if value is None else f"{value:4.1f}x"


def print_report(asset, reference, channel, rows, swings, volume_window):
    label = channel.get("label", "(unlabelled)")
    end_date = channel.get("end_date")
    effective_end = rows[-1]["date"]

    print(f"{asset}/{reference}")
    print(f"Channel: {label}")
    print(
        f"Period:  {channel['start_date']} -> "
        f"{end_date or effective_end}  "
        f"[{'ACTIVE' if end_date is None else 'HISTORICAL'}]"
    )
    print(f"Volume comparison window: {volume_window} preceding days")
    print()

    print("DATE         MOVE    RANGE  CLOSEPOS  VOLxAVG  STATE")
    print("--------------------------------------------------")

    for row in rows:
        print(
            f"{row['date']}  "
            f"{signed(row['move_pct'])}  "
            f"{unsigned(row['range_pct'])}  "
            f"{unsigned(row['close_position_pct'])}  "
            f"{ratio(row['volume_ratio'])}    "
            f"{row['state']}"
        )

    print()
    print("SWINGS")
    print("------")

    if not swings:
        print("No UP/DOWN swings found.")
    else:
        for index, swing in enumerate(swings, start=1):
            print(
                f"{index:>2}. {swing['state']:<4}  "
                f"{swing['start_date']} -> {swing['end_date']}  "
                f"{swing['days']:>2} days  "
                f"{signed(swing['amplitude_pct'])}"
            )

    up_swings = [s for s in swings if s["state"] == "UP" and s["amplitude_pct"] is not None]
    down_swings = [s for s in swings if s["state"] == "DOWN" and s["amplitude_pct"] is not None]

    print()
    print("SUMMARY")
    print("-------")
    print(f"Daily observations:       {len(rows)}")
    print(f"Detected swings:          {len(swings)}")

    if up_swings:
        print(
            f"Average UP duration:       "
            f"{statistics.mean(s['days'] for s in up_swings):.1f} days"
        )
        print(
            f"Average UP amplitude:      "
            f"{statistics.mean(s['amplitude_pct'] for s in up_swings):+.1f}%"
        )

    if down_swings:
        print(
            f"Average DOWN duration:     "
            f"{statistics.mean(s['days'] for s in down_swings):.1f} days"
        )
        print(
            f"Average DOWN amplitude:    "
            f"{statistics.mean(s['amplitude_pct'] for s in down_swings):+.1f}%"
        )

    latest = rows[-1]
    print()
    print(f"Current daily state:       {latest['state']}")
    print(f"Current close position:    {unsigned(latest['close_position_pct'])}")
    print(f"Current volume vs average: {ratio(latest['volume_ratio'])}")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Describe swing behaviour inside a trading channel."
    )
    parser.add_argument("asset", help="Asset symbol, e.g. MMT or DGB")
    parser.add_argument(
        "channel_label",
        nargs="?",
        default="ACTIVE",
        help="Channel label. Omit it, or use ACTIVE, for current open channel.",
    )
    parser.add_argument(
        "--volume-window",
        type=int,
        default=DEFAULT_VOLUME_WINDOW,
        help=f"Preceding days used for average volume (default: {DEFAULT_VOLUME_WINDOW}).",
    )
    parser.add_argument(
        "--flat-threshold",
        type=float,
        default=DEFAULT_FLAT_THRESHOLD,
        help="Absolute close-change percentage treated as FLAT (default: 0).",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.volume_window < 1:
        parser.error("--volume-window must be at least 1.")
    if args.flat_threshold < 0:
        parser.error("--flat-threshold cannot be negative.")

    asset = args.asset.upper()

    try:
        config = load_config()
        reference = get_reference_currency(config)
        data_dir = get_data_dir(config)
        channel = find_channel(asset, args.channel_label)
        history = load_history(history_path(data_dir, asset, reference))
        channel_rows = select_channel_rows(history, channel)
        rows = calculate_rows(
            history,
            channel_rows,
            args.volume_window,
            args.flat_threshold,
        )
        swings = build_swings(rows)
        print_report(asset, reference, channel, rows, swings, args.volume_window)

    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
