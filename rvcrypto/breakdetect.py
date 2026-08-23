#!/usr/bin/env python3
"""
breakdetect.py

Experimental channel-break / regime-change detector for rvcrypto.

Typical use:

    python3 breakdetect.py MMT
    python3 breakdetect.py MMT ACTIVE

This version combines:

    volume regime
    current swing direction
    volatility regime
    moving-average position/influence
    local channel position
    simple channel-end triangulation

The triangulation is deliberately simple:

    1. Find the highest HIGH inside the selected channel.
    2. Find the highest HIGH after that first peak.
    3. Draw a straight line through those two peaks.
    4. Extend that line until it reaches the channel baseline.
    5. Report the estimated intersection date.

By default the baseline is the lowest LOW in the selected channel.

Manual overrides are also supported:

    --peak1 2026-07-31
    --peak2 2026-08-10
    --baseline 0.1535

The geometry estimates when the current declining upper envelope would
reach the baseline if that slope continued.  It does NOT predict that
the market will actually follow that path.

Possible qualitative outcomes:

    NO BREAK
    UP BREAK POSSIBLE
    UP BREAK STRONG
    DOWN BREAK POSSIBLE
    DOWN BREAK STRONG
    CONFLICTING BREAK PRESSURE
"""

import argparse
import configparser
import io
import json
import statistics
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

import actionstatus

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
        raise FileNotFoundError(
            f"Channel file not found: {CHANNEL_FILE}"
        )

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
    return data_dir / (
        f"{asset.upper()}_{reference_currency.upper()}.json"
    )


def load_history(path):
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
        return {
            "direction": "FLAT",
            "age": 1,
        }

    age = 0

    for item in reversed(states):
        if item["state"] != current_state:
            break
        age += 1

    return {
        "direction": current_state,
        "age": age,
    }


def intraday_range_pct(row):
    if row["open"] == 0:
        return None

    return (
        (row["high"] - row["low"])
        / row["open"]
        * 100.0
    )


def volatility_state(channel_rows, recent_window):
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
            "channel_median": None,
            "recent_median": None,
            "ratio": None,
            "trend": "UNKNOWN",
        }

    channel_median = statistics.median(ranges)

    recent = ranges[
        -min(recent_window, len(ranges)):
    ]

    recent_median = statistics.median(recent)

    ratio = (
        recent_median / channel_median
        if channel_median != 0
        else None
    )

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
    volumes = [
        row["volume"]
        for row in rows
    ]

    return {
        "average": statistics.mean(volumes),
        "median": statistics.median(volumes),
    }


def volume_state(history, channel, before_days, recent_window):
    start_date = channel.get("start_date")
    end_date = channel.get("end_date")

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

    if not pre_rows or not channel_rows:
        return {
            "whole_vs_pre": None,
            "recent_vs_pre": None,
            "recent_vs_channel": None,
            "trend": "UNKNOWN",
        }

    pre = volume_stats(pre_rows)
    whole = volume_stats(channel_rows)

    recent = volume_stats(
        channel_rows[
            -min(recent_window, len(channel_rows)):
        ]
    )

    def combined_ratio(a, b):
        ratios = []

        if b["average"] != 0:
            ratios.append(
                a["average"] / b["average"]
            )

        if b["median"] != 0:
            ratios.append(
                a["median"] / b["median"]
            )

        return (
            statistics.mean(ratios)
            if ratios
            else None
        )

    whole_vs_pre = combined_ratio(
        whole,
        pre,
    )

    recent_vs_pre = combined_ratio(
        recent,
        pre,
    )

    recent_vs_channel = combined_ratio(
        recent,
        whole,
    )

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
            result.append(
                running_sum / period
            )

    return result


