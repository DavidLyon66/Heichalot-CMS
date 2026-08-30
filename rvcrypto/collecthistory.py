#!/usr/bin/env python3
"""
collecthistory.py

Collect daily price and volume history for a crypto token using the
public Binance Spot REST API.

Typical use:

    python3 collecthistory.py DGB

The default history length for a new token is 365 days:

    python3 collecthistory.py DGB --days 365

A different initial history length can be requested:

    python3 collecthistory.py DGB --days 1000

Design
------

The program expects to run in a single project directory containing:

    collecthistory.py
    config.ini
    data/

The reference currency is taken from config.ini. For example, if the
reference currency is USDT:

    python3 collecthistory.py DGB

uses the Binance market:

    DGBUSDT

and stores the result in:

    data/DGB_USDT.json

Incremental updates
-------------------

The --days value is primarily for the first collection.

If data/DGB_USDT.json does not exist, the requested number of previous
daily candles is downloaded.

If the file already exists, old market data is NOT downloaded again.
The program finds the most recent stored date and requests only the
missing daily candles after that date.

Existing marker sections and other top-level JSON fields are preserved.

Daily candles
-------------

Only completed UTC daily candles are stored.

The current day's Binance candle is deliberately ignored because it is
still changing. This avoids storing a partial daily candle and then
mistaking it for finished historical data on the next run.

Stored market data
------------------

Each daily record contains:

    date
    open
    high
    low
    close
    volume

Although this project primarily needs price and volume, OHLC values are
retained because later tools such as channeldetect.py may need daily
highs and lows.

Markers
-------

New asset files contain empty observational marker collections:

    daily-channel-markers
    weekly-channel-markers
    monthly-channel-markers

    daily-spike-markers
    weekly-spike-markers
    monthly-spike-markers

collecthistory.py does not interpret or modify those markers.

Example config.ini
------------------

    [market-data]
    provider = binance
    reference_currency = USDT
    base_url = https://api.binance.com

    [storage]
    data_dir = data

Scope
-----

This program intentionally does not calculate indicators, detect spikes
or channels, create forecasts, perform remote viewing, or graph data.
Its job is only to maintain a small local historical market dataset.
"""

import argparse
import configparser
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CONFIG_FILE = "config.ini"
INTERVAL = "1d"
BINANCE_MAX_KLINES = 1000
ONE_DAY_MS = 24 * 60 * 60 * 1000


def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def utc_midnight(dt=None):
    if dt is None:
        dt = datetime.now(timezone.utc)
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def datetime_to_ms(dt):
    return int(dt.timestamp() * 1000)


def date_to_utc(date_text):
    return datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def request_klines(base_url, pair, start_ms, end_ms, limit=1000):
    params = urlencode({
        "symbol": pair,
        "interval": INTERVAL,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": min(limit, BINANCE_MAX_KLINES),
    })

    url = f"{base_url.rstrip('/')}/api/v3/klines?{params}"
    request = Request(url, headers={"User-Agent": "Heichalot-Crypto-History/0.1"})

    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Binance returned HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Unable to contact Binance: {exc.reason}") from exc


def fetch_klines(base_url, pair, start_dt, end_dt):
    start_ms = datetime_to_ms(start_dt)
    end_ms = datetime_to_ms(end_dt)

    rows = []
    cursor = start_ms

    while cursor <= end_ms:
        page = request_klines(
            base_url=base_url,
            pair=pair,
            start_ms=cursor,
            end_ms=end_ms,
            limit=BINANCE_MAX_KLINES,
        )

        if not page:
            break

        rows.extend(page)
        last_open_ms = int(page[-1][0])
        next_cursor = last_open_ms + ONE_DAY_MS

        if next_cursor <= cursor:
            break

        cursor = next_cursor

        if len(page) < BINANCE_MAX_KLINES:
            break

    return rows


def convert_klines(klines):
    records = []

    for candle in klines:
        open_time = datetime.fromtimestamp(candle[0] / 1000, tz=timezone.utc)
        records.append({
            "date": open_time.strftime("%Y-%m-%d"),
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4]),
            "volume": float(candle[5]),
        })

    return records


def new_asset_document(asset, reference_currency, pair):
    return {
        "asset": asset,
        "reference_currency": reference_currency,
        "pair": pair,
        "interval": INTERVAL,
        "daily-channel-markers": [],
        "weekly-channel-markers": [],
        "monthly-channel-markers": [],
        "daily-spike-markers": [],
        "weekly-spike-markers": [],
        "monthly-spike-markers": [],
        "daily-peak-markers": [],
        "data": [],
    }


def load_asset_document(path, asset, reference_currency, pair):
    if not path.exists():
        return new_asset_document(asset, reference_currency, pair)

    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)

    if "data" not in document or not isinstance(document["data"], list):
        raise ValueError(f"{path} does not contain a valid 'data' list")

    return document


def latest_date(records):
    dates = [
        row.get("date")
        for row in records
        if isinstance(row, dict) and row.get("date")
    ]
    return max(dates) if dates else None


def merge_records(existing, incoming):
    merged = {}

    for row in existing:
        if isinstance(row, dict) and row.get("date"):
            merged[row["date"]] = row

    added = 0

    for row in incoming:
        date = row.get("date")
        if not date:
            continue
        if date not in merged:
            merged[date] = row
            added += 1

    return [merged[key] for key in sorted(merged)], added


def save_document(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=4)
        handle.write("\n")


def main():
    parser = argparse.ArgumentParser(
        description="Collect daily Binance price/volume history"
    )
    parser.add_argument(
        "token",
        help="Token symbol, for example DGB, BTC or MMT",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="Initial history length in days (default: 365)",
    )
    args = parser.parse_args()

    if args.days < 1:
        parser.error("--days must be at least 1")

    token = args.token.upper()
    config = load_config()

    reference_currency = config.get(
        "market-data", "reference_currency", fallback="USDT"
    ).upper()
    base_url = config.get(
        "market-data", "base_url", fallback="https://api.binance.com"
    )
    data_dir = Path(
        config.get("storage", "data_dir", fallback="data")
    )

    pair = f"{token}{reference_currency}"
    data_file = data_dir / f"{token}_{reference_currency}.json"

    try:
        document = load_asset_document(
            data_file, token, reference_currency, pair
        )

        today_utc = utc_midnight()
        end_dt = today_utc - timedelta(milliseconds=1)
        last_date = latest_date(document["data"])

        if last_date:
            start_dt = date_to_utc(last_date) + timedelta(days=1)

            if start_dt >= today_utc:
                print(
                    f"{token}/{reference_currency}: "
                    f"history already current through {last_date}."
                )
                return

            print(
                f"{token}/{reference_currency}: "
                f"existing history ends {last_date}"
            )
            print(
                f"Collecting missing daily history from "
                f"{start_dt:%Y-%m-%d}..."
            )
        else:
            start_dt = today_utc - timedelta(days=args.days)
            print(f"{token}/{reference_currency}: no existing history.")
            print(f"Collecting previous {args.days} completed days...")

        klines = fetch_klines(
            base_url=base_url,
            pair=pair,
            start_dt=start_dt,
            end_dt=end_dt,
        )

        incoming = convert_klines(klines)
        merged, added = merge_records(document["data"], incoming)

        document["asset"] = token
        document["reference_currency"] = reference_currency
        document["pair"] = pair
        document["interval"] = INTERVAL
        document["data"] = merged

        save_document(data_file, document)

        if added:
            print(f"Added {added} daily record{'' if added == 1 else 's'}.")
            print(f"Stored {len(merged)} total records in {data_file}")
        else:
            print("No new completed daily candles were returned.")

    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
