#!/usr/bin/env python3
"""
estimatetrades.py <asset>
    [--channel ACTIVE|label]
    [--date YYYY-MM-DD]
    [--target N]
    [--budget DOLLARS]
    [--reality-trimfactor FACTOR]
    [--json]
    [--threejs]
    [--stream]

Estimate how many >=20% trading opportunities may remain in a channel.

Output modes
------------
Default:
    Human-readable report rendered from REPORT_TEMPLATE.

--json:
    Emit the underlying structured JSON data.

--threejs:
    Emit the Three.js layer command rendered from THREEJS_TEMPLATE.

--stream:
    Send whichever output mode was selected through tools.lan instead
    of printing it locally.

Examples
--------
    python3 estimatetrades.py MMT

    python3 estimatetrades.py MMT \
        --target 8 \
        --budget 1000 \
        --reality-trimfactor .75

    python3 estimatetrades.py MMT --json

    python3 estimatetrades.py MMT --json --stream

    python3 estimatetrades.py MMT --threejs --stream

Design note
-----------
The calculation and the presentation are deliberately separated.

    analyse(...)
        -> plain Python dict

    render_report(data)
        -> Jinja2 human report

    render_json(data)
        -> JSON

    render_threejs(data)
        -> Jinja2 Three.js layer command

That gives server-desktop.py a future direct-import path while keeping
the command-line utility intact.

The estimator is still provisional.  Once shape matching exists, the
expected remaining turns/trades can be trained from matched historical
channel shapes rather than the simple heuristic below.
"""

import argparse
import configparser
import json
import statistics
from datetime import date
from pathlib import Path

from tools import lan

try:
    from jinja2 import Template
except ImportError as exc:
    raise RuntimeError(
        "estimatetrades.py requires Jinja2."
    ) from exc


BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.ini"
CHANNEL_FILE = BASE / "data" / "tradingchannels.json"

DEFAULT_QUOTE = "USDT"
DEFAULT_TRADES = 6
DEFAULT_REALITY_TRIMFACTOR = 0.75
MIN_SWING_PCT = 20.0

DEFAULT_TOPIC = "rvcrypto/estimatetrades"
DEFAULT_JSON_TOPIC = "rvcrypto/estimatetrades/json"
DEFAULT_THREEJS_TOPIC = "rvcrypto/estimatetrades/threejs"


REPORT_TEMPLATE = r"""
{{ asset }}/{{ reference_currency }}
Channel:                 {{ channel.label }}
Period:                  {{ channel.start_date }} -> {{ channel.end_date }}
Latest data:             {{ latest_data }}

ESTIMATED TRADES LEFT
---------------------
Minimum swing counted:   {{ "%.0f"|format(parameters.minimum_swing_pct) }}%
Default opportunity set: {{ parameters.default_trades }}
Requested target:        {{ parameters.target }}
Median channel range:    {{ "%.1f"|format(volatility.median_range_pct) if volatility.median_range_pct is not none else "n/a" }}%
Volatility adjustment:   {{ "%+d"|format(volatility.adjustment) }}
Estimated total:         {{ trades.expected_total }}
Completed >=20% legs:    {{ trades.completed }}

ESTIMATED LEFT:          {{ trades.remaining }}
Approx buys left:        {{ trades.buys_remaining }}
Approx sells left:       {{ trades.sells_remaining }}
{% if qualifying_swings %}
QUALIFYING COMPLETED SWINGS
---------------------------
{% for swing in qualifying_swings -%}
{{ "%-4s"|format(swing.direction) }} {{ swing.start_date }} -> {{ swing.end_date }} {{ "%+.1f"|format(swing.amplitude_pct) }}%
{% endfor %}
{% endif -%}
{% if returns.best_case_potential is not none %}
Best case potential return:   ${{ "{:,.2f}".format(returns.best_case_potential) }}
Reality-trimmed return @{{ "%.2f"|format(parameters.reality_trimfactor) }}: ${{ "{:,.2f}".format(returns.reality_trimmed) }}
{% endif %}
Note: experimental heuristic only. This estimate needs historical backtesting/training.
""".strip()


THREEJS_TEMPLATE = r"""
CryptoGraph.command(
    "ADD_ESTIMATE_TRADES_LAYER",
    {{ payload_json }}
);
""".strip()


