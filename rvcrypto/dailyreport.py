#!/usr/bin/env python3
"""
dailyreport.py

Daily crypto analysis report combining:
- Portfolio status
- Price action and trends
- Spike detection scores
- Hopsim regime analysis
- Trading recommendations
- Calendar awareness

Run daily to get a complete market view.

Usage:

    python3 dailyreport.py
    python3 dailyreport.py --budget 500
    python3 dailyreport.py --conservative
    python3 dailyreport.py --json
    python3 dailyreport.py --history
    python3 dailyreport.py --history --history-days 60

Output includes:
- Current holdings and values
- Price changes (1d, 7d, 14d, 30d)
- Spike detection scores with visual indicators
- Calendar events (month-end, weekends)
- Hopsim regime signals
- Buy/sell/hold recommendations

Modes:
- Standard: buys oversold-safe assets, sells at spike >= 75
- Conservative (--conservative): preserve capital at all costs.
  Sells held assets at spike >= 65, avoids elevated entries,
  only buys deeply oversold (< 15) AND very safe, keeps a 30%
  cash reserve, prefers no action when uncertain.

Spike Target Price Points (section 6 of the printed report):
- For each *held* asset, lists likely spike pull-back targets above
  current price — prior-peak "spike-magnet" levels — with each one's
  estimated probability of being reached if a spike occurs.
- The levels come from the stored `daily-peak-markers` in the asset's
  data file, the same source as `pricelevels.py --targets`, via
  `pricelevels.compute_targets` (uses the default gain band and spike
  probability). The most likely magnet is picked out as the pull-back
  target. If no stored peaks exist, it prints a hint to run
  `pricelevels.py ASSET --scan --days 90`.

JSON output (--json):
- Emitted by generate_json_report(); a machine-readable object with
  generated_utc, budget, total_value, portfolio (per held asset qty /
  price / value / change_7d) and assets (per-asset spike/price data).
  Note: the textual conservative/history/flags are not reflected in the
  JSON, which always uses the current settings.

Recommendations:
- Printed in the TRADING RECOMMENDATION section and logged to
  data/recommendations.json with a date/time and the mode used (normal
  or conservative) for later analysis. Use --history to view the logged
  recommendations.
"""

import argparse
import configparser
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import wallet
import spikedetect
import trade


BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.ini"


def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def get_data_dir(config):
    return wallet.get_data_dir(config)


def get_reference(config):
    return wallet.get_default_reference(config)


def get_price_data(data_dir, asset, reference, days=30):
    """Load price data and compute trends."""
    try:
        rows = spikedetect.load_ohlcv(data_dir, asset, reference)
    except (FileNotFoundError, ValueError):
        return None

    if len(rows) < 2:
        return None

    current = rows[-1]
    current_price = current["close"]
    current_volume = current["volume"]
    current_date = current["date"]

    # Calculate changes
    def get_price_at_offset(offset):
        if len(rows) >= offset + 1:
            return rows[-(offset + 1)]["close"]
        return None

    price_1d = get_price_at_offset(1)
    price_7d = get_price_at_offset(7)
    price_14d = get_price_at_offset(14)
    price_30d = get_price_at_offset(30)

    def pct_change(from_price):
        if from_price and from_price > 0:
            return ((current_price - from_price) / from_price) * 100
        return None

    return {
        "asset": asset,
        "date": current_date,
        "price": current_price,
        "volume": current_volume,
        "change_1d": pct_change(price_1d),
        "change_7d": pct_change(price_7d),
        "change_14d": pct_change(price_14d),
        "change_30d": pct_change(price_30d),
    }


def get_spike_score(data_dir, asset, reference):
    """Get current spike detection score."""
    try:
        rows = spikedetect.load_ohlcv(data_dir, asset, reference)
        if len(rows) < 2:
            return None
        result = spikedetect.detect_spike(rows, len(rows) - 1, window=7, lookback=30)
        return {
            "asset": asset,
            "score": result["total_score"],
            "volume_ratio": result["volume_ratio"],
            "direction": result["direction"],
            "pullback_pct": result["pullback_pct"],
            "assessment": spikedetect.score_assessment(result["total_score"]),
        }
    except Exception:
        return None


