#!/usr/bin/env python3
import argparse, json
import html
from datetime import date
from pathlib import Path
import configparser

import actionstatus
import sys

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import lan

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
    path = DATA / "tradingchannels.json"

    if not path.exists():
        return None

    doc = load(path)
    found = [
        c for c in doc.get("channels", [])
        if str(c.get("asset", "")).upper() == asset
        and not c.get("end_date")
    ]

    if not found:
        return None

    if len(found) > 1:
        raise ValueError(
            f"More than one active channel exists for {asset}."
        )

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
    

def analyse(asset):
    """
    Run the TODAY analysis and return plain Python data.

    A trading channel is optional. If no active channel exists, TODAY
    uses the full available history and still reports the current
    price-zone status.
    """
    asset = str(asset).strip().upper()

    config = load_config()
    channel = active_channel(asset)

    latest = latest_history_date(asset)

    c = actionstatus.cfg()
    quote = actionstatus.reference(c)

    rows = actionstatus.history(
        asset,
        quote,
        c,
    )

    if channel is None:
        selected = list(rows)
        day = None
    else:
        start = date.fromisoformat(
            channel["start_date"]
        )

        day = (latest - start).days

        selected = actionstatus.channel_rows(
            rows,
            channel,
        )

    if not selected:
        raise ValueError(
            f"No history for {asset}/{quote}"
        )

    position = actionstatus.channel_position_pct(
        selected
    )

    zone = actionstatus.channel_zone(
        position
    )

    if zone == "EXTREME BUY ZONE":
        action = "STRONG BUY SIGNAL"
        message = "Price is in the extreme buy zone. "

    elif zone == "STRONG BUY ZONE":
        action = "BUY SIGNAL"
        message = "Price is in the strong buy zone. "

    elif zone == "EXTREME SELL ZONE":
        action = "STRONG SELL SIGNAL"
        message = "Price is in the extreme sell zone. "

    elif zone == "STRONG SELL ZONE":
        action = "SELL SIGNAL"
        message = "Price is in the strong sell zone. "

    elif channel is None:
        action = "HOLD"
        message = (
            "No active trading channel. "
            "Showing current position from available history."
        )

    else:
        action, message = rule(
            asset,
            channel,
            day,
        )

    hot_start, hot_end = get_hot_window(
        asset,
        channel,
    )

    channel_data = None

    if channel is not None:
        channel_data = {
            "label": channel.get("label"),
            "start_date": channel.get("start_date"),
            "end_date": channel.get("end_date"),
            "status": (
                "ACTIVE"
                if channel.get("end_date") is None
                else "HISTORICAL"
            ),
            "day": day,
            "hot_window_start": hot_start,
            "hot_window_end": hot_end,
        }

    return {
        "schema": "rvcrypto.today.v1",
        "type": "today",
        "asset": asset,
        "reference_currency": quote,
        "channel": channel_data,
        "latest_data": latest.isoformat(),
        "position_pct": position,
        "price_zone": zone,
        "action": action,
        "message": message,
    }

def report_text(data):
    """
    Render the existing plain-text TODAY report.
    """
    channel = data["channel"]

    if channel is None:
        return (
            f"{data['asset']}/{data['reference_currency']}\n"
            f"Channel:        (available history)\n"
            f"Latest data:    {data['latest_data']}\n"
            f"Price zone:     {data['price_zone']}\n"
            f"\n## TODAY\n\n"
            f"{data['action']}\n"
            f"{data['message']}"
        )

    return (
        f"{data['asset']}/{data['reference_currency']}\n"
        f"Channel start: {channel['start_date']}\n"
        f"Latest data:   {data['latest_data']}\n"
        f"Hot window:    days "
        f"{channel['hot_window_start']}-"
        f"{channel['hot_window_end']}\n"
        f"Channel day:   {channel['day']}\n"
        f"Price zone:    {data['price_zone']}\n"
        f"\n## TODAY\n\n"
        f"{data['action']}\n"
        f"{data['message']}"
    )

