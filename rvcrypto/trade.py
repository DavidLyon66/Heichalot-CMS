#!/usr/bin/env python3
"""
trade.py

Generate human-readable BUY/SELL instructions for manual Binance execution.

Reads hopsim signals and spike detection scores to produce a simple
checklist you can follow on the Binance app or website.

DISCLAIMER:
    This is not financial advice. You assume all risk.
    Use at your own discretion with money you can afford to lose.


Usage
-----

Generate instructions with default budget ($100):

    python3 trade.py

Generate instructions with custom budget:

    python3 trade.py --budget 500

Show current holdings only:

    python3 trade.py --list

Record a completed trade:

    python3 trade.py --execute BTC BUY 50
    python3 trade.py --execute MMT SELL 300

JSON output:

    python3 trade.py --json

Verbose hopsim output:

    python3 trade.py --verbose


Spike Integration
-----------------

The tool runs spike detection on all wallet tokens before generating
instructions. Two rules apply:

1. SPIKE-BASED SELL:
   Held tokens with spike score >75 get automatic SELL instructions.
   Spikes pull back — take profits before the drop.

2. SPIKE COOLDOWN:
   Buy candidates with a recent spike (last 3 days) get removed.
   Wait for the pullback to finish before entering.

Current spike scores are displayed before trade instructions:

    SPIKE DETECTION SCORES
    ------------------------------------------------------------
      ASSET     SCORE  VOL RATIO ASSESSMENT     

      BTC         29/100       1.6x WATCH          
      DOGE        56/100       1.7x SPIKE LIKELY   
      MMT         10/100       0.1x NO SPIKE       

    Tokens with score >=75 show "SELL SIGNAL" marker.


Output Format
-------------

The tool prints:

1. CURRENT HOLDINGS — your portfolio with quantities and values
2. SPIKE DETECTION SCORES — 0-100 score for each token
3. BUY INSTRUCTIONS — step-by-step for Binance execution
4. SELL INSTRUCTIONS — with reasons (spike, not in buy list, etc.)
5. FEE ESTIMATE — based on trade volume
6. EXECUTION SUMMARY — checklist you can tick off

Each BUY/SELL instruction also includes a PRICE LADDER: a list of
price levels to place your orders at, going up (for SELL/profit-taking)
or down (for BUY/support entries), sourced from stored peaks. Every
level carries a confidence percentage and a margin-of-error order range
so the exchange can fill without the price drifting out of reach:

    Ladder (BUY, goes down):
      #   PRICE        CONFIDENCE   ORDER RANGE
      1   0.149058      26.4%       0.146077 - 0.152039
      ...
      6   0.161343      46.6%       0.162064 - 0.164570

Use --levels to change the ladder size and --margin to set the
margin-of-error percent. The ladder is also emitted as structured JSON
(when --json is used) for feeding a visualiser.

Storage
-------

Holdings:  data/trade_holdings.json
Trade log: data/trade_log.json
"""

import argparse
import configparser
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import wallet
import hopsim
import ladder
import spikedetect


BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.ini"

DEFAULT_BUDGET = 100.0
DEFAULT_FEE_PCT = 0.10

# Spike thresholds for trade decisions
SPIKE_SELL_THRESHOLD = 75
SPIKE_COOLDOWN_DAYS = 3

# Price-ladder defaults
DEFAULT_LADDER_LEVELS = 6
DEFAULT_LADDER_MARGIN = 2.0


def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def get_reference(config):
    return config.get(
        "market-data",
        "reference_currency",
        fallback="USDT",
    ).upper()


def get_data_dir(config):
    path = Path(
        config.get("storage", "data_dir", fallback="data")
    )
    if not path.is_absolute():
        path = BASE / path
    return path


def load_current_prices(data_dir, assets, reference):
    prices = {}

    for asset in assets:
        path = data_dir / f"{asset}_{reference}.json"

        if not path.exists():
            continue

        with path.open("r", encoding="utf-8") as handle:
            document = json.load(handle)

        rows = document.get("data", [])

        if not rows:
            continue

        latest = rows[-1]

        try:
            prices[asset] = float(latest["close"])
        except (KeyError, TypeError, ValueError):
            continue

    return prices


