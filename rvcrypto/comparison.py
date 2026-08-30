#!/usr/bin/env python3
"""
comparison.py

Compare the recommendations of existing rvcrypto analysis tools
with the new hopsim correlation-based hopping strategy.

Runs each analysis module on every enabled wallet token, then
presents a side-by-side comparison.

Typical use:

    python3 comparison.py
    python3 comparison.py --json
    python3 comparison.py --hopsim-window 21 --hopsim-clusters 6
"""

import argparse
import configparser
import json
import sys
from pathlib import Path

import wallet

import actionstatus
import breakdetect
import estimatetrades
import hopsim

try:
    import today
    HAS_TODAY = True
except Exception:
    HAS_TODAY = False

try:
    import turndetect
    HAS_TURNDETECT = True
except Exception:
    HAS_TURNDETECT = False


BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.ini"

DEFAULT_HOPSIM_WINDOW = 21
DEFAULT_HOPSIM_CLUSTERS = 6
DEFAULT_HOPSIM_CONFIDENCE = 0.28
DEFAULT_HOPSIM_FORWARD_DAYS = 10


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


def safe_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        return {"error": str(exc)}


def run_actionstatus(asset):
    result = safe_call(actionstatus.analyse, asset)

    if isinstance(result, dict) and "error" not in result:
        return {
            "tool": "actionstatus",
            "action": result.get("action", "UNKNOWN"),
            "zone": result.get("zone", "UNKNOWN"),
            "position_pct": result.get("position_pct"),
            "status": result.get("status", ""),
        }

    return {
        "tool": "actionstatus",
        "action": "ERROR",
        "zone": "ERROR",
        "position_pct": None,
        "status": str(result.get("error", "unknown")),
    }


def run_today(asset):
    if not HAS_TODAY:
        return {
            "tool": "today",
            "action": "UNAVAILABLE",
            "price_zone": "UNAVAILABLE",
            "position_pct": None,
            "message": "module not importable",
        }

    result = safe_call(today.analyse, asset)

    if isinstance(result, dict) and "error" not in result:
        return {
            "tool": "today",
            "action": result.get("action", "UNKNOWN"),
            "price_zone": result.get("price_zone", "UNKNOWN"),
            "position_pct": result.get("position_pct"),
            "message": result.get("message", ""),
        }

    return {
        "tool": "today",
        "action": "NO CHANNEL",
        "price_zone": "NO CHANNEL",
        "position_pct": None,
        "message": str(result.get("error", "unknown")),
    }


def run_breakdetect(asset):
    result = safe_call(breakdetect.make_report, asset)

    if isinstance(result, dict) and "error" not in result:
        break_data = result.get("json", {}).get("break", {})
        return {
            "tool": "breakdetect",
            "assessment": break_data.get("assessment", "UNKNOWN"),
            "up_score": break_data.get("up_total", 0),
            "down_score": break_data.get("down_total", 0),
        }

    return {
        "tool": "breakdetect",
        "assessment": "ERROR",
        "up_score": 0,
        "down_score": 0,
    }


def run_turndetect(asset):
    if not HAS_TURNDETECT:
        return {
            "tool": "turndetect",
            "assessment": "UNAVAILABLE",
            "total_score": 0,
            "swing_direction": "UNAVAILABLE",
            "swing_age": 0,
        }

    result = safe_call(turndetect.make_report, asset)

    if isinstance(result, dict) and "error" not in result:
        turn_data = result.get("json", {}).get("turn", {})
        swing = result.get("json", {}).get("current_swing", {})
        return {
            "tool": "turndetect",
            "assessment": turn_data.get("assessment", "UNKNOWN"),
            "total_score": turn_data.get("total", 0),
            "swing_direction": swing.get("direction", "UNKNOWN"),
            "swing_age": swing.get("days", 0),
        }

    return {
        "tool": "turndetect",
        "assessment": "NO CHANNEL",
        "total_score": 0,
        "swing_direction": "NO CHANNEL",
        "swing_age": 0,
    }