def ma_state(history, periods):
    closes = [
        row["close"]
        for row in history
    ]

    series = {
        period: simple_moving_average(
            closes,
            period,
        )
        for period in periods
    }

    ma_rows = []

    for index, row in enumerate(history):
        mas = {
            period: series[period][index]
            for period in periods
        }

        if any(
            value is None
            for value in mas.values()
        ):
            continue

        values = list(mas.values())
        centre = statistics.median(values)

        if centre == 0:
            continue

        spread_pct = (
            (max(values) - min(values))
            / centre
            * 100.0
        )

        displacement_pct = (
            (row["close"] - centre)
            / centre
            * 100.0
        )

        ma_rows.append({
            "date": row["date"],
            "centre": centre,
            "spread_pct": spread_pct,
            "displacement_pct": displacement_pct,
            "abs_displacement_pct":
                abs(displacement_pct),
        })

    if not ma_rows:
        return None

    current = ma_rows[-1]

    displacement_values = [
        row["abs_displacement_pct"]
        for row in ma_rows
    ]

    spread_values = [
        row["spread_pct"]
        for row in ma_rows
    ]

    displacement_rank = (
        sum(
            value
            <= current["abs_displacement_pct"]
            for value in displacement_values
        )
        / len(displacement_values)
    )

    spread_rank = (
        sum(
            value
            <= current["spread_pct"]
            for value in spread_values
        )
        / len(spread_values)
    )

    compression_score = (
        1.0 - spread_rank
    )

    influence_score = (
        0.70 * displacement_rank
        + 0.30 * compression_score
    )

    if influence_score < 0.50:
        influence = "LITTLE"
    elif influence_score < 0.70:
        influence = "LIGHT"
    elif influence_score < 0.90:
        influence = "MEDIUM"
    else:
        influence = "STRONG"

    displacement_pct = current[
        "displacement_pct"
    ]

    if displacement_pct > 1.0:
        position = "ABOVE"
    elif displacement_pct < -1.0:
        position = "BELOW"
    else:
        position = "NEUTRAL"

    return {
        "centre": current["centre"],
        "spread_pct": current["spread_pct"],
        "displacement_pct":
            displacement_pct,
        "position": position,
        "influence": influence,
        "influence_score": influence_score,
    }


def local_channel_position(channel_rows, window):
    recent = channel_rows[
        -min(window, len(channel_rows)):
    ]

    local_high = max(
        row["high"]
        for row in recent
    )

    local_low = min(
        row["low"]
        for row in recent
    )

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


def parse_date(text):
    return datetime.strptime(
        text,
        "%Y-%m-%d",
    ).date()


def find_row_by_date(rows, date_text):
    for row in rows:
        if row["date"] == date_text:
            return row

    raise ValueError(
        f"No channel row found for {date_text}."
    )


def channel_end_geometry(
    channel_rows,
    peak1_date=None,
    peak2_date=None,
    baseline=None,
):
    """
    Estimate channel-end date from a descending line through two highs.

    Automatic mode:
        peak1 = highest HIGH in channel
        peak2 = highest HIGH after peak1
        baseline = lowest LOW in channel

    Manual peak dates select those rows but still use each day's HIGH.
    """

    if len(channel_rows) < 3:
        return {
            "available": False,
            "reason": "not enough channel rows",
        }

    if peak1_date:
        peak1 = find_row_by_date(
            channel_rows,
            peak1_date,
        )
    else:
        peak1 = max(
            channel_rows,
            key=lambda row: row["high"],
        )

    peak1_index = channel_rows.index(
        peak1
    )

    after_peak1 = channel_rows[
        peak1_index + 1:
    ]

    if not after_peak1:
        return {
            "available": False,
            "reason": "no observations after first peak",
        }

    if peak2_date:
        peak2 = find_row_by_date(
            channel_rows,
            peak2_date,
        )

        if parse_date(peak2["date"]) <= parse_date(
            peak1["date"]
        ):
            raise ValueError(
                "--peak2 must be after --peak1."
            )
    else:
        peak2 = max(
            after_peak1,
            key=lambda row: row["high"],
        )

    baseline_price = (
        float(baseline)
        if baseline is not None
        else min(
            row["low"]
            for row in channel_rows
        )
    )

    d1 = parse_date(
        peak1["date"]
    )

    d2 = parse_date(
        peak2["date"]
    )

    day_span = (
        d2 - d1
    ).days

    if day_span <= 0:
        return {
            "available": False,
            "reason": "peak dates are not separated",
        }

    p1 = peak1["high"]
    p2 = peak2["high"]

    slope_per_day = (
        (p2 - p1)
        / day_span
    )

    if slope_per_day >= 0:
        return {
            "available": False,
            "reason": (
                "peak line is flat or rising; "
                "no declining intersection"
            ),
            "peak1": peak1,
            "peak2": peak2,
            "baseline": baseline_price,
            "slope_per_day": slope_per_day,
        }

    days_from_peak2 = (
        (baseline_price - p2)
        / slope_per_day
    )

    if days_from_peak2 < 0:
        return {
            "available": False,
            "reason": (
                "baseline lies above extrapolated "
                "second peak"
            ),
        }

    intersection_date = (
        d2
        + timedelta(
            days=days_from_peak2
        )
    )

    latest_date = parse_date(
        channel_rows[-1]["date"]
    )

    days_remaining = (
        intersection_date - latest_date
    ).total_seconds() / 86400.0

    return {
        "available": True,
        "peak1": peak1,
        "peak2": peak2,
        "baseline": baseline_price,
        "slope_per_day": slope_per_day,
        "intersection_date":
            intersection_date,
        "days_from_peak2":
            days_from_peak2,
        "days_remaining":
            days_remaining,
    }