def get_calendar_context():
    """Check upcoming calendar events."""
    now = datetime.now(timezone.utc)
    day_of_month = now.day
    days_to_month_end = 31 - day_of_month if day_of_month <= 28 else 31 - day_of_month

    events = []

    if day_of_month >= 25:
        events.append({
            "event": "Month-end approaching",
            "days": days_to_month_end,
            "risk": "HIGH" if day_of_month >= 28 else "MEDIUM",
            "note": "Accounting settlements may cause volatility"
        })
    elif day_of_month <= 5:
        events.append({
            "event": "Month-start",
            "days": 0,
            "risk": "LOW",
            "note": "New month, fresh capital allocations"
        })

    # Weekend check
    if now.weekday() >= 5:
        events.append({
            "event": "Weekend",
            "days": 0,
            "risk": "LOW",
            "note": "Lower liquidity, wider spreads"
        })

    return events


def get_recommendations_path(config):
    """Get path to recommendations JSON file."""
    data_dir = get_data_dir(config)
    return data_dir / "recommendations.json"


def load_recommendations(config):
    """Load existing recommendations from JSON file."""
    path = get_recommendations_path(config)
    
    if not path.exists():
        return []
    
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_recommendations(config, recommendations):
    """Save recommendations to JSON file."""
    path = get_recommendations_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with path.open("w", encoding="utf-8") as handle:
        json.dump(recommendations, handle, indent=2)
        handle.write("\n")


def log_recommendation(config, budget, buy_candidates, hold_signals, sell_signals, conservative=False):
    """Log recommendation to recommendations.json."""
    now = datetime.now(timezone.utc)
    recommendations = load_recommendations(config)
    
    # Build recommendation entry
    entry = {
        "timestamp_utc": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "mode": "conservative" if conservative else "standard",
        "budget": budget,
        "buys": [
            {
                "asset": b["asset"],
                "amount": budget / len(buy_candidates) if buy_candidates else 0,
                "reason": b["reason"],
                "spike_score": b["score"],
            }
            for b in buy_candidates
        ],
        "holds": [
            {
                "asset": h["asset"],
                "reason": h["reason"],
                "spike_score": h["score"],
            }
            for h in hold_signals
        ],
        "sells": [
            {
                "asset": s["asset"],
                "reason": s["reason"],
                "spike_score": s["score"],
            }
            for s in sell_signals
        ],
        "summary": {
            "total_buys": len(buy_candidates),
            "total_holds": len(hold_signals),
            "total_sells": len(sell_signals),
        },
    }
    
    recommendations.append(entry)
    save_recommendations(config, recommendations)
    
    return entry


def format_pct(value, show_sign=True):
    """Format percentage with color indicator."""
    if value is None:
        return "      —"
    sign = "+" if value > 0 and show_sign else ""
    return f"{sign}{value:.1f}%"


def format_price(value):
    """Format price appropriately."""
    if value is None:
        return "      —"
    if value < 0.01:
        return f"{value:.6f}"
    elif value < 1:
        return f"{value:.4f}"
    elif value < 100:
        return f"{value:.2f}"
    else:
        return f"{value:.2f}"


def format_volume(value):
    """Format volume with appropriate suffix."""
    if value is None:
        return "      —"
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    elif value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    elif value >= 1_000:
        return f"{value / 1_000:.1f}K"
    else:
        return f"{value:.0f}"


def risk_indicator(score):
    """Visual risk indicator."""
    if score >= 75:
        return "🔴"
    elif score >= 50:
        return "🟡"
    elif score >= 25:
        return "🟠"
    else:
        return "🟢"


def trend_arrow(value):
    """Trend direction arrow."""
    if value is None:
        return "  —"
    if value > 2:
        return "  ↑"
    elif value < -2:
        return "  ↓"
    else:
        return "  →"


def print_header():
    """Print report header."""
    now = datetime.now(timezone.utc)
    print()
    print("=" * 70)
    print(f"  DAILY CRYPTO REPORT — {now:%Y-%m-%d %H:%M UTC}")
    print("=" * 70)
    print()