def load_json_file(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def reference_currency(config):
    return config.get(
        "market-data",
        "reference_currency",
        fallback=DEFAULT_QUOTE,
    ).upper()


def data_dir(config):
    path = Path(
        config.get(
            "storage",
            "data_dir",
            fallback="data",
        )
    )

    if not path.is_absolute():
        path = BASE / path

    return path


def load_history(config, asset, quote, cutoff=None):
    path = data_dir(config) / f"{asset}_{quote}.json"

    document = load_json_file(path)
    rows = []

    for raw in document.get("data", []):
        try:
            row = {
                "date": str(raw["date"]),
                "open": float(raw["open"]),
                "high": float(raw["high"]),
                "low": float(raw["low"]),
                "close": float(raw["close"]),
                "volume": float(raw.get("volume", 0.0)),
            }
        except (KeyError, TypeError, ValueError):
            continue

        if cutoff is None or row["date"] <= cutoff:
            rows.append(row)

    rows.sort(key=lambda row: row["date"])

    if not rows:
        raise ValueError("No usable market history.")

    return rows


def find_channel(asset, label="ACTIVE", as_of=None):
    document = load_json_file(CHANNEL_FILE)

    matches = [
        channel
        for channel in document.get("channels", [])
        if str(channel.get("asset", "")).upper() == asset
    ]

    active_requested = str(label or "ACTIVE").upper() == "ACTIVE"

    if active_requested:
        matches = [
            channel
            for channel in matches
            if channel.get("end_date") is None
        ]
    else:
        matches = [
            channel
            for channel in matches
            if str(channel.get("label", "")).casefold()
            == str(label).casefold()
        ]

    if not matches:
        raise ValueError(
            f'No channel "{label}" found for {asset}.'
        )

    if len(matches) > 1:
        raise ValueError(
            f'More than one channel "{label}" found for {asset}.'
        )

    channel = dict(matches[0])

    # Keep the real semantic label separate from the stored optional label.
    channel["_display_label"] = (
        "ACTIVE"
        if active_requested
        else channel.get("label") or "(unlabelled)"
    )

    # Regression hook: truncate the selected channel at --date.
    if as_of:
        real_end = channel.get("end_date")

        if real_end is None or real_end > as_of:
            channel["end_date"] = as_of

    return channel


def select_channel_rows(history, channel):
    start = channel.get("start_date")
    end = channel.get("end_date")

    if not start:
        raise ValueError("Selected channel has no start_date.")

    rows = [
        row
        for row in history
        if row["date"] >= start
        and (
            end is None
            or row["date"] <= end
        )
    ]

    if not rows:
        raise ValueError(
            "No market data falls inside the selected channel."
        )

    return rows


def build_swings(rows):
    """
    First-pass close-to-close swing detector.

    TODO:
        Replace this with an import from channelswing.py once that
        module has a stable callable interface.
    """
    if len(rows) < 2:
        return []

    swings = []
    current = None

    for index in range(1, len(rows)):
        previous = rows[index - 1]
        row = rows[index]

        if row["close"] > previous["close"]:
            direction = "UP"
        elif row["close"] < previous["close"]:
            direction = "DOWN"
        else:
            continue

        if current is None or current["direction"] != direction:
            if current is not None:
                swings.append(current)

            current = {
                "direction": direction,
                "start_date": previous["date"],
                "end_date": row["date"],
                "start_close": previous["close"],
                "end_close": row["close"],
            }
        else:
            current["end_date"] = row["date"]
            current["end_close"] = row["close"]

    if current is not None:
        swings.append(current)

    for swing in swings:
        swing["amplitude_pct"] = (
            swing["end_close"]
            / swing["start_close"]
            - 1.0
        ) * 100.0

    return swings


def intraday_range_pct(row):
    if row["open"] == 0:
        return None

    return (
        (row["high"] - row["low"])
        / row["open"]
        * 100.0
    )


def volatility_budget(rows):
    """
    Provisional volatility -> opportunity-count adjustment.

    TODO:
        Backtest this against completed channels and, later, matched
        shape classes.  More volatile channels should generally expose
        more qualifying trading opportunities.
    """
    ranges = [
        intraday_range_pct(row)
        for row in rows
    ]

    ranges = [
        value
        for value in ranges
        if value is not None
    ]

    if not ranges:
        return None, 0

    median_range = statistics.median(ranges)

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
        swing
        for swing in swings
        if abs(swing["amplitude_pct"]) >= MIN_SWING_PCT
    ]

    median_range, adjustment = volatility_budget(rows)

    expected_total = max(
        2,
        target + adjustment,
    )

    completed = len(qualifying)

    remaining = max(
        0,
        expected_total - completed,
    )

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


