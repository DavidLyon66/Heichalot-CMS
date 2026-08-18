#!/usr/bin/env python3

"""
addchannel.py

Record and manage manually observed trading channels.

Storage:

    data/tradingchannels.json


Add a new active channel
------------------------

    python3 addchannel.py DGB 2026-08-12

An active channel has:

    "end_date": null

A label is optional while the channel is still active.


Add a completed/historical channel
----------------------------------

    python3 addchannel.py DGB 2026-07-20 2026-08-11

Optional metadata:

    python3 addchannel.py DGB 2026-07-20 2026-08-11 \
        --label "July Triangle" \
        --description "Best Trading time ever"


List channels for one asset
---------------------------

    python3 addchannel.py DGB --list

Channels are shown newest first.

The default list limit is 10:

    python3 addchannel.py DGB --list --limit 20


Close the current active channel
--------------------------------

Close it yesterday:

    python3 addchannel.py DGB --close

Close it on a particular date:

    python3 addchannel.py DGB --close 2026-08-11

The aliases below also mean yesterday:

    python3 addchannel.py DGB --close yesterday
    python3 addchannel.py DGB --close -1

A closed channel should have a label.

If --label is supplied, it is used:

    python3 addchannel.py DGB --close \
        --label "August Triangle"

If the active channel already has a label and --label is omitted, that
label is retained.

If there is still no label, a default is created:

    Channel ending 2026-08-11

An optional description may be added or replaced while closing:

    python3 addchannel.py DGB --close \
        --label "August Triangle" \
        --description "Very volatile final week"


Design
------

This utility deliberately records observations only.

It does not:

    calculate channel geometry
    identify highs/lows
    estimate an apex
    calculate volatility
    decide whether a channel is tradeable

Those jobs belong to other small tools.

For an asset, this first version expects at most one active channel.
If corrupt/experimental data contains multiple active channels,
--close refuses to guess which one should be closed.
"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path


DATA_FILE = (
    Path(__file__).resolve().parent
    / "data"
    / "tradingchannels.json"
)

DEFAULT_LIST_LIMIT = 10


def validate_date(value):
    """Require an ISO YYYY-MM-DD date."""
    try:
        parsed = datetime.strptime(
            value,
            "%Y-%m-%d",
        )
    except ValueError as exc:
        raise ValueError(
            f"Invalid date '{value}'. "
            "Expected YYYY-MM-DD."
        ) from exc

    return parsed.date()


def yesterday_text():
    """
    Return yesterday in local system time as YYYY-MM-DD.

    This is appropriate for this CLI because collecthistory.py stores
    completed daily candles and the operator normally closes a channel
    after the preceding trading day has finished.
    """
    return (
        datetime.now().date()
        - timedelta(days=1)
    ).isoformat()


def resolve_close_date(value):
    """
    Resolve the --close date.

    None, "yesterday" and "-1" all mean yesterday.
    """
    if value in (None, "", "yesterday", "-1"):
        return yesterday_text()

    validate_date(value)
    return value


def load_channels():
    """Load tradingchannels.json or create an empty structure."""
    if not DATA_FILE.exists():
        return {
            "channels": []
        }

    with DATA_FILE.open(
        "r",
        encoding="utf-8",
    ) as handle:
        data = json.load(handle)

    if "channels" not in data:
        data["channels"] = []

    if not isinstance(
        data["channels"],
        list,
    ):
        raise ValueError(
            "'channels' must be a list."
        )

    return data


def save_channels(data):
    """Write tradingchannels.json."""
    DATA_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with DATA_FILE.open(
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(
            data,
            handle,
            indent=2,
            ensure_ascii=False,
        )
        handle.write("\n")


def add_channel(
    data,
    asset,
    start_date,
    end_date=None,
    label=None,
    description=None,
):
    """
    Add one observed trading channel.

    end_date=None means the channel is active.
    """
    validate_date(start_date)

    if end_date is not None:
        validate_date(end_date)

        if end_date < start_date:
            raise ValueError(
                "end_date cannot be before "
                "start_date."
            )

    channel = {
        "asset": asset.upper(),
        "start_date": start_date,
        "end_date": end_date,
    }

    if label:
        channel["label"] = label

    if description:
        channel["description"] = (
            description
        )

    data["channels"].append(channel)

    data["channels"].sort(
        key=lambda item: (
            item.get("asset", ""),
            item.get("start_date", ""),
        )
    )

    return channel


def asset_channels(data, asset):
    """Return all channels for an asset."""
    asset = asset.upper()

    return [
        channel
        for channel in data["channels"]
        if str(
            channel.get("asset", "")
        ).upper() == asset
    ]


def list_channels(
    data,
    asset,
    limit=DEFAULT_LIST_LIMIT,
):
    """
    Print channels for one asset newest first.
    """
    channels = asset_channels(
        data,
        asset,
    )

    channels.sort(
        key=lambda item: (
            item.get("start_date", "")
        ),
        reverse=True,
    )

    if limit > 0:
        channels = channels[:limit]

    if not channels:
        print(
            f"No channels recorded for "
            f"{asset.upper()}."
        )
        return

    print(
        f"{asset.upper()} trading channels "
        f"(newest first)"
    )
    print()

    for channel in channels:
        start = channel.get(
            "start_date",
            "?",
        )

        end = channel.get(
            "end_date"
        )

        status = (
            "ACTIVE"
            if end is None
            else end
        )

        label = channel.get(
            "label",
            ""
        )

        print(
            f"{start} -> {status}"
            + (
                f"  {label}"
                if label
                else ""
            )
        )

        description = channel.get(
            "description"
        )

        if description:
            print(
                f"    {description}"
            )


def find_active_channel(
    data,
    asset,
):
    """
    Return the one active channel for asset.

    Refuse to guess if more than one is active.
    """
    active = [
        channel
        for channel in asset_channels(
            data,
            asset,
        )
        if channel.get("end_date") is None
    ]

    if not active:
        raise ValueError(
            f"No active channel found for "
            f"{asset.upper()}."
        )

    if len(active) > 1:
        raise ValueError(
            f"More than one active channel "
            f"exists for {asset.upper()}; "
            f"refusing to guess which one "
            f"to close."
        )

    return active[0]


def close_channel(
    data,
    asset,
    end_date,
    label=None,
    description=None,
):
    """
    Close the current active channel.

    Label precedence:

        1. --label supplied now
        2. existing label on active channel
        3. generated default
    """
    validate_date(end_date)

    channel = find_active_channel(
        data,
        asset,
    )

    start_date = channel.get(
        "start_date"
    )

    if not start_date:
        raise ValueError(
            "Active channel has no "
            "start_date."
        )

    validate_date(start_date)

    if end_date < start_date:
        raise ValueError(
            "close date cannot be before "
            "channel start date."
        )

    channel["end_date"] = end_date

    if label:
        channel["label"] = label
    elif not channel.get("label"):
        channel["label"] = (
            f"Channel ending {end_date}"
        )

    if description is not None:
        if description:
            channel["description"] = (
                description
            )
        else:
            channel.pop(
                "description",
                None,
            )

    return channel


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Add, list or close observed "
            "trading channels."
        )
    )

    parser.add_argument(
        "asset",
        help=(
            "Asset symbol, e.g. "
            "DGB or MMT"
        ),
    )

    parser.add_argument(
        "start_date",
        nargs="?",
        help=(
            "Channel start date, "
            "YYYY-MM-DD"
        ),
    )

    parser.add_argument(
        "end_date",
        nargs="?",
        help=(
            "Optional end date when adding "
            "a historical channel"
        ),
    )

    mode = parser.add_mutually_exclusive_group()

    mode.add_argument(
        "--list",
        action="store_true",
        help=(
            "List channels for this asset "
            "newest first."
        ),
    )

    mode.add_argument(
        "--close",
        nargs="?",
        const="yesterday",
        metavar="DATE",
        help=(
            "Close the current active channel. "
            "If DATE is omitted, use yesterday."
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIST_LIMIT,
        help=(
            "Maximum channels displayed by "
            f"--list (default: "
            f"{DEFAULT_LIST_LIMIT})."
        ),
    )

    parser.add_argument(
        "--label",
        help=(
            "Optional channel label. "
            "On close, a default is generated "
            "if none exists."
        ),
    )

    parser.add_argument(
        "--description",
        help=(
            "Optional channel description "
            "or observation."
        ),
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    asset = args.asset.upper()

    try:
        data = load_channels()

        if args.list:
            if args.start_date or args.end_date:
                parser.error(
                    "--list does not accept "
                    "start_date/end_date."
                )

            if args.limit < 1:
                parser.error(
                    "--limit must be at least 1."
                )

            list_channels(
                data,
                asset,
                args.limit,
            )
            return

        if args.close is not None:
            if args.start_date or args.end_date:
                parser.error(
                    "--close does not accept "
                    "start_date/end_date."
                )

            close_date = resolve_close_date(
                args.close
            )

            channel = close_channel(
                data=data,
                asset=asset,
                end_date=close_date,
                label=args.label,
                description=args.description,
            )

            save_channels(data)

            print(
                f"Closed channel: "
                f"{asset} "
                f"{channel['start_date']} "
                f"-> {channel['end_date']}"
            )

            print(
                f"Label: "
                f"{channel['label']}"
            )

            if channel.get(
                "description"
            ):
                print(
                    "Description: "
                    f"{channel['description']}"
                )

            print(
                f"Stored in {DATA_FILE}"
            )

            return

        if not args.start_date:
            parser.error(
                "start_date is required when "
                "adding a channel. Use --list "
                "or --close for those operations."
            )

        channel = add_channel(
            data=data,
            asset=asset,
            start_date=args.start_date,
            end_date=args.end_date,
            label=args.label,
            description=args.description,
        )

        save_channels(data)

        status = (
            "active"
            if channel["end_date"] is None
            else "historical"
        )

        print(
            f"Added {status} channel: "
            f"{channel['asset']} "
            f"{channel['start_date']} "
            f"-> "
            f"{channel['end_date'] or 'ACTIVE'}"
        )

        if channel.get("label"):
            print(
                f"Label: "
                f"{channel['label']}"
            )

        print(
            f"Stored in {DATA_FILE}"
        )

    except (
        ValueError,
        json.JSONDecodeError,
    ) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
