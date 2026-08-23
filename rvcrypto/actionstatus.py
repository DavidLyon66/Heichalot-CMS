#!/usr/bin/env python3
"""
actionstatus.py <asset> [--date YYYY-MM-DD] [--stream]

Small daily action-state helper for rvcrypto.

Outputs one of:
    HOLD (wait for spike)
    IGNORE
    ENTERING BUY ZONE
    ENTERING SELL ZONE
    LEAVING SELL ZONE

--date limits all calculations to that market date for regression testing.
--stream sends the final status through tools.lan.
"""

import argparse, configparser, json, statistics, sys
from datetime import date
from pathlib import Path
import sys

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import lan

BASE=Path(__file__).resolve().parent
CONFIG=BASE/"config.ini"
CHANNELS=BASE/"data"/"tradingchannels.json"
DEFAULT_QUOTE="USDT"
TOLERANCE_PCT=3.0
MIN_SAMPLES=2

def load(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)

def cfg():
    c=configparser.ConfigParser()
    c.read(CONFIG)
    return c

def reference(c):
    return c.get("market-data","reference_currency",fallback=DEFAULT_QUOTE).upper()

def data_dir(c):
    p=Path(c.get("storage","data_dir",fallback="data"))
    return p if p.is_absolute() else BASE/p

def history(asset,quote,cfg_obj,cutoff=None):
    path=data_dir(cfg_obj)/f"{asset}_{quote}.json"
    rows=[]
    for r in load(path).get("data",[]):
        try:
            row={
                "date":str(r["date"]),
                "open":float(r["open"]),
                "high":float(r["high"]),
                "low":float(r["low"]),
                "close":float(r["close"]),
                "volume":float(r.get("volume",0.0)),
            }
        except (KeyError,TypeError,ValueError):
            continue
        if cutoff is None or row["date"]<=cutoff:
            rows.append(row)
    rows.sort(key=lambda r:r["date"])
    if not rows:
        raise ValueError("No usable history.")
    return rows

def find_channel(asset,target_date):
    matches=[]
    for c in load(CHANNELS).get("channels",[]):
        if str(c.get("asset","")).upper()!=asset:
            continue
        start=c.get("start_date")
        end=c.get("end_date")
        if start and start<=target_date and (end is None or target_date<=end):
            matches.append(c)
    if not matches:
        return None
    matches.sort(key=lambda c:c.get("start_date",""))
    return matches[-1]

def channel_rows(rows,channel):
    start=channel["start_date"]
    end=channel.get("end_date")
    return [r for r in rows if r["date"]>=start and (end is None or r["date"]<=end)]

def daily(rows):
    out=[]
    prev=None
    for r in rows:
        state="FLAT"
        low_exc=high_exc=None
        if prev and prev["close"]:
            pc=prev["close"]
            if r["close"]>pc: state="UP"
            elif r["close"]<pc: state="DOWN"
            low_exc=(r["low"]/pc-1.0)*100.0
            high_exc=(r["high"]/pc-1.0)*100.0
        out.append({**r,"state":state,"low_exc":low_exc,"high_exc":high_exc})
        prev=r
    return out

def zone(rows,direction,latest_close):
    samples=[
        r for r in rows[:-1]
        if r["state"]==direction
        and r["low_exc"] is not None
        and r["high_exc"] is not None
    ]
    if len(samples)<MIN_SAMPLES:
        return None
    low_pct=statistics.median(r["low_exc"] for r in samples)
    high_pct=statistics.median(r["high_exc"] for r in samples)
    return {
        "low": latest_close*(1.0+low_pct/100.0),
        "high": latest_close*(1.0+high_pct/100.0),
    }

def near(price,target):
    if target in (None,0):
        return False
    return abs(price/target-1.0)*100.0<=TOLERANCE_PCT


def channel_position_pct(rows):
    """
    Position of latest close inside the full selected trading channel.

    0%   = channel low
    100% = channel high
    """
    if not rows:
        return None

    low = min(r["low"] for r in rows)
    high = max(r["high"] for r in rows)
    close = rows[-1]["close"]

    span = high - low
    if span <= 0:
        return None

    return (close - low) / span * 100.0


def channel_zone(position_pct):
    """
    Six equal channel-height zones.
    """
    if position_pct is None:
        return "UNKNOWN ZONE"

    if position_pct < 100.0 / 6.0:
        return "EXTREME BUY ZONE"

    if position_pct < 200.0 / 6.0:
        return "STRONG BUY ZONE"

    if position_pct < 50.0:
        return "LIGHT BUY ZONE"

    if position_pct < 400.0 / 6.0:
        return "LIGHT SELL ZONE"

    if position_pct < 500.0 / 6.0:
        return "STRONG SELL ZONE"

    return "EXTREME SELL ZONE"