def run_estimatetrades(asset):
    result = safe_call(estimatetrades.analyse, asset)

    if isinstance(result, dict) and "error" not in result:
        trades = result.get("trades", {})
        returns = result.get("returns", {})
        return {
            "tool": "estimatetrades",
            "remaining": trades.get("remaining", 0),
            "completed": trades.get("completed", 0),
            "buys_remaining": trades.get("buys_remaining", 0),
            "sells_remaining": trades.get("sells_remaining", 0),
            "reality_trimmed": returns.get("reality_trimmed"),
        }

    return {
        "tool": "estimatetrades",
        "remaining": 0,
        "completed": 0,
        "buys_remaining": 0,
        "sells_remaining": 0,
        "reality_trimmed": None,
    }


def run_hopsim_signals(hopsim_data):
    signals = hopsim_data.get("signals", [])

    by_target = {}
    for sig in signals:
        target = sig["predicted_winner"]
        by_target[target] = by_target.get(target, 0) + 1

    if not by_target:
        return {}

    sorted_targets = sorted(
        by_target.items(),
        key=lambda x: x[1],
        reverse=True,
    )

    return {
        "total_signals": len(signals),
        "targets": dict(sorted_targets),
        "top_target": sorted_targets[0][0] if sorted_targets else None,
        "top_count": sorted_targets[0][1] if sorted_targets else 0,
    }


def run_hopsim_per_token(hopsim_data, assets):
    regimes = hopsim_data.get("json", {}).get("regimes", {})
    signals = hopsim_data.get("signals", [])

    token_recommendations = {}

    for asset in assets:
        regime_predictions = {}

        for regime_id, info in regimes.items():
            winner = info.get("predicted_winner", "")
            conf = info.get("confidence", 0)
            probs = info.get("winner_probabilities", {})

            asset_prob = probs.get(asset, 0)

            if winner == asset:
                regime_predictions[regime_id] = {
                    "status": "PREDICTED WINNER",
                    "confidence": conf,
                    "probability": asset_prob,
                }
            elif asset_prob > 0.20:
                regime_predictions[regime_id] = {
                    "status": "STRONG CONTENDER",
                    "confidence": conf,
                    "probability": asset_prob,
                }
            else:
                regime_predictions[regime_id] = {
                    "status": "WEAK",
                    "confidence": conf,
                    "probability": asset_prob,
                }

        asset_signals = [
            s for s in signals
            if s.get("predicted_winner") == asset
        ]

        if asset_signals:
            recommendation = "BUY TARGET"
            signal_count = len(asset_signals)
        else:
            is_predicted_elsewhere = any(
                s.get("predicted_winner") != asset
                for s in signals
                if s.get("predicted_winner")
            )

            if is_predicted_elsewhere:
                recommendation = "SELL/AVOID"
                signal_count = 0
            else:
                recommendation = "HOLD"
                signal_count = 0

        token_recommendations[asset] = {
            "recommendation": recommendation,
            "signal_count": signal_count,
            "regime_predictions": regime_predictions,
        }

    return token_recommendations


def normalise_action(raw_action):
    action = str(raw_action).upper()

    if "BUY" in action:
        return "BUY"
    if "SELL" in action:
        return "SELL"
    if "HOLD" in action or "WAIT" in action:
        return "HOLD"
    if "IGNORE" in action:
        return "HOLD"
    if "EXIT" in action:
        return "SELL"
    if "NO BREAK" in action or "POSSIBLE" in action:
        return "HOLD"
    if "STRONG" in action and "UP" in action:
        return "BUY"
    if "STRONG" in action and "DOWN" in action:
        return "SELL"
    if "CONFLICTING" in action:
        return "HOLD"
    if "NO CHANNEL" in action or "UNAVAILABLE" in action:
        return None

    return "HOLD"


