#!/usr/bin/env python3
"""
breakdetect.py

Experimental channel-break / regime-change detector for rvcrypto.

Typical use:

    python3 breakdetect.py MMT
    python3 breakdetect.py MMT ACTIVE
    python3 breakdetect.py MMT "July Triangle"

Purpose
-------

This tool asks a different question from turndetect.py.

turndetect.py:
    "Does the current snake look like it may turn inside the channel?"

breakdetect.py:
    "Does the current channel itself look like it may be ending?"

The first version evaluates two competing scenarios:

    UP BREAK / NEXT CHANNEL
    DOWN BREAK / VOLUME WITHDRAWAL

The program does NOT know whether capital is actually being deposited
or withdrawn by particular market participants.

"Volume withdrawal" is shorthand for:
    recent daily volume materially below the channel's own volume regime.

"Next channel" is shorthand for:
    upward regime-change / break possibility.

Possible qualitative outcomes:

    NO BREAK
    UP BREAK POSSIBLE
    UP BREAK STRONG
    DOWN BREAK POSSIBLE
    DOWN BREAK STRONG
    CONFLICTING BREAK PRESSURE

This first scoring model is deliberately transparent and provisional.
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
DEFAULT_VOLUME_BEFORE = -30
DEFAULT_RECENT_WINDOW = 3
DEFAULT_POSITION_WINDOW = 5
DEFAULT_MA_PERIODS = [7, 25, 99]


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
        c for c in channels
        if str(c.get("asset", "")).casefold() == asset_key
    ]

    active_requested = (
        label is None
        or not str(label).strip()
        or str(label).strip().casefold() == "active"
    )

    if active_requested:
        matches = [c for c in asset_matches if c.get("end_date") is None]
        if not matches:
            raise ValueError(f"No active channel found for {asset}.")
        if len(matches) > 1:
            raise ValueError(f"More than one active channel exists for {asset}.")
        return matches[0]

    label_key = str(label).strip().casefold()
    matches = [
        c for c in asset_matches
        if str(c.get("label", "")).casefold() == label_key
    ]

    if not matches:
        raise ValueError(f'No channel labelled "{label}" found for {asset}.')
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


def classify_direction(close, previous_close):
    if previous_close is None:
        return "FLAT"
    if close > previous_close:
        return "UP"
    if close < previous_close:
        return "DOWN"
    return "FLAT"


def current_swing_state(history, channel_rows):
    previous_closes = previous_close_map(history)

    states = [
        {
            "date": row["date"],
            "state": classify_direction(
                row["close"],
                previous_closes.get(row["date"]),
            ),
        }
        for row in channel_rows
    ]

    current_state = states[-1]["state"]

    if current_state == "FLAT":
        return {"direction": "FLAT", "age": 1}

    age = 0
    for item in reversed(states):
        if item["state"] != current_state:
            break
        age += 1

    return {"direction": current_state, "age": age}


def intraday_range_pct(row):
    if row["open"] == 0:
        return None
    return (row["high"] - row["low"]) / row["open"] * 100.0


def volatility_state(channel_rows, recent_window):
    ranges = [intraday_range_pct(row) for row in channel_rows]
    ranges = [value for value in ranges if value is not None]

    if not ranges:
        return {
            "channel_median": None,
            "recent_median": None,
            "ratio": None,
            "trend": "UNKNOWN",
        }

    channel_median = statistics.median(ranges)
    recent = ranges[-min(recent_window, len(ranges)):]
    recent_median = statistics.median(recent)
    ratio = recent_median / channel_median if channel_median else None

    if ratio is None:
        trend = "UNKNOWN"
    elif ratio < 0.75:
        trend = "COMPRESSED"
    elif ratio > 1.25:
        trend = "EXPANDED"
    else:
        trend = "NORMAL"

    return {
        "channel_median": channel_median,
        "recent_median": recent_median,
        "ratio": ratio,
        "trend": trend,
    }


def volume_stats(rows):
    volumes = [row["volume"] for row in rows]
    return {
        "average": statistics.mean(volumes),
        "median": statistics.median(volumes),
    }


def volume_state(history, channel, before_days, recent_window):
    start_date = channel.get("start_date")
    end_date = channel.get("end_date")

    before_candidates = [row for row in history if row["date"] < start_date]
    pre_rows = before_candidates[before_days:]

    channel_rows = [
        row
        for row in history
        if row["date"] >= start_date
        and (end_date is None or row["date"] <= end_date)
    ]

    if not pre_rows or not channel_rows:
        return {
            "whole_vs_pre": None,
            "recent_vs_pre": None,
            "recent_vs_channel": None,
            "trend": "UNKNOWN",
        }

    pre = volume_stats(pre_rows)
    whole = volume_stats(channel_rows)
    recent = volume_stats(channel_rows[-min(recent_window, len(channel_rows)):])

    def combined_ratio(a, b):
        ratios = []
        if b["average"] != 0:
            ratios.append(a["average"] / b["average"])
        if b["median"] != 0:
            ratios.append(a["median"] / b["median"])
        return statistics.mean(ratios) if ratios else None

    whole_vs_pre = combined_ratio(whole, pre)
    recent_vs_pre = combined_ratio(recent, pre)
    recent_vs_channel = combined_ratio(recent, whole)

    if recent_vs_channel is None:
        trend = "UNKNOWN"
    elif recent_vs_channel >= 1.25:
        trend = "RISING"
    elif recent_vs_channel <= 0.75:
        trend = "FALLING"
    else:
        trend = "STABLE"

    return {
        "whole_vs_pre": whole_vs_pre,
        "recent_vs_pre": recent_vs_pre,
        "recent_vs_channel": recent_vs_channel,
        "trend": trend,
    }


def simple_moving_average(values, period):
    result = []
    running_sum = 0.0

    for index, value in enumerate(values):
        running_sum += value

        if index >= period:
            running_sum -= values[index - period]

        if index + 1 < period:
            result.append(None)
        else:
            result.append(running_sum / period)

    return result


def ma_state(history, periods):
    closes = [row["close"] for row in history]
    series = {
        period: simple_moving_average(closes, period)
        for period in periods
    }

    ma_rows = []

    for index, row in enumerate(history):
        mas = {period: series[period][index] for period in periods}

        if any(value is None for value in mas.values()):
            continue

        values = list(mas.values())
        centre = statistics.median(values)

        if centre == 0:
            continue

        spread_pct = (max(values) - min(values)) / centre * 100.0
        displacement_pct = (row["close"] - centre) / centre * 100.0

        ma_rows.append({
            "date": row["date"],
            "centre": centre,
            "spread_pct": spread_pct,
            "displacement_pct": displacement_pct,
            "abs_displacement_pct": abs(displacement_pct),
        })

    if not ma_rows:
        return None

    current = ma_rows[-1]
    displacement_values = [row["abs_displacement_pct"] for row in ma_rows]
    spread_values = [row["spread_pct"] for row in ma_rows]

    displacement_rank = (
        sum(
            value <= current["abs_displacement_pct"]
            for value in displacement_values
        )
        / len(displacement_values)
    )

    spread_rank = (
        sum(
            value <= current["spread_pct"]
            for value in spread_values
        )
        / len(spread_values)
    )

    compression_score = 1.0 - spread_rank
    influence_score = 0.70 * displacement_rank + 0.30 * compression_score

    if influence_score < 0.50:
        influence = "LITTLE"
    elif influence_score < 0.70:
        influence = "LIGHT"
    elif influence_score < 0.90:
        influence = "MEDIUM"
    else:
        influence = "STRONG"

    displacement_pct = current["displacement_pct"]

    if displacement_pct > 1.0:
        position = "ABOVE"
    elif displacement_pct < -1.0:
        position = "BELOW"
    else:
        position = "NEUTRAL"

    return {
        "centre": current["centre"],
        "spread_pct": current["spread_pct"],
        "displacement_pct": displacement_pct,
        "position": position,
        "influence": influence,
        "influence_score": influence_score,
    }


def local_channel_position(channel_rows, window):
    recent = channel_rows[-min(window, len(channel_rows)):]

    local_high = max(row["high"] for row in recent)
    local_low = min(row["low"] for row in recent)
    latest_close = recent[-1]["close"]

    span = local_high - local_low

    if span <= 0:
        position_pct = None
    else:
        position_pct = (
            (latest_close - local_low)
            / span
            * 100.0
        )

    return {
        "local_high": local_high,
        "local_low": local_low,
        "latest_close": latest_close,
        "position_pct": position_pct,
        "window": len(recent),
    }


def score_break(swing, volume, volatility, ma, position):
    up = []
    down = []

    def add(name, up_score=0.0, down_score=0.0):
        up.append((name, up_score))
        down.append((name, down_score))

    recent_vs_channel = volume.get("recent_vs_channel")

    if recent_vs_channel is not None:
        if recent_vs_channel >= 2.0:
            add("Volume regime", up_score=2.0)
        elif recent_vs_channel >= 1.25:
            add("Volume regime", up_score=1.25)
        elif recent_vs_channel <= 0.40:
            add("Volume regime", down_score=2.0)
        elif recent_vs_channel <= 0.75:
            add("Volume regime", down_score=1.25)
        else:
            add("Volume regime")
    else:
        add("Volume regime")

    if volume.get("trend") == "RISING":
        add("Volume trend", up_score=1.0)
    elif volume.get("trend") == "FALLING":
        add("Volume trend", down_score=1.0)
    else:
        add("Volume trend")

    if swing["direction"] == "UP":
        add("Current swing", up_score=1.5)
    elif swing["direction"] == "DOWN":
        add("Current swing", down_score=1.5)
    else:
        add("Current swing")

    if ma is None:
        add("MA position")
    elif ma["position"] == "ABOVE":
        add("MA position", up_score=1.0, down_score=0.25)
    elif ma["position"] == "BELOW":
        add("MA position", up_score=0.25, down_score=1.0)
    else:
        add("MA position")

    if ma is None:
        add("MA influence")
    else:
        mapping = {
            "LITTLE": 0.0,
            "LIGHT": 0.25,
            "MEDIUM": 0.60,
            "STRONG": 1.00,
        }

        points = mapping.get(ma["influence"], 0.0)

        if ma["position"] == "ABOVE":
            add("MA influence", up_score=points, down_score=points * 0.5)
        elif ma["position"] == "BELOW":
            add("MA influence", up_score=points * 0.5, down_score=points)
        else:
            add(
                "MA influence",
                up_score=points * 0.5,
                down_score=points * 0.5,
            )

    pos = position.get("position_pct")

    if pos is not None:
        if pos >= 90:
            add("Local channel position", up_score=2.0)
        elif pos >= 75:
            add("Local channel position", up_score=1.0)
        elif pos <= 10:
            add("Local channel position", down_score=2.0)
        elif pos <= 25:
            add("Local channel position", down_score=1.0)
        else:
            add("Local channel position")
    else:
        add("Local channel position")

    vtrend = volatility.get("trend")

    if vtrend == "EXPANDED":
        if swing["direction"] == "UP":
            add("Volatility regime", up_score=1.0, down_score=0.25)
        elif swing["direction"] == "DOWN":
            add("Volatility regime", up_score=0.25, down_score=1.0)
        else:
            add("Volatility regime", up_score=0.5, down_score=0.5)
    elif vtrend == "COMPRESSED":
        add("Volatility regime", up_score=0.5, down_score=0.5)
    else:
        add("Volatility regime")

    up_total = sum(score for _, score in up)
    down_total = sum(score for _, score in down)

    return {
        "up_components": up,
        "down_components": down,
        "up_total": up_total,
        "down_total": down_total,
    }


def classify_break(up_total, down_total):
    strongest = max(up_total, down_total)
    difference = abs(up_total - down_total)

    if strongest < 3.0:
        return "NO BREAK"

    if (
        up_total >= 4.5
        and down_total >= 4.5
        and difference < 1.5
    ):
        return "CONFLICTING BREAK PRESSURE"

    if up_total > down_total:
        return "UP BREAK STRONG" if up_total >= 6.0 else "UP BREAK POSSIBLE"

    if down_total > up_total:
        return (
            "DOWN BREAK STRONG"
            if down_total >= 6.0
            else "DOWN BREAK POSSIBLE"
        )

    return "NO BREAK"


def fmt_pct(value, signed=False):
    if value is None:
        return "n/a"
    return f"{value:+.1f}%" if signed else f"{value:.1f}%"


def fmt_ratio(value):
    if value is None:
        return "n/a"
    return f"{value:.2f}x"


def fmt_price(value):
    if value is None:
        return "n/a"
    if abs(value) >= 1:
        return f"{value:.4f}"
    return f"{value:.6f}"


def print_components(title, components):
    print(title)
    print("-" * len(title))

    for name, score in components:
        print(f"{name + ':':<26}{score:.2f}")

    print()


def print_report(
    asset,
    reference,
    channel,
    swing,
    volume,
    volatility,
    ma,
    position,
    score,
):
    label = channel.get("label", "(unlabelled)")
    status = "ACTIVE" if channel.get("end_date") is None else "HISTORICAL"

    print(f"{asset}/{reference}")
    print(f"Channel: {label}")
    print(f"Status:  {status}")
    print()

    print("CURRENT")
    print("-------")
    print(f"Swing direction:          {swing['direction']}")
    print(f"Swing age:                {swing['age']} days")
    print(f"Latest close:             {fmt_price(position['latest_close'])}")
    print(f"Local channel position:   {fmt_pct(position['position_pct'])}")
    print(f"Local high:               {fmt_price(position['local_high'])}")
    print(f"Local low:                {fmt_price(position['local_low'])}")
    print()

    print("VOLUME")
    print("------")
    print(f"Whole channel vs pre:     {fmt_ratio(volume['whole_vs_pre'])}")
    print(f"Recent vs pre:            {fmt_ratio(volume['recent_vs_pre'])}")
    print(f"Recent vs channel:        {fmt_ratio(volume['recent_vs_channel'])}")
    print(f"Trend:                    {volume['trend']}")
    print()

    print("VOLATILITY")
    print("----------")
    print(f"Channel median range:     {fmt_pct(volatility['channel_median'])}")
    print(f"Recent median range:      {fmt_pct(volatility['recent_median'])}")
    print(f"Recent/channel ratio:     {fmt_ratio(volatility['ratio'])}")
    print(f"Regime:                   {volatility['trend']}")
    print()

    print("MOVING AVERAGES")
    print("---------------")

    if ma is None:
        print("Not enough history for requested MAs.")
    else:
        print(f"Price vs MA cluster:      {fmt_pct(ma['displacement_pct'], signed=True)}")
        print(f"MA position:              {ma['position']}")
        print(f"MA spread:                {fmt_pct(ma['spread_pct'])}")
        print(f"MA change influence:      {ma['influence']}")

    print()

    print_components("UP BREAK COMPONENTS", score["up_components"])
    print_components("DOWN BREAK COMPONENTS", score["down_components"])

    print("BREAK SUMMARY")
    print("-------------")
    print(f"UP break score:           {score['up_total']:.2f}")
    print(f"DOWN break score:         {score['down_total']:.2f}")
    print(
        f"Assessment:               "
        f"{classify_break(score['up_total'], score['down_total'])}"
    )
    print()
    print(
        "Note: this is an experimental regime-change score. "
        "It does not establish capital inflow/outflow or predict "
        "that a channel break will occur."
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Estimate whether a trading channel shows signs "
            "of an UP or DOWN regime break."
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
        default=DEFAULT_VOLUME_BEFORE,
        help=(
            "Pre-channel volume comparison window "
            f"(default: {DEFAULT_VOLUME_BEFORE})."
        ),
    )

    parser.add_argument(
        "--recent-window",
        type=int,
        default=DEFAULT_RECENT_WINDOW,
        help=(
            "Recent days used for volume and volatility "
            f"(default: {DEFAULT_RECENT_WINDOW})."
        ),
    )

    parser.add_argument(
        "--position-window",
        type=int,
        default=DEFAULT_POSITION_WINDOW,
        help=(
            "Recent days used for local channel high/low "
            f"(default: {DEFAULT_POSITION_WINDOW})."
        ),
    )

    parser.add_argument(
        "--ma",
        nargs="+",
        type=int,
        default=DEFAULT_MA_PERIODS,
        metavar="N",
        help="SMA periods (default: 7 25 99).",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.before >= 0:
        parser.error("--before must be negative, for example -30.")

    if args.recent_window < 1:
        parser.error("--recent-window must be at least 1.")

    if args.position_window < 2:
        parser.error("--position-window must be at least 2.")

    periods = sorted(set(args.ma))

    if len(periods) < 2:
        parser.error("--ma requires at least two periods.")

    if any(period < 1 for period in periods):
        parser.error("All MA periods must be positive integers.")

    asset = args.asset.upper()

    try:
        config = load_config()
        reference = get_reference_currency(config)
        data_dir = get_data_dir(config)

        channel = find_channel(asset, args.channel_label)
        history = load_history(history_path(data_dir, asset, reference))
        channel_rows = select_channel_rows(history, channel)

        swing = current_swing_state(history, channel_rows)
        volume = volume_state(
            history,
            channel,
            args.before,
            args.recent_window,
        )
        volatility = volatility_state(
            channel_rows,
            args.recent_window,
        )
        ma = ma_state(
            history,
            periods,
        )
        position = local_channel_position(
            channel_rows,
            args.position_window,
        )

        score = score_break(
            swing=swing,
            volume=volume,
            volatility=volatility,
            ma=ma,
            position=position,
        )

        print_report(
            asset=asset,
            reference=reference,
            channel=channel,
            swing=swing,
            volume=volume,
            volatility=volatility,
            ma=ma,
            position=position,
            score=score,
        )

    except (
        FileNotFoundError,
        ValueError,
        json.JSONDecodeError,
        statistics.StatisticsError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