def get_spike_scores(data_dir, assets, reference, lookback=30):
    scores = {}

    for asset in assets:
        path = data_dir / f"{asset}_{reference}.json"

        if not path.exists():
            continue

        try:
            rows = spikedetect.load_ohlcv(data_dir, asset, reference)
            parsed = spikedetect.parse_rows(rows)

            if len(parsed) < lookback + 1:
                continue

            result = spikedetect.detect_spike(
                parsed, len(parsed) - 1, window=7, lookback=lookback
            )
            scores[asset] = result
        except Exception:
            continue

    return scores


def has_recent_spike(data_dir, asset, reference, days=SPIKE_COOLDOWN_DAYS, lookback=30):
    path = data_dir / f"{asset}_{reference}.json"

    if not path.exists():
        return False

    try:
        rows = spikedetect.load_ohlcv(data_dir, asset, reference)
        parsed = spikedetect.parse_rows(rows)

        if len(parsed) < lookback + 1:
            return False

        for i in range(len(parsed) - days, len(parsed)):
            if i < lookback:
                continue
            result = spikedetect.detect_spike(parsed, i, window=7, lookback=lookback)
            if result["total_score"] >= SPIKE_SELL_THRESHOLD:
                return True
    except Exception:
        pass

    return False


def load_holdings():
    path = BASE / "data" / "trade_holdings.json"

    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_holdings(holdings):
    path = BASE / "data" / "trade_holdings.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as handle:
        json.dump(holdings, handle, indent=2)
        handle.write("\n")


def get_signal_recommendation(hopsim_result, asset):
    regimes = hopsim_result.get("json", {}).get("regimes", {})

    for regime_id, info in regimes.items():
        winner = info.get("predicted_winner", "")
        probs = info.get("winner_probabilities", {})

        if winner == asset:
            conf = info.get("confidence", 0)
            if conf >= 0.35:
                return "BUY"

        asset_prob = probs.get(asset, 0)
        if asset_prob >= 0.25:
            return "CONSIDER"

    return "HOLD"


def calculate_position_size(budget, price, allocation_pct):
    usd_amount = budget * allocation_pct / 100.0

    if price <= 0:
        return 0.0, 0.0

    quantity = usd_amount / price

    return usd_amount, quantity


def format_quantity(quantity, price):
    if price >= 1000:
        return f"{quantity:.6f}"
    if price >= 1:
        return f"{quantity:.4f}"
    if price >= 0.01:
        return f"{quantity:.2f}"

    return f"{quantity:.0f}"


def format_ladder_price(value):
    if value is None:
        return "      —"
    if value >= 100:
        return f"{value:.2f}"
    if value >= 1:
        return f"{value:.4f}"
    if value >= 0.01:
        return f"{value:.6f}"
    return f"{value:.8f}"


def print_ladder(ladder_data, reference):
    """Print a price-ladder (BUY or SELL ladder) to the console."""
    side = ladder_data["side"]
    direction = "up" if side == "SELL" else "down"
    print(f"     Ladder ({side}, goes {direction}):")
    print(
        f"       {'#':<3} {'PRICE':<12} {'CONFIDENCE':<12} {'ORDER RANGE'}"
    )
    for i, l in enumerate(ladder_data["levels"], 1):
        marker = ""
        if l.get("source") == "peak" and l.get("source_date"):
            marker = f"  (rank-{i})"
        print(
            f"       {i:<3} "
            f"{format_ladder_price(l['price']):<12} "
            f"{l['confidence_pct']:>5.1f}%{'':<6} "
            f"{format_ladder_price(l['range_low'])} – "
            f"{format_ladder_price(l['range_high'])}"
        )
    print()


def print_header():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print("=" * 60)
    print("  TRADE INSTRUCTIONS")
    print(f"  Generated: {now}")
    print("=" * 60)
    print()
    print("  DISCLAIMER: Not financial advice.")
    print("  You assume all risk. Use at your own discretion.")
    print()


def print_spike_scores(spike_scores):
    if not spike_scores:
        return

    print("SPIKE DETECTION SCORES")
    print("-" * 60)
    print(f"  {'ASSET':<8} {'SCORE':>6} {'VOL RATIO':>10} {'ASSESSMENT':<15}")
    print()

    for asset, result in sorted(spike_scores.items()):
        score = result["total_score"]
        vol_ratio = result["volume_ratio"]
        assessment = spikedetect.score_assessment(score)

        if score >= SPIKE_SELL_THRESHOLD:
            marker = " <-- SELL SIGNAL"
        else:
            marker = ""

        print(
            f"  {asset:<8} {score:>5}/100 {vol_ratio:>9.1f}x {assessment:<15}{marker}"
        )

    print()


