#!/usr/bin/env python3
"""
turninfluence.py

Experimental "snake turn" influence report for the rvcrypto toolkit.

Typical use:

    python3 turninfluence.py MMT
    python3 turninfluence.py MMT ACTIVE
    python3 turninfluence.py MMT "July Triangle"

This tool does NOT claim to detect or predict a reversal.
It combines already-existing measurements into one qualitative
"turn influence" assessment.

Inputs considered:
    current swing direction and age
    same-direction historical swing duration inside the channel
    latest close position inside the daily range
    recent close-position deterioration/improvement
    volatility compression
    volume influence and trend
    moving-average influence

Output:
    LITTLE TURN INFLUENCE
    LIGHT TURN INFLUENCE
    MEDIUM TURN INFLUENCE
    STRONG TURN INFLUENCE

The weights are deliberately transparent and provisional.
"""

import argparse
import configparser
import io
import json
import statistics
import sys
from contextlib import redirect_stdout
from pathlib import Path
from datetime import datetime, timedelta

from tools import lan


BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.ini"
CHANNEL_FILE = BASE_DIR / "data" / "tradingchannels.json"

DEFAULT_REFERENCE_CURRENCY = "USDT"
DEFAULT_VOLUME_BEFORE = -30
DEFAULT_RECENT_WINDOW = 3
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
        row for row in history
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


def close_position(row):
    span = row["high"] - row["low"]
    if span <= 0:
        return None
    return (row["close"] - row["low"]) / span * 100.0


def classify_direction(close, previous_close):
    if previous_close is None:
        return "FLAT"
    if close > previous_close:
        return "UP"
    if close < previous_close:
        return "DOWN"
    return "FLAT"


def build_daily_states(history, channel_rows):
    previous_closes = previous_close_map(history)
    results = []

    for row in channel_rows:
        previous_close = previous_closes.get(row["date"])
        move_pct = None
        if previous_close not in (None, 0):
            move_pct = (row["close"] / previous_close - 1.0) * 100.0

        results.append({
            **row,
            "previous_close": previous_close,
            "move_pct": move_pct,
            "state": classify_direction(row["close"], previous_close),
            "close_position_pct": close_position(row),
        })

    return results


def build_swings(rows):
    swings = []
    current = None

    for row in rows:
        state = row["state"]

        if state == "FLAT":
            if current:
                swings.append(current)
                current = None
            continue

        if current is None or current["state"] != state:
            if current:
                swings.append(current)

            current = {
                "state": state,
                "start_date": row["date"],
                "end_date": row["date"],
                "days": 1,
                "rows": [row],
            }
        else:
            current["end_date"] = row["date"]
            current["days"] += 1
            current["rows"].append(row)

    if current:
        swings.append(current)

    return swings


def same_direction_duration_stats(swings, state):
    durations = [s["days"] for s in swings if s["state"] == state]
    if not durations:
        return {"count": 0, "median": None, "average": None}

    return {
        "count": len(durations),
        "median": statistics.median(durations),
        "average": statistics.mean(durations),
    }


def intraday_range_pct(row):
    if row["open"] == 0:
        return None
    return (row["high"] - row["low"]) / row["open"] * 100.0


def calculate_volatility(channel_rows, recent_window):
    ranges = [intraday_range_pct(r) for r in channel_rows]
    ranges = [v for v in ranges if v is not None]
    if not ranges:
        return {"channel_median": None, "recent_median": None, "ratio": None}

    channel_median = statistics.median(ranges)
    recent = ranges[-min(recent_window, len(ranges)):]
    recent_median = statistics.median(recent)
    ratio = recent_median / channel_median if channel_median else None

    return {
        "channel_median": channel_median,
        "recent_median": recent_median,
        "ratio": ratio,
    }


def volume_stats(rows):
    volumes = [r["volume"] for r in rows]
    return {
        "average": statistics.mean(volumes),
        "median": statistics.median(volumes),
    }