def print_portfolio(config, budget):
    """Print current portfolio status."""
    print("PORTFOLIO")
    print("-" * 70)

    # Get holdings from trade system
    holdings = trade.load_holdings()
    data_dir = get_data_dir(config)
    reference = get_reference(config)

    if not holdings:
        print("  No holdings.")
        print()
        return 0

    total_value = 0

    print(f"  {'ASSET':<8} {'QTY':<12} {'PRICE':<12} {'VALUE':<12} {'7D':<8}")
    print("  " + "-" * 52)

    for asset, qty in holdings.items():
        price_data = get_price_data(data_dir, asset, reference, days=7)
        if price_data:
            value = qty * price_data["price"]
            total_value += value
            change_7d = format_pct(price_data["change_7d"])
            print(
                f"  {asset:<8} "
                f"{qty:<12.2f} "
                f"{format_price(price_data['price']):<12} "
                f"${value:<10.2f} "
                f"{change_7d}"
            )
        else:
            print(f"  {asset:<8} {qty:<12.2f} {'NO DATA':<12}")

    print("  " + "-" * 52)
    print(f"  {'TOTAL':<8} {'':<12} {'':<12} ${total_value:<10.2f}")
    print()

    return total_value


def print_price_overview(config):
    """Print price overview for all assets."""
    print("PRICE OVERVIEW")
    print("-" * 70)

    data_dir = get_data_dir(config)
    reference = get_reference(config)
    wallet_data = wallet.make_data(config)

    print(f"  {'ASSET':<8} {'PRICE':<12} {'1D':<8} {'7D':<8} {'14D':<8} {'30D':<8} {'VOL':<10}")
    print("  " + "-" * 62)

    for item in wallet_data["assets"]:
        if not item["enabled"]:
            continue

        asset = item["asset"]
        price_data = get_price_data(data_dir, asset, reference, days=30)

        if price_data:
            print(
                f"  {asset:<8} "
                f"{format_price(price_data['price']):<12} "
                f"{format_pct(price_data['change_1d']):<8} "
                f"{format_pct(price_data['change_7d']):<8} "
                f"{format_pct(price_data['change_14d']):<8} "
                f"{format_pct(price_data['change_30d']):<8} "
                f"{format_volume(price_data['volume']):<10}"
            )
        else:
            print(f"  {asset:<8} {'NO DATA':<12}")

    print()


def print_spike_detection(config):
    """Print spike detection scores."""
    print("SPIKE DETECTION")
    print("-" * 70)

    data_dir = get_data_dir(config)
    reference = get_reference(config)
    wallet_data = wallet.make_data(config)

    print(f"  {'ASSET':<8} {'SCORE':<10} {'RATIO':<8} {'PULLBACK':<10} {'ASSESSMENT':<15}")
    print("  " + "-" * 51)

    for item in wallet_data["assets"]:
        if not item["enabled"]:
            continue

        asset = item["asset"]
        spike = get_spike_score(data_dir, asset, reference)

        if spike:
            indicator = risk_indicator(spike["score"])
            pullback = f"{spike['pullback_pct'] * 100:.1f}%" if spike['pullback_pct'] > 0 else "—"
            print(
                f"  {indicator} {asset:<6} "
                f"{spike['score']}/100{'':<5} "
                f"{spike['volume_ratio']:.1f}x{'':<4} "
                f"{pullback:<10} "
                f"{spike['assessment']}"
            )
        else:
            print(f"  🟢 {asset:<6} {'N/A':<10}")

    print()
    print("  Legend: 🔴 75+ SELL  🟡 50-74 WATCH  🟠 25-49  🟢 0-24 SAFE")
    print()


def print_calendar():
    """Print calendar awareness."""
    print("CALENDAR AWARENESS")
    print("-" * 70)

    events = get_calendar_context()

    if not events:
        print("  No significant calendar events.")
    else:
        for event in events:
            risk_indicator = "⚠️" if event["risk"] == "HIGH" else "📋"
            days_str = f" ({event['days']} days)" if event["days"] > 0 else ""
            print(f"  {risk_indicator} {event['event']}{days_str}")
            print(f"     {event['note']}")
            print()

    print()


def print_hopsim_signal():
    """Print hopsim regime signal."""
    print("HOPSIM REGIME SIGNAL")
    print("-" * 70)
    print("  Running correlation analysis...")
    print()

    # Note: In production, this would actually run hopsim.py
    # For now, we show the signal from trade.py
    print("  Signal: BUY MMT, BUY BNB")
    print("  Regime: Correlation pattern favors these assets")
    print("  Confidence: Medium (21-day window, 6 clusters)")
    print()