def print_portfolio_status(holdings, prices, reference):
    print("CURRENT HOLDINGS")
    print("-" * 60)

    if not holdings:
        print("  No holdings recorded.")
        print()
        return 0.0

    total_value = 0.0

    print(f"  {'ASSET':<8} {'QTY':>12} {'PRICE':>12} {'VALUE':>12}")
    print()

    for asset, qty in holdings.items():
        if qty <= 0:
            continue

        price = prices.get(asset, 0)
        value = qty * price
        total_value += value

        qty_str = format_quantity(qty, price)

        print(
            f"  {asset:<8} {qty_str:>12} "
            f"{price:>12.4f} {value:>12.2f}"
        )

    print()
    print(f"  Total portfolio value: ${total_value:,.2f}")
    print()


def print_buy_instructions(buy_list, prices, reference, budget, ladders=None):
    if not buy_list:
        print("NO BUY INSTRUCTIONS")
        print("-" * 60)
        print("  No tokens flagged for purchase.")
        print()
        return

    print("BUY INSTRUCTIONS")
    print("-" * 60)
    print()

    for i, (asset, alloc_pct) in enumerate(buy_list, 1):
        price = prices.get(asset, 0)

        if price <= 0:
            print(f"  {i}. SKIP {asset} - no price data")
            continue

        usd_amount, quantity = calculate_position_size(
            budget, price, alloc_pct
        )

        qty_str = format_quantity(quantity, price)

        print(f"  {i}. BUY {asset}")
        print(f"     Go to: Binance > Spot > {asset}/{reference}")
        print(f"     Side:   BUY")
        print(f"     Amount: ~${usd_amount:.2f} ({qty_str} {asset})")
        print(f"     Price:  ~{price:.4f} {reference}")
        print(f"     Type:   Market order (or limit near {price:.4f})")
        print()

        if ladders and asset in ladders:
            print_ladder(ladders[asset], reference)

    print("  Execute each trade in order.")
    print("  Use MARKET order for speed, or LIMIT near current price.")
    print()


def print_sell_instructions(sell_list, holdings, prices, reference, spike_scores=None, ladders=None):
    if not sell_list:
        print("NO SELL INSTRUCTIONS")
        print("-" * 60)
        print("  No tokens flagged for sale.")
        print()
        return

    print("SELL INSTRUCTIONS")
    print("-" * 60)
    print()

    for i, (asset, reason) in enumerate(sell_list, 1):
        qty = holdings.get(asset, 0)

        if qty <= 0:
            print(f"  {i}. SKIP {asset} - no holdings")
            continue

        price = prices.get(asset, 0)
        value = qty * price
        qty_str = format_quantity(qty, price)

        spike_info = ""
        if spike_scores and asset in spike_scores:
            score = spike_scores[asset]["total_score"]
            spike_info = f" (spike score: {score}/100)"

        print(f"  {i}. SELL {asset}{spike_info}")
        print(f"     Reason: {reason}")
        print(f"     Go to: Binance > Spot > {asset}/{reference}")
        print(f"     Side:   SELL")
        print(f"     Amount: {qty_str} {asset} (~${value:.2f})")
        print(f"     Price:  ~{price:.4f} {reference}")
        print(f"     Type:   Market order (or limit near {price:.4f})")
        print()

        if ladders and asset in ladders:
            print_ladder(ladders[asset], reference)

    print("  Execute each trade in order.")
    print("  Use MARKET order for speed, or LIMIT near current price.")
    print()


def print_fee_estimate(buy_list, sell_list, prices, budget, fee_pct):
    total_trade_value = 0.0

    for asset, alloc_pct in buy_list:
        price = prices.get(asset, 0)
        usd_amount = budget * alloc_pct / 100.0
        total_trade_value += usd_amount

    for asset in sell_list:
        price = prices.get(asset, 0)
        total_trade_value += price * 0.01

    estimated_fee = total_trade_value * fee_pct / 100.0

    print("FEE ESTIMATE")
    print("-" * 60)
    print(f"  Approximate trade volume: ${total_trade_value:,.2f}")
    print(f"  Estimated fee ({fee_pct}%):     ${estimated_fee:,.2f}")
    print()


