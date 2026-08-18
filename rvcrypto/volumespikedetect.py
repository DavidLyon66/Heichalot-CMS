#!/usr/bin/env python3

"""
volumespikedetect.py

Small experimental utility for recording known/observed crypto
volume/price spike events.

At this stage the program deliberately does NOT attempt to detect
spikes automatically.  It records human-observed spike events so that
later analysis tools have a stable set of historical events to study.

The spike data is kept separately from mechanically collected market
history.

Example market history:

    data/MMT_USDT.json

Example spike observations:

    data/MMT_USDT_spikes.json


Examples
--------

Add a spike:

    python3 volumespikedetect.py MMT \
        --add-day-spike 2026-07-31 -5 4

Add a labelled spike:

    python3 volumespikedetect.py MMT \
        --add-day-spike 2026-07-31 -5 4 \
        --label "Unknown July Spike"

Add a description:

    python3 volumespikedetect.py MMT \
        --add-day-spike 2026-07-31 -5 4 \
        --label "Unknown July Spike" \
        --description "We need to remote-view this to find out why"

List recorded spikes:

    python3 volumespikedetect.py MMT --list

Remove a spike:

    python3 volumespikedetect.py MMT \
        --remove-day-spike 2026-07-31


Offset convention
-----------------

days_before MUST be zero or negative.

For example:

    -5

means:

    five days before the nominated spike date.

days_after MUST be zero or positive.

This deliberately makes the stored values useful as relative offsets:

    -5 -4 -3 -2 -1  0  +1 +2 +3 +4
                     ^
                  spike day

This should also make later graphing and analysis relatively simple.
"""

import argparse
import configparser
import json
from datetime import datetime
from pathlib import Path


DEFAULT_REFERENCE_CURRENCY = "USDT"


def load_config():
    """
    Load config.ini from the same directory as this program.

    Nothing currently depends strongly on configuration, but using
    ConfigParser now leaves room for the reference currency and other
    settings to become configurable without changing the command-line
    interface.
    """

    config = configparser.ConfigParser()

    config_path = Path(__file__).resolve().parent / "config.ini"

    if config_path.exists():
        config.read(config_path)

    return config


def get_reference_currency(config):
    """
    Return the local/reference currency.

    For now USDT remains the default.

    This intentionally tolerates several possible future config
    layouts rather than making the rest of the program dependent on
    one unfinished config.ini design.
    """

    candidates = [
        ("market", "reference_currency"),
        ("crypto", "reference_currency"),
        ("general", "reference_currency"),
    ]

    for section, option in candidates:
        if config.has_option(section, option):
            value = config.get(section, option).strip()

            if value:
                return value.upper()

    return DEFAULT_REFERENCE_CURRENCY


def spike_file_path(asset, reference_currency):
    """
    Return the spike metadata filename.

    Example:

        data/DGB_USDT_spikes.json
    """

    base_dir = Path(__file__).resolve().parent
    data_dir = base_dir / "data"

    data_dir.mkdir(parents=True, exist_ok=True)

    filename = (
        f"{asset.upper()}_"
        f"{reference_currency.upper()}_spikes.json"
    )

    return data_dir / filename


def empty_spike_file(asset, reference_currency):
    """
    Create the initial in-memory structure for a spike file.

    Additional marker classes can be added later without changing the
    historical market-data file.
    """

    return {
        "asset": asset.upper(),
        "reference_currency": reference_currency.upper(),
        "daily_spikes": [],
    }


def load_spikes(path, asset, reference_currency):
    """
    Load an existing spike file or return an empty structure.
    """

    if not path.exists():
        return empty_spike_file(asset, reference_currency)

    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if "daily_spikes" not in data:
        data["daily_spikes"] = []

    return data


def save_spikes(path, data):
    """
    Save spike metadata in human-readable JSON.
    """

    with path.open("w", encoding="utf-8") as handle:
        json.dump(
            data,
            handle,
            indent=2,
            ensure_ascii=False,
        )

        handle.write("\n")


def validate_date(value):
    """
    Require an ISO YYYY-MM-DD date.

    Using one canonical representation makes later joins against the
    daily history files straightforward.
    """

    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError(
            f"Invalid date '{value}'. "
            "Expected YYYY-MM-DD."
        )

    return value


