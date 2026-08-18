#!/usr/bin/env python3
import argparse, json
from datetime import date
from pathlib import Path
import configparser

import actionstatus
from tools import lan

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.ini"
DATA = BASE_DIR / "data"
QUOTE = "USDT"

def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config

def load(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)

def active_channel(asset):
    doc = load(DATA / "tradingchannels.json")
    found = [c for c in doc.get("channels", [])
             if str(c.get("asset","")).upper() == asset
             and not c.get("end_date")]
    if len(found) != 1:
        raise ValueError(f"Expected one active channel for {asset}; found {len(found)}")
    return found[0]

def latest_history_date(asset):
    rows = load(DATA / f"{asset}_{QUOTE}.json").get("data", [])
    if not rows:
        raise ValueError(f"No history for {asset}/{QUOTE}")
    return date.fromisoformat(max(r["date"] for r in rows))

def get_hot_window(asset, channel):
    """
    Return the preferred trading-day range for this asset.

    Hard-coded for now. Later this can be calculated from historical
    spike/channel behaviour without changing the rule engine.
    """

    windows = {
        "MMT": (1, 4),
        "DGB": (1, 4),
        "ACE": (1, 4),
    }

    return windows.get(asset.upper(), (1, 4))
    
def rule(asset, channel, day):
    hot_start, hot_end = get_hot_window(asset, channel)

    if day <= 0:
        return "WAIT 1 DAY", "Buy tomorrow's dip."

    if day == hot_start:
        return "BUY DIP", "Buy today's dip."

    if hot_start < day <= hot_end:
        return "TRADE", "Trade the high volatility."

    if hot_end < day <= hot_end + 3:
        return "EXIT", "Exit the channel."

    return (
        "STOP",
        "Hands off the keyboard. Do not trade. "
        "Wait for the channel to finish."
    )
    
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("asset")
    ap.add_argument("--stream",action="store_true")
    args = ap.parse_args()
    asset = args.asset.upper()

    try:
        config = load_config()
        channel = active_channel(asset)
        start = date.fromisoformat(channel["start_date"])
        latest = latest_history_date(asset)
        day = (latest - start).days
        
        # Determine current position inside the trading channel.
        c = actionstatus.cfg()
        quote = actionstatus.reference(c)

        rows = actionstatus.history(
            asset,
            quote,
            c,
        )

        selected = actionstatus.channel_rows(
            rows,
            channel,
        )

        position = actionstatus.channel_position_pct(
            selected
        )

        zone = actionstatus.channel_zone(
            position
        )

        # Extreme/strong price opportunities override the normal
        # channel-age trading discipline.
        if zone == "EXTREME BUY ZONE":
            action = "STRONG BUY SIGNAL"
            message = (
                "Price is in the extreme buy zone. "
            )

        elif zone == "STRONG BUY ZONE":
            action = "BUY SIGNAL"
            message = (
                "Price is in the strong buy zone. "
            )

        elif zone == "EXTREME SELL ZONE":
            action = "STRONG SELL SIGNAL"
            message = (
                "Price is in the extreme sell zone. "
            )

        elif zone == "STRONG SELL ZONE":
            action = "SELL SIGNAL"
            message = (
                "Price is in the strong sell zone. "
            )

        else:
            action, message = rule(asset, channel, day)

        hot_start, hot_end = get_hot_window(asset, channel)

        report = (
            f"{asset}/{QUOTE}\n"
            f"Channel start: {start}\n"
            f"Latest data:   {latest}\n"
            f"Hot window:    days {hot_start}-{hot_end}\n"
            f"Channel day:   {day}\n"
            f"Price zone:    {zone}\n"
            f"\n## TODAY\n\n"
            f"{action}\n"
            f"{message}"
        )

        if args.stream:
            
            lan.stream(
                report,
                config=config,
                topic=config.get(
                    "today",
                    "topic",
                    fallback="rvcrypto/today",
                ),
            )            

            alerts_enabled = config.getboolean(
                "alerts",
                "enabled",
                fallback=True,
            )

            if alerts_enabled and action in {
                "BUY SIGNAL",
                "STRONG BUY SIGNAL",
                "SELL SIGNAL",
                "STRONG SELL SIGNAL",
            }:
                lan.stream(
                    report,
                    config=config,
                    topic=config.get(
                        "alerts",
                        "topic",
                        fallback="rvcrypto/alert",
                    ),
                )            
            
        else:
            print(report)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
        ap.error(str(e))

if __name__ == "__main__":
    main()
