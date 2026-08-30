#!/usr/bin/env python3
"""
ladder.py

Build a ladder of trade price-levels for a BUY or SELL instruction,
each with a confidence percentage and a margin-of-error cushion.

Design
------
A ladder is a list of price levels to place orders at. For a SELL
(taking profit), levels sit ABOVE the current price; for a BUY
(entering a position), levels sit BELOW the current price.

Levels come from the stored daily-peak-markers in each asset's data
file (see pricelevels.py). Each level reports:

    price           - the level itself (the order price)
    confidence_pct  - estimated probability this level is reached
    range_low       - price - margin (valid order range, lower bound)
    range_high      - price + margin (valid order range, upper bound)

Margin of error
---------------
Exchanges may not fill orders that drift even a few cents. A fixed
margin (default 2%) creates a cushion range around each level. Ranges
are guaranteed non-overlapping: when two levels are closer than the
margin would allow, the bounds are clamped so the ladder stays ordered.

Confidence model
----------------
For SELL (profit-taking above):
    - Uses stored peaks above current price, ranked by reach
      probability from pricelevels.compute_targets.
    - The nearest/strongest magnet has the highest confidence.

For BUY (entries below):
    - Uses stored peaks below current price as support references.
    - Confidence decreases with depth below current price (deeper
      support is less likely to be touched in a normal pullback).

If there are fewer stored peaks than the requested ladder size, the
ladder is back-filled with price-scaled levels whose confidence decays
to a small floor, so the ladder is always complete.

DISCLAIMER: Not financial advice. Use at your own risk.
"""

import argparse
import configparser
import json
from pathlib import Path

import pricelevels


BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.ini"

DEFAULT_LEVELS = 6
DEFAULT_MARGIN_PCT = 2.0
MIN_CONFIDENCE = 5.0     # floor confidence (%) for back-filled levels
FILL_STEP_PCT = 1.5      # spacing (%) for back-filled levels


def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def get_data_dir(config):
    path = Path(
        config.get("storage", "data_dir", fallback="data")
    )
    if not path.is_absolute():
        path = BASE / path
    return path


def get_reference(config):
    return config.get(
        "market-data",
        "reference_currency",
        fallback="USDT",
    ).strip().upper()


def _clamp_to_overlap(range_low, range_high, prev_high, margin_pct):
    """Prevent neighbouring ranges from overlapping with the previous."""
    if prev_high is None:
        return range_low, range_high
    if range_low <= prev_high:
        range_low = prev_high + 1e-9
        range_high = max(range_high, range_low)
    return range_low, range_high


def _confidence_for_depth(side, depth):
    """Confidence (%) from a level's fractional distance from current price.

    Shallower levels (closer to current price) are more likely to be
    reached, so confidence decays with depth.
    """
    base = 55.0
    decay = 1.0 / (1.0 + depth * 12.0)
    conf = base * decay
    return round(max(MIN_CONFIDENCE, min(conf, 55.0)), 1)