def assess_alignment(opinions):
    actions = [
        normalise_action(o)
        for o in opinions
        if o not in ("ERROR", "UNKNOWN", "NO CHANNEL", "UNAVAILABLE")
        and normalise_action(o) is not None
    ]

    if not actions:
        return "NO DATA"

    buy_count = actions.count("BUY")
    sell_count = actions.count("SELL")
    hold_count = actions.count("HOLD")

    total = len(actions)

    if buy_count > total / 2:
        return "STRONG BUY CONSENSUS"
    if sell_count > total / 2:
        return "STRONG SELL CONSENSUS"
    if hold_count > total / 2:
        return "HOLD CONSENSUS"

    if buy_count > sell_count and buy_count > hold_count:
        return "LEANING BUY"
    if sell_count > buy_count and sell_count > hold_count:
        return "LEANING SELL"

    return "MIXED / NO CONSENSUS"


def print_comparison_table(token_results, hopsim_signals, hopsim_per_token):
    print("COMPARISON: EXISTING TOOLS vs HOPSIM")
    print("=" * 72)
    print()

    print("TOOL LEGEND")
    print("-" * 72)
    print("  actionstatus  = Daily action state (BUY/SELL ZONE)")
    print("  today         = Price zone analysis")
    print("  breakdetect   = Channel break / regime change")
    print("  turndetect    = Snake turn influence")
    print("  estimatetrades= Remaining trade opportunities")
    print("  hopsim        = Correlation-based hopping strategy")
    print()

    for asset, data in token_results.items():
        token_class = data.get("class", "unknown")
        ret = data.get("return_pct", 0)

        print(f"{asset} ({token_class})  [{ret:+.1f}%]")
        print("-" * 72)

        action_result = data["actionstatus"]
        today_result = data["today"]
        break_result = data["breakdetect"]
        turn_result = data["turndetect"]
        estimate_result = data["estimatetrades"]

        print(
            f"  actionstatus:  "
            f"{action_result['action']:<24} "
            f"zone: {action_result['zone']}"
        )

        print(
            f"  today:         "
            f"{today_result['action']:<24} "
            f"zone: {today_result['price_zone']}"
        )

        break_assessment = break_result['assessment']

        if break_result['assessment'] not in ("ERROR", "NO CHANNEL"):
            print(
                f"  breakdetect:   "
                f"{break_assessment:<24} "
                f"up: {break_result['up_score']:.1f} "
                f"down: {break_result['down_score']:.1f}"
            )
        else:
            print(
                f"  breakdetect:   "
                f"{break_assessment}"
            )

        turn_assessment = turn_result['assessment']

        if turn_result['assessment'] not in ("ERROR", "NO CHANNEL", "UNAVAILABLE"):
            print(
                f"  turndetect:    "
                f"{turn_assessment:<24} "
                f"swing: {turn_result['swing_direction']} "
                f"({turn_result['swing_age']}d)"
            )
        else:
            print(
                f"  turndetect:    "
                f"{turn_assessment}"
            )

        est_remaining = estimate_result["remaining"]
        est_completed = estimate_result["completed"]

        print(
            f"  estimatetrades:"
            f" {est_remaining} remaining "
            f"({est_completed} completed)"
        )

        if asset in hopsim_per_token:
            hs = hopsim_per_token[asset]
            rec = hs["recommendation"]
            count = hs["signal_count"]

            if rec == "BUY TARGET":
                print(
                    f"  hopsim:        "
                    f"-> {asset:<24} "
                    f"({count} signals predict this token)"
                )
            elif rec == "SELL/AVOID":
                print(
                    f"  hopsim:        "
                    f"SELL/AVOID (other tokens predicted to outperform)"
                )
            else:
                print(
                    f"  hopsim:        "
                    f"HOLD (no strong signal)"
                )
        else:
            print(f"  hopsim:        no data")

        print()

    print("ALIGNMENT SUMMARY")
    print("-" * 72)
    print(
        f"  {'ASSET':<8} "
        f"{'EXISTING TOOLS':<30} "
        f"{'HOPSIM':<20} "
        f"{'ALIGNMENT':<20}"
    )
    print()

    for asset, data in token_results.items():
        existing_opinions = [
            normalise_action(data["actionstatus"]["action"]),
            normalise_action(data["today"]["action"]),
            normalise_action(data["breakdetect"]["assessment"]),
            normalise_action(data["turndetect"]["assessment"]),
        ]

        valid_opinions = [
            o for o in existing_opinions
            if o is not None
        ]

        if not valid_opinions:
            existing_summary = "NO DATA"
        else:
            existing_summary = assess_alignment(
                [o for o in existing_opinions if o is not None]
            )

        if asset in hopsim_per_token:
            hs = hopsim_per_token[asset]
            rec = hs["recommendation"]

            if rec == "BUY TARGET":
                hopsim_action = f"-> {asset}"
                hopsim_norm = "BUY"
            elif rec == "SELL/AVOID":
                hopsim_action = "SELL/AVOID"
                hopsim_norm = "SELL"
            else:
                hopsim_action = "HOLD"
                hopsim_norm = "HOLD"
        else:
            hopsim_action = "NO DATA"
            hopsim_norm = "HOLD"

        align_actions = [
            o for o in existing_opinions + [hopsim_norm]
            if o is not None
        ]

        alignment = assess_alignment(align_actions)

        print(
            f"  {asset:<8} "
            f"{existing_summary:<30} "
            f"{hopsim_action:<20} "
            f"{alignment:<20}"
        )

    print()


