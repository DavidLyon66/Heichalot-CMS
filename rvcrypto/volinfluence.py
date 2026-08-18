#!/usr/bin/env python3
"""
volinfluence.py

Estimate how strongly trading volume has changed around a recorded
trading channel.

Typical use:

    python3 volinfluence.py MMT

or:

    python3 volinfluence.py MMT ACTIVE

or for a historical named channel:

    python3 volinfluence.py MMT "July Triangle"

By default the tool compares the channel with the 30 completed daily
rows immediately before the channel started.

Override that window with:

    python3 volinfluence.py MMT --before -60

The --before value is deliberately negative because it represents a
relative period before channel start.

Examples:

    --before -30
    --before -60
    --before -90


Purpose
-------

The question is simple:

    "Did a materially larger amount of trading volume arrive when this
     channel started, compared with the period immediately before it?"

This tool is descriptive.  It does not claim to know who supplied the
capital or why volume changed.


Measurements
------------

PRE-CHANNEL

    The previous N market days before channel start.

CHANNEL

    All daily market rows from channel start through channel end,
    or through the latest available row if the channel is active.

The report calculates:

    total volume
    average daily volume
    median daily volume

Because the pre-channel and channel periods can contain different
numbers of days, the influence assessment is based primarily on daily
volume ratios rather than raw totals.


Influence
---------

Two ratios are calculated:

    average ratio =
        channel average volume / pre-channel average volume

    median ratio =
        channel median volume / pre-channel median volume

The provisional influence ratio is the mean of those two ratios.

This is intentionally transparent and easy to replace later.

Initial qualitative levels:

    ratio < 1.25       LITTLE
    ratio < 2.00       LIGHT
    ratio < 4.00       MEDIUM
    ratio >= 4.00      HIGH

The report therefore ends with one of:

    LITTLE VOLUME INFLUENCE
    LIGHT VOLUME INFLUENCE
    MEDIUM VOLUME INFLUENCE
    HIGH VOLUME INFLUENCE

These thresholds are experimental.  Later versions can calibrate them
against historical spike markers and channel outcomes.


Optional recent comparison
--------------------------

The report also compares the most recent N channel days with the
pre-channel baseline.

Default:

    --recent 3

This helps distinguish:

    a channel that started with heavy volume but has since gone quiet

from:

    a channel where elevated volume is still active.


Scope
-----

This tool does not:

    identify traders or market-makers
    infer source of capital
    predict direction
    detect spikes
    calculate moving averages
    make trading decisions
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
DEFAULT_BEFORE_DAYS = -30
DEFAULT_RECENT_DAYS = 3


def load_config():
    """Load config.ini if present."""
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def get_reference_currency(config):
    """Return configured reference currency."""
    return config.get(
        "market-data",
        "reference_currency",
        fallback=DEFAULT_REFERENCE_CURRENCY,
    ).upper()


def get_data_dir(config):
    """Return configured data directory."""
    value = config.get(
        "storage",
        "data_dir",
        fallback="data",
    )

    path = Path(value)

    if not path.is_absolute():
        path = BASE_DIR / path

    return path


def load_json(path):
    """Load JSON document."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def find_channel(asset, label=None):
    """
    Find active or named channel.

    Blank / omitted / ACTIVE means the current open channel.
    """
    if not CHANNEL_FILE.exists():
        raise FileNotFoundError(
            f"Channel file not found: {CHANNEL_FILE}"
        )

    document = load_json(CHANNEL_FILE)
    channels = document.get("channels", [])

    asset_key = asset.casefold()

    asset_matches = [
        channel
        for channel in channels
        if str(
            channel.get("asset", "")
        ).casefold() == asset_key
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
            raise ValueError(
                f"No active channel found for {asset}."
            )

        if len(matches) > 1:
            raise ValueError(
                f"More than one active channel exists for {asset}."
            )

        return matches[0]

    label_key = str(label).strip().casefold()

    matches = [
        channel
        for channel in asset_matches
        if str(
            channel.get("label", "")
        ).casefold() == label_key
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
    """Return data/MMT_USDT.json style path."""
    return data_dir / (
        f"{asset.upper()}_{reference_currency.upper()}.json"
    )


def load_history(path):
    """Load date + volume history."""
    if not path.exists():
        raise FileNotFoundError(
            f"Market history not found: {path}"
        )

    document = load_json(path)
    rows = document.get("data")

    if not isinstance(rows, list):
        raise ValueError(
            f"{path} does not contain a valid 'data' list."
        )

    usable = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        try:
            usable.append({
                "date": str(row["date"]),
                "volume": float(row["volume"]),
            })
        except (KeyError, TypeError, ValueError):
            continue

    usable.sort(key=lambda row: row["date"])

    if not usable:
        raise ValueError(
            f"No usable volume rows found in {path}."
        )

    return usable


def split_periods(history, channel, before_days):
    """
    Split history into pre-channel and channel rows.

    before_days must be negative.

    Example:

        -30

    selects up to 30 stored daily rows immediately before start_date.
    """
    if before_days >= 0:
        raise ValueError(
            "--before must be negative, for example -30."
        )

    start_date = channel.get("start_date")
    end_date = channel.get("end_date")

    if not start_date:
        raise ValueError(
            "Channel does not contain start_date."
        )

    before_candidates = [
        row
        for row in history
        if row["date"] < start_date
    ]

    pre_rows = before_candidates[
        before_days:
    ]

    channel_rows = [
        row
        for row in history
        if row["date"] >= start_date
        and (
            end_date is None
            or row["date"] <= end_date
        )
    ]

    if not pre_rows:
        raise ValueError(
            "No pre-channel volume data is available."
        )

    if not channel_rows:
        raise ValueError(
            "No market data falls inside this channel."
        )

    return pre_rows, channel_rows


def volume_stats(rows):
    """Return total/mean/median volume statistics."""
    volumes = [
        row["volume"]
        for row in rows
    ]

    return {
        "days": len(volumes),
        "total": sum(volumes),
        "average": statistics.mean(volumes),
        "median": statistics.median(volumes),
        "first_date": rows[0]["date"],
        "last_date": rows[-1]["date"],
    }


def safe_ratio(numerator, denominator):
    """Return ratio or None where denominator is zero."""
    if denominator == 0:
        return None

    return numerator / denominator


def influence_stats(pre, channel):
    """
    Compare pre-channel and channel daily volume levels.
    """
    average_ratio = safe_ratio(
        channel["average"],
        pre["average"],
    )

    median_ratio = safe_ratio(
        channel["median"],
        pre["median"],
    )

    available = [
        value
        for value in (
            average_ratio,
            median_ratio,
        )
        if value is not None
    ]

    if available:
        influence_ratio = statistics.mean(
            available
        )
    else:
        influence_ratio = None

    return {
        "average_ratio": average_ratio,
        "median_ratio": median_ratio,
        "influence_ratio": influence_ratio,
    }


def classify_influence(ratio):
    """Convert ratio to qualitative volume influence."""
    if ratio is None:
        return "UNKNOWN VOLUME INFLUENCE"

    if ratio < 1.25:
        return "LITTLE VOLUME INFLUENCE"

    if ratio < 2.00:
        return "LIGHT VOLUME INFLUENCE"

    if ratio < 4.00:
        return "MEDIUM VOLUME INFLUENCE"

    return "HIGH VOLUME INFLUENCE"


def compact_number(value):
    """Format large volumes compactly."""
    absolute = abs(value)

    if absolute >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"

    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"

    if absolute >= 1_000:
        return f"{value / 1_000:.2f}K"

    return f"{value:.2f}"


def fmt_ratio(value):
    """Format ratio."""
    if value is None:
        return "n/a"

    return f"{value:.2f}x"


def print_period(title, stats):
    """Print one period's volume statistics."""
    print(title)
    print("-" * len(title))
    print(
        f"Period:                  "
        f"{stats['first_date']} -> {stats['last_date']}"
    )
    print(
        f"Days:                    "
        f"{stats['days']}"
    )
    print(
        f"Total volume:            "
        f"{compact_number(stats['total'])}"
    )
    print(
        f"Average daily volume:    "
        f"{compact_number(stats['average'])}"
    )
    print(
        f"Median daily volume:     "
        f"{compact_number(stats['median'])}"
    )
    print()


def print_report(
    asset,
    reference,
    channel,
    pre_stats,
    channel_stats,
    influence,
    recent_stats,
    recent_influence,
    before_days,
    recent_days,
):
    """Print Default volume influence report."""
    label = channel.get(
        "label",
        "(unlabelled)",
    )

    status = (
        "ACTIVE"
        if channel.get("end_date") is None
        else "HISTORICAL"
    )

    print(f"{asset}/{reference}")
    print(f"Channel: {label}")
    print(
        f"Channel status: {status}"
    )
    print(
        f"Pre-channel comparison: {before_days} days"
    )
    print()

    print_period(
        "PRE-CHANNEL",
        pre_stats,
    )

    print_period(
        "CHANNEL",
        channel_stats,
    )

    print("CHANNEL / PRE-CHANNEL")
    print("---------------------")
    print(
        f"Average daily ratio:     "
        f"{fmt_ratio(influence['average_ratio'])}"
    )
    print(
        f"Median daily ratio:      "
        f"{fmt_ratio(influence['median_ratio'])}"
    )
    print(
        f"Influence ratio:         "
        f"{fmt_ratio(influence['influence_ratio'])}"
    )
    print()

    if recent_stats is not None:
        print(f"RECENT {recent_days} CHANNEL DAYS")
        print("-" * (20 + len(str(recent_days))))
        print(
            f"Period:                  "
            f"{recent_stats['first_date']} -> "
            f"{recent_stats['last_date']}"
        )
        print(
            f"Average daily volume:    "
            f"{compact_number(recent_stats['average'])}"
        )
        print(
            f"Median daily volume:     "
            f"{compact_number(recent_stats['median'])}"
        )
        print(
            f"Average vs pre-channel:  "
            f"{fmt_ratio(recent_influence['average_ratio'])}"
        )
        print(
            f"Median vs pre-channel:   "
            f"{fmt_ratio(recent_influence['median_ratio'])}"
        )
        print()

    print("ASSESSMENT")
    print("----------")
    print(
        classify_influence(
            influence["influence_ratio"]
        )
    )
    print()
    print(
        "Note: influence describes how much daily trading volume "
        "has increased relative to the pre-channel baseline. "
        "It does not identify the source of that volume or predict direction."
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Estimate trading-volume influence around a channel."
        )
    )

    parser.add_argument(
        "asset",
        help="Asset symbol, e.g. MMT or DGB",
    )

    parser.add_argument(
        "channel_label",
        nargs="?",
        default="ACTIVE",
        help=(
            "Channel label. Omit it, or use ACTIVE, "
            "for the current open channel."
        ),
    )

    parser.add_argument(
        "--before",
        type=int,
        default=DEFAULT_BEFORE_DAYS,
        help=(
            "Pre-channel comparison window as a negative day count "
            f"(default: {DEFAULT_BEFORE_DAYS})."
        ),
    )

    parser.add_argument(
        "--recent",
        type=int,
        default=DEFAULT_RECENT_DAYS,
        help=(
            "Recent channel days to compare with pre-channel baseline "
            f"(default: {DEFAULT_RECENT_DAYS})."
        ),
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.before >= 0:
        parser.error(
            "--before must be negative, for example -30."
        )

    if args.recent < 1:
        parser.error(
            "--recent must be at least 1."
        )

    asset = args.asset.upper()

    try:
        config = load_config()

        reference = get_reference_currency(
            config
        )

        data_dir = get_data_dir(
            config
        )

        channel = find_channel(
            asset,
            args.channel_label,
        )

        history = load_history(
            history_path(
                data_dir,
                asset,
                reference,
            )
        )

        pre_rows, channel_rows = split_periods(
            history,
            channel,
            args.before,
        )

        pre_stats = volume_stats(
            pre_rows
        )

        channel_stats = volume_stats(
            channel_rows
        )

        influence = influence_stats(
            pre_stats,
            channel_stats,
        )

        recent_rows = channel_rows[
            -min(args.recent, len(channel_rows)):
        ]

        recent_stats = volume_stats(
            recent_rows
        )

        recent_influence = influence_stats(
            pre_stats,
            recent_stats,
        )

        print_report(
            asset=asset,
            reference=reference,
            channel=channel,
            pre_stats=pre_stats,
            channel_stats=channel_stats,
            influence=influence,
            recent_stats=recent_stats,
            recent_influence=recent_influence,
            before_days=args.before,
            recent_days=len(recent_rows),
        )

    except (
        FileNotFoundError,
        ValueError,
        json.JSONDecodeError,
        statistics.StatisticsError,
    ) as exc:
        print(
            f"Error: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