def build_ladder(
    config,
    asset,
    side,
    levels=DEFAULT_LEVELS,
    margin_pct=DEFAULT_MARGIN_PCT,
):
    """Build the ladder for `asset` for BUY or SELL.

    Returns a dict:
        {
          "asset": asset,
          "side": "SELL" | "BUY",
          "current_price": ...,
          "margin_pct": ...,
          "levels": [ {price, confidence_pct, range_low, range_high}, ... ]
        }
    """
    data_dir = get_data_dir(config)
    reference = get_reference(config)

    doc, peaks = pricelevels.load_peaks(data_dir, asset, reference)
    rows = doc.get("data", [])
    if not rows:
        raise ValueError(f"No data for {asset}/{reference}")
    current_price = rows[-1]["close"]

    targets = pricelevels.compute_targets(
        peaks, rows, current_price,
        pricelevels.DEFAULT_SPIKE_PROB,
        pricelevels.DEFAULT_MIN_GAIN,
        pricelevels.DEFAULT_MAX_GAIN,
    )

    side = side.upper()
    if side == "SELL":
        # Profit-taking: peaks above current price, ranked by probability.
        # The nearest strong magnet is the primary profit target.
        pool = sorted(
            [t for t in targets if t["peak_price"] > current_price],
            key=lambda x: x["probability_pct"], reverse=True,
        )
        ladder = [{
            "price": t["peak_price"],
            "confidence_pct": round(t["probability_pct"], 1),
            "source": "peak",
            "source_date": t["peak_date"],
        } for t in pool]

        # Back-fill above current price with decaying confidence, only for
        # levels we lack. Place them at the low-confidence tail (furthest
        # from current) so real peaks keep priority.
        if len(ladder) < levels:
            far = ladder[-1]["price"] if ladder else current_price
            k = 1
            while len(ladder) < levels:
                price = far * (1 + k * FILL_STEP_PCT / 100.0)
                depth = (price - current_price) / current_price
                conf = _confidence_for_depth("SELL", depth)
                # Never outrank real peaks for the same ballpark
                if ladder and conf >= ladder[-1]["confidence_pct"]:
                    conf = max(MIN_CONFIDENCE, ladder[-1]["confidence_pct"] * 0.7)
                ladder.append({
                    "price": price,
                    "confidence_pct": round(conf, 1),
                    "source": "derived",
                    "source_date": None,
                })
                k += 1

    elif side == "BUY":
        # Support entries below current price, shallower = stronger.
        pool = sorted(
            [t for t in targets if t["peak_price"] < current_price],
            key=lambda x: x["peak_price"], reverse=True,
        )
        if pool:
            pool = pool[:levels]
        ladder = []
        for t in pool:
            depth = (current_price - t["peak_price"]) / current_price
            ladder.append({
                "price": t["peak_price"],
                "confidence_pct": _confidence_for_depth("BUY", depth),
                "source": "support_peak",
                "source_date": t["peak_date"],
            })

        # Back-fill below current price with decaying confidence.
        if len(ladder) < levels:
            near = ladder[-1]["price"] if ladder else current_price
            k = 1
            while len(ladder) < levels:
                price = near * (1 - k * FILL_STEP_PCT / 100.0)
                depth = (current_price - price) / current_price
                conf = _confidence_for_depth("BUY", depth)
                ladder.append({
                    "price": price,
                    "confidence_pct": round(conf, 1),
                    "source": "derived",
                    "source_date": None,
                })
                k += 1

    else:
        raise ValueError(f"side must be BUY or SELL, got {side!r}")

    # Sort ascending by price, keep the ladder to `levels` entries, then
    # assign non-overlapping margin ranges.
    ladder.sort(key=lambda x: x["price"])
    ladder = ladder[-levels:] if side == "BUY" else ladder[:levels]

    margin = margin_pct / 100.0
    prev_high = None
    for l in ladder:
        low = l["price"] * (1 - margin)
        high = l["price"] * (1 + margin)
        low, high = _clamp_to_overlap(low, high, prev_high, margin_pct)
        l["range_low"] = round(low, 8)
        l["range_high"] = round(high, 8)
        l["price"] = round(l["price"], 8)
        prev_high = high

    return {
        "schema": "rvcrypto.ladder.v1",
        "type": "ladder",
        "asset": asset,
        "side": side,
        "reference_currency": reference,
        "current_price": current_price,
        "margin_pct": margin_pct,
        "levels": ladder,
    }


# ---------------------------------------------------------------------------
# CLI + rendering
# ---------------------------------------------------------------------------

def format_price(value):
    if value is None:
        return "      —"
    if value >= 100:
        return f"{value:.2f}"
    if value >= 1:
        return f"{value:.4f}"
    if value >= 0.01:
        return f"{value:.6f}"
    return f"{value:.8f}"


def render_ladder(ladder):
    side = ladder["side"]
    direction = "up" if side == "SELL" else "down"
    print()
    print(f"PRICE LADDER: {ladder['asset']}/{ladder['reference_currency']} "
          f"({side} - ladder goes {direction})")
    print("=" * 78)
    print(f"  Current price:     {format_price(ladder['current_price'])}")
    print(f"  Margin of error:   ±{ladder['margin_pct']}% per level")
    print()
    print(f"  {'#':<4} {'PRICE':<16} {'CONFIDENCE':<12} {'ORDER RANGE'}")
    print("  " + "-" * 70)
    for i, l in enumerate(ladder["levels"], 1):
        marker = ""
        if l.get("source") == "peak":
            marker = f"  [peak {l.get('source_date','')}]"
        elif l.get("source") == "support_peak":
            marker = f"  [support {l.get('source_date','')}]"
        print(
            f"  {i:<4} "
            f"{format_price(l['price']):<16} "
            f"{l['confidence_pct']:>5.1f}%{'':<6} "
            f"{format_price(l['range_low'])} – {format_price(l['range_high'])}{marker}"
        )
    print()


def build_parser():
    parser = argparse.ArgumentParser(
        description="Build a price-ladder of trade levels with confidence "
                    "and margin-of-error ranges.",
    )
    parser.add_argument("asset", help="Asset symbol, e.g. MMT.")
    parser.add_argument("side", choices=["BUY", "SELL"],
                        help="Direction of the trade instruction.")
    parser.add_argument(
        "--levels", type=int, default=DEFAULT_LEVELS,
        help=f"Number of ladder levels (default: {DEFAULT_LEVELS}).",
    )
    parser.add_argument(
        "--margin", type=float, default=DEFAULT_MARGIN_PCT,
        help=f"Margin of error %% per level (default: {DEFAULT_MARGIN_PCT}).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit the ladder as JSON.",
    )
    return parser


def main():
    args = build_parser().parse_args()
    config = load_config()
    ladder = build_ladder(
        config, args.asset.upper(), args.side,
        levels=args.levels, margin_pct=args.margin,
    )
    if args.json:
        print(json.dumps(ladder, indent=2))
    else:
        render_ladder(ladder)


if __name__ == "__main__":
    main()
