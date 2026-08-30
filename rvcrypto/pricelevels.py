#!/usr/bin/env python3
"""
pricelevels.py

Manage stored price-peak levels (support/resistance magnets) and use
them to estimate tradable spike-target price points.

Background
----------
Prices that spike often return to previous peaks (swap/liquidity
pools, stop clusters, breakout points). Instead of re-detecting peaks
algorithmically every run (fragile, asset-specific), this tool stores
verified peak levels in each asset's data file (daily-peak-markers)
covering roughly the last 3 months, then uses those stored levels for
trading decisions.

Two workflow stages:
  1. STORE peaks  -- scan the OHLCV history once, review, and persist
                     the significant prior highs into the data file.
  2. TRADE targets-- read the stored peaks and compute the probability
                     a spike transports price up to each one, ranked,
                     tuned for tradable 10-20% moves.

Storage
-------
Peak levels live in each ASSET_REFERENCE.json under the
'daily-peak-markers' field (matching the existing marker convention):

    "daily-peak-markers": [
        {"date": "2026-08-05", "price": 0.248300, "kind": "daily",
         "note": "Aug 2026 high"}
    ]

Peak marker fields:
    date   - ISO date of the peak bar
    price  - the high at the peak
    kind   - 'daily' (or later weekly/monthly)
    note   - optional human annotation
    verified - bool, whether a human confirmed it

Usage
-----

Scan & store peaks (recommended: do this once per week):

    # Show peaks that would be detected, without writing
    python3 pricelevels.py MMT --scan --dry-run

    # Detect and store peaks from the last 90 days
    python3 pricelevels.py MMT --scan --days 90

    # Detect and store, but prompt to verify each candidate
    python3 pricelevels.py MMT --scan --days 90 --verify

Manual peak management:

    python3 pricelevels.py MMT --peaks            # list stored peaks
    python3 pricelevels.py MMT --add 0.2483 2026-08-05 "Aug high"
    python3 pricelevels.py MMT --remove 0.2483
    python3 pricelevels.py MMT --clear-peaks

Trade targets from stored peaks:

    python3 pricelevels.py MMT --targets
    python3 pricelevels.py MMT --targets --min-gain 10 --max-gain 20
    python3 pricelevels.py MMT --targets --json

DISCLAIMER: Not financial advice. Use at your own risk.
"""

import argparse
import configparser
import json
from datetime import datetime, timezone
from pathlib import Path

import spikedetect


BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.ini"

PEAK_FIELD = "daily-peak-markers"
DEFAULT_DAYS = 90
DEFAULT_SPIKE_PROB = 40
PEAK_WINDOW = 7          # detection window for local maxima
MIN_PEAK_SEPARATION = 0.03  # peaks closer than 3% are merged
DEFAULT_MIN_GAIN = 8.0
DEFAULT_MAX_GAIN = 25.0
LEVEL_CAP = 10


def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def get_data_dir(config):
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


def get_reference(config):
    return config.get(
        "market-data",
        "reference_currency",
        fallback="USDT",
    ).strip().upper()


def asset_file_path(data_dir, asset, reference):
    return data_dir / f"{asset}_{reference}.json"


def load_asset_document(data_dir, asset, reference):
    """Load the full data file document (not just rows)."""
    path = asset_file_path(data_dir, asset, reference)
    if not path.exists():
        raise FileNotFoundError(f"No data file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_asset_document(data_dir, asset, reference, document):
    path = asset_file_path(data_dir, asset, reference)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2)
        handle.write("\n")
    return path


def load_peaks(data_dir, asset, reference):
    doc = load_asset_document(data_dir, asset, reference)
    peaks = doc.get(PEAK_FIELD, [])
    if not isinstance(peaks, list):
        peaks = []
    return doc, peaks


def save_peaks(data_dir, asset, reference, doc, peaks):
    # Remove stale peaks older than a cap to avoid unbounded growth,
    # but keep them beyond the 3-month window if verified.
    doc[PEAK_FIELD] = peaks
    return save_asset_document(data_dir, asset, reference, doc)


