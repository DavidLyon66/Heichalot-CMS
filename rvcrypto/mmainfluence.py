#!/usr/bin/env python3
"""
mmainfluence.py

Estimate moving-average influence for a crypto asset using the same
basic SMA convention commonly used by exchange charting tools:

    SMA(N) = arithmetic mean of the previous N closing prices,
             including the current row.

Typical use:

    python3 mmainfluence.py MMT

or:

    python3 mmainfluence.py MMT ACTIVE

or for a historical channel:

    python3 mmainfluence.py MMT "July Triangle"

The current open channel is selected when the channel argument is
omitted or is ACTIVE.


Purpose
-------

This tool does NOT predict direction.

It estimates whether a spike-like change is:

    LITTLE CHANGE POSSIBLE
    LIGHT CHANGE POSSIBLE
    MEDIUM CHANGE POSSIBLE
    STRONG CHANGE POSSIBLE

"Change" means unusually large price movement / spike potential,
not specifically UP or DOWN.

A separate bias is reported:

    BELOW MA CLUSTER
    ABOVE MA CLUSTER
    NEUTRAL

That bias is descriptive only.


Moving averages
---------------

Default SMA periods:

    7
    25
    99

They can be overridden:

    python3 mmainfluence.py MMT --ma 7 25 99

or:

    python3 mmainfluence.py MMT --ma 5 20 50


Core measurements
-----------------

For each day with enough history:

    SMA7
    SMA25
    SMA99

The MA cluster centre is the median of the selected moving averages.

The MA cluster spread is:

    (max(MAs) - min(MAs)) / cluster_centre * 100

The price displacement is:

    (close - cluster_centre) / cluster_centre * 100

The current day's absolute price displacement is compared against the
historical distribution of absolute displacement values.

The current MA spread is also compared against the historical
distribution of MA spreads.


Influence score
---------------

The first version intentionally uses a simple percentile-style score.

Two components are measured:

    displacement_rank
        how extreme the absolute price-vs-cluster distance is

    spread_rank
        how unusually compressed the moving-average cluster is

Compression influence is inverted:

    tighter-than-usual MA cluster
        contributes more potential influence

    wider-than-usual MA cluster
        contributes less compression influence

The combined score is:

    70% price displacement extremeness
    30% MA compression extremeness

This weighting is deliberately provisional.

It should be treated as an experimental template that can later be
calibrated against known spike markers in *_spikes.json.


Classification
--------------

Combined score:

    < 0.50      LITTLE CHANGE POSSIBLE
    < 0.70      LIGHT CHANGE POSSIBLE
    < 0.90      MEDIUM CHANGE POSSIBLE
    >= 0.90     STRONG CHANGE POSSIBLE

These are relative-to-history classifications rather than absolute
market claims.


Channel usage
-------------

The selected channel determines the reporting window, but SMA values
may use earlier market history before the channel start.

That matters especially for SMA99.


Scope
-----

This tool does not:

    detect crossovers
    produce buy/sell instructions
    forecast exact prices
    calculate EMA
    use remote-viewing
    use on-chain data

Those can remain separate programs.
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
DEFAULT_MA_PERIODS = [7, 25, 99]


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
    """Load and minimally validate close history."""
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
                "close": float(row["close"]),
            })
        except (KeyError, TypeError, ValueError):
            continue

    usable.sort(key=lambda row: row["date"])

    if not usable:
        raise ValueError(
            f"No usable close rows found in {path}."
        )

    return usable


def simple_moving_average(values, period):
    """
    Return SMA series aligned to values.

    Rows without enough history return None.
    """
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


def build_ma_rows(history, periods):
    """
    Calculate all requested SMAs plus cluster statistics.
    """
    closes = [
        row["close"]
        for row in history
    ]

    ma_series = {
        period: simple_moving_average(
            closes,
            period,
        )
        for period in periods
    }

    rows = []

    for index, row in enumerate(history):
        mas = {
            period: ma_series[period][index]
            for period in periods
        }

        if any(
            value is None
            for value in mas.values()
        ):
            continue

        ma_values = list(mas.values())
        cluster_centre = statistics.median(
            ma_values
        )

        if cluster_centre == 0:
            continue

        cluster_spread_pct = (
            (max(ma_values) - min(ma_values))
            / cluster_centre
            * 100.0
        )

        displacement_pct = (
            (row["close"] - cluster_centre)
            / cluster_centre
            * 100.0
        )

        rows.append({
            "date": row["date"],
            "close": row["close"],
            "mas": mas,
            "cluster_centre": cluster_centre,
            "cluster_spread_pct": cluster_spread_pct,
            "displacement_pct": displacement_pct,
            "abs_displacement_pct": abs(
                displacement_pct
            ),
        })

    return rows


def select_channel_rows(ma_rows, channel):
    """Select MA rows falling inside the requested channel."""
    start_date = channel.get("start_date")
    end_date = channel.get("end_date")

    if not start_date:
        raise ValueError(
            "Channel does not contain start_date."
        )

    selected = [
        row
        for row in ma_rows
        if row["date"] >= start_date
        and (
            end_date is None
            or row["date"] <= end_date
        )
    ]

    if not selected:
        raise ValueError(
            "No moving-average rows fall inside this channel. "
            "There may not be enough history for the longest MA."
        )

    return selected


def empirical_rank(values, current):
    """
    Return approximate empirical rank in range 0..1.

    Equal values count as part of the lower/equal group.
    """
    if not values:
        return 0.0

    count = sum(
        value <= current
        for value in values
    )

    return count / len(values)


def calculate_influence(all_ma_rows, current):
    """
    Calculate provisional influence score.

    Displacement extremeness:
        high empirical rank = unusually far from MA cluster

    Compression extremeness:
        low spread rank = unusually tight cluster
        therefore compression score = 1 - spread_rank
    """
    displacement_values = [
        row["abs_displacement_pct"]
        for row in all_ma_rows
    ]

    spread_values = [
        row["cluster_spread_pct"]
        for row in all_ma_rows
    ]

    displacement_rank = empirical_rank(
        displacement_values,
        current["abs_displacement_pct"],
    )

    spread_rank = empirical_rank(
        spread_values,
        current["cluster_spread_pct"],
    )

    compression_score = (
        1.0 - spread_rank
    )

    combined_score = (
        0.70 * displacement_rank
        + 0.30 * compression_score
    )

    return {
        "displacement_rank": displacement_rank,
        "spread_rank": spread_rank,
        "compression_score": compression_score,
        "combined_score": combined_score,
    }


def classify_change(score):
    """Convert influence score into qualitative output."""
    if score < 0.50:
        return "LITTLE CHANGE POSSIBLE"

    if score < 0.70:
        return "LIGHT CHANGE POSSIBLE"

    if score < 0.90:
        return "MEDIUM CHANGE POSSIBLE"

    return "STRONG CHANGE POSSIBLE"


def classify_bias(displacement_pct):
    """Describe price location relative to MA cluster."""
    if abs(displacement_pct) < 1.0:
        return "NEUTRAL"

    if displacement_pct > 0:
        return "ABOVE MA CLUSTER"

    return "BELOW MA CLUSTER"


def fmt_price(value):
    """Format low-value crypto prices cleanly."""
    if abs(value) >= 100:
        return f"{value:.2f}"

    if abs(value) >= 1:
        return f"{value:.4f}"

    return f"{value:.6f}"


def fmt_pct(value, signed=False):
    """Format percent."""
    if signed:
        return f"{value:+.1f}%"

    return f"{value:.1f}%"


def fmt_rank(value):
    """Format rank as percentage."""
    return f"{value * 100.0:.0f}th percentile"


def print_report(
    asset,
    reference,
    channel,
    periods,
    current,
    influence,
):
    """Print mmainfluence Default report."""
    label = channel.get(
        "label",
        "(unlabelled)",
    )

    status = (
        "ACTIVE"
        if channel.get("end_date") is None
        else "HISTORICAL"
    )

    end_date = (
        channel.get("end_date")
        or current["date"]
    )

    print(f"{asset}/{reference}")
    print(f"Channel: {label}")
    print(
        f"Period:  {channel['start_date']} -> "
        f"{end_date}  [{status}]"
    )
    print()

    print("CURRENT MOVING AVERAGES")
    print("-----------------------")
    print(
        f"Close:                    "
        f"{fmt_price(current['close'])}"
    )

    for period in periods:
        print(
            f"SMA{period:<3}:                  "
            f"{fmt_price(current['mas'][period])}"
        )

    print()
    print(
        f"MA cluster centre:        "
        f"{fmt_price(current['cluster_centre'])}"
    )
    print(
        f"Price vs cluster:         "
        f"{fmt_pct(current['displacement_pct'], signed=True)}"
    )
    print(
        f"MA cluster spread:        "
        f"{fmt_pct(current['cluster_spread_pct'])}"
    )
    print(
        f"Bias:                     "
        f"{classify_bias(current['displacement_pct'])}"
    )
    print()

    print("INFLUENCE")
    print("---------")
    print(
        f"Price displacement rank:  "
        f"{fmt_rank(influence['displacement_rank'])}"
    )
    print(
        f"MA spread rank:           "
        f"{fmt_rank(influence['spread_rank'])}"
    )
    print(
        f"Compression influence:    "
        f"{influence['compression_score']:.2f}"
    )
    print(
        f"Combined influence score: "
        f"{influence['combined_score']:.2f}"
    )
    print()
    print(
        f"Assessment:               "
        f"{classify_change(influence['combined_score'])}"
    )
    print()
    print(
        "Note: CHANGE refers to spike-like movement potential, "
        "not a prediction of direction."
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Estimate moving-average influence and spike potential."
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
        "--ma",
        nargs="+",
        type=int,
        default=DEFAULT_MA_PERIODS,
        metavar="N",
        help=(
            "SMA periods "
            "(default: 7 25 99)"
        ),
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    periods = sorted(set(args.ma))

    if len(periods) < 2:
        parser.error(
            "--ma requires at least two periods."
        )

    if any(
        period < 1
        for period in periods
    ):
        parser.error(
            "All MA periods must be positive integers."
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

        all_ma_rows = build_ma_rows(
            history,
            periods,
        )

        if not all_ma_rows:
            raise ValueError(
                "Not enough history to calculate "
                f"SMA{max(periods)}."
            )

        channel_ma_rows = select_channel_rows(
            all_ma_rows,
            channel,
        )

        current = channel_ma_rows[-1]

        influence = calculate_influence(
            all_ma_rows,
            current,
        )

        print_report(
            asset=asset,
            reference=reference,
            channel=channel,
            periods=periods,
            current=current,
            influence=influence,
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