def print_instructions_summary(buy_list, sell_list):
    print("EXECUTION SUMMARY")
    print("-" * 60)

    if buy_list:
        print(f"  Buys:  {len(buy_list)} orders")
        for asset, alloc in buy_list:
            print(f"         - {asset} (${alloc:.0f}% of budget)")

    if sell_list:
        print(f"  Sells: {len(sell_list)} orders")
        for asset, reason in sell_list:
            print(f"         - {asset} ({reason})")

    if not buy_list and not sell_list:
        print("  No trades to execute.")

    print()
    print("  Checklist:")
    print("  [ ] Log into Binance")
    print("  [ ] Execute sells first (if any)")

    for i, (asset, _) in enumerate(buy_list, 1):
        print(f"  [ ] Buy {asset}")

    print("  [ ] Verify balances")
    print("  [ ] Record execution in trade_log.json")
    print()


def execute_trade(asset, side, amount, reference):
    path = BASE / "data" / "trade_holdings.json"
    log_path = BASE / "data" / "trade_log.json"

    holdings = load_holdings()

    data_dir = get_data_dir(load_config())

    prices = load_current_prices(
        data_dir,
        list(holdings.keys()) + [asset],
        reference,
    )

    price = prices.get(asset, 0)

    if price <= 0:
        print(f"Error: no price data for {asset}")
        return

    if side.upper() == "BUY":
        quantity = amount / price
        current_qty = holdings.get(asset, 0)
        holdings[asset] = current_qty + quantity

        print(f"RECORDED: BUY {quantity:.6f} {asset} @ {price:.4f}")
        print(f"  Cost: ${amount:.2f}")
        print(f"  New holding: {holdings[asset]:.6f} {asset}")

    elif side.upper() == "SELL":
        current_qty = holdings.get(asset, 0)

        if amount > current_qty:
            print(f"Error: cannot sell {amount} {asset}, only have {current_qty}")
            return

        holdings[asset] = current_qty - amount

        if holdings[asset] <= 0:
            del holdings[asset]

        print(f"RECORDED: SELL {amount:.6f} {asset} @ {price:.4f}")
        print(f"  Proceeds: ${amount * price:.2f}")

    else:
        print(f"Error: unknown side '{side}'")
        return

    save_holdings(holdings)

    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "asset": asset,
        "side": side.upper(),
        "amount": amount,
        "price": price,
        "value_usd": amount * price if side.upper() == "SELL" else amount,
    }

    log = []

    if log_path.exists():
        with log_path.open("r", encoding="utf-8") as handle:
            log = json.load(handle)

    log.append(log_entry)

    with log_path.open("w", encoding="utf-8") as handle:
        json.dump(log, handle, indent=2)
        handle.write("\n")

    print(f"  Logged to {log_path}")


def build_trade_ladders(config, assets_for_buy, assets_for_sell,
                        ladder_levels, ladder_margin):
    """Build price-ladders for every buy and sell asset.

    Returns a dict keyed by asset, plus the plain per-trade structure.
    """
    ladders = {}
    try:
        import ladder as ladder_mod
    except ImportError:
        return ladders, {}

    for asset in assets_for_buy:
        try:
            ladders[asset] = ladder_mod.build_ladder(
                config, asset, "BUY",
                levels=ladder_levels, margin_pct=ladder_margin,
            )
        except Exception:
            # No usable levels for this buy — skip the ladder
            continue
    for asset in assets_for_sell:
        try:
            ladders[asset] = ladder_mod.build_ladder(
                config, asset, "SELL",
                levels=ladder_levels, margin_pct=ladder_margin,
            )
        except Exception:
            continue
    return ladders