def format_price(value):
    if value is None:
        return "      —"
    if value >= 100:
        return f"{value:.2f}"
    elif value >= 1:
        return f"{value:.4f}"
    elif value >= 0.01:
        return f"{value:.6f}"
    else:
        return f"{value:.8f}"


# ---------------------------------------------------------------------------
# Scanning / detection
# ---------------------------------------------------------------------------

def detect_candidate_peaks(rows, lookback_days, window=PEAK_WINDOW):
    """Detect significant local highs over the last `lookback_days`.

    Working retrospectively from the latest bar, find bars whose high
    is a local maximum over a surrounding window. Returns candidates
    sorted newest-first.
    """
    n = len(rows)
    start = max(0, n - lookback_days)
    candidates = []

    for i in range(start + window, n - 1):
        lo = max(start, i - window)
        hi = min(n, i + window)
        window_highs = [rows[j]["high"] for j in range(lo, hi)]

        if rows[i]["high"] >= max(window_highs) * 0.998:
            candidates.append({
                "date": rows[i]["date"],
                "price": rows[i]["high"],
                "index": i,
                "kind": "daily",
                "verified": False,
                "note": "",
            })

    # Merge near-identical peaks (within MIN_PEAK_SEPARATION)
    merged = []
    for cand in candidates:
        merged_into = None
        for m in merged:
            if abs(m["price"] - cand["price"]) / m["price"] <= MIN_PEAK_SEPARATION:
                merged_into = m
                break
        if merged_into is not None:
            # Keep the higher price and latest date
            if cand["price"] > merged_into["price"]:
                merged_into["price"] = cand["price"]
                merged_into["date"] = cand["date"]
                merged_into["index"] = cand["index"]
        else:
            merged.append(dict(cand))

    merged.sort(key=lambda x: x["date"], reverse=True)
    return merged


def scan_and_store(config, asset, days, dry_run, verify):
    """Detect peaks over `days` and store them into the data file."""
    data_dir = get_data_dir(config)
    reference = get_reference(config)

    doc = load_asset_document(data_dir, asset, reference)
    rows = doc.get("data", [])
    if not rows:
        raise ValueError(f"No data for {asset}/{reference}")

    candidates = detect_candidate_peaks(rows, days)

    existing = [p.get("price") for p in doc.get(PEAK_FIELD, [])]

    # Keep only candidates not already stored
    new_peaks = []
    for cand in candidates:
        already = False
        for e in existing:
            if abs(e - cand["price"]) / e <= MIN_PEAK_SEPARATION:
                already = True
                break
        if not already:
            new_peaks.append(cand)

    if dry_run:
        print(f"DRY RUN ({asset}/{reference}) - {len(new_peaks)} candidate peak(s) "
              f"found in last {days} days:")
        print(f"  {'DATE':<12} {'PRICE':<14} {'NOTE'}")
        print("  " + "-" * 44)
        for p in new_peaks:
            print(f"  {p['date']:<12} {format_price(p['price']):<14}")
        print()
        print("  (nothing written - use without --dry-run to store)")
        return []

    # Optionally verify each
    to_store = []
    for p in new_peaks:
        if verify:
            prompt = (f"Store peak {format_price(p['price'])} "
                      f"from {p['date']}? [y/N]: ")
            answer = input(prompt).strip().lower()
            if answer in ("y", "yes"):
                p["verified"] = True
                to_store.append(p)
        else:
            to_store.append(p)

    if not to_store:
        print(f"{asset}/{reference}: no new peaks to store.")
        return []

    doc.setdefault(PEAK_FIELD, []).extend(to_store)
    path = save_asset_document(data_dir, asset, reference, doc)

    print(f"{asset}/{reference}: stored {len(to_store)} new peak(s) "
          f"in {path.name}")
    for p in to_store:
        marker = f" [verified]" if p.get("verified") else ""
        print(f"  {p['date']}  {format_price(p['price'])}{marker}")

    return to_store


# ---------------------------------------------------------------------------
# Peak list management
# ---------------------------------------------------------------------------

