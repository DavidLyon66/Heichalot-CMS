#!/usr/bin/env python3
"""
wallet.py

Tracked-asset registry and asset bootstrap utility for rvcrypto.

Commands:

    python3 wallet.py --list
    python3 wallet.py --add MMT
    python3 wallet.py --add DGB
    python3 wallet.py --remove DGB
    python3 wallet.py --json
    python3 wallet.py --spike-summary
    python3 wallet.py --spike-history
    python3 wallet.py --spike-history --history-days 60
    python3 wallet.py --spike-history --sort volume
    python3 wallet.py --spike-history --sort events --reverse

--add replaces the old addasset.py workflow:
    1. Add the asset to data/wallet.json if it is not already present.
    2. Collect initial Binance daily history for ASSET/REFERENCE.
    3. Save that history to data/ASSET_REFERENCE.json.

--spike-summary shows current spike detection scores for all wallet
assets, including volume ratio, assessment, and historical context.

--spike-history shows recent spike events for all wallet assets,
sorted by score descending. Use --history-days to change the lookback
period (default: 30 days).

--sort controls sorting order:
    score    Sort by max score (default)
    date     Sort by most recent event
    volume   Sort by highest volume ratio
    events   Sort by number of events
    asset    Sort alphabetically by asset

--reverse reverses sort order (ascending instead of descending).

--json-spike outputs the spike summary or history as JSON for
programmatic use.

Three.js owns z-positioning and stacking. wallet.py owns membership,
stable sort order, and whether an asset is a widget/reference display.
"""

import argparse
import configparser
import json
from datetime import datetime, timezone
from pathlib import Path

import collecthistory
import spikedetect


BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.ini"

DEFAULT_DATA_DIR = "data"
DEFAULT_WALLET_FILE = "wallet.json"
DEFAULT_REFERENCE_CURRENCY = "USDT"
DEFAULT_DAYS = 365
SCHEMA = "rvcrypto.wallet.v1"


def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def get_data_dir(config):
    path = Path(
        config.get(
            "storage",
            "data_dir",
            fallback=DEFAULT_DATA_DIR,
        )
    )

    if not path.is_absolute():
        path = BASE / path

    return path


def get_wallet_path(config):
    data_dir = get_data_dir(config)

    value = config.get(
        "wallet",
        "file",
        fallback=DEFAULT_WALLET_FILE,
    ).strip()

    path = Path(value)

    if not path.is_absolute():
        path = data_dir / path

    return path


def get_default_reference(config):
    return config.get(
        "market-data",
        "reference_currency",
        fallback=DEFAULT_REFERENCE_CURRENCY,
    ).strip().upper()


def parse_bool(value):
    value = str(value).strip().lower()

    if value in ("true", "yes", "1", "on"):
        return True

    if value in ("false", "no", "0", "off"):
        return False

    raise argparse.ArgumentTypeError(
        "expected true or false"
    )


def empty_wallet():
    return {
        "schema": SCHEMA,
        "assets": [],
    }


def ensure_wallet(path):
    if path.exists():
        return

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            empty_wallet(),
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def load_wallet(path):
    ensure_wallet(path)

    with path.open(
        "r",
        encoding="utf-8",
    ) as handle:
        document = json.load(handle)

    if not isinstance(document, dict):
        raise ValueError(
            "wallet.json must contain a JSON object."
        )

    assets = document.get("assets", [])

    if not isinstance(assets, list):
        raise ValueError(
            'wallet.json field "assets" must be a list.'
        )

    return document


def save_wallet(path, document):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            document,
            handle,
            indent=2,
        )
        handle.write("\n")


def normalise_asset(raw, default_reference):
    if not isinstance(raw, dict):
        raise ValueError(
            "Each wallet asset must be a JSON object."
        )

    asset = str(
        raw.get("asset", "")
    ).strip().upper()

    if not asset:
        raise ValueError(
            "Wallet asset is missing an asset symbol."
        )

    reference = str(
        raw.get(
            "reference_currency",
            default_reference,
        )
    ).strip().upper()

    if not reference:
        reference = default_reference

    try:
        sortorder = int(
            raw.get("sortorder", 0)
        )
    except (TypeError, ValueError):
        raise ValueError(
            f"{asset}: sortorder must be an integer."
        )

    return {
        "asset": asset,
        "reference_currency": reference,
        "enabled": bool(
            raw.get("enabled", True)
        ),
        "sortorder": sortorder,
        "widget": bool(
            raw.get("widget", False)
        ),
    }


