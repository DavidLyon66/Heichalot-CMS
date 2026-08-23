#!/usr/bin/env python3
"""
whalecheck.py <asset> --date <YYYY-MM-DD> [--api rv|onchain] [--stream]

Experimental spike-investigation helper for rvcrypto.

Examples:

    python3 whalecheck.py MMT --date 2026-07-31
    python3 whalecheck.py MMT --date 2026-07-31 --api rv
    python3 whalecheck.py MMT --date 2026-07-31 --api rv --stream
    python3 whalecheck.py MMT --date 2026-07-31 --api onchain

The default API is "rv".

When api=rv, the program builds a structured remote-viewing request.
When api=onchain, this first version reports that the feature is not
available yet.

The remote-viewing prompt is intentionally embedded here as a
Jinja2-compatible template so it can be edited in one place now and
moved into a separate template file later if useful.

The program does not perform remote viewing itself.  It only emits the
request.

With --stream:
    tools.lan.stream() is used, so config.ini [stream] determines
    whether output goes to console or MQTT.

Without --stream:
    output is always printed locally.
"""

import argparse
import configparser
from pathlib import Path
import sys

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import lan

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.ini"

DEFAULT_API = "rv"
DEFAULT_RV_TOPIC = "rvcrypto/remote-viewing"


RV_PROMPT_TEMPLATE = r"""
---
type: remote-viewing.request
source: whalecheck.py
asset: {{ asset }}
reference_currency: {{ reference_currency }}
target_date: {{ target_date }}
target_type: crypto-volume-price-spike
---

Please remote-view the unusual trading spike involving {{ asset }}/{{ reference_currency }}
on {{ target_date }}.

The objective is to investigate the main reason behind the spike without assuming
in advance what caused it.

Please describe, as independently as possible:

1. The main event or activity associated with the spike.
2. The primary types of organisations, institutions, groups, or market participants
   involved.
3. Where those participants were generally located geographically, if that can be
   perceived with reasonable confidence.
4. Whether the activity appears more consistent with buying, selling, transfer,
   settlement, treasury movement, exchange activity, coordinated market activity,
   or some other cause.
5. Whether one dominant participant/event appears responsible, or whether the spike
   seems to result from several unrelated participants.
6. Any timing, operational, accounting-period, settlement-period, or organisational
   context that appears relevant.
7. Any other distinctive information that could later be checked against market,
   exchange, or blockchain evidence.

Please clearly separate stronger impressions from weak or uncertain impressions.
Do not assume that a large price/volume spike must have been caused by a whale,
payment, exchange, institution, or accounting event merely because those are
possibilities being investigated.
""".strip()


def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def get_reference_currency(config):
    return config.get(
        "market-data",
        "reference_currency",
        fallback="USDT",
    ).upper()


def render_rv_prompt(asset, reference_currency, target_date):
    """
    Render the embedded Jinja2-compatible prompt template.

    Jinja2 is used when installed.  A tiny fallback replacement is kept
    so this utility can still function in a minimal rvcrypto environment.
    """
    values = {
        "asset": asset,
        "reference_currency": reference_currency,
        "target_date": target_date,
    }

    try:
        from jinja2 import Template
        return Template(RV_PROMPT_TEMPLATE).render(**values)
    except ImportError:
        text = RV_PROMPT_TEMPLATE
        for key, value in values.items():
            text = text.replace("{{ " + key + " }}", str(value))
            text = text.replace("{{" + key + "}}", str(value))
        return text


def output_text(text, stream_requested, config):
    if not stream_requested:
        print(text)
        return

    topic = config.get(
        "whalecheck",
        "rv_topic",
        fallback=DEFAULT_RV_TOPIC,
    )

    lan.stream(
        text,
        config=config,
        topic=topic,
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a remote-viewing request or future on-chain "
            "investigation for a crypto spike."
        )
    )

    parser.add_argument(
        "asset",
        help="Asset symbol, e.g. MMT",
    )

    parser.add_argument(
        "--date",
        required=True,
        metavar="YYYY-MM-DD",
        help="Date of the spike/event to investigate",
    )

    parser.add_argument(
        "--api",
        choices=("rv", "onchain"),
        default=DEFAULT_API,
        help="Investigation API (default: rv)",
    )

    parser.add_argument(
        "--stream",
        action="store_true",
        help=(
            "Send output using tools.lan and config.ini [stream] "
            "instead of forcing local console output."
        ),
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    asset = args.asset.upper()
    config = load_config()
    reference_currency = get_reference_currency(config)

    if args.api == "onchain":
        text = (
            f"{asset}/{reference_currency} {args.date}\n"
            "ONCHAIN\n"
            "Not available. Please check later."
        )
        output_text(
            text=text,
            stream_requested=args.stream,
            config=config,
        )
        return

    prompt = render_rv_prompt(
        asset=asset,
        reference_currency=reference_currency,
        target_date=args.date,
    )

    output_text(
        text=prompt,
        stream_requested=args.stream,
        config=config,
    )


if __name__ == "__main__":
    main()