def list_peaks(config, asset):
    data_dir = get_data_dir(config)
    reference = get_reference(config)
    doc, peaks = load_peaks(data_dir, asset, reference)

    if not peaks:
        print(f"{asset}/{reference}: no stored peaks. "
              f"Run --scan to detect some, or --add to add manually.")
        return

    current_price = doc["data"][-1]["close"] if doc.get("data") else None

    print(f"STORED PEAKS: {asset}/{reference}")
    print("=" * 60)
    print(f"  Current price: {format_price(current_price)}")
    print(f"  {'DATE':<12} {'PRICE':<14} {'GAIN':<10} {'VERIFIED':<9} {'NOTE'}")
    print("  " + "-" * 56)

    for p in sorted(peaks, key=lambda x: x.get("date", "")):
        gain = ""
        if current_price and p.get("price", 0) > 0:
            g = ((p["price"] - current_price) / current_price) * 100
            gain = f"+{g:.1f}%"
        verified = "yes" if p.get("verified") else "no"
        note = p.get("note", "")
        print(
            f"  {p.get('date',''):<12} "
            f"{format_price(p.get('price')):<14} "
            f"{gain:<10} "
            f"{verified:<9} "
            f"{note}"
        )
    print()


def add_peak(config, asset, price, date_str, note):
    data_dir = get_data_dir(config)
    reference = get_reference(config)
    doc, peaks = load_peaks(data_dir, asset, reference)

    price_f = float(price)
    peak = {
        "date": date_str,
        "price": price_f,
        "kind": "daily",
        "verified": True,
        "note": note or "",
    }
    peaks.append(peak)
    save_peaks(data_dir, asset, reference, doc, peaks)
    print(f"{asset}/{reference}: added peak {format_price(price_f)} at {date_str}")


def remove_peak(config, asset, price):
    data_dir = get_data_dir(config)
    reference = get_reference(config)
    doc, peaks = load_peaks(data_dir, asset, reference)

    price = float(price)
    remaining = [p for p in peaks if abs(p.get("price") - price) / price > MIN_PEAK_SEPARATION]

    if len(remaining) == len(peaks):
        print(f"{asset}/{reference}: no peak found near {format_price(price)}")
        return

    save_peaks(data_dir, asset, reference, doc, remaining)
    print(f"{asset}/{reference}: removed peak near {format_price(price)}")


def clear_peaks(config, asset):
    data_dir = get_data_dir(config)
    reference = get_reference(config)
    doc, peaks = load_peaks(data_dir, asset, reference)

    save_peaks(data_dir, asset, reference, doc, [])
    print(f"{asset}/{reference}: cleared all stored peaks.")


# ---------------------------------------------------------------------------
# Trading targets from stored peaks
# ---------------------------------------------------------------------------

def compute_targets(peaks, rows, current_price, spike_prob, min_gain, max_gain):
    """Compute probability a spike reaches each stored peak.

    Factors:
      - distance from current (bell-curved around the tradable band)
      - recency of last touch (recent peaks are 'active' magnets)
      - visit strength (how often price came back to that region)

    Returns targets sorted by probability descending, each with its
    projected gain.
    """
    n = len(rows)
    results = []

    for peak in peaks:
        price = peak.get("price")
        if not price or price <= current_price:
            continue

        gain_pct = ((price - current_price) / current_price) * 100

        # Recency: peaks touched within last ~45 days are active
        recency_days = n
        if peak.get("date"):
            for i in range(n - 1, -1, -1):
                if rows[i]["date"] == peak["date"]:
                    recency_days = n - 1 - i
                    break
        recency_factor = max(0.0, 1.0 - (recency_days / 90.0))
        if recency_days > 180:
            recency_factor *= 0.5

        # Distance factor, bell-shaped around the tradable band
        if min_gain <= gain_pct <= max_gain:
            mid = (min_gain + max_gain) / 2.0
            spread = (max_gain - min_gain)
            distance_factor = 2.71828 ** -(((gain_pct - mid) / (spread * 0.45)) ** 2)
        elif gain_pct < min_gain:
            distance_factor = 0.7
        else:
            distance_factor = 2.71828 ** (-(gain_pct - max_gain) / 10.0)

        # Visit strength: how many stored peaks sit near this one
        visit_count = 1
        for other in peaks:
            if other is not peak and other.get("price"):
                if abs(other["price"] - price) / price <= MIN_PEAK_SEPARATION:
                    visit_count += 1
        visit_factor = min(1.0, visit_count / 3.0)

        # Composite (weight distance most)
        raw = (
            0.55 * distance_factor
            + 0.30 * recency_factor
            + 0.15 * visit_factor
        )

        prob = raw * (spike_prob / 100.0) * 100.0
        prob = min(90.0, max(0.0, prob))

        results.append({
            "peak_date": peak.get("date", ""),
            "peak_price": round(price, 8),
            "gain_pct": round(gain_pct, 1),
            "recency_days": recency_days,
            "visits": visit_count,
            "verified": bool(peak.get("verified")),
            "note": peak.get("note", ""),
            "probability_pct": round(prob, 1),
        })

    results.sort(key=lambda x: x["probability_pct"], reverse=True)
    return results