def classify(rows):
    if len(rows)<3:
        return "HOLD (wait for spike)"

    latest=rows[-1]["close"]
    up=zone(rows,"UP",latest)
    down=zone(rows,"DOWN",latest)

    buy_targets=[z["low"] for z in (up,down) if z]
    sell_targets=[z["high"] for z in (up,down) if z]

    if any(near(latest,t) for t in buy_targets):
        return "ENTERING BUY ZONE"

    if any(near(latest,t) for t in sell_targets):
        return "ENTERING SELL ZONE"

    if len(rows)>=2:
        previous=rows[-2]["close"]
        if previous>latest and any(near(previous,t) for t in sell_targets):
            return "LEAVING SELL ZONE"

    return "HOLD (wait for spike)"


def analyse(asset, target_date=None):
    """
    Reusable action-status analysis.

    Returns plain Python data and does not print or publish anything.
    """
    asset = str(asset).strip().upper()

    c = cfg()
    quote = reference(c)

    rows = history(
        asset,
        quote,
        c,
        target_date,
    )

    target = (
        target_date
        or rows[-1]["date"]
    )

    date.fromisoformat(target)

    channel = find_channel(
        asset,
        target,
    )

    if channel is None:
        return {
            "schema": "rvcrypto.actionstatus.v1",
            "type": "actionstatus",
            "asset": asset,
            "reference_currency": quote,
            "date": target,
            "channel": None,
            "action": "IGNORE",
            "position_pct": None,
            "zone": None,
            "status": "IGNORE",
        }

    selected = channel_rows(
        rows,
        channel,
    )

    if not selected:
        return {
            "schema": "rvcrypto.actionstatus.v1",
            "type": "actionstatus",
            "asset": asset,
            "reference_currency": quote,
            "date": target,
            "channel": channel,
            "action": "IGNORE",
            "position_pct": None,
            "zone": None,
            "status": "IGNORE",
        }

    action = classify(
        daily(selected)
    )

    position = channel_position_pct(
        selected
    )

    zone_name = channel_zone(
        position
    )

    status = (
        f"{action} - "
        f"YOU ARE IN THE {zone_name}"
    )

    return {
        "schema": "rvcrypto.actionstatus.v1",
        "type": "actionstatus",
        "asset": asset,
        "reference_currency": quote,
        "date": target,
        "channel": {
            "label": channel.get("label"),
            "start_date": channel.get("start_date"),
            "end_date": channel.get("end_date"),
            "status": (
                "ACTIVE"
                if channel.get("end_date") is None
                else "HISTORICAL"
            ),
        },
        "action": action,
        "position_pct": position,
        "zone": zone_name,
        "status": status,
    }


def report_text(data):
    """
    Render a compact text report for the floating report panel.
    """
    if data["channel"] is None:
        return (
            f"{data['asset']}/{data['reference_currency']}\n"
            f"Date:       {data['date']}\n\n"
            f"ACTION STATUS\n"
            f"-------------\n"
            f"IGNORE\n"
            f"No trading channel is active for this date."
        )

    position = data.get("position_pct")

    position_text = (
        f"{position:.1f}%"
        if position is not None
        else "n/a"
    )

    channel = data["channel"]

    return (
        f"{data['asset']}/{data['reference_currency']}\n"
        f"Channel:    {channel.get('label') or '(unlabelled)'}\n"
        f"Period:     {channel.get('start_date')} -> "
        f"{channel.get('end_date') or data['date']}  "
        f"[{channel.get('status')}]\n"
        f"Date:       {data['date']}\n\n"
        f"ACTION STATUS\n"
        f"-------------\n"
        f"{data['action']}\n\n"
        f"Channel position: {position_text}\n"
        f"Price zone:       {data['zone']}\n\n"
        f"{data['status']}"
    )


def make_report(asset, target_date=None):
    """
    Return the standard rvcrypto report envelope.
    """
    data = analyse(
        asset,
        target_date=target_date,
    )

    return {
        "schema": "rvcrypto.report.v1",
        "type": "actionstatus",
        "asset": data["asset"],
        "reference_currency":
            data["reference_currency"],

        "report": report_text(data),

        "json": data,

        # No graph overlay for actionstatus yet.
        "display": None,

        "image": None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("asset")
    ap.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
    )
    ap.add_argument(
        "--stream",
        action="store_true",
    )

    a = ap.parse_args()

    try:
        result = make_report(
            a.asset,
            target_date=a.date,
        )

        status = result["json"]["status"]

        if a.stream:
            c = cfg()

            lan.stream(
                status,
                config=c,
                topic="rvcrypto/actionstatus",
            )
        else:
            print(status)

    except (
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        statistics.StatisticsError,
        RuntimeError,
    ) as e:
        print(
            f"Error: {e}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__=="__main__":
    main()