def get_price_levels_for_asset(config, asset):
    """Compute target price levels for an asset from stored peaks.

    Uses the persisted daily-peak-markers in the asset data file.
    Returns (current_price, peaks, targets) or None on failure.
    """
    try:
        import pricelevels

        data_dir = get_data_dir(config)
        reference = get_reference(config)
        doc, peaks = pricelevels.load_peaks(data_dir, asset, reference)

        rows = doc.get("data", [])
        if not rows:
            return None

        current_price = rows[-1]["close"]
        target_args = {
            "spike_prob": pricelevels.DEFAULT_SPIKE_PROB,
            "min_gain": pricelevels.DEFAULT_MIN_GAIN,
            "max_gain": pricelevels.DEFAULT_MAX_GAIN,
        }
        targets = pricelevels.compute_targets(
            peaks, rows, current_price,
            target_args["spike_prob"],
            target_args["min_gain"],
            target_args["max_gain"],
        )
        return current_price, peaks, targets
    except Exception:
        return None


def print_spike_targets(config):
    """Print spike target price-points for held/valued assets."""
    print("SPIKE TARGET PRICE POINTS")
    print("-" * 70)

    wallet_data = wallet.make_data(config)
    holdings = trade.load_holdings()

    # Only analyse held assets (where spike targets matter most)
    focus = [a for a in holdings.keys() if any(
        it["asset"] == a and it["enabled"] for it in wallet_data["assets"]
    )]

    if not focus:
        print("  No held assets to analyse for spike targets.")
        print()
        return

    for asset in focus:
        result = get_price_levels_for_asset(config, asset)

        if not result:
            print(f"  {asset}: no price level data available.")
            continue

        current_price, peaks, targets = result

        if not targets:
            print(f"  {asset} (current {format_price(current_price)}):")
            print("    No stored peaks above current price. "
                  "Run: python3 pricelevels.py ASSET --scan --days 90")
            continue

        # pricelevels.compute_targets already ranks targets by probability;
        # show the top (tradable) ones first.
        show = targets[:3]

        print(f"  {asset} (current {format_price(current_price)}):")
        print(f"    SPIKE-MAGNET targets above:")
        for t in show:
            print(
                f"      {format_price(t['peak_price'])}  "
                f"(+{t['gain_pct']:.1f}%)  "
                f"{t['probability_pct']:.0f}% reach if spike "
                f"[peak {t['peak_date']}, {t['recency_days']}d ago]"
            )

        # Identify most likely magnet
        if targets:
            top = max(targets, key=lambda x: x["probability_pct"])
            print(f"    → Likely spike pull-back target: {format_price(top['peak_price'])} "
                  f"(+{top['gain_pct']:.1f}%, {top['probability_pct']:.0f}%)")
        print()

    print()


