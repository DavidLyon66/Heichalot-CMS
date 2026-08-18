#!/usr/bin/env python3
"""
channelvolatility.py

Report price volatility for a named trading channel.

Typical use:

    python3 channelvolatility.py MMT "Current Channel"

The channel is looked up in:

    data/tradingchannels.json

The corresponding daily OHLCV history is loaded from:

    data/<ASSET>_<REFERENCE> .json

For example:

    data/MMT_USDT.json

The channel itself supplies the date range, so the operator does not
need to enter start/end dates again.

If the channel has no end_date, it is considered active and the report
runs from its start_date through the latest available daily market row.


Reports
-------

The first report is called:

    Default

It can be selected explicitly:

    python3 channelvolatility.py MMT "Current Channel" --report Default

or:

    python3 channelvolatility.py MMT "Current Channel" --option Default

At present Default is the only report.  The --report/--option interface
exists so other volatility reports can be added later without changing
the basic command structure.


Default report
--------------

The Default report shows:

    - daily close-to-close percentage changes
    - daily high-low trading ranges
    - a short summary of the channel volatility

Close-to-close:

    ((today_close / previous_close) - 1) * 100

The previous close is taken from the market history immediately before
the current day.  This means the first day of a channel can still have
a close-to-close calculation if the preceding market day is available.

Intraday high-low range:

    ((high - low) / open) * 100

This is the same simple definition used in the exploratory MMT report
that motivated this utility.

The report is descriptive only.  It does not decide whether volatility
is good, bad, predictive, or tradeable.
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


def load_config():
    """Load config.ini if present."""
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def get_reference_currency(config):
    """
    Find the configured reference currency.

    This accepts the [market-data] layout used by collecthistory.py,
    with a USDT fallback.
    """
    return config.get(
        "market-data",
        "reference_currency",
        fallback=DEFAULT_REFERENCE_CURRENCY,
    ).upper()


def get_data_dir(config):
    """Return the configured data directory."""
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
    """Load a JSON document."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def find_channel(asset, label=None):
    """
    Find a channel for an asset.

    If label is omitted, blank, or ACTIVE, return the current
    open channel (the channel whose end_date is None).

    Otherwise find the historical channel by label.

    Comparisons are case-insensitive.
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
            f'More than one channel labelled "{label}" '
            f"exists for {asset}."
        )

    return matches[0]
   

def history_path(data_dir, asset, reference_currency):
    """Return data/MMT_USDT.json style path."""
    return data_dir / (
        f"{asset.upper()}_{reference_currency.upper()}.json"
    )


def load_history(path):
    """Load and minimally validate OHLCV history."""
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
        raise ValueError(
            f"No usable OHLC rows found in {path}."
        )

    return usable


def select_channel_rows(history, channel):
    """
    Select rows inside the channel, inclusive.

    For an active channel, use all available rows from start_date onward.
    """
    start_date = channel.get("start_date")
    end_date = channel.get("end_date")

    if not start_date:
        raise ValueError(
            "Channel does not contain start_date."
        )

    selected = [
        row
        for row in history
        if row["date"] >= start_date
        and (
            end_date is None
            or row["date"] <= end_date
        )
    ]

    if not selected:
        raise ValueError(
            "No market data falls inside this channel."
        )

    return selected


def previous_close_map(history):
    """
    Map each date to the immediately preceding stored close.

    Daily crypto data normally has no gaps, but using the actual prior
    stored row is more robust than manufacturing calendar dates.
    """
    result = {}
    previous = None

    for row in history:
        result[row["date"]] = (
            previous["close"]
            if previous is not None
            else None
        )
        previous = row

    return result


def calculate_default(history, channel_rows):
    """
    Calculate the Default volatility report.

    intraday_range_pct:
        (high - low) / open * 100

    close_change_pct:
        (close / previous_close - 1) * 100
    """
    previous_closes = previous_close_map(history)
    results = []

    for row in channel_rows:
        open_price = row["open"]

        if open_price == 0:
            intraday = None
        else:
            intraday = (
                (row["high"] - row["low"])
                / open_price
                * 100.0
            )

        previous_close = previous_closes.get(
            row["date"]
        )

        if previous_close in (None, 0):
            close_change = None
        else:
            close_change = (
                (row["close"] / previous_close)
                - 1.0
            ) * 100.0

        results.append({
            **row,
            "close_change_pct": close_change,
            "intraday_range_pct": intraday,
        })

    return results


def format_signed(value):
    """Format a signed percentage."""
    if value is None:
        return "   n/a"

    return f"{value:+6.1f}%"


def format_unsigned(value):
    """Format an unsigned percentage."""
    if value is None:
        return "  n/a"

    return f"{value:5.1f}%"


def pct_values(rows, field):
    """Return non-null percentage values from result rows."""
    return [
        row[field]
        for row in rows
        if row.get(field) is not None
    ]


def print_default_report(asset, reference, channel, rows):
    """Print the human-readable Default report."""
    label = channel.get("label", "(unlabelled)")
    start_date = channel.get("start_date")
    end_date = channel.get("end_date")

    effective_end = rows[-1]["date"]
    status = "ACTIVE" if end_date is None else "HISTORICAL"

    print(f"{asset}/{reference}")
    print(f"Channel: {label}")
    print(
        f"Period:  {start_date} -> "
        f"{end_date or effective_end}  [{status}]"
    )

    description = channel.get("description")
    if description:
        print(f"Note:    {description}")

    print()

    print("CLOSE-TO-CLOSE MOVES")
    print("--------------------")

    for row in rows:
        print(
            f"{row['date']}  "
            f"{format_signed(row['close_change_pct'])}"
        )

    print()
    print("DAILY HIGH-LOW RANGES")
    print("---------------------")

    for row in rows:
        print(
            f"{row['date']}  "
            f"{format_unsigned(row['intraday_range_pct'])}"
        )

    ranges = pct_values(
        rows,
        "intraday_range_pct",
    )

    changes = pct_values(
        rows,
        "close_change_pct",
    )

    print()
    print("SUMMARY")
    print("-------")
    print(f"Daily observations:       {len(rows)}")

    if ranges:
        print(
            f"Average intraday range:   "
            f"{statistics.mean(ranges):.1f}%"
        )
        print(
            f"Median intraday range:    "
            f"{statistics.median(ranges):.1f}%"
        )
        print(
            f"Maximum intraday range:   "
            f"{max(ranges):.1f}%"
        )

        ten_plus = sum(
            value >= 10.0
            for value in ranges
        )

        twenty_plus = sum(
            value >= 20.0
            for value in ranges
        )

        print(
            f"Days >= 10% range:        "
            f"{ten_plus}/{len(ranges)}"
        )
        print(
            f"Days >= 20% range:        "
            f"{twenty_plus}/{len(ranges)}"
        )

    if changes:
        absolute_changes = [
            abs(value)
            for value in changes
        ]

        print(
            f"Average abs close move:   "
            f"{statistics.mean(absolute_changes):.1f}%"
        )
        print(
            f"Maximum abs close move:   "
            f"{max(absolute_changes):.1f}%"
        )

    print()

    if ranges:
        average = statistics.mean(ranges)

        if average >= 20:
            regime = "very high"
        elif average >= 10:
            regime = "elevated"
        elif average >= 5:
            regime = "moderate"
        else:
            regime = "relatively low"

        print(
            "Default observation: "
            f"intraday volatility is {regime} "
            f"over this marked channel "
            f"(average range {average:.1f}%)."
        )


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Report volatility for a named trading channel."
        )
    )

    parser.add_argument(
        "asset",
        help="Asset symbol, for example MMT or DGB",
    )

    parser.add_argument(
        "channel_label",
        nargs="?",
        default="ACTIVE",
        help=(
            "Channel label from tradingchannels.json. "
            "Omit it, or use ACTIVE, for the current open channel."
        ),
    )
    
    parser.add_argument(
        "--report",
        "--option",
        dest="report",
        default="Default",
        help=(
            "Report to run (currently: Default)"
        ),
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    asset = args.asset.upper()

    report = args.report.strip().casefold()

    if report != "default":
        parser.error(
            f"Unknown report '{args.report}'. "
            "Currently available: Default."
        )

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

        channel_rows = select_channel_rows(
            history,
            channel,
        )

        results = calculate_default(
            history,
            channel_rows,
        )

        print_default_report(
            asset=asset,
            reference=reference,
            channel=channel,
            rows=results,
        )

    except (
        FileNotFoundError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(
            f"Error: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