def print_portfolio_comparison(hopsim_result):
    bt = hopsim_result.get("json", {}).get("backtest", {})

    if not bt:
        return

    print("PORTFOLIO BACKTEST")
    print("-" * 72)
    print(f"  Initial capital:     ${bt.get('initial_capital', 0):,.2f}")
    print(f"  Hopsim strategy:     ${bt.get('final_value', 0):,.2f}  "
          f"({bt.get('total_return_pct', 0):+.2f}%)")
    print(f"  Buy-and-hold:        ${bt.get('buy_hold_value', 0):,.2f}  "
          f"({bt.get('buy_hold_return_pct', 0):+.2f}%)")

    advantage = (
        bt.get("total_return_pct", 0)
        - bt.get("buy_hold_return_pct", 0)
    )

    if advantage > 0:
        print(f"  Hopsim advantage:    {advantage:+.2f}% (outperformed)")
    else:
        print(f"  Hopsim advantage:    {advantage:+.2f}% (underperformed)")

    print(f"  Total trades:        {bt.get('total_trades', 0)}")
    print()


def print_regime_summary(hopsim_result):
    regimes = hopsim_result.get("json", {}).get("regimes", {})

    if not regimes:
        return

    print("HOPSIM REGIME ANALYSIS")
    print("-" * 72)
    print(
        f"  {'REGIME':<10} "
        f"{'PREDICTED WINNER':<20} "
        f"{'CONFIDENCE':<12} "
        f"{'SAMPLES':<10}"
    )
    print()

    for regime_id in sorted(regimes.keys(), key=int):
        info = regimes[regime_id]
        winner = info.get("predicted_winner", "?")
        conf = info.get("confidence", 0)
        samples = info.get("sample_count", 0)

        print(
            f"  {regime_id:<10} "
            f"{winner:<20} "
            f"{conf:<12.0%} "
            f"{samples:<10}"
        )

    print()


def print_hopsim_detailed_analysis(hopsim_per_token, hopsim_result):
    regimes = hopsim_result.get("json", {}).get("regimes", {})

    if not regimes:
        return

    print("HOPSIM PER-TOKEN REGIME ANALYSIS")
    print("-" * 72)
    print()

    for asset in sorted(hopsim_per_token.keys()):
        data = hopsim_per_token[asset]
        regime_preds = data.get("regime_predictions", {})

        if not regime_preds:
            continue

        rec = data["recommendation"]
        count = data["signal_count"]

        if rec == "BUY TARGET":
            header = f"{asset}: BUY TARGET ({count} signals)"
        elif rec == "SELL/AVOID":
            header = f"{asset}: SELL/AVOID"
        else:
            header = f"{asset}: HOLD"

        print(f"  {header}")
        print()

        for regime_id in sorted(regime_preds.keys(), key=int):
            pred = regime_preds[regime_id]
            status = pred["status"]
            prob = pred["probability"]

            if status == "PREDICTED WINNER":
                marker = "*"
            elif status == "STRONG CONTENDER":
                marker = "+"
            else:
                marker = " "

            print(
                f"    {marker} Regime {regime_id}: "
                f"{status:<20} "
                f"prob: {prob:.0%}"
            )

        print()