def score_break(
    swing,
    volume,
    volatility,
    ma,
    position,
    geometry,
):
    up = []
    down = []

    def add(
        name,
        up_score=0.0,
        down_score=0.0,
    ):
        up.append(
            (name, up_score)
        )

        down.append(
            (name, down_score)
        )

    recent_vs_channel = volume.get(
        "recent_vs_channel"
    )

    if recent_vs_channel is not None:
        if recent_vs_channel >= 2.0:
            add(
                "Volume regime",
                up_score=2.0,
            )
        elif recent_vs_channel >= 1.25:
            add(
                "Volume regime",
                up_score=1.25,
            )
        elif recent_vs_channel <= 0.40:
            add(
                "Volume regime",
                down_score=2.0,
            )
        elif recent_vs_channel <= 0.75:
            add(
                "Volume regime",
                down_score=1.25,
            )
        else:
            add(
                "Volume regime"
            )
    else:
        add(
            "Volume regime"
        )

    if volume.get(
        "trend"
    ) == "RISING":
        add(
            "Volume trend",
            up_score=1.0,
        )
    elif volume.get(
        "trend"
    ) == "FALLING":
        add(
            "Volume trend",
            down_score=1.0,
        )
    else:
        add(
            "Volume trend"
        )

    if swing["direction"] == "UP":
        add(
            "Current swing",
            up_score=1.5,
        )
    elif swing["direction"] == "DOWN":
        add(
            "Current swing",
            down_score=1.5,
        )
    else:
        add(
            "Current swing"
        )

    if ma is None:
        add(
            "MA position"
        )
    elif ma["position"] == "ABOVE":
        add(
            "MA position",
            up_score=1.0,
            down_score=0.25,
        )
    elif ma["position"] == "BELOW":
        add(
            "MA position",
            up_score=0.25,
            down_score=1.0,
        )
    else:
        add(
            "MA position"
        )

    if ma is None:
        add(
            "MA influence"
        )
    else:
        mapping = {
            "LITTLE": 0.0,
            "LIGHT": 0.25,
            "MEDIUM": 0.60,
            "STRONG": 1.00,
        }

        points = mapping.get(
            ma["influence"],
            0.0,
        )

        if ma["position"] == "ABOVE":
            add(
                "MA influence",
                up_score=points,
                down_score=points * 0.5,
            )
        elif ma["position"] == "BELOW":
            add(
                "MA influence",
                up_score=points * 0.5,
                down_score=points,
            )
        else:
            add(
                "MA influence",
                up_score=points * 0.5,
                down_score=points * 0.5,
            )

    pos = position.get(
        "position_pct"
    )

    if pos is not None:
        if pos >= 90:
            add(
                "Local channel position",
                up_score=2.0,
            )
        elif pos >= 75:
            add(
                "Local channel position",
                up_score=1.0,
            )
        elif pos <= 10:
            add(
                "Local channel position",
                down_score=2.0,
            )
        elif pos <= 25:
            add(
                "Local channel position",
                down_score=1.0,
            )
        else:
            add(
                "Local channel position"
            )
    else:
        add(
            "Local channel position"
        )

    vtrend = volatility.get(
        "trend"
    )

    if vtrend == "EXPANDED":
        if swing["direction"] == "UP":
            add(
                "Volatility regime",
                up_score=1.0,
                down_score=0.25,
            )
        elif swing["direction"] == "DOWN":
            add(
                "Volatility regime",
                up_score=0.25,
                down_score=1.0,
            )
        else:
            add(
                "Volatility regime",
                up_score=0.5,
                down_score=0.5,
            )

    elif vtrend == "COMPRESSED":
        add(
            "Volatility regime",
            up_score=0.5,
            down_score=0.5,
        )

    else:
        add(
            "Volatility regime"
        )

    # Geometry is timing pressure, not direction.
    geometry_score = 0.0

    if geometry.get(
        "available"
    ):
        remaining = geometry.get(
            "days_remaining"
        )

        if remaining is not None:
            if 0 <= remaining <= 5:
                geometry_score = 0.75
            elif 5 < remaining <= 10:
                geometry_score = 0.35

    add(
        "Geometry pressure",
        up_score=geometry_score,
        down_score=geometry_score,
    )

    up_total = sum(
        score
        for _, score in up
    )

    down_total = sum(
        score
        for _, score in down
    )

    return {
        "up_components": up,
        "down_components": down,
        "up_total": up_total,
        "down_total": down_total,
    }