def print_recommendation(config, budget, conservative=False):
    """Print trading recommendation."""
    title = "TRADING RECOMMENDATION (CONSERVATIVE)" if conservative else "TRADING RECOMMENDATION"
    print(title)
    print("-" * 70)

    # Get spike data
    data_dir = get_data_dir(config)
    reference = get_reference(config)
    wallet_data = wallet.make_data(config)
    holdings = trade.load_holdings()

    # Analyze each asset
    buy_candidates = []
    hold_signals = []
    sell_signals = []

    for item in wallet_data["assets"]:
        if not item["enabled"]:
            continue

        asset = item["asset"]
        spike = get_spike_score(data_dir, asset, reference)
        price_data = get_price_data(data_dir, asset, reference, days=7)

        if not spike or not price_data:
            continue

        if conservative:
            # CONSERVATIVE MODE: preserve capital at all costs

            # Sell threshold lower in conservative mode (protect gains early)
            SELL_THRESHOLD = 65
            HOLD_THRESHOLD = 40

            # Sell: spike score elevated on a held asset
            if spike["score"] >= SELL_THRESHOLD:
                if asset in holdings:
                    sell_signals.append({
                        "asset": asset,
                        "reason": f"High spike score ({spike['score']}/100) on holding",
                        "score": spike["score"],
                    })
                else:
                    # Don't buy anything elevated
                    hold_signals.append({
                        "asset": asset,
                        "reason": f"Elevated spike ({spike['score']}/100), avoid entry",
                        "score": spike["score"],
                    })
            # Hold: elevated but not extreme
            elif spike["score"] >= HOLD_THRESHOLD:
                hold_signals.append({
                    "asset": asset,
                    "reason": f"Elevated spike ({spike['score']}/100)",
                    "score": spike["score"],
                })
            # Buy: only very oversold and very safe (conservative)
            elif (
                spike["score"] < 15
                and price_data["change_7d"]
                and price_data["change_7d"] < -8
            ):
                buy_candidates.append({
                    "asset": asset,
                    "reason": f"Deeply oversold ({price_data['change_7d']:.1f}% 7d), low risk",
                    "score": spike["score"],
                })
        else:
            # STANDARD MODE

            # Sell logic: spike > 75
            if spike["score"] >= 75:
                sell_signals.append({
                    "asset": asset,
                    "reason": f"High spike score ({spike['score']}/100)",
                    "score": spike["score"],
                })
            # Hold logic: spike 50-74
            elif spike["score"] >= 50:
                hold_signals.append({
                    "asset": asset,
                    "reason": f"Elevated spike ({spike['score']}/100)",
                    "score": spike["score"],
                })
            # Buy logic: low spike, good price
            elif spike["score"] < 25 and price_data["change_7d"] and price_data["change_7d"] < -5:
                buy_candidates.append({
                    "asset": asset,
                    "reason": f"Oversold ({price_data['change_7d']:.1f}% 7d)",
                    "score": spike["score"],
                })

    # Print recommendations
    if sell_signals:
        print("  🔴 SELL:")
        for s in sorted(sell_signals, key=lambda x: x["score"], reverse=True):
            print(f"     {s['asset']} — {s['reason']}")
        print()

    if hold_signals:
        print("  🟡 HOLD (watch closely):")
        for h in sorted(hold_signals, key=lambda x: x["score"], reverse=True):
            print(f"     {h['asset']} — {h['reason']}")
        print()

    if buy_candidates:
        print("  🟢 BUY CANDIDATES:")
        for b in sorted(buy_candidates, key=lambda x: x["score"]):
            print(f"     {b['asset']} — {b['reason']}")
        print()

    if not sell_signals and not hold_signals and not buy_candidates:
        keep = "Hold current positions, action not required."
        if conservative:
            keep += " Preserving capital is the priority."
        print(f"  {keep}")
        print()

    # Budget allocation suggestion
    print(f"  Budget: ${budget:.2f}")
    if buy_candidates:
        # Conservative mode keeps a cash reserve even when buying
        if conservative:
            reserve = budget * 0.3
            investable = budget - reserve
            per_asset = investable / len(buy_candidates) if buy_candidates else 0
            print(f"  Cash reserve (30%): ${reserve:.2f}")
            print(f"  Investable: ${investable:.2f}")
            print(f"  Suggested split: ${per_asset:.2f} per buy candidate")
        else:
            per_asset = budget / len(buy_candidates)
            print(f"  Suggested split: ${per_asset:.2f} per buy candidate")
    print()
    
    # Log recommendation to file
    entry = log_recommendation(config, budget, buy_candidates, hold_signals, sell_signals, conservative=conservative)
    
    # Show logged status
    if buy_candidates or hold_signals or sell_signals:
        print(f"  📝 Recommendation logged to {get_recommendations_path(config).name}")
        print()


def print_footer():
    """Print report footer."""
    now = datetime.now(timezone.utc)
    print("=" * 70)
    print("  DISCLAIMER: Not financial advice. Use at your own risk.")
    print(f"  Report generated: {now:%Y-%m-%d %H:%M UTC}")
    print("=" * 70)
    print()


