#!/usr/bin/env python3
"""
graph.py

Prepare local crypto history for cryptograph.html.

Typical use:

    python3 graph.py MMT

By default the most recent 60 daily observations are prepared.

A smaller window may be requested:

    python3 graph.py MMT --days 30

The display is deliberately capped at 60 daily observations for now.
This is a presentation limit, not a data-storage limit.

The most useful current mode is --stream:

    python3 graph.py MMT --stream

This prints JavaScript commands which can be copied directly into the
browser console while cryptograph.html is open.

Example output:

    CryptoGraph.command("CLEAR_ASSET_LAYER");
    CryptoGraph.command("ADD_ASSET_LAYER", {...});

The name --stream is intentional.  The longer-term idea is that these
commands may eventually be sent directly to an iframe or another viewer.
For now stdout acts as the simplest possible transport.


Directory layout
----------------

Expected project layout:

    graph.py
    config.ini
    data/
        MMT_USDT.json
        DGB_USDT.json
        ...

The reference currency is read from config.ini:

    [market-data]
    reference_currency = USDT

The storage directory is also configurable:

    [storage]
    data_dir = data


Input format
------------

graph.py expects the JSON produced by collecthistory.py.

Only these fields are currently required from each data row:

    date
    close

If a future analysis program later adds:

    "future": true

to a row, graph.py preserves it and cryptograph.html can render that
observation using its future colour.

Nothing in this program attempts to calculate forecasts.


Colour
------

The normal asset colour may be supplied:

    python3 graph.py MMT --colour "#38bdf8" --stream

The future colour may also be supplied:

    python3 graph.py MMT \
        --colour "#38bdf8" \
        --future-colour "#e5e7eb" \
        --stream

These are simply passed through to cryptograph.html.


Scope
-----

graph.py intentionally does not:

    draw the graph itself
    calculate moving averages
    calculate channels
    detect spikes
    create future prices
    launch a browser
    communicate with the CMS

Its job is only:

    load asset history
    choose a recent display window
    build the ADD_ASSET_LAYER payload
    optionally print browser commands

cryptograph.html remains responsible for visual appearance.
"""

import argparse
import configparser
import json
import sys
from pathlib import Path


CONFIG_FILE = "config.ini"
DEFAULT_DAYS = 60
MAX_DISPLAY_DAYS = 60

DEFAULT_ASSET_COLOUR = "#38bdf8"
DEFAULT_FUTURE_COLOUR = "#e5e7eb"


def load_config():
    """Load config.ini while allowing sensible fallbacks."""
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def resolve_data_file(data_dir, token, reference_currency):
    """
    Resolve the asset history file.

    First try the configured reference currency:

        data/MMT_USDT.json

    If that file does not exist, allow one unambiguous TOKEN_*.json
    match.  This keeps the script usable if the configured reference
    currency changes after historical data has already been collected.
    """
    preferred = data_dir / f"{token}_{reference_currency}.json"

    if preferred.exists():
        return preferred

    matches = sorted(data_dir.glob(f"{token}_*.json"))

    if len(matches) == 1:
        return matches[0]

    if not matches:
        raise FileNotFoundError(
            f"No history file found for {token} in {data_dir}"
        )

    names = ", ".join(path.name for path in matches)

    raise RuntimeError(
        f"Multiple history files found for {token}: {names}. "
        f"Set reference_currency in config.ini to choose one."
    )


def load_document(path):
    """Load and minimally validate one collecthistory.py JSON file."""
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)

    rows = document.get("data")

    if not isinstance(rows, list):
        raise ValueError(
            f"{path} does not contain a valid 'data' list"
        )

    return document


def prepare_rows(rows, days):
    """
    Select the most recent usable rows.

    We sort by ISO YYYY-MM-DD date before slicing so the display remains
    predictable even if a file has been manually edited.

    Only date + close + optional future are sent to the browser.
    """
    usable = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        date = row.get("date")
        close = row.get("close")

        if not date or close is None:
            continue

        try:
            close = float(close)
        except (TypeError, ValueError):
            continue

        item = {
            "date": str(date),
            "close": close,
        }

        if row.get("future"):
            item["future"] = True

        usable.append(item)

    usable.sort(key=lambda row: row["date"])

    return usable[-days:]


def build_payload(document, rows, colour, future_colour):
    """Build the current ADD_ASSET_LAYER payload."""
    return {
        "asset": document.get("asset", "Asset"),
        "reference_currency": document.get(
            "reference_currency",
            ""
        ),
        "colour": colour,
        "future_colour": future_colour,
        "data": rows,
    }


def emit_stream(payload):
    """
    Print browser-console commands.

    json.dumps() produces valid JavaScript object syntax for this payload,
    so the output can be pasted directly into the browser console.
    """
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    print('CryptoGraph.command("CLEAR_ASSET_LAYER");')
    print(
        'CryptoGraph.command("ADD_ASSET_LAYER", '
        + encoded
        + ");"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Prepare crypto history for cryptograph.html"
    )

    parser.add_argument(
        "token",
        help="Token symbol, for example MMT or DGB",
    )

    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=(
            f"Number of recent daily observations to display "
            f"(default: {DEFAULT_DAYS}, maximum: {MAX_DISPLAY_DAYS})"
        ),
    )

    parser.add_argument(
        "--stream",
        action="store_true",
        help="Print CryptoGraph browser commands to stdout",
    )

    parser.add_argument(
        "--colour",
        default=DEFAULT_ASSET_COLOUR,
        help=(
            "Asset bar colour passed to cryptograph.html "
            f"(default: {DEFAULT_ASSET_COLOUR})"
        ),
    )

    parser.add_argument(
        "--future-colour",
        default=DEFAULT_FUTURE_COLOUR,
        help=(
            "Future-value bar colour passed to cryptograph.html "
            f"(default: {DEFAULT_FUTURE_COLOUR})"
        ),
    )

    args = parser.parse_args()

    if args.days < 1:
        parser.error("--days must be at least 1")

    if args.days > MAX_DISPLAY_DAYS:
        print(
            f"Display is currently limited to "
            f"{MAX_DISPLAY_DAYS} days; using {MAX_DISPLAY_DAYS}.",
            file=sys.stderr,
        )
        args.days = MAX_DISPLAY_DAYS

    token = args.token.upper()

    config = load_config()

    reference_currency = config.get(
        "market-data",
        "reference_currency",
        fallback="USDT",
    ).upper()

    data_dir = Path(
        config.get(
            "storage",
            "data_dir",
            fallback="data",
        )
    )

    try:
        data_file = resolve_data_file(
            data_dir,
            token,
            reference_currency,
        )

        document = load_document(data_file)

        rows = prepare_rows(
            document["data"],
            args.days,
        )

        if not rows:
            raise ValueError(
                f"No usable date/close records found in {data_file}"
            )

        payload = build_payload(
            document=document,
            rows=rows,
            colour=args.colour,
            future_colour=args.future_colour,
        )

        if args.stream:
            emit_stream(payload)
            return

        print(
            f"{payload['asset']}/{payload['reference_currency']}: "
            f"{len(rows)} display points "
            f"({rows[0]['date']} -> {rows[-1]['date']})"
        )
        print(
            "Use --stream to print commands for cryptograph.html."
        )

    except (
        FileNotFoundError,
        RuntimeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