def render_targets(config, asset, min_gain, max_gain, spike_prob, cap):
    data_dir = get_data_dir(config)
    reference = get_reference(config)
    doc, peaks = load_peaks(data_dir, asset, reference)

    rows = doc.get("data", [])
    if not rows:
        raise ValueError(f"No data for {asset}/{reference}")
    current_price = rows[-1]["close"]

    targets = compute_targets(peaks, rows, current_price, spike_prob, min_gain, max_gain)

    print()
    print(f"SPIKE TRADE TARGETS: {asset}/{reference}")
    print("=" * 66)
    print(f"  Current price: {format_price(current_price)}")
    print(f"  Target band: +{min_gain:.0f}% to +{max_gain:.0f}%")
    print(f"  Spike base probability: {spike_prob:.0f}%")
    print()

    in_band = [t for t in targets if min_gain <= t["gain_pct"] <= max_gain]
    other = [t for t in targets if not (min_gain <= t["gain_pct"] <= max_gain)]

    print("  PRIMARY TRADE TARGETS (within band):")
    print(f"  {'PEAK':<15} {'TARGET':<14} {'GAIN':<8} {'RECENCY':<9} {'PROB':<8} {'NOTE'}")
    print("  " + "-" * 64)
    if not in_band:
        print("  (no stored peak currently within the band)")
        print()
    for t in in_band[:cap]:
        rec = f"{t['recency_days']}d"
        print(
            f"  {t['peak_date']:<15} "
            f"{format_price(t['peak_price']):<14} "
            f"+{t['gain_pct']:>4.1f}%{'':<3} "
            f"{rec:<9} "
            f"{t['probability_pct']:>4.1f}%{'':<3} "
            f"{t['note']}"
        )
    print()

    if other:
        print("  OTHER STORED PEAKS (outside band):")
        print(f"  {'PEAK':<15} {'TARGET':<14} {'GAIN':<8} {'RECENCY':<9} {'PROB':<8}")
        print("  " + "-" * 52)
        for t in other[:cap]:
            rec = f"{t['recency_days']}d"
            print(
                f"  {t['peak_date']:<15} "
                f"{format_price(t['peak_price']):<14} "
                f"+{t['gain_pct']:>4.1f}%{'':<3} "
                f"{rec:<9} "
                f"{t['probability_pct']:>4.1f}%"
            )
        print()

    print("  INTERPRETATION")
    print("  " + "-" * 46)
    if in_band:
        top = max(in_band, key=lambda x: x["probability_pct"])
        print(f"  Top spike target: {format_price(top['peak_price'])} "
              f"(+{top['gain_pct']:.1f}%)  {top['probability_pct']:.0f}% if a spike occurs")
        print(f"    {top['peak_date']}, {top['recency_days']}d ago, "
              f"visited {top['visits']}x, verified={top['verified']}")
    elif other:
        nearest = min(other, key=lambda x: x["gain_pct"])
        print(f"  Closest peak is {format_price(nearest['peak_price'])} "
              f"(+{nearest['gain_pct']:.1f}%) — outside current band.")
        print("  Consider widening --max-gain or adding a nearer peak.")
    else:
        print("  No stored peaks above current price. Run --scan or --add.")
    print()

    return targets