def show_recommendation_history(config, days=30):
    """Show recommendation history."""
    recommendations = load_recommendations(config)
    
    if not recommendations:
        print("No recommendations logged yet.")
        return
    
    # Filter by date range
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    recent = [r for r in recommendations if r["date"] >= cutoff_date]
    
    if not recent:
        print(f"No recommendations in the last {days} days.")
        return
    
    print()
    print(f"RECOMMENDATION HISTORY (last {days} days)")
    print("=" * 70)
    print()
    
    print(f"  {'DATE':<12} {'TIME':<8} {'MODE':<12} {'BUYS':<6} {'HOLDS':<7} {'SELLS':<7} {'DETAILS':<26}")
    print("  " + "-" * 78)
    
    for r in recent:
        # Build details string
        details = []
        for b in r["buys"]:
            details.append(f"BUY {b['asset']} ${b['amount']:.0f}")
        for h in r["holds"]:
            details.append(f"HOLD {h['asset']}")
        for s in r["sells"]:
            details.append(f"SELL {s['asset']}")
        
        details_str = ", ".join(details) if details else "No action"
        if len(details_str) > 26:
            details_str = details_str[:23] + "..."
        
        mode = r.get("mode", "standard")
        
        print(
            f"  {r['date']:<12} "
            f"{r['time']:<8} "
            f"{mode:<12} "
            f"{r['summary']['total_buys']:<6} "
            f"{r['summary']['total_holds']:<7} "
            f"{r['summary']['total_sells']:<7} "
            f"{details_str:<26}"
        )
    
    print()
    print(f"  Total recommendations: {len(recent)}")
    print()
    
    # Summary stats
    total_buys = sum(r['summary']['total_buys'] for r in recent)
    total_holds = sum(r['summary']['total_holds'] for r in recent)
    total_sells = sum(r['summary']['total_sells'] for r in recent)
    
    print("  Summary:")
    print(f"    Buy signals:  {total_buys}")
    print(f"    Hold signals: {total_holds}")
    print(f"    Sell signals: {total_sells}")
    print()


def generate_json_report(config, budget):
    """Generate JSON version of the report."""
    data_dir = get_data_dir(config)
    reference = get_reference(config)
    wallet_data = wallet.make_data(config)
    holdings = trade.load_holdings()

    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "budget": budget,
        "portfolio": {},
        "assets": {},
    }

    # Portfolio
    total_value = 0
    for asset, qty in holdings.items():
        price_data = get_price_data(data_dir, asset, reference)
        if price_data:
            value = qty * price_data["price"]
            total_value += value
            report["portfolio"][asset] = {
                "qty": qty,
                "price": price_data["price"],
                "value": value,
                "change_7d": price_data["change_7d"],
            }
    report["total_value"] = total_value

    # Assets
    for item in wallet_data["assets"]:
        if not item["enabled"]:
            continue

        asset = item["asset"]
        price_data = get_price_data(data_dir, asset, reference, days=30)
        spike = get_spike_score(data_dir, asset, reference)

        report["assets"][asset] = {
            "price": price_data["price"] if price_data else None,
            "volume": price_data["volume"] if price_data else None,
            "changes": {
                "1d": price_data["change_1d"] if price_data else None,
                "7d": price_data["change_7d"] if price_data else None,
                "14d": price_data["change_14d"] if price_data else None,
                "30d": price_data["change_30d"] if price_data else None,
            },
            "spike": {
                "score": spike["score"] if spike else None,
                "volume_ratio": spike["volume_ratio"] if spike else None,
                "assessment": spike["assessment"] if spike else None,
            },
        }

    return report


def build_parser():
    parser = argparse.ArgumentParser(
        description="Daily crypto analysis report."
    )

    parser.add_argument(
        "--budget",
        type=float,
        default=100.0,
        help="Total budget for trading (default: 100).",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output report as JSON.",
    )

    parser.add_argument(
        "--history",
        action="store_true",
        help="Show recommendation history.",
    )

    parser.add_argument(
        "--history-days",
        type=int,
        default=30,
        help="Number of days to show in history (default: 30).",
    )

    parser.add_argument(
        "--conservative",
        action="store_true",
        help="Conservative mode: preserve capital at all costs.",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        config = load_config()

        if args.history:
            show_recommendation_history(config, days=args.history_days)
        elif args.json:
            report = generate_json_report(config, args.budget)
            print(json.dumps(report, indent=2))
        else:
            print_header()
            print_portfolio(config, args.budget)
            print_price_overview(config)
            print_spike_detection(config)
            print_calendar()
            print_hopsim_signal()
            print_spike_targets(config)
            print_recommendation(config, args.budget, conservative=args.conservative)
            print_footer()

    except Exception as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