def volume_influence(history, channel, before_days, recent_window):
    start_date = channel.get("start_date")
    end_date = channel.get("end_date")

    before_candidates = [r for r in history if r["date"] < start_date]
    pre_rows = before_candidates[before_days:]
    channel_rows = [
        r for r in history
        if r["date"] >= start_date
        and (end_date is None or r["date"] <= end_date)
    ]

    if not pre_rows or not channel_rows:
        return {"whole_ratio": None, "recent_ratio": None, "trend": "UNKNOWN"}

    pre = volume_stats(pre_rows)
    whole = volume_stats(channel_rows)
    recent = volume_stats(channel_rows[-min(recent_window, len(channel_rows)):])

    def combined_ratio(period):
        ratios = []
        if pre["average"]:
            ratios.append(period["average"] / pre["average"])
        if pre["median"]:
            ratios.append(period["median"] / pre["median"])
        return statistics.mean(ratios) if ratios else None

    whole_ratio = combined_ratio(whole)
    recent_ratio = combined_ratio(recent)

    if whole_ratio is None or recent_ratio is None:
        trend = "UNKNOWN"
    elif recent_ratio >= whole_ratio * 1.25:
        trend = "RISING"
    elif recent_ratio <= whole_ratio * 0.75:
        trend = "FALLING"
    else:
        trend = "STABLE"

    return {
        "whole_ratio": whole_ratio,
        "recent_ratio": recent_ratio,
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


def ma_influence(history, periods):
    closes = [r["close"] for r in history]
    ma_series = {
        p: simple_moving_average(closes, p)
        for p in periods
    }

    ma_rows = []

    for index, row in enumerate(history):
        mas = {p: ma_series[p][index] for p in periods}

        if any(v is None for v in mas.values()):
            continue

        values = list(mas.values())
        centre = statistics.median(values)
        if centre == 0:
            continue

        spread = (max(values) - min(values)) / centre * 100.0
        displacement = (row["close"] - centre) / centre * 100.0

        ma_rows.append({
            "date": row["date"],
            "spread_pct": spread,
            "displacement_pct": displacement,
            "abs_displacement_pct": abs(displacement),
        })

    if not ma_rows:
        return None

    current = ma_rows[-1]

    displacement_values = [r["abs_displacement_pct"] for r in ma_rows]
    spread_values = [r["spread_pct"] for r in ma_rows]

    displacement_rank = (
        sum(v <= current["abs_displacement_pct"] for v in displacement_values)
        / len(displacement_values)
    )

    spread_rank = (
        sum(v <= current["spread_pct"] for v in spread_values)
        / len(spread_values)
    )

    compression_score = 1.0 - spread_rank
    score = 0.70 * displacement_rank + 0.30 * compression_score

    if score < 0.50:
        level = "LITTLE"
    elif score < 0.70:
        level = "LIGHT"
    elif score < 0.90:
        level = "MEDIUM"
    else:
        level = "STRONG"

    if current["displacement_pct"] > 1.0:
        bias = "ABOVE MA CLUSTER"
    elif current["displacement_pct"] < -1.0:
        bias = "BELOW MA CLUSTER"
    else:
        bias = "NEUTRAL"

    return {
        "score": score,
        "level": level,
        "bias": bias,
        "displacement_pct": current["displacement_pct"],
        "spread_pct": current["spread_pct"],
    }


def score_turn(current_swing, duration_stats, volatility, volume, ma):
    components = []

    # Swing age: max 2.0
    age_score = 0.0
    median_duration = duration_stats["median"]

    if median_duration:
        ratio = current_swing["days"] / median_duration
        if ratio >= 1.5:
            age_score = 2.0
        elif ratio >= 1.0:
            age_score = 1.5
        elif ratio >= 0.75:
            age_score = 1.0
        elif ratio >= 0.50:
            age_score = 0.5

    components.append(("Swing age", age_score))

    # Latest head position: max 2.0
    latest = current_swing["rows"][-1]
    cp = latest["close_position_pct"]
    head_score = 0.0

    if cp is not None:
        if current_swing["state"] == "UP":
            if cp < 20:
                head_score = 2.0
            elif cp < 40:
                head_score = 1.0
        elif current_swing["state"] == "DOWN":
            if cp > 80:
                head_score = 2.0
            elif cp > 60:
                head_score = 1.0

    components.append(("Head position", head_score))

    # Recent close-position momentum: max 1.5
    position_score = 0.0
    cps = [
        r["close_position_pct"]
        for r in current_swing["rows"][-3:]
        if r["close_position_pct"] is not None
    ]

    if len(cps) >= 2:
        delta = cps[-1] - cps[0]

        if current_swing["state"] == "UP":
            if delta <= -50:
                position_score = 1.5
            elif delta <= -25:
                position_score = 1.0
            elif delta <= -10:
                position_score = 0.5

        elif current_swing["state"] == "DOWN":
            if delta >= 50:
                position_score = 1.5
            elif delta >= 25:
                position_score = 1.0
            elif delta >= 10:
                position_score = 0.5

    components.append(("Head momentum", position_score))

    # Volatility compression: max 1.5
    vol_score = 0.0
    vol_ratio = volatility.get("ratio")

    if vol_ratio is not None:
        if vol_ratio < 0.50:
            vol_score = 1.5
        elif vol_ratio < 0.75:
            vol_score = 1.0
        elif vol_ratio < 1.00:
            vol_score = 0.5

    components.append(("Volatility compression", vol_score))

    # Volume level: max 1.5
    volume_score = 0.0
    whole_ratio = volume.get("whole_ratio")

    if whole_ratio is not None:
        if whole_ratio >= 8.0:
            volume_score = 1.5
        elif whole_ratio >= 4.0:
            volume_score = 1.0
        elif whole_ratio >= 2.0:
            volume_score = 0.5

    components.append(("Volume influence", volume_score))

    # Volume trend: max 0.5
    volume_trend_score = 0.5 if volume.get("trend") == "RISING" else 0.0
    components.append(("Volume trend", volume_trend_score))

    # MA influence: max 1.0
    ma_score = 0.0

    if ma is not None:
        if ma["level"] == "STRONG":
            ma_score = 1.0
        elif ma["level"] == "MEDIUM":
            ma_score = 0.75
        elif ma["level"] == "LIGHT":
            ma_score = 0.35

    components.append(("MA influence", ma_score))

    total = sum(score for _, score in components)

    return {
        "components": components,
        "total": total,
    }


def classify_turn(total):
    if total < 2.5:
        return "LITTLE TURN INFLUENCE"
    if total < 4.5:
        return "LIGHT TURN INFLUENCE"
    if total < 6.5:
        return "MEDIUM TURN INFLUENCE"
    return "STRONG TURN INFLUENCE"


def fmt_pct(value, signed=False):
    if value is None:
        return "n/a"
    return f"{value:+.1f}%" if signed else f"{value:.1f}%"


def fmt_ratio(value):
    if value is None:
        return "n/a"
    return f"{value:.2f}x"


def print_report(
    asset,
    reference,
    channel,
    daily_rows,
    current_swing,
    duration_stats,
    volatility,
    volume,
    ma,
    score,
):
    label = channel.get("label", "(unlabelled)")
    end_date = channel.get("end_date") or daily_rows[-1]["date"]
    status = "ACTIVE" if channel.get("end_date") is None else "HISTORICAL"
    latest = daily_rows[-1]

    print(f"{asset}/{reference}")
    print(f"Channel: {label}")
    print(f"Period:  {channel['start_date']} -> {end_date}  [{status}]")
    print()

    print("CURRENT SWING")
    print("-------------")
    print(f"Direction:                {current_swing['state']}")
    print(f"Age:                      {current_swing['days']} days")
    print(f"Start:                    {current_swing['start_date']}")
    print(
        f"Same-direction median:    "
        f"{duration_stats['median'] if duration_stats['median'] is not None else 'n/a'} days"
    )
    print(f"Same-direction samples:   {duration_stats['count']}")

    possible_turn = (
        "DOWN" if current_swing["state"] == "UP"
        else "UP" if current_swing["state"] == "DOWN"
        else "UNKNOWN"
    )
    print(f"If turn occurs:           {possible_turn}")
    print()

    print("HEAD POSITION")
    print("-------------")
    print(f"Latest close position:    {fmt_pct(latest['close_position_pct'])}")

    recent_positions = [
        r["close_position_pct"]
        for r in daily_rows[-3:]
        if r["close_position_pct"] is not None
    ]

    if recent_positions:
        print(
            "Recent positions:         "
            + " -> ".join(f"{v:.1f}%" for v in recent_positions)
        )
    print()

    print("VOLATILITY")
    print("----------")
    print(f"Channel median range:     {fmt_pct(volatility['channel_median'])}")
    print(f"Recent median range:      {fmt_pct(volatility['recent_median'])}")
    print(f"Recent/channel ratio:     {fmt_ratio(volatility['ratio'])}")
    print()

    print("VOLUME")
    print("------")
    print(f"Whole channel influence:  {fmt_ratio(volume['whole_ratio'])}")
    print(f"Recent influence:         {fmt_ratio(volume['recent_ratio'])}")
    print(f"Trend:                    {volume['trend']}")
    print()

    print("MOVING AVERAGES")
    print("---------------")
    if ma is None:
        print("Not enough history for requested MAs.")
    else:
        print(f"Change influence:         {ma['level']}")
        print(f"Price position:           {ma['bias']}")
        print(f"Price vs MA cluster:      {fmt_pct(ma['displacement_pct'], signed=True)}")
        print(f"MA cluster spread:        {fmt_pct(ma['spread_pct'])}")
    print()

    print("TURN COMPONENTS")
    print("---------------")
    for name, component_score in score["components"]:
        print(f"{name + ':':<26}{component_score:.2f}")

    print()
    print(f"Total turn score:         {score['total']:.2f}")
    print(f"Assessment:               {classify_turn(score['total'])}")
    print()
    print(
        "Note: turn influence is an experimental convergence of descriptive "
        "measurements. It does not predict that a reversal will occur."
    )


def median_direction_move(daily_rows, direction):
    """
    Return the median close-to-close percentage move for rows
    matching the requested direction.

    Example:

        direction = "DOWN"

    might return:

        -6.9

    meaning the median observed DOWN-day close movement in the
    selected channel was -6.9%.
    """

    moves = [
        row["move_pct"]
        for row in daily_rows
        if row.get("state") == direction
        and row.get("move_pct") is not None
    ]

    if not moves:
        return None

    return statistics.median(moves)


def generate_future_trend(
    daily_rows,
    direction,
    trend_count,
):
    """
    Generate a deliberately simple future price path.

    The latest completed close is used as the starting point.

    Each projected day compounds the median historical daily move
    for the current swing direction.

    The rows are marked future=True so cryptograph.html uses its
    future colour.

    This is a conditional continuation model, not a prediction.
    """

    if trend_count < 1:
        return []

    median_move = median_direction_move(
        daily_rows,
        direction,
    )

    if median_move is None:
        return []

    latest = daily_rows[-1]

    current_price = latest["close"]

    current_date = datetime.strptime(
        latest["date"],
        "%Y-%m-%d",
    ).date()

    future_rows = []

    for offset in range(1, trend_count + 1):
        current_date += timedelta(days=1)

        current_price *= (
            1.0 + median_move / 100.0
        )

        future_rows.append({
            "date": current_date.isoformat(),
            "close": round(current_price, 8),
            "future": True,
        })

    return future_rows


def backtest_step_colour(direction, step, total_steps):
    """
    Display-only colour hint for a rolling backtest path.

    UP continuation becomes progressively brighter green.
    DOWN continuation becomes progressively brighter blue.
    FLAT/unknown remains white.

    The prediction algorithm is unchanged; these colours are only
    presentation metadata for cryptograph.html.
    """
    total_steps = max(1, int(total_steps))
    step = max(1, min(int(step), total_steps))

    if direction == "UP":
        colours = [
            "#b9dfc3",
            "#8fd39f",
            "#60c77a",
            "#34b95b",
        ]
    elif direction == "DOWN":
        colours = [
            "#c7dcf5",
            "#93c5fd",
            "#60a5fa",
            "#3b82f6",
        ]
    else:
        colours = ["#e5e7eb"]

    if len(colours) == 1:
        return colours[0]

    index = round(
        (step - 1)
        * (len(colours) - 1)
        / max(1, total_steps - 1)
    )

    return colours[index]


def generate_rolling_backtest(
    daily_rows,
    trend_count=4,
):
    """
    Re-run the existing continuation projection at each historical day.

    Each origin date uses only rows available up to that date, then calls
    generate_future_trend() unchanged. This is display/backtest plumbing,
    not a change to the projection algorithm.
    """
    if trend_count < 1:
        return []

    results = []

    # Start once a directional state is possible. Skip the final/current row
    # because it has no realised future inside the selected historical data.
    for end_index in range(1, len(daily_rows) - 1):
        prefix = daily_rows[:end_index + 1]
        swings = build_swings(prefix)

        if not swings:
            continue

        current_swing = swings[-1]
        direction = current_swing.get("state")

        if direction not in {"UP", "DOWN"}:
            continue

        predicted = generate_future_trend(
            daily_rows=prefix,
            direction=direction,
            trend_count=trend_count,
        )

        if not predicted:
            continue

        points = []

        for step, row in enumerate(predicted, start=1):
            points.append({
                **row,
                "step": step,
                "colour": backtest_step_colour(
                    direction,
                    step,
                    trend_count,
                ),
            })

        results.append({
            "origin_date": prefix[-1]["date"],
            "origin_close": prefix[-1]["close"],
            "direction": direction,
            "points": points,
        })

    return results


def build_graph_payload(
    asset,
    reference_currency,
    history,
    future_rows,
    days=30,
    colour="#38bdf8",
    future_colour="#e5e7eb",
):
    """
    Build the Three.js ADD_ASSET_LAYER payload without transporting it.

    This is the reusable library form for Flask/API, MQTT, console,
    future CMS storage, and later image/render layers.
    """
    historical_rows = [
        {
            "date": row["date"],
            "close": row["close"],
        }
        for row in history[-days:]
    ]

    return {
        "asset": asset,
        "reference_currency": reference_currency,
        "colour": colour,
        "future_colour": future_colour,
        "data": historical_rows + future_rows,
    }


def emit_graph_stream(
    asset,
    reference_currency,
    history,
    future_rows,
    config,
    days=30,
    colour="#38bdf8",
    future_colour="#e5e7eb",
):
    """
    Emit CryptoGraph commands through the configured stream transport.
    """
    payload = build_graph_payload(
        asset=asset,
        reference_currency=reference_currency,
        history=history,
        future_rows=future_rows,
        days=days,
        colour=colour,
        future_colour=future_colour,
    )

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    stream_text = (
        'CryptoGraph.command("CLEAR_ASSET_LAYER");\n'
        'CryptoGraph.command('
        '"ADD_ASSET_LAYER", '
        + encoded
        + ");"
    )

    lan.stream(
        stream_text,
        config=config,
    )


def make_report(
    asset,
    channel_label="ACTIVE",
    before=DEFAULT_VOLUME_BEFORE,
    recent_window=DEFAULT_RECENT_WINDOW,
    ma_periods=None,
    trend_count=0,
    graph_days=30,
    options=None,
):
    """
    Run the turn-influence analysis as a reusable library function.

    The return envelope is intended to become the common rvcrypto report
    interface:

        report   human-readable text for a panel/CMS story
        json     structured analysis data
        display  Three.js command payload
        image    reserved for future SVG/PNG/etc.
    """
    asset = str(asset).strip().upper()

    if before >= 0:
        raise ValueError("before must be negative, for example -30.")

    if recent_window < 1:
        raise ValueError("recent_window must be at least 1.")

    if trend_count < 0:
        raise ValueError("trend_count cannot be negative.")

    if graph_days < 1:
        raise ValueError("graph_days must be at least 1.")

    if ma_periods is None:
        ma_periods = DEFAULT_MA_PERIODS

    periods = sorted(set(int(value) for value in ma_periods))

    if len(periods) < 2:
        raise ValueError("At least two MA periods are required.")

    if any(period < 1 for period in periods):
        raise ValueError("All MA periods must be positive integers.")

    config = load_config()
    reference = get_reference_currency(config)
    data_dir = get_data_dir(config)

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

    daily_rows = build_daily_states(
        history,
        channel_rows,
    )

    swings = build_swings(daily_rows)

    if not swings:
        raise ValueError(
            "No UP/DOWN swings found in selected channel."
        )

    current_swing = swings[-1]

    duration_stats = same_direction_duration_stats(
        swings[:-1],
        current_swing["state"],
    )

    volatility = calculate_volatility(
        channel_rows,
        recent_window,
    )

    volume = volume_influence(
        history,
        channel,
        before,
        recent_window,
    )

    ma = ma_influence(
        history,
        periods,
    )

    score = score_turn(
        current_swing,
        duration_stats,
        volatility,
        volume,
        ma,
    )

    future_rows = generate_future_trend(
        daily_rows=daily_rows,
        direction=current_swing["state"],
        trend_count=trend_count,
    )

    options = dict(options or {})
    rolling_backtest = []

    if options.get("rolling-backtest"):
        rolling_backtest = generate_rolling_backtest(
            daily_rows=daily_rows,
            trend_count=trend_count or 4,
        )

    graph_payload = build_graph_payload(
        asset=asset,
        reference_currency=reference,
        history=history,
        future_rows=future_rows,
        days=graph_days,
    )

    graph_payload["display_options"] = options

    if rolling_backtest:
        graph_payload["rolling_backtest"] = rolling_backtest

    report_buffer = io.StringIO()

    with redirect_stdout(report_buffer):
        print_report(
            asset=asset,
            reference=reference,
            channel=channel,
            daily_rows=daily_rows,
            current_swing=current_swing,
            duration_stats=duration_stats,
            volatility=volatility,
            volume=volume,
            ma=ma,
            score=score,
        )

    report_text = report_buffer.getvalue().rstrip()

    result = {
        "schema": "rvcrypto.report.v1",
        "type": "turndetect",
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

            "current_swing": {
                "direction": current_swing["state"],
                "start_date": current_swing["start_date"],
                "end_date": current_swing["end_date"],
                "days": current_swing["days"],
            },

            "duration_stats": duration_stats,
            "volatility": volatility,
            "volume": volume,
            "moving_average": ma,

            "turn": {
                "components": [
                    {
                        "name": name,
                        "score": component_score,
                    }
                    for name, component_score
                    in score["components"]
                ],
                "total": score["total"],
                "assessment": classify_turn(score["total"]),
            },

            "future_trend": future_rows,
            "rolling_backtest": rolling_backtest,
        },

        "display_options": options,

        "display": {
            "command": "ADD_ASSET_LAYER",
            "value": graph_payload,
        },

        "image": None,
    }

    return result


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Combine channel measurements into an experimental turn influence."
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
        help=f"Pre-channel volume comparison window (default: {DEFAULT_VOLUME_BEFORE}).",
    )

    parser.add_argument(
        "--recent-window",
        type=int,
        default=DEFAULT_RECENT_WINDOW,
        help=f"Recent-day window for volatility/volume (default: {DEFAULT_RECENT_WINDOW}).",
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
        "--stream",
        action="store_true",
        help=(
            "Emit CryptoGraph commands using config.ini [stream] (console or mqtt)."
        ),
    )

    parser.add_argument(
        "--trend-count",
        type=int,
        default=0,
        metavar="DAYS",
        help=(
            "Generate DAYS of conditional future trend data."
        ),
    )

    parser.add_argument(
        "--graph-days",
        type=int,
        default=30,
        help=(
            "Number of historical days included in graph output "
            "(default: 30)."
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
            ma_periods=args.ma,
            trend_count=args.trend_count,
            graph_days=args.graph_days,
        )

        if args.stream:
            config = load_config()
            payload = result["display"]["value"]

            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )

            stream_text = (
                'CryptoGraph.command("CLEAR_ASSET_LAYER");\n'
                'CryptoGraph.command('
                '"ADD_ASSET_LAYER", '
                + encoded
                + ");"
            )

            lan.stream(
                stream_text,
                config=config,
            )
            return

        print(result["report"])

    except (
        FileNotFoundError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
        statistics.StatisticsError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
