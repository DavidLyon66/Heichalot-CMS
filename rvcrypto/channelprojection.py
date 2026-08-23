#!/usr/bin/env python3
"""
channelprojection.py

Produce a simple conditional projection report for a recorded trading
channel.

Typical use:

    python3 channelprojection.py MMT

or:

    python3 channelprojection.py MMT ACTIVE

or for a named historical channel:

    python3 channelprojection.py MMT "July Triangle"


Purpose
-------

This tool does NOT attempt to predict whether the next day will be UP
or DOWN.

Instead it calculates:

    1. the channel's rolling median centreline
    2. a simple next-day centre projection
    3. a conditional UP scenario
    4. a conditional DOWN scenario
    5. a volatility-compression ratio

The idea is to answer:

    "If tomorrow behaves like a typical UP day in this channel,
     what low/high range would be plausible?"

and separately:

    "If tomorrow behaves like a typical DOWN day in this channel,
     what low/high range would be plausible?"

The result is therefore a descriptive conditional projection based on
the behaviour already observed inside the selected channel.


Channel selection
-----------------

These are equivalent:

    python3 channelprojection.py MMT
    python3 channelprojection.py MMT ACTIVE

Both use the current channel whose end_date is null.

Historical channels are selected by label.


Centreline
----------

For each day:

    midpoint = (high + low) / 2

A rolling median is then applied over the midpoint series.

Default:

    --median-window 3

The projected next-day centre is:

    latest rolling median centre
        +
    median daily change in the rolling median centre

This is intentionally conservative and simple.


Conditional UP/DOWN scenarios
-----------------------------

Each channel day is classified using close-to-close direction:

    UP
        close > previous close

    DOWN
        close < previous close

    FLAT
        close == previous close

For each UP day the tool calculates:

    low excursion:
        (low / previous_close - 1) * 100

    high excursion:
        (high / previous_close - 1) * 100

The median low/high excursions across all UP days form the UP scenario.

The same calculation is performed for DOWN days.

The next scenario prices are based on the latest close:

    projected_low =
        latest_close * (1 + median_low_excursion / 100)

    projected_high =
        latest_close * (1 + median_high_excursion / 100)


Volatility compression
----------------------

The normal channel range is represented by the median intraday range:

    (high - low) / open * 100

The recent range is the median of the most recent N channel rows.

Default:

    --recent-window 3

The volatility ratio is:

    recent_median_range / channel_median_range

Examples:

    1.00x
        recent volatility is roughly normal for the channel

    0.50x
        recent volatility is about half the channel median

    1.50x
        recent volatility is about 50% above the channel median


Scope
-----

This utility is experimental.

It does not:

    produce a buy/sell instruction
    decide the next direction
    estimate probability of UP versus DOWN
    use moving averages
    use remote-viewing data
    use on-chain data
    calculate channel geometry

Those can remain separate tools and later feed into the same report if
they prove useful.
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
DEFAULT_MEDIAN_WINDOW = 3
DEFAULT_RECENT_WINDOW = 3


def load_config():
    """Load config.ini if present."""
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def get_reference_currency(config):
    """Return configured local/reference currency."""
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
    """Load JSON."""
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
                f"No active channel found for {asset}.\n" \
                f"Please add a channel with addchannel.py"
            )

        if len(matches) > 1:
            raise ValueError(
                f"More than one active channel exists for {asset}.\n" \
                 "Please remove one from data/tradingchannels.json"
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
            f"No usable OHLCV rows found in {path}."
        )

    return usable


def select_channel_rows(history, channel):
    """Select history rows inside channel, inclusive."""
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
    """Map date -> immediately preceding close."""
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


def rolling_median(values, window):
    """
    Return rolling median values.

    For the first rows, use however many values are available.
    """
    result = []

    for index in range(len(values)):
        start = max(
            0,
            index - window + 1,
        )

        result.append(
            statistics.median(
                values[start:index + 1]
            )
        )

    return result


def calculate_midpoint_series(rows, median_window):
    """Build raw midpoint and rolling median centreline."""
    midpoints = [
        (row["high"] + row["low"]) / 2.0
        for row in rows
    ]

    centres = rolling_median(
        midpoints,
        median_window,
    )

    return midpoints, centres


def calculate_centre_projection(centres):
    """
    Project next centre using median centre delta.

    If there is only one centre point, keep it unchanged.
    """
    latest = centres[-1]

    if len(centres) < 2:
        return latest, 0.0

    deltas = [
        centres[index] - centres[index - 1]
        for index in range(1, len(centres))
    ]

    median_delta = statistics.median(
        deltas
    )

    projected = latest + median_delta

    return projected, median_delta


def classify_direction(close, previous_close):
    """Return UP, DOWN or FLAT."""
    if previous_close is None:
        return "FLAT"

    if close > previous_close:
        return "UP"

    if close < previous_close:
        return "DOWN"

    return "FLAT"


def calculate_excursions(history, channel_rows):
    """
    Calculate previous-close-relative low/high excursions
    for UP and DOWN days.
    """
    previous_closes = previous_close_map(
        history
    )

    buckets = {
        "UP": [],
        "DOWN": [],
    }

    for row in channel_rows:
        previous_close = previous_closes.get(
            row["date"]
        )

        if previous_close in (None, 0):
            continue

        direction = classify_direction(
            row["close"],
            previous_close,
        )

        if direction not in buckets:
            continue

        low_excursion = (
            row["low"] / previous_close
            - 1.0
        ) * 100.0

        high_excursion = (
            row["high"] / previous_close
            - 1.0
        ) * 100.0

        buckets[direction].append({
            "date": row["date"],
            "low_excursion_pct": low_excursion,
            "high_excursion_pct": high_excursion,
        })

    return buckets


def median_scenario(rows):
    """Return median low/high excursion for one direction."""
    if not rows:
        return None

    return {
        "count": len(rows),
        "median_low_excursion_pct":
            statistics.median(
                row["low_excursion_pct"]
                for row in rows
            ),
        "median_high_excursion_pct":
            statistics.median(
                row["high_excursion_pct"]
                for row in rows
            ),
    }


def intraday_range_pct(row):
    """Return high-low range as percentage of open."""
    if row["open"] == 0:
        return None

    return (
        (row["high"] - row["low"])
        / row["open"]
        * 100.0
    )


def calculate_volatility(channel_rows, recent_window):
    """
    Calculate channel median range, recent median range
    and their ratio.
    """
    ranges = [
        intraday_range_pct(row)
        for row in channel_rows
    ]

    ranges = [
        value
        for value in ranges
        if value is not None
    ]

    if not ranges:
        return {
            "channel_median_range_pct": None,
            "recent_median_range_pct": None,
            "volatility_ratio": None,
        }

    channel_median = statistics.median(
        ranges
    )

    recent_values = ranges[
        -min(recent_window, len(ranges)):
    ]

    recent_median = statistics.median(
        recent_values
    )

    if channel_median == 0:
        ratio = None
    else:
        ratio = (
            recent_median / channel_median
        )

    return {
        "channel_median_range_pct":
            channel_median,
        "recent_median_range_pct":
            recent_median,
        "volatility_ratio":
            ratio,
    }


def apply_scenario(latest_close, scenario):
    """Convert percentage excursions into projected prices."""
    if scenario is None:
        return None

    low_pct = scenario[
        "median_low_excursion_pct"
    ]

    high_pct = scenario[
        "median_high_excursion_pct"
    ]

    return {
        **scenario,
        "projected_low":
            latest_close
            * (1.0 + low_pct / 100.0),
        "projected_high":
            latest_close
            * (1.0 + high_pct / 100.0),
    }


def fmt_price(value):
    """Format price with enough precision for low-valued assets."""
    if value is None:
        return "n/a"

    if abs(value) >= 100:
        return f"{value:.2f}"

    if abs(value) >= 1:
        return f"{value:.4f}"

    return f"{value:.6f}"


def fmt_pct(value, signed=False):
    """Format percentage."""
    if value is None:
        return "n/a"

    if signed:
        return f"{value:+.1f}%"

    return f"{value:.1f}%"


def fmt_ratio(value):
    """Format x-ratio."""
    if value is None:
        return "n/a"

    return f"{value:.2f}x"


def describe_volatility_ratio(value):
    """Return a simple descriptive label."""
    if value is None:
        return "unknown"

    if value < 0.50:
        return "strong compression"

    if value < 0.75:
        return "compression"

    if value < 1.25:
        return "near channel normal"

    if value < 1.75:
        return "elevated"

    return "strongly elevated"


def print_scenario(title, scenario):
    """Print one conditional scenario."""
    print(title)
    print("-" * len(title))

    if scenario is None:
        print(
            "Not enough directional observations "
            "inside this channel."
        )
        print()
        return

    print(
        f"Observations:              "
        f"{scenario['count']}"
    )
    print(
        f"Median low excursion:      "
        f"{fmt_pct(scenario['median_low_excursion_pct'], signed=True)}"
    )
    print(
        f"Median high excursion:     "
        f"{fmt_pct(scenario['median_high_excursion_pct'], signed=True)}"
    )
    print(
        f"Possible low / buy area:   "
        f"{fmt_price(scenario['projected_low'])}"
    )
    print(
        f"Possible high / sell area: "
        f"{fmt_price(scenario['projected_high'])}"
    )
    print()


def print_report(
    asset,
    reference,
    channel,
    channel_rows,
    centres,
    projected_centre,
    median_centre_delta,
    up_scenario,
    down_scenario,
    volatility,
    median_window,
    recent_window,
):
    """Print the Default conditional projection report."""
    label = channel.get(
        "label",
        "(unlabelled)",
    )

    end_date = channel.get(
        "end_date"
    )

    effective_end = channel_rows[-1]["date"]
    latest_close = channel_rows[-1]["close"]

    print(f"{asset}/{reference}")
    print(f"Channel: {label}")
    print(
        f"Period:  {channel['start_date']} -> "
        f"{end_date or effective_end}  "
        f"[{'ACTIVE' if end_date is None else 'HISTORICAL'}]"
    )
    print()

    print("CURRENT")
    print("-------")
    print(
        f"Latest close:              "
        f"{fmt_price(latest_close)}"
    )
    print(
        f"Latest median centre:      "
        f"{fmt_price(centres[-1])}"
    )
    print(
        f"Projected next centre:     "
        f"{fmt_price(projected_centre)}"
    )
    print(
        f"Median centre delta:       "
        f"{fmt_price(median_centre_delta)}"
    )
    print(
        f"Centre median window:      "
        f"{median_window} days"
    )
    print()

    print("VOLATILITY")
    print("----------")
    print(
        f"Channel median range:      "
        f"{fmt_pct(volatility['channel_median_range_pct'])}"
    )
    print(
        f"Recent median range:       "
        f"{fmt_pct(volatility['recent_median_range_pct'])}"
    )
    print(
        f"Recent/channel ratio:      "
        f"{fmt_ratio(volatility['volatility_ratio'])}"
    )
    print(
        f"Recent window:             "
        f"{recent_window} days"
    )
    print(
        f"Condition:                 "
        f"{describe_volatility_ratio(volatility['volatility_ratio'])}"
    )
    print()

    print_scenario(
        "IF NEXT DAY IS UP",
        up_scenario,
    )

    print_scenario(
        "IF NEXT DAY IS DOWN",
        down_scenario,
    )

    print(
        "Note: these are conditional historical projections "
        "from the selected channel, not predictions of direction."
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Project conditional next-day channel ranges."
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
        "--median-window",
        type=int,
        default=DEFAULT_MEDIAN_WINDOW,
        help=(
            "Rolling median window used for the channel centreline "
            f"(default: {DEFAULT_MEDIAN_WINDOW})."
        ),
    )

    parser.add_argument(
        "--recent-window",
        type=int,
        default=DEFAULT_RECENT_WINDOW,
        help=(
            "Recent-day window used for volatility comparison "
            f"(default: {DEFAULT_RECENT_WINDOW})."
        ),
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.median_window < 1:
        parser.error(
            "--median-window must be at least 1."
        )

    if args.recent_window < 1:
        parser.error(
            "--recent-window must be at least 1."
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

        channel_rows = select_channel_rows(
            history,
            channel,
        )

        _, centres = calculate_midpoint_series(
            channel_rows,
            args.median_window,
        )

        (
            projected_centre,
            median_centre_delta,
        ) = calculate_centre_projection(
            centres
        )

        excursions = calculate_excursions(
            history,
            channel_rows,
        )

        up_scenario = apply_scenario(
            channel_rows[-1]["close"],
            median_scenario(
                excursions["UP"]
            ),
        )

        down_scenario = apply_scenario(
            channel_rows[-1]["close"],
            median_scenario(
                excursions["DOWN"]
            ),
        )

        volatility = calculate_volatility(
            channel_rows,
            args.recent_window,
        )

        print_report(
            asset=asset,
            reference=reference,
            channel=channel,
            channel_rows=channel_rows,
            centres=centres,
            projected_centre=projected_centre,
            median_centre_delta=median_centre_delta,
            up_scenario=up_scenario,
            down_scenario=down_scenario,
            volatility=volatility,
            median_window=args.median_window,
            recent_window=args.recent_window,
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