def best_case_return(
    budget,
    remaining_trades,
    median_range_pct,
):
    if budget is None:
        return None

    if budget < 0:
        raise ValueError(
            "--budget must be zero or greater."
        )

    if (
        remaining_trades <= 0
        or median_range_pct is None
    ):
        return 0.0

    factor = max(
        0.0,
        median_range_pct,
    ) / 100.0

    return budget * (
        (1.0 + factor) ** remaining_trades
        - 1.0
    )


def build_layer_data(
    asset,
    quote,
    channel,
    rows,
    result,
    target,
    budget,
    reality_trimfactor,
):
    """
    Create the single structured record used by every renderer.

    This is the main future import hook for server-desktop.py.
    """
    best_case = best_case_return(
        budget,
        result["remaining"],
        result["median_range_pct"],
    )

    reality_trimmed = (
        None
        if best_case is None
        else best_case * reality_trimfactor
    )

    end_date = (
        channel.get("end_date")
        or rows[-1]["date"]
    )

    return {
        "schema": "rvcrypto.estimatetrades.v1",
        "type": "estimate_trades",
        "layer_type": "estimate_trades",
        "asset": asset,
        "reference_currency": quote,
        "channel": {
            "label": channel["_display_label"],
            "start_date": channel["start_date"],
            "end_date": end_date,
            "status": (
                "ACTIVE"
                if channel["_display_label"] == "ACTIVE"
                else "HISTORICAL"
            ),
        },
        "latest_data": rows[-1]["date"],
        "parameters": {
            "default_trades": DEFAULT_TRADES,
            "target": target,
            "minimum_swing_pct": MIN_SWING_PCT,
            "budget": budget,
            "reality_trimfactor": reality_trimfactor,
        },
        "volatility": {
            "median_range_pct": result["median_range_pct"],
            "adjustment": result["volatility_adjustment"],
        },
        "trades": {
            "expected_total": result["expected_total"],
            "completed": result["completed"],
            "remaining": result["remaining"],
            "buys_remaining": result["buys_remaining"],
            "sells_remaining": result["sells_remaining"],
        },
        "returns": {
            "best_case_potential": best_case,
            "reality_trimmed": reality_trimmed,
        },
        "qualifying_swings": result["qualifying_swings"],
    }


def analyse(
    asset,
    channel_label="ACTIVE",
    as_of=None,
    target=DEFAULT_TRADES,
    budget=None,
    reality_trimfactor=DEFAULT_REALITY_TRIMFACTOR,
):
    """
    Callable analysis interface.

    Returns plain Python data and does not print or publish anything.
    """
    if target < 1:
        raise ValueError(
            "--target must be at least 1."
        )

    if not 0.0 <= reality_trimfactor <= 1.0:
        raise ValueError(
            "--reality-trimfactor must be between 0 and 1."
        )

    if as_of:
        date.fromisoformat(as_of)

    asset = asset.upper()

    config = load_config()
    quote = reference_currency(config)

    history = load_history(
        config,
        asset,
        quote,
        cutoff=as_of,
    )

    channel = find_channel(
        asset,
        channel_label,
        as_of=as_of,
    )

    rows = select_channel_rows(
        history,
        channel,
    )

    result = estimate(
        rows,
        target=target,
    )

    data = build_layer_data(
        asset=asset,
        quote=quote,
        channel=channel,
        rows=rows,
        result=result,
        target=target,
        budget=budget,
        reality_trimfactor=reality_trimfactor,
    )

    return data


def render_report(data):
    return Template(
        REPORT_TEMPLATE
    ).render(**data).strip()


def render_json(data):
    return json.dumps(
        data,
        indent=2,
        ensure_ascii=False,
    )