def action_icon_svg(action):
    """
    Return a tiny inline SVG icon for the current instruction.

    BUY  -> pale green triangle pointing up
    SELL -> pale orange triangle pointing down
    HOLD/WAIT/STOP/other -> blue square
    """
    action_upper = str(action or "").upper()

    if "BUY" in action_upper:
        return """
<svg viewBox="0 0 120 120"
     width="110" height="110"
     aria-label="Buy">
  <polygon
      points="60,12 108,104 12,104"
      fill="#b9dfc3" />
</svg>
""".strip()

    if (
        "SELL" in action_upper
        or action_upper == "EXIT"
    ):
        return """
<svg viewBox="0 0 120 120"
     width="110" height="110"
     aria-label="Sell">
  <polygon
      points="12,16 108,16 60,108"
      fill="#efc08f" />
</svg>
""".strip()

    return """
<svg viewBox="0 0 120 120"
     width="110" height="110"
     aria-label="Hold">
  <rect
      x="18" y="18"
      width="84" height="84"
      rx="5"
      fill="#8fbddd" />
</svg>
""".strip()


def report_html(data):
    """
    Render a deliberately tiny self-contained HTML TODAY card.

    Later this can move into a Jinja2 template without changing
    make_report() or the Flask endpoint.
    """
    asset = html.escape(
        str(data["asset"])
    )

    reference = html.escape(
        str(data["reference_currency"])
    )

    action = html.escape(
        str(data["action"])
    )

    message = html.escape(
        str(data["message"])
    )

    zone = html.escape(
        str(data["price_zone"])
    )

    latest = html.escape(
        str(data["latest_data"])
    )

    channel_day = html.escape(
        str(
            data["channel"]["day"]
            if data["channel"] is not None
            else "n/a"
        )
    )

    icon = action_icon_svg(
        data["action"]
    )

    return f"""
<div style="
    font-family:system-ui,sans-serif;
    color:#eef3f5;
    background:rgba(18,23,26,0.88);
    border:1px solid rgba(170,190,200,0.78);
    border-radius:10px;
    padding:22px;
    box-sizing:border-box;
    width:100%;
    height:100%;
">
  <div style="
      display:flex;
      align-items:center;
      gap:24px;
  ">
    <div style="
        flex:0 0 120px;
        text-align:center;
    ">
      {icon}
    </div>

    <div style="flex:1;">
      <div style="
          font-size:18px;
          opacity:0.72;
          margin-bottom:4px;
      ">
        {asset} / {reference}
      </div>

      <div style="
          font-size:34px;
          font-weight:700;
          line-height:1.05;
          margin-bottom:10px;
      ">
        {action}
      </div>

      <div style="
          font-size:18px;
          line-height:1.4;
          margin-bottom:18px;
      ">
        {message}
      </div>

      <div style="
          font-family:monospace;
          font-size:14px;
          line-height:1.6;
          opacity:0.72;
      ">
        Price zone: {zone}<br>
        Channel day: {channel_day}<br>
        Latest data: {latest}
      </div>
    </div>
  </div>
</div>
""".strip()


def make_report(asset):
    """
    Return the standard rvcrypto report envelope.
    """
    data = analyse(asset)

    return {
        "schema": "rvcrypto.report.v1",
        "type": "today",
        "asset": data["asset"],
        "reference_currency":
            data["reference_currency"],

        "report": report_text(data),
        "html": report_html(data),

        "json": data,

        # TODAY currently has no graph overlay.
        "display": None,

        # Reserved for future generated SVG/PNG/etc.
        "image": None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("asset")
    ap.add_argument(
        "--stream",
        action="store_true",
    )

    args = ap.parse_args()

    try:
        result = make_report(
            args.asset
        )

        report = result["report"]
        data = result["json"]
        action = data["action"]

        if args.stream:
            config = load_config()

            lan.stream(
                report,
                config=config,
                topic=config.get(
                    "today",
                    "topic",
                    fallback="rvcrypto/today",
                ),
            )

            alerts_enabled = (
                config.getboolean(
                    "alerts",
                    "enabled",
                    fallback=True,
                )
            )

            if (
                alerts_enabled
                and action in {
                    "BUY SIGNAL",
                    "STRONG BUY SIGNAL",
                    "SELL SIGNAL",
                    "STRONG SELL SIGNAL",
                }
            ):
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

    except (
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
    ) as e:
        ap.error(str(e))


if __name__ == "__main__":
    main()
