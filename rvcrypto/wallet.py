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

--add replaces the old addasset.py workflow:
    1. Add the asset to data/wallet.json if it is not already present.
    2. Collect initial Binance daily history for ASSET/REFERENCE.
    3. Save that history to data/ASSET_REFERENCE.json.

Three.js owns z-positioning and stacking. wallet.py owns membership,
stable sort order, and whether an asset is a widget/reference display.
"""

import argparse
import configparser
import json
from datetime import datetime, timezone
from pathlib import Path

import collecthistory


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