def make_report(
    hopsim_window,
    hopsim_clusters,
    hopsim_confidence,
    hopsim_forward_days,
    verbose=False,
):
    config = load_config()
    reference = get_reference(config)

    wallet_data = wallet.make_data(config)
    assets = [
        item["asset"]
        for item in wallet_data["assets"]
        if item["enabled"]
    ]

    if not assets:
        raise ValueError("No enabled tokens in wallet.")

    print("Loading hopsim analysis...")
    print()

    hopsim_result = safe_call(
        hopsim.make_report,
        window=hopsim_window,
        clusters=hopsim_clusters,
        confidence=hopsim_confidence,
        forward_days=hopsim_forward_days,
        verbose=verbose,
    )

    if isinstance(hopsim_result, dict) and "error" in hopsim_result:
        print(f"Error running hopsim: {hopsim_result['error']}")
        sys.exit(1)

    hopsim_signals = run_hopsim_signals(hopsim_result)
    hopsim_per_token = run_hopsim_per_token(hopsim_result, assets)

    token_results = {}

    for asset in assets:
        print(f"Analysing {asset}...")

        data_dir = hopsim.get_data_dir(config)

        token_history = hopsim.load_token_history(
            data_dir, asset, reference
        )

        if token_history is None:
            continue

        start_price = token_history[0]["close"]
        end_price = token_history[-1]["close"]
        return_pct = (end_price / start_price - 1.0) * 100.0

        token_class = "safe" if asset in hopsim.SAFE_TOKENS else "unsafe"

        token_results[asset] = {
            "class": token_class,
            "return_pct": return_pct,
            "actionstatus": run_actionstatus(asset),
            "today": run_today(asset),
            "breakdetect": run_breakdetect(asset),
            "turndetect": run_turndetect(asset),
            "estimatetrades": run_estimatetrades(asset),
        }

    print()

    print_comparison_table(token_results, hopsim_signals, hopsim_per_token)
    print_portfolio_comparison(hopsim_result)
    print_regime_summary(hopsim_result)
    print_hopsim_detailed_analysis(hopsim_per_token, hopsim_result)

    return {
        "token_results": token_results,
        "hopsim_signals": hopsim_signals,
        "hopsim_result": hopsim_result.get("json", {})
            if isinstance(hopsim_result, dict)
            else {},
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Compare existing rvcrypto analysis tools with "
            "the hopsim correlation-based hopping strategy."
        )
    )

    parser.add_argument(
        "--hopsim-window",
        type=int,
        default=DEFAULT_HOPSIM_WINDOW,
        metavar="DAYS",
        help=(
            "Hopsim correlation window "
            f"(default: {DEFAULT_HOPSIM_WINDOW})."
        ),
    )

    parser.add_argument(
        "--hopsim-clusters",
        type=int,
        default=DEFAULT_HOPSIM_CLUSTERS,
        metavar="N",
        help=(
            "Hopsim regime clusters "
            f"(default: {DEFAULT_HOPSIM_CLUSTERS})."
        ),
    )

    parser.add_argument(
        "--hopsim-confidence",
        type=float,
        default=DEFAULT_HOPSIM_CONFIDENCE,
        metavar="0-1",
        help=(
            "Hopsim confidence threshold "
            f"(default: {DEFAULT_HOPSIM_CONFIDENCE})."
        ),
    )

    parser.add_argument(
        "--hopsim-forward-days",
        type=int,
        default=DEFAULT_HOPSIM_FORWARD_DAYS,
        metavar="DAYS",
        help=(
            "Hopsim forward lookahead "
            f"(default: {DEFAULT_HOPSIM_FORWARD_DAYS})."
        ),
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

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        result = make_report(
            hopsim_window=args.hopsim_window,
            hopsim_clusters=args.hopsim_clusters,
            hopsim_confidence=args.hopsim_confidence,
            hopsim_forward_days=args.hopsim_forward_days,
            verbose=args.verbose,
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