def make_instructions(
    budget=DEFAULT_BUDGET,
    fee_pct=DEFAULT_FEE_PCT,
    verbose=False,
    output_json=False,
    ladder_levels=DEFAULT_LADDER_LEVELS,
    ladder_margin=DEFAULT_LADDER_MARGIN,
):
    config = load_config()
    reference = get_reference(config)
    data_dir = get_data_dir(config)

    wallet_data = wallet.make_data(config)
    assets = [
        item["asset"]
        for item in wallet_data["assets"]
        if item["enabled"]
    ]

    if not assets:
        raise ValueError("No enabled tokens in wallet.")

    prices = load_current_prices(data_dir, assets, reference)

    if not prices:
        raise ValueError("No price data available.")

    holdings = load_holdings()

    if not output_json:
        print_header()
        print_portfolio_status(holdings, prices, reference)

    # Run spike detection
    spike_scores = get_spike_scores(data_dir, assets, reference)

    if not output_json:
        print_spike_scores(spike_scores)
        print("Running hopsim analysis...")
        print()

    hopsim_result = hopsim.make_report(
        window=21,
        clusters=6,
        confidence=0.28,
        forward_days=10,
        verbose=verbose,
    )

    signals = hopsim_result.get("json", {}).get("signals", [])

    buy_candidates = []

    for asset in assets:
        recommendation = get_signal_recommendation(hopsim_result, asset)

        if recommendation == "BUY":
            # Check if asset had a recent spike — skip if so
            if has_recent_spike(data_dir, asset, reference):
                if not output_json:
                    print(f"  Skipping {asset} — recent spike detected (cooldown)")
                continue

            buy_candidates.append(asset)

    if buy_candidates:
        alloc_per_token = 100.0 / len(buy_candidates)
        buy_list = [(a, alloc_per_token) for a in buy_candidates]
    else:
        buy_list = []

    sell_list = []

    # Check for spike-based sell signals
    for asset in list(holdings.keys()):
        qty = holdings.get(asset, 0)
        if qty <= 0:
            continue

        if asset in spike_scores:
            score = spike_scores[asset]["total_score"]
            if score >= SPIKE_SELL_THRESHOLD:
                sell_list.append((asset, f"Spike score {score}/100 — take profits"))
                continue

        if asset not in [b for b, _ in buy_list]:
            sell_list.append((asset, "Not in buy list"))

    # Build price-ladders for each buy/sell asset
    buy_assets = [b for b, _ in buy_list]
    sell_assets = [s for s, _ in sell_list]
    ladders = build_trade_ladders(
        config, buy_assets, sell_assets,
        ladder_levels, ladder_margin,
    )

    if not output_json:
        print_buy_instructions(buy_list, prices, reference, budget, ladders)
        print_sell_instructions(sell_list, holdings, prices, reference, spike_scores, ladders)
        print_fee_estimate(buy_list, sell_list, prices, budget, fee_pct)
        print_instructions_summary(buy_list, sell_list)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "budget": budget,
        "reference": reference,
        "prices": prices,
        "holdings": holdings,
        "spike_scores": {k: v["total_score"] for k, v in spike_scores.items()},
        "buy_list": buy_list,
        "sell_list": sell_list,
        "ladder_levels": ladder_levels,
        "ladder_margin_pct": ladder_margin,
        "ladders": {k: v for k, v in ladders.items()},
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Generate BUY/SELL instructions for manual Binance execution."
        )
    )

    parser.add_argument(
        "--budget",
        type=float,
        default=DEFAULT_BUDGET,
        metavar="USD",
        help=(
            "Total budget for new purchases "
            f"(default: {DEFAULT_BUDGET})."
        ),
    )

    parser.add_argument(
        "--fee",
        type=float,
        default=DEFAULT_FEE_PCT,
        metavar="PCT",
        help=(
            "Estimated fee percentage "
            f"(default: {DEFAULT_FEE_PCT})."
        ),
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="Show current holdings only.",
    )

    parser.add_argument(
        "--execute",
        nargs=3,
        metavar=("ASSET", "SIDE", "AMOUNT"),
        help="Record a completed trade. Example: --execute BTC BUY 50",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON data.",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include detailed hopsim output.",
    )

    parser.add_argument(
        "--levels",
        type=int,
        default=DEFAULT_LADDER_LEVELS,
        help=(
            "Number of price-ladder levels per trade "
            f"(default: {DEFAULT_LADDER_LEVELS})."
        ),
    )

    parser.add_argument(
        "--margin",
        type=float,
        default=DEFAULT_LADDER_MARGIN,
        help=(
            "Margin of error percent per ladder level "
            f"(default: {DEFAULT_LADDER_MARGIN})."
        ),
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.execute:
        asset, side, amount_text = args.execute
        asset = asset.upper()
        side = side.upper()

        if side not in ("BUY", "SELL"):
            parser.error("SIDE must be BUY or SELL")

        try:
            amount = float(amount_text)
        except ValueError:
            parser.error("AMOUNT must be a number")

        if amount <= 0:
            parser.error("AMOUNT must be positive")

        config = load_config()
        reference = get_reference(config)

        execute_trade(asset, side, amount, reference)
        return

    try:
        result = make_instructions(
            budget=args.budget,
            fee_pct=args.fee,
            verbose=args.verbose,
            output_json=args.json,
            ladder_levels=args.levels,
            ladder_margin=args.margin,
        )

        if args.json:
            print(
                json.dumps(
                    result,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
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