def render_targets_json(config, asset, min_gain, max_gain, spike_prob, cap):
    data_dir = get_data_dir(config)
    reference = get_reference(config)
    doc, peaks = load_peaks(data_dir, asset, reference)
    rows = doc.get("data", [])
    current_price = rows[-1]["close"] if rows else None

    targets = compute_targets(peaks, rows, current_price, spike_prob, min_gain, max_gain)

    return {
        "schema": "rvcrypto.spiketargets.v1",
        "type": "spiketargets",
        "asset": asset,
        "reference_currency": reference,
        "current_price": current_price,
        "spike_probability": spike_prob,
        "target_band": {"min_gain_pct": min_gain, "max_gain_pct": max_gain},
        "targets": targets[:cap],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Store and use price-peak levels for spike trading. Detect peaks "
            "into ASSET data files, manage them, and compute tradable "
            "spike-target probabilities."
        )
    )

    parser.add_argument(
        "asset",
        metavar="ASSET",
        help="Asset symbol, e.g. MMT or DGB.",
    )

    # Modes (mutually exclusive)
    group = parser.add_mutually_exclusive_group(required=True)

    group.add_argument(
        "--scan",
        action="store_true",
        help="Detect and store peaks from recent OHLCV history.",
    )
    group.add_argument(
        "--peaks",
        action="store_true",
        help="List stored peaks.",
    )
    group.add_argument(
        "--targets",
        action="store_true",
        help="Compute spike trade targets from stored peaks.",
    )
    group.add_argument(
        "--add",
        nargs=2,
        metavar=("PRICE", "DATE"),
        help="Add a peak manually (PRICE DATE).",
    )
    group.add_argument(
        "--remove",
        metavar="PRICE",
        help="Remove a peak by its approximate price.",
    )
    group.add_argument(
        "--clear-peaks",
        action="store_true",
        help="Remove all stored peaks for this asset.",
    )

    # Scan options
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"Lookback days for --scan (default: {DEFAULT_DAYS}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --scan, show candidates without writing.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="With --scan, prompt to confirm each candidate.",
    )

    # Target options
    parser.add_argument(
        "--min-gain",
        type=float,
        default=DEFAULT_MIN_GAIN,
        help=f"Min gain for a primary spike target %% (default: {DEFAULT_MIN_GAIN}).",
    )
    parser.add_argument(
        "--max-gain",
        type=float,
        default=DEFAULT_MAX_GAIN,
        help=f"Max gain for a primary spike target %% (default: {DEFAULT_MAX_GAIN}).",
    )
    parser.add_argument(
        "--prob-spike",
        type=float,
        default=DEFAULT_SPIKE_PROB,
        help=f"Base probability of a spike occurring (default: {DEFAULT_SPIKE_PROB}%%).",
    )
    parser.add_argument(
        "--cap",
        type=int,
        default=LEVEL_CAP,
        help=f"Max targets to show (default: {LEVEL_CAP}).",
    )

    # Output
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON (with --targets or --peaks).",
    )

    # --add note
    parser.add_argument(
        "--note",
        metavar="TEXT",
        help="Optional note for --add.",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        config = load_config()
        asset = args.asset.strip().upper()

        if args.scan:
            scan_and_store(config, asset, args.days, args.dry_run, args.verify)

        elif args.peaks:
            if args.json:
                data_dir = get_data_dir(config)
                reference = get_reference(config)
                doc, peaks = load_peaks(data_dir, asset, reference)
                print(json.dumps({"asset": asset, "peaks": peaks}, indent=2))
            else:
                list_peaks(config, asset)

        elif args.targets:
            if args.json:
                print(json.dumps(
                    render_targets_json(
                        config, asset, args.min_gain, args.max_gain,
                        args.prob_spike, args.cap,
                    ),
                    indent=2,
                ))
            else:
                render_targets(
                    config, asset, args.min_gain, args.max_gain,
                    args.prob_spike, args.cap,
                )

        elif args.add:
            add_peak(config, asset, args.add[0], args.add[1], args.note)

        elif args.remove:
            remove_peak(config, asset, args.remove)

        elif args.clear_peaks:
            clear_peaks(config, asset)

    except (OSError, ValueError, json.JSONDecodeError, FileNotFoundError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