def make_data(config=None):
    """
    Callable interface for server-desktop.py later.
    """
    if config is None:
        config = load_config()

    default_reference = get_default_reference(
        config
    )

    path = get_wallet_path(config)
    document = load_wallet(path)

    assets = [
        normalise_asset(
            raw,
            default_reference,
        )
        for raw in document.get(
            "assets",
            [],
        )
    ]

    assets.sort(
        key=lambda item: (
            item["sortorder"],
            item["asset"],
        )
    )

    return {
        "schema": document.get(
            "schema",
            SCHEMA,
        ),
        "type": "wallet",
        "assets": assets,
    }


def render_json(data):
    return json.dumps(
        data,
        indent=2,
        ensure_ascii=False,
    )


def next_sortorder(document):
    values = []

    for raw in document.get(
        "assets",
        [],
    ):
        try:
            values.append(
                int(
                    raw.get(
                        "sortorder",
                        0,
                    )
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

    if not values:
        return 10

    # Leave gaps so manual reordering remains convenient.
    return (
        max(values) // 10 + 1
    ) * 10


def find_wallet_asset(
    document,
    asset,
    reference,
):
    for raw in document.get(
        "assets",
        [],
    ):
        if (
            str(
                raw.get(
                    "asset",
                    "",
                )
            ).upper()
            == asset
            and str(
                raw.get(
                    "reference_currency",
                    reference,
                )
            ).upper()
            == reference
        ):
            return raw

    return None

def update_asset_history(
    config,
    asset,
    reference,
    days=365,
):
    """
    Bootstrap/update history using collecthistory.py's canonical format.

    This deliberately reuses collecthistory.py. 
    That gives wallet --add the same:
      - OHLCV records
      - completed UTC daily candles only
      - incremental update behaviour
      - marker preservation
      - canonical ASSET_REFERENCE.json layout
    """
    base_url = config.get(
        "market-data",
        "base_url",
        fallback="https://api.binance.com",
    )

    data_dir = get_data_dir(config)
    data_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    pair = f"{asset}{reference}"
    data_file = data_dir / f"{asset}_{reference}.json"

    document = collecthistory.load_asset_document(
        data_file,
        asset,
        reference,
        pair,
    )

    today_utc = collecthistory.utc_midnight()
    end_dt = today_utc - collecthistory.timedelta(
        milliseconds=1
    )

    last_date = collecthistory.latest_date(
        document["data"]
    )

    if last_date:
        start_dt = (
            collecthistory.date_to_utc(last_date)
            + collecthistory.timedelta(days=1)
        )

        if start_dt >= today_utc:
            print(
                f"{asset}/{reference}: "
                f"history already current through {last_date}."
            )
            return data_file

        print(
            f"{asset}/{reference}: "
            f"existing history ends {last_date}"
        )
        print(
            "Collecting missing daily history from "
            f"{start_dt:%Y-%m-%d}..."
        )

    else:
        start_dt = (
            today_utc
            - collecthistory.timedelta(days=days)
        )

        print(
            f"{asset}/{reference}: no existing history."
        )
        print(
            f"Collecting previous {days} completed days..."
        )

    klines = collecthistory.fetch_klines(
        base_url=base_url,
        pair=pair,
        start_dt=start_dt,
        end_dt=end_dt,
    )

    incoming = collecthistory.convert_klines(
        klines
    )

    merged, added = collecthistory.merge_records(
        document["data"],
        incoming,
    )

    document["asset"] = asset
    document["reference_currency"] = reference
    document["pair"] = pair
    document["interval"] = collecthistory.INTERVAL
    document["data"] = merged

    collecthistory.save_document(
        data_file,
        document,
    )

    if added:
        print(
            f"Added {added} daily record"
            f"{'' if added == 1 else 's'}."
        )
        print(
            f"Stored {len(merged)} total records "
            f"in {data_file}"
        )
    else:
        print(
            "No new completed daily candles were returned."
        )

    return data_file

def update_history(config):
    wallet = make_data(config)

    for item in wallet["assets"]:
        if not item["enabled"]:
            continue

        asset = item["asset"]
        reference = item["reference_currency"]

        print()
        print(f"Updating {asset}/{reference}...")

        update_asset_history(
            config=config,
            asset=asset,
            reference=reference,
        )


def get_spike_scores(config):
    """
    Get spike detection scores for all wallet assets.
    Returns list of dicts with asset, score, volume_ratio, assessment, details.
    """
    wallet = make_data(config)
    data_dir = get_data_dir(config)
    reference = get_default_reference(config)
    
    results = []
    
    for item in wallet["assets"]:
        if not item["enabled"]:
            continue
        
        asset = item["asset"]
        
        try:
            rows = spikedetect.load_ohlcv(data_dir, asset, reference)
            
            if len(rows) < 2:
                raise ValueError("Not enough data")
            
            # Score the most recent day
            result = spikedetect.detect_spike(rows, len(rows) - 1, window=7, lookback=30)
            
            score = result["total_score"]
            vol_ratio = result["volume_ratio"]
            assessment = spikedetect.score_assessment(score)
            volume = result["volume"]
            
            # Get historical stats from last 30 days
            lookback = min(30, len(rows) - 1)
            recent_scores = []
            for i in range(len(rows) - lookback, len(rows)):
                try:
                    r = spikedetect.detect_spike(rows, i, window=7, lookback=30)
                    recent_scores.append(r["total_score"])
                except Exception:
                    continue
            
            avg_score = sum(recent_scores) / len(recent_scores) if recent_scores else 0
            max_score = max(recent_scores) if recent_scores else 0
            events = len([s for s in recent_scores if s >= 50])
            
            results.append({
                "asset": asset,
                "score": score,
                "volume_ratio": vol_ratio,
                "assessment": assessment,
                "volume": volume,
                "avg_30d": round(avg_score, 1),
                "max_30d": max_score,
                "recent_events": events,
            })
        except Exception as e:
            results.append({
                "asset": asset,
                "score": 0,
                "volume_ratio": 1.0,
                "assessment": "ERROR",
                "volume": 0,
                "avg_30d": 0,
                "max_30d": 0,
                "recent_events": 0,
                "error": str(e),
            })
    
    return results


def spike_assessment_label(score):
    if score >= 75:
        return "SELL SIGNAL"
    elif score >= 50:
        return "SPIKE LIKELY"
    elif score >= 25:
        return "WATCH"
    else:
        return "NO SPIKE"


def show_spike_summary(config, sort_by="score", reverse=False):
    """
    Display spike detection summary for all wallet assets.
    Format: clear, readable table with current scores and historical context.
    """
    results = get_spike_scores(config)
    
    if not results:
        print("No enabled assets in wallet.")
        return
    
    print()
    print("SPIKE DETECTION SUMMARY")
    print("=" * 60)
    print()
    print("Current scores with 30-day context:")
    print()
    
    # Header
    print(f"  {'ASSET':<8} {'SCORE':<10} {'VOL RATIO':<12} {'ASSESSMENT':<15} {'30D AVG':<10} {'30D MAX':<10} {'EVENTS':<8}")
    print("  " + "-" * 72)
    
    # Sort results
    if sort_by == "score":
        results.sort(key=lambda x: x["score"], reverse=not reverse)
    elif sort_by == "date":
        # For current scores, date is always today, so sort by asset
        results.sort(key=lambda x: x["asset"], reverse=reverse)
    elif sort_by == "volume":
        results.sort(key=lambda x: x["volume_ratio"], reverse=not reverse)
    elif sort_by == "events":
        results.sort(key=lambda x: x["recent_events"], reverse=not reverse)
    elif sort_by == "asset":
        results.sort(key=lambda x: x["asset"], reverse=reverse)
    
    for r in results:
        score_str = f"{r['score']}/100"
        vol_str = f"{r['volume_ratio']:.1f}x"
        assessment = spike_assessment_label(r['score'])
        
        # Add marker for high scores
        marker = " <-- SELL" if r['score'] >= 75 else ""
        
        print(
            f"  {r['asset']:<8} "
            f"{score_str:<10} "
            f"{vol_str:<12} "
            f"{assessment:<15} "
            f"{r['avg_30d']:<10} "
            f"{r['max_30d']:<10} "
            f"{r['recent_events']:<8}"
            f"{marker}"
        )
    
    print()
    print("Legend:")
    print("  SCORE      0-100 spike probability (higher = more likely)")
    print("  VOL RATIO  Current volume / 20-day average (>2.0x = unusual)")
    print("  30D AVG    Average score over last 30 days")
    print("  30D MAX    Highest score in last 30 days")
    print("  EVENTS     Days with score >= 50 in last 30 days")
    print()
    print("Assessment thresholds:")
    print("  75+   SELL SIGNAL  — Spike imminent, take profits")
    print("  50-74 SPIKE LIKELY — Elevated risk, monitor closely")
    print("  25-49 WATCH        — Some activity, no action needed")
    print("  0-24  NO SPIKE     — Quiet, normal conditions")
    print()
    
    # Show actionable items
    sells = [r for r in results if r['score'] >= 75]
    watches = [r for r in results if 50 <= r['score'] < 75]
    
    if sells:
        print("ACTION REQUIRED:")
        for r in sells:
            print(f"  SELL {r['asset']} — score {r['score']}/100")
        print()
    
    if watches:
        print("MONITOR CLOSELY:")
        for r in watches:
            print(f"  WATCH {r['asset']} — score {r['score']}/100")
        print()


def get_spike_history(config, days=30):
    """
    Get recent spike history for all wallet assets.
    Returns list of dicts with asset and list of recent spike events.
    """
    wallet = make_data(config)
    data_dir = get_data_dir(config)
    reference = get_default_reference(config)
    
    results = []
    
    for item in wallet["assets"]:
        if not item["enabled"]:
            continue
        
        asset = item["asset"]
        
        try:
            rows = spikedetect.load_ohlcv(data_dir, asset, reference)
            
            if len(rows) < 2:
                raise ValueError("Not enough data")
            
            # Get recent spike events (last N days)
            events = []
            start_idx = max(0, len(rows) - days)
            
            for i in range(start_idx, len(rows)):
                try:
                    result = spikedetect.detect_spike(rows, i, window=7, lookback=30)
                    score = result["total_score"]
                    
                    if score >= 25:  # Only include WATCH and above
                        events.append({
                            "date": result["date"],
                            "score": score,
                            "volume_ratio": result["volume_ratio"],
                            "direction": result["direction"],
                            "pullback_pct": result["pullback_pct"],
                            "volume": result["volume"],
                        })
                except Exception:
                    continue
            
            # Sort by score descending
            events.sort(key=lambda x: x["score"], reverse=True)
            
            results.append({
                "asset": asset,
                "events": events,
                "total_days": days,
            })
        except Exception as e:
            results.append({
                "asset": asset,
                "events": [],
                "total_days": days,
                "error": str(e),
            })
    
    return results


def show_spike_history(config, days=30, sort_by="score", reverse=False):
    """
    Display recent spike history for all wallet assets.
    Format: clear, readable list of recent events by asset.
    """
    results = get_spike_history(config, days)
    
    if not results:
        print("No enabled assets in wallet.")
        return
    
    print()
    print(f"SPIKE HISTORY (last {days} days)")
    print("=" * 60)
    print()
    
    # Sort results
    if sort_by == "score":
        # Sort by max score descending
        results.sort(key=lambda x: max([e["score"] for e in x["events"]]) if x["events"] else 0, reverse=not reverse)
    elif sort_by == "date":
        # Sort by most recent event date descending
        def get_latest_date(r):
            if r["events"]:
                return max(e["date"] for e in r["events"])
            return "0000-00-00"
        results.sort(key=get_latest_date, reverse=not reverse)
    elif sort_by == "volume":
        # Sort by max volume ratio descending
        def get_max_vol(r):
            if r["events"]:
                return max(e["volume_ratio"] for e in r["events"])
            return 0
        results.sort(key=get_max_vol, reverse=not reverse)
    elif sort_by == "events":
        # Sort by number of events descending
        results.sort(key=lambda x: len(x["events"]), reverse=not reverse)
    elif sort_by == "asset":
        results.sort(key=lambda x: x["asset"], reverse=reverse)
    
    for r in results:
        asset = r["asset"]
        events = r["events"]
        
        if not events:
            print(f"  {asset}: No spikes detected in last {days} days")
            continue
        
        print(f"  {asset}: {len(events)} spike(s) detected")
        
        # Show top 5 events
        for e in events[:5]:
            direction = e["direction"]
            pullback = e["pullback_pct"]
            vol_ratio = e["volume_ratio"]
            
            # Format direction with pullback
            if direction == "UP" and pullback > 0:
                dir_str = f"UP (pulled back {pullback * 100:.1f}%)"
            elif direction == "DOWN" and pullback > 0:
                dir_str = f"DOWN (pulled back {pullback * 100:.1f}%)"
            else:
                dir_str = direction
            
            print(
                f"    {e['date']}  "
                f"score {e['score']:>3}/100  "
                f"{vol_ratio:.1f}x vol  "
                f"{dir_str}"
            )
        
        if len(events) > 5:
            print(f"    ... and {len(events) - 5} more")
        
        print()
    
    print("Legend:")
    print("  score     0-100 spike probability")
    print("  vol       volume ratio (current / 20-day average)")
    print("  direction price movement direction")
    print("  pulled back % decline after spike (mean reversion)")
    print()
    print("Sort options:")
    print("  --sort score    Sort by max score (default)")
    print("  --sort date     Sort by most recent event")
    print("  --sort volume   Sort by highest volume ratio")
    print("  --sort events   Sort by number of events")
    print("  --sort asset    Sort alphabetically by asset")
    print("  --reverse       Reverse sort order (ascending)")
    print()
        
def add_asset(
    config,
    asset,
    reference=None,
    days=DEFAULT_DAYS,
    widget=False,
):
    asset = asset.strip().upper()

    if not asset:
        raise ValueError(
            "Asset symbol cannot be empty."
        )

    if reference is None:
        reference = (
            get_default_reference(
                config
            )
        )

    reference = (
        reference.strip().upper()
    )

    wallet_path = get_wallet_path(
        config
    )

    document = load_wallet(
        wallet_path
    )

    existing = find_wallet_asset(
        document,
        asset,
        reference,
    )

    if existing is None:
        record = {
            "asset": asset,
            "reference_currency": reference,
            "enabled": True,
            "sortorder": next_sortorder(document),
            "widget": False if widget is None else widget,
        }

        document.setdefault(
            "assets",
            [],
        ).append(
            record
        )

        document["schema"] = (
            document.get(
                "schema",
                SCHEMA,
            )
        )

        save_wallet(
            wallet_path,
            document,
        )

        print(
            f"Added {asset}/{reference} "
            f"to {wallet_path}"
        )

    else:
        if widget is not None and bool(existing.get("widget", False)) != widget:
            existing["widget"] = widget
            save_wallet(wallet_path, document)

            print(
                f"Updated {asset}/{reference}: "
                f"widget={widget}"
            )
        else:
            print(
                f"{asset}/{reference} is already "
                f"in {wallet_path}"
            )

    # Preserve addasset.py behaviour: --add also creates/refreshes
    # the initial market-data file.
    update_asset_history(
        config,
        asset,
        reference,
        days=days,
    )



def remove_asset(
    config,
    asset,
):
    """
    Remove an asset from wallet.json and delete its local history file(s).

    No confirmation is requested.

    If the same asset appears with more than one reference currency,
    every matching wallet entry and corresponding ASSET_REFERENCE.json
    history file is removed.
    """
    asset = asset.strip().upper()

    if not asset:
        raise ValueError(
            "Asset symbol cannot be empty."
        )

    wallet_path = get_wallet_path(config)
    document = load_wallet(wallet_path)

    assets = document.get("assets", [])

    matches = [
        raw
        for raw in assets
        if str(
            raw.get("asset", "")
        ).strip().upper() == asset
    ]

    if not matches:
        print(
            f"{asset} is not in {wallet_path}"
        )
        return

    document["assets"] = [
        raw
        for raw in assets
        if str(
            raw.get("asset", "")
        ).strip().upper() != asset
    ]

    save_wallet(
        wallet_path,
        document,
    )

    print(
        f"Removed {asset} from {wallet_path}"
    )

    data_dir = get_data_dir(config)

    for raw in matches:
        reference = str(
            raw.get(
                "reference_currency",
                get_default_reference(config),
            )
        ).strip().upper()

        history_path = (
            data_dir
            / f"{asset}_{reference}.json"
        )

        if history_path.exists():
            history_path.unlink()

            print(
                f"Deleted history file "
                f"{history_path}"
            )


def list_assets(config):
    data = make_data(config)

    assets = data["assets"]

    if not assets:
        print("Wallet is empty.")
        return

    print(
        f"{'ORDER':<7} "
        f"{'ASSET':<8} "
        f"{'REFERENCE':<10} "
        f"{'ENABLED':<8} "
        f"{'WIDGET':<6}"
    )

    for item in assets:
        print(
            f"{item['sortorder']:<7} "
            f"{item['asset']:<8} "
            f"{item['reference_currency']:<10} "
            f"{str(item['enabled']):<8} "
            f"{str(item['widget']):<6}"
        )


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Manage and render the rvcrypto "
            "tracked-asset wallet registry."
        )
    )

    actions = parser.add_mutually_exclusive_group(
        required=True
    )

    actions.add_argument(
        "--list",
        action="store_true",
        help="List tracked assets.",
    )

    actions.add_argument(
        "--add",
        metavar="ASSET",
        help=(
            "Add an asset to wallet.json and "
            "collect its initial Binance history."
        ),
    )
    actions.add_argument(
        "--remove",
        "--delete",
        dest="remove",
        metavar="ASSET",
        help=(
            "Remove an asset from wallet.json and "
            "delete its local history file(s)."
        ),
    )

    actions.add_argument(
        "--json",
        action="store_true",
        help="Render wallet.json as normalized JSON.",
    )

    actions.add_argument(
        "--spike-summary",
        action="store_true",
        help="Show spike detection scores for all wallet assets.",
    )

    actions.add_argument(
        "--spike-history",
        action="store_true",
        help="Show recent spike history for all wallet assets.",
    )

    parser.add_argument(
        "--json-spike",
        action="store_true",
        help="Output spike summary as JSON (use with --spike-summary or --spike-history).",
    )

    parser.add_argument(
        "--history-days",
        type=int,
        default=30,
        help="Number of days to look back for --spike-history (default: 30).",
    )

    parser.add_argument(
        "--sort",
        choices=["score", "date", "volume", "events", "asset"],
        default="score",
        help="Sort spike results by: score (default), date, volume, events, or asset.",
    )

    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Reverse sort order (ascending instead of descending).",
    )

    parser.add_argument(
        "--reference",
        metavar="CURRENCY",
        help=(
            "Reference currency for --add "
            "(default: config.ini market-data "
            "reference_currency or USDT)."
        ),
    )

    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=(
            "Initial Binance history days collected "
            f"by --add (default: {DEFAULT_DAYS})."
        ),
    )

    actions.add_argument(
        "--update-history",
        action="store_true",
        help="Update market history for all enabled wallet assets.",
    )

    parser.add_argument(
        "--widget",
        type=parse_bool,
        default=None,
        metavar="true/false",
        help=(
            "Mark an added asset as a Three.js widget "
            "(default: false)."
        ),
    )
    
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.days < 1:
        parser.error(
            "--days must be at least 1."
        )

    try:
        config = load_config()

        if args.list:
            list_assets(
                config
            )

        elif args.add:
            add_asset(
                config=config,
                asset=args.add,
                reference=args.reference,
                days=args.days,
                widget=args.widget,
            )

        elif args.remove:
            remove_asset(
                config=config,
                asset=args.remove,
            )

        elif args.json:
            print(
                render_json(
                    make_data(
                        config
                    )
                )
            )
           
        elif args.spike_summary:
            if args.json_spike:
                results = get_spike_scores(config)
                print(json.dumps(results, indent=2))
            else:
                show_spike_summary(config, sort_by=args.sort, reverse=args.reverse)

        elif args.spike_history:
            if args.json_spike:
                results = get_spike_history(config, days=args.history_days)
                print(json.dumps(results, indent=2))
            else:
                show_spike_history(config, days=args.history_days, sort_by=args.sort, reverse=args.reverse)

        elif args.update_history:
            update_history(config)            

    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        parser.error(
            str(exc)
        )


if __name__ == "__main__":
    main()