def threejs_payload(data):
    """
    Keep the Three.js payload deliberately smaller than the full
    analytical JSON record.

    The GUI can still fetch/import the full JSON if it needs it.
    """
    return {
        "layer_type": "estimate_trades",
        "asset": data["asset"],
        "reference_currency": data["reference_currency"],
        "channel": data["channel"]["label"],
        "title": "Estimate Trades",
        "message": (
            "Chasing Trading Target of "
            + (
                f"${data['returns']['reality_trimmed']:,.2f}"
                if data["returns"]["reality_trimmed"] is not None
                else "an estimated channel return"
            )
            + f" for {data['asset']} in the current channel"
        ),
        "target_return": data["returns"]["reality_trimmed"],
        "remaining_trades": data["trades"]["remaining"],
        "buys_remaining": data["trades"]["buys_remaining"],
        "sells_remaining": data["trades"]["sells_remaining"],
        "median_range_pct": data["volatility"]["median_range_pct"],
    }


def render_threejs(data):
    payload_json = json.dumps(
        threejs_payload(data),
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return Template(
        THREEJS_TEMPLATE
    ).render(
        payload_json=payload_json
    ).strip()



def make_report(
    asset,
    channel_label="ACTIVE",
    as_of=None,
    target=DEFAULT_TRADES,
    budget=None,
    reality_trimfactor=DEFAULT_REALITY_TRIMFACTOR,
):
    """
    Return the standard rvcrypto report envelope for server/API use.
    """
    data = analyse(
        asset=asset,
        channel_label=channel_label,
        as_of=as_of,
        target=target,
        budget=budget,
        reality_trimfactor=reality_trimfactor,
    )

    return {
        "schema": "rvcrypto.report.v1",
        "type": "estimatetrades",
        "asset": data["asset"],
        "reference_currency":
            data["reference_currency"],

        "report": render_report(data),

        "json": data,

        # The existing --threejs renderer uses
        # ADD_ESTIMATE_TRADES_LAYER, which CryptoGraph does not yet
        # implement. Keep this API-safe for now.
        "display": None,

        "image": None,
    }


def output_topic(config, mode):
    if mode == "json":
        return config.get(
            "estimatetrades",
            "json_topic",
            fallback=DEFAULT_JSON_TOPIC,
        )

    if mode == "threejs":
        return config.get(
            "estimatetrades",
            "threejs_topic",
            fallback=DEFAULT_THREEJS_TOPIC,
        )

    return config.get(
        "estimatetrades",
        "topic",
        fallback=DEFAULT_TOPIC,
    )


def build_parser():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "asset",
    )

    parser.add_argument(
        "--channel",
        default="ACTIVE",
    )

    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
    )

    parser.add_argument(
        "--target",
        type=int,
        default=DEFAULT_TRADES,
        help=(
            "Requested baseline number of trade opportunities "
            f"(default: {DEFAULT_TRADES})"
        ),
    )

    parser.add_argument(
        "--budget",
        type=float,
        metavar="DOLLARS",
    )

    parser.add_argument(
        "--reality-trimfactor",
        type=float,
        default=DEFAULT_REALITY_TRIMFACTOR,
        metavar="FACTOR",
        help=(
            "Fraction of theoretical best-case return retained "
            f"(default: {DEFAULT_REALITY_TRIMFACTOR})"
        ),
    )

    mode = parser.add_mutually_exclusive_group()

    mode.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON instead of the standard report.",
    )

    mode.add_argument(
        "--threejs",
        action="store_true",
        help="Output the Jinja2-rendered Three.js Estimate Trades layer.",
    )

    parser.add_argument(
        "--stream",
        action="store_true",
        help="Send selected output through tools.lan.",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        data = analyse(
            asset=args.asset,
            channel_label=args.channel,
            as_of=args.date,
            target=args.target,
            budget=args.budget,
            reality_trimfactor=args.reality_trimfactor,
        )

        if args.json:
            mode = "json"
            output = render_json(data)
        elif args.threejs:
            mode = "threejs"
            output = render_threejs(data)
        else:
            mode = "report"
            output = render_report(data)

        if args.stream:
            config = load_config()

            lan.stream(
                output,
                config=config,
                topic=output_topic(
                    config,
                    mode,
                ),
            )
        else:
            print(output)

    except (
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        statistics.StatisticsError,
        RuntimeError,
    ) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