def classify_break(
    up_total,
    down_total,
):
    strongest = max(
        up_total,
        down_total,
    )

    difference = abs(
        up_total - down_total
    )

    if strongest < 3.0:
        return "NO BREAK"

    if (
        up_total >= 4.5
        and down_total >= 4.5
        and difference < 1.5
    ):
        return (
            "CONFLICTING BREAK PRESSURE"
        )

    if up_total > down_total:
        return (
            "UP BREAK STRONG"
            if up_total >= 6.0
            else "UP BREAK POSSIBLE"
        )

    if down_total > up_total:
        return (
            "DOWN BREAK STRONG"
            if down_total >= 6.0
            else "DOWN BREAK POSSIBLE"
        )

    return "NO BREAK"


def fmt_pct(
    value,
    signed=False,
):
    if value is None:
        return "n/a"

    return (
        f"{value:+.1f}%"
        if signed
        else f"{value:.1f}%"
    )


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


def print_components(
    title,
    components,
):
    print(title)
    print(
        "-" * len(title)
    )

    for name, score in components:
        print(
            f"{name + ':':<26}"
            f"{score:.2f}"
        )

    print()


def print_geometry(
    geometry,
):
    print(
        "CHANNEL END GEOMETRY"
    )
    print(
        "--------------------"
    )

    if not geometry.get(
        "available"
    ):
        print(
            "Estimate unavailable: "
            f"{geometry.get('reason', 'unknown reason')}"
        )
        print()
        return

    peak1 = geometry[
        "peak1"
    ]

    peak2 = geometry[
        "peak2"
    ]

    intersection = geometry[
        "intersection_date"
    ]

    print(
        f"Peak 1:                  "
        f"{peak1['date']} @ "
        f"{fmt_price(peak1['high'])}"
    )

    print(
        f"Peak 2:                  "
        f"{peak2['date']} @ "
        f"{fmt_price(peak2['high'])}"
    )

    print(
        f"Baseline:                "
        f"{fmt_price(geometry['baseline'])}"
    )

    print(
        f"Peak-line slope/day:     "
        f"{fmt_price(geometry['slope_per_day'])}"
    )

    print(
        f"Estimated intersection:  "
        f"{intersection.isoformat()}"
    )

    print(
        f"Estimated days remaining:"
        f"  {geometry['days_remaining']:.1f}"
    )

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
    geometry,
    score,
):
    label = channel.get(
        "label",
        "(unlabelled)",
    )

    status = (
        "ACTIVE"
        if channel.get("end_date") is None
        else "HISTORICAL"
    )

    print(
        f"{asset}/{reference}"
    )

    print(
        f"Channel: {label}"
    )

    print(
        f"Status:  {status}"
    )

    print()

    print(
        "CURRENT"
    )
    print(
        "-------"
    )

    print(
        f"Swing direction:          "
        f"{swing['direction']}"
    )

    print(
        f"Swing age:                "
        f"{swing['age']} days"
    )

    print(
        f"Latest close:             "
        f"{fmt_price(position['latest_close'])}"
    )

    print(
        f"Local channel position:   "
        f"{fmt_pct(position['position_pct'])}"
    )

    print()

    print(
        "VOLUME"
    )
    print(
        "------"
    )

    print(
        f"Whole channel vs pre:     "
        f"{fmt_ratio(volume['whole_vs_pre'])}"
    )

    print(
        f"Recent vs pre:            "
        f"{fmt_ratio(volume['recent_vs_pre'])}"
    )

    print(
        f"Recent vs channel:        "
        f"{fmt_ratio(volume['recent_vs_channel'])}"
    )

    print(
        f"Trend:                    "
        f"{volume['trend']}"
    )

    print()

    print(
        "VOLATILITY"
    )
    print(
        "----------"
    )

    print(
        f"Channel median range:     "
        f"{fmt_pct(volatility['channel_median'])}"
    )

    print(
        f"Recent median range:      "
        f"{fmt_pct(volatility['recent_median'])}"
    )

    print(
        f"Recent/channel ratio:     "
        f"{fmt_ratio(volatility['ratio'])}"
    )

    print(
        f"Regime:                   "
        f"{volatility['trend']}"
    )

    print()

    print(
        "MOVING AVERAGES"
    )
    print(
        "---------------"
    )

    if ma is None:
        print(
            "Not enough history for requested MAs."
        )
    else:
        print(
            f"Price vs MA cluster:      "
            f"{fmt_pct(ma['displacement_pct'], signed=True)}"
        )

        print(
            f"MA position:              "
            f"{ma['position']}"
        )

        print(
            f"MA spread:                "
            f"{fmt_pct(ma['spread_pct'])}"
        )

        print(
            f"MA change influence:      "
            f"{ma['influence']}"
        )

    print()

    print_geometry(
        geometry
    )

    print_components(
        "UP BREAK COMPONENTS",
        score["up_components"],
    )

    print_components(
        "DOWN BREAK COMPONENTS",
        score["down_components"],
    )

    print(
        "BREAK SUMMARY"
    )
    print(
        "-------------"
    )

    print(
        f"UP break score:           "
        f"{score['up_total']:.2f}"
    )

    print(
        f"DOWN break score:         "
        f"{score['down_total']:.2f}"
    )

    print(
        f"Assessment:               "
        f"{classify_break(score['up_total'], score['down_total'])}"
    )

    print()

    print(
        "Note: geometry estimates timing pressure only. "
        "It contributes equally to UP and DOWN break scores."
    )