def add_day_spike(
    data,
    date,
    days_before,
    days_after,
    label=None,
    description=None,
):
    """
    Add one manually observed daily spike.

    days_before is deliberately stored as a negative offset.

    days_after is stored as a positive offset.

    The spike day itself is implicitly offset zero.
    """

    validate_date(date)

    if days_before > 0:
        raise ValueError(
            "days_before must be zero or negative "
            "(for example -5)."
        )

    if days_after < 0:
        raise ValueError(
            "days_after must be zero or positive "
            "(for example 4)."
        )

    existing = next(
        (
            spike
            for spike in data["daily_spikes"]
            if spike.get("date") == date
        ),
        None,
    )

    if existing:
        raise ValueError(
            f"A daily spike is already recorded for {date}."
        )

    spike = {
        "date": date,
        "days_before": days_before,
        "days_after": days_after,
    }

    if label:
        spike["label"] = label

    if description:
        spike["description"] = description

    data["daily_spikes"].append(spike)

    data["daily_spikes"].sort(
        key=lambda item: item.get("date", "")
    )

    return spike


def remove_day_spike(data, date):
    """
    Remove a daily spike identified by its central spike date.

    Returns True if something was removed.
    """

    validate_date(date)

    original_count = len(data["daily_spikes"])

    data["daily_spikes"] = [
        spike
        for spike in data["daily_spikes"]
        if spike.get("date") != date
    ]

    return len(data["daily_spikes"]) != original_count


def list_spikes(data):
    """
    Print currently recorded daily spike markers.
    """

    spikes = data.get("daily_spikes", [])

    if not spikes:
        print("No daily spike markers.")
        return

    asset = data.get("asset", "?")
    reference = data.get("reference_currency", "?")

    print(f"{asset}/{reference} daily spike markers")
    print()

    for spike in spikes:
        date = spike.get("date", "?")
        before = spike.get("days_before", 0)
        after = spike.get("days_after", 0)

        label = spike.get("label")

        if label:
            print(
                f"{date}  "
                f"[{before} .. +{after}]  "
                f"{label}"
            )
        else:
            print(
                f"{date}  "
                f"[{before} .. +{after}]"
            )

        description = spike.get("description")

        if description:
            print(f"    {description}")


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Record and inspect crypto spike markers."
        )
    )

    parser.add_argument(
        "asset",
        help="Crypto asset symbol, e.g. MMT or DGB",
    )

    actions = parser.add_mutually_exclusive_group(
        required=True
    )

    actions.add_argument(
        "--add-day-spike",
        nargs=3,
        metavar=(
            "DATE",
            "DAYS_BEFORE",
            "DAYS_AFTER",
        ),
        help=(
            "Add a daily spike marker. "
            "DAYS_BEFORE should be negative."
        ),
    )

    actions.add_argument(
        "--remove-day-spike",
        metavar="DATE",
        help="Remove the spike marker for DATE.",
    )

    actions.add_argument(
        "--list",
        action="store_true",
        help="List recorded spike markers.",
    )

    parser.add_argument(
        "--label",
        help="Optional short human-readable spike label.",
    )

    parser.add_argument(
        "--description",
        help="Optional longer description or research note.",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    asset = args.asset.upper()

    config = load_config()

    reference_currency = get_reference_currency(
        config
    )

    path = spike_file_path(
        asset,
        reference_currency,
    )

    data = load_spikes(
        path,
        asset,
        reference_currency,
    )

    if args.add_day_spike:
        date, before_text, after_text = (
            args.add_day_spike
        )

        try:
            days_before = int(before_text)
            days_after = int(after_text)

            spike = add_day_spike(
                data=data,
                date=date,
                days_before=days_before,
                days_after=days_after,
                label=args.label,
                description=args.description,
            )

        except ValueError as error:
            parser.error(str(error))

        save_spikes(path, data)

        print(
            f"Added daily spike: {spike['date']} "
            f"({spike['days_before']} .. "
            f"+{spike['days_after']})"
        )

        if spike.get("label"):
            print(
                f"Label: {spike['label']}"
            )

        print(f"Stored in {path}")

        return

    if args.remove_day_spike:
        try:
            removed = remove_day_spike(
                data,
                args.remove_day_spike,
            )
        except ValueError as error:
            parser.error(str(error))

        if not removed:
            print(
                "No daily spike marker found for "
                f"{args.remove_day_spike}."
            )
            return

        save_spikes(path, data)

        print(
            "Removed daily spike: "
            f"{args.remove_day_spike}"
        )

        print(f"Stored in {path}")

        return

    if args.list:
        list_spikes(data)


if __name__ == "__main__":
    main()