def _json_safe_geometry(geometry):
    """
    Return a JSON-serialisable copy of channel-end geometry.
    """
    result = dict(geometry)

    intersection = result.get("intersection_date")
    if intersection is not None:
        result["intersection_date"] = intersection.isoformat()

    return result


def make_report(
    asset,
    channel_label="ACTIVE",
    before=DEFAULT_VOLUME_BEFORE,
    recent_window=DEFAULT_RECENT_WINDOW,
    position_window=DEFAULT_POSITION_WINDOW,
    ma_periods=None,
    peak1=None,
    peak2=None,
    baseline=None,
):
    """
    Reusable library interface for break-detection analysis.

    Returns the standard rvcrypto report envelope:

        report   human-readable report text
        json     structured analysis data
        display  optional Three.js layer payload
        image    reserved for future SVG/PNG/etc.
    """
    asset = str(asset).strip().upper()

    if before >= 0:
        raise ValueError(
            "before must be negative, for example -30."
        )

    if recent_window < 1:
        raise ValueError(
            "recent_window must be at least 1."
        )

    if position_window < 2:
        raise ValueError(
            "position_window must be at least 2."
        )

    if ma_periods is None:
        ma_periods = DEFAULT_MA_PERIODS

    periods = sorted(
        set(int(value) for value in ma_periods)
    )

    if len(periods) < 2:
        raise ValueError(
            "At least two MA periods are required."
        )

    if any(period < 1 for period in periods):
        raise ValueError(
            "All MA periods must be positive integers."
        )

    config = load_config()

    reference = get_reference_currency(
        config
    )

    data_dir = get_data_dir(
        config
    )

    channel = find_channel(
        asset,
        channel_label,
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

    swing = current_swing_state(
        history,
        channel_rows,
    )

    volume = volume_state(
        history,
        channel,
        before,
        recent_window,
    )

    volatility = volatility_state(
        channel_rows,
        recent_window,
    )

    ma = ma_state(
        history,
        periods,
    )

    position = local_channel_position(
        channel_rows,
        position_window,
    )

    geometry = channel_end_geometry(
        channel_rows,
        peak1_date=peak1,
        peak2_date=peak2,
        baseline=baseline,
    )

    score = score_break(
        swing=swing,
        volume=volume,
        volatility=volatility,
        ma=ma,
        position=position,
        geometry=geometry,
    )

    report_buffer = io.StringIO()

    with redirect_stdout(report_buffer):
        print_report(
            asset=asset,
            reference=reference,
            channel=channel,
            swing=swing,
            volume=volume,
            volatility=volatility,
            ma=ma,
            position=position,
            geometry=geometry,
            score=score,
        )

    report_text = (
        report_buffer
        .getvalue()
        .rstrip()
    )

    return {
        "schema": "rvcrypto.report.v1",
        "type": "breakdetect",
        "asset": asset,
        "reference_currency": reference,

        "report": report_text,

        "json": {
            "channel": {
                "label": channel.get("label"),
                "start_date": channel.get("start_date"),
                "end_date": channel.get("end_date"),
                "status": (
                    "ACTIVE"
                    if channel.get("end_date") is None
                    else "HISTORICAL"
                ),
            },

            "swing": swing,
            "volume": volume,
            "volatility": volatility,
            "moving_average": ma,
            "position": position,
            "geometry": _json_safe_geometry(
                geometry
            ),

            "break": {
                "up_components": [
                    {
                        "name": name,
                        "score": component_score,
                    }
                    for name, component_score
                    in score["up_components"]
                ],

                "down_components": [
                    {
                        "name": name,
                        "score": component_score,
                    }
                    for name, component_score
                    in score["down_components"]
                ],

                "up_total":
                    score["up_total"],

                "down_total":
                    score["down_total"],

                "assessment":
                    classify_break(
                        score["up_total"],
                        score["down_total"],
                    ),
            },
        },

        # No graph replacement for breakdetect yet.
        # Keeping the field makes the return shape match the other
        # rvcrypto analysis modules.
        "display": None,
        "image": None,
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Estimate whether a trading channel shows "
            "signs of an UP or DOWN regime break."
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
            "Recent days used for local high/low "
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

    parser.add_argument(
        "--peak1",
        metavar="YYYY-MM-DD",
        help=(
            "Optional manual first upper-envelope peak date."
        ),
    )

    parser.add_argument(
        "--peak2",
        metavar="YYYY-MM-DD",
        help=(
            "Optional manual second upper-envelope peak date."
        ),
    )

    parser.add_argument(
        "--baseline",
        type=float,
        help=(
            "Optional channel baseline price. "
            "Default is the channel's lowest LOW."
        ),
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        result = make_report(
            asset=args.asset,
            channel_label=args.channel_label,
            before=args.before,
            recent_window=args.recent_window,
            position_window=args.position_window,
            ma_periods=args.ma,
            peak1=args.peak1,
            peak2=args.peak2,
            baseline=args.baseline,
        )

        print(
            result["report"]
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
