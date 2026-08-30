#!/usr/bin/env python3
"""
hopsim.py

Cryptocurrency hopping-simulation engine for rvcrypto.

Finds optimum hopping strategies between tokens by detecting
repeating correlation patterns across historical price data.

Typical use:

    python3 hopsim.py
    python3 hopsim.py --window 14 --clusters 5
    python3 hopsim.py --fee 0.001 --confidence 0.6
    python3 hopsim.py --json
    python3 hopsim.py --verbose

Token classes:

    SAFE:   BTC, ETH, BNB
    UNSAFE: MMT, DGB, DOGE, SOL

The simulation:
    1. Loads daily close prices for all enabled wallet tokens.
    2. Computes rolling pairwise correlation between all token pairs.
    3. Clusters correlation states into discrete regimes (K-Means).
    4. For each regime, records which token outperformed in subsequent days.
    5. When the current window matches a historical regime, generates
       a hop signal toward the predicted winner.
    6. Backtests the strategy with configurable transaction fees.
    7. Compares total return against a buy-and-hold baseline.
"""

import argparse
import configparser
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

import wallet
import collecthistory


BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.ini"

SAFE_TOKENS = {"BTC", "ETH", "BNB"}
UNSAFE_TOKENS = {"MMT", "DGB", "DOGE", "SOL"}

DEFAULT_WINDOW = 14
DEFAULT_CLUSTERS = 5
DEFAULT_FEE_PCT = 0.10
DEFAULT_CONFIDENCE = 0.60
DEFAULT_FORWARD_DAYS = 7
DEFAULT_MIN_REGIME_SAMPLES = 3


def load_config():
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return config


def get_data_dir(config):
    path = Path(
        config.get("storage", "data_dir", fallback="data")
    )
    if not path.is_absolute():
        path = BASE / path
    return path


def get_reference(config):
    return config.get(
        "market-data",
        "reference_currency",
        fallback="USDT",
    ).upper()


def load_token_history(data_dir, asset, reference):
    path = data_dir / f"{asset}_{reference}.json"

    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)

    rows = document.get("data", [])

    if not rows:
        return None

    records = []

    for row in rows:
        try:
            records.append({
                "date": str(row["date"]),
                "close": float(row["close"]),
            })
        except (KeyError, TypeError, ValueError):
            continue

    records.sort(key=lambda r: r["date"])

    if not records:
        return None

    return records


def build_close_dataframe(data_dir, assets, reference):
    series = {}

    for asset in assets:
        records = load_token_history(data_dir, asset, reference)

        if records is None:
            print(
                f"Warning: no history for {asset}/{reference}, skipping.",
                file=sys.stderr,
            )
            continue

        dates = [r["date"] for r in records]
        closes = [r["close"] for r in records]

        series[asset] = pd.Series(
            closes,
            index=pd.DatetimeIndex(dates),
            name=asset,
        )

    if not series:
        raise ValueError("No token history available.")

    df = pd.DataFrame(series)

    df = df.dropna()

    if len(df) < DEFAULT_WINDOW + DEFAULT_FORWARD_DAYS:
        raise ValueError(
            f"Insufficient overlapping history: {len(df)} days."
        )

    return df


def compute_daily_returns(close_df):
    return close_df.pct_change().dropna()


def rolling_correlation_features(returns, window):
    assets = list(returns.columns)
    pairs = []

    for i in range(len(assets)):
        for j in range(i + 1, len(assets)):
            pairs.append((assets[i], assets[j]))

    features = []

    for end_idx in range(window, len(returns)):
        start_idx = end_idx - window
        window_returns = returns.iloc[start_idx:end_idx]

        row = {}

        for asset_a, asset_b in pairs:
            corr = window_returns[asset_a].corr(
                window_returns[asset_b]
            )

            if np.isnan(corr):
                corr = 0.0

            pair_label = f"{asset_a}_{asset_b}"
            row[pair_label] = corr

        features.append(row)

    feature_df = pd.DataFrame(features)

    offset = window

    feature_df.index = returns.index[offset:]

    return feature_df, pairs


def cluster_regimes(feature_df, n_clusters, seed=42):
    scaler = StandardScaler()

    scaled = scaler.fit_transform(feature_df)

    kmeans = KMeans(
        n_clusters=n_clusters,
        random_state=seed,
        n_init=10,
    )

    labels = kmeans.fit_predict(scaled)

    regime_series = pd.Series(
        labels,
        index=feature_df.index,
        name="regime",
    )

    return regime_series, kmeans, scaler


def compute_forward_returns(close_df, forward_days):
    forward = close_df.pct_change(forward_days).shift(-forward_days)
    return forward


def build_regime_outcome_map(
    regime_series,
    forward_returns,
    assets,
    min_samples,
):
    regime_map = {}

    for regime_id in sorted(regime_series.unique()):
        mask = regime_series == regime_id
        regime_dates = regime_series[mask].index

        outcomes = forward_returns.loc[
            forward_returns.index.isin(regime_dates)
        ]

        outcomes = outcomes.dropna()

        if len(outcomes) < min_samples:
            continue

        winner_counts = {asset: 0 for asset in assets}
        total = len(outcomes)

        for _, row in outcomes.iterrows():
            best_asset = row[assets].idxmax()
            winner_counts[best_asset] += 1

        winner_probs = {
            asset: count / total
            for asset, count in winner_counts.items()
        }

        best_asset = max(winner_probs, key=winner_probs.get)
        best_prob = winner_probs[best_asset]

        regime_map[regime_id] = {
            "regime_id": int(regime_id),
            "sample_count": total,
            "winner_probabilities": winner_probs,
            "predicted_winner": best_asset,
            "confidence": best_prob,
        }

    return regime_map


def detect_token_class(asset):
    asset = asset.upper()

    if asset in SAFE_TOKENS:
        return "safe"

    if asset in UNSAFE_TOKENS:
        return "unsafe"

    return "unknown"


def generate_hop_signals(
    regime_series,
    regime_map,
    assets,
    confidence_threshold,
):
    signals = []

    for date, regime_id in regime_series.items():
        regime_info = regime_map.get(regime_id)

        if regime_info is None:
            continue

        if regime_info["confidence"] < confidence_threshold:
            continue

        signals.append({
            "date": date.strftime("%Y-%m-%d"),
            "regime_id": regime_info["regime_id"],
            "predicted_winner": regime_info["predicted_winner"],
            "confidence": regime_info["confidence"],
            "sample_count": regime_info["sample_count"],
        })

    return signals


def backtest(
    close_df,
    signals,
    assets,
    fee_pct,
    initial_capital,
):
    dates = close_df.index
    prices = close_df.values

    n_assets = len(assets)
    allocation = initial_capital / n_assets

    holdings = {asset: allocation for asset in assets}

    total_trades = 0
    hop_log = []

    signal_dates = {}
    for sig in signals:
        signal_dates[sig["date"]] = sig

    for i, date in enumerate(dates):
        date_str = date.strftime("%Y-%m-%d")

        for j, asset in enumerate(assets):
            if i > 0:
                prev_price = prices[i - 1, j]
                curr_price = prices[i, j]

                if prev_price > 0:
                    holdings[asset] *= curr_price / prev_price

        sig = signal_dates.get(date_str)

        if sig is not None:
            target = sig["predicted_winner"]
            current_best = max(holdings, key=holdings.get)

            if target != current_best and target in assets:
                sell_value = holdings[current_best]
                fee = sell_value * fee_pct / 100.0
                net_value = sell_value - fee

                holdings[current_best] = 0.0
                holdings[target] += net_value

                total_trades += 1

                hop_log.append({
                    "date": date_str,
                    "from": current_best,
                    "to": target,
                    "confidence": sig["confidence"],
                    "portfolio_value": sum(holdings.values()),
                })

    final_value = sum(holdings.values())

    bh_value = initial_capital

    for j, asset in enumerate(assets):
        first_price = prices[0, j]
        last_price = prices[-1, j]

        if first_price > 0:
            bh_value += (initial_capital / n_assets) * (
                last_price / first_price - 1.0
            )

    return {
        "initial_capital": initial_capital,
        "final_value": final_value,
        "total_return_pct": (final_value / initial_capital - 1.0) * 100.0,
        "buy_hold_value": bh_value,
        "buy_hold_return_pct": (bh_value / initial_capital - 1.0) * 100.0,
        "total_trades": total_trades,
        "hop_log": hop_log,
    }


def print_report(
    assets,
    close_df,
    regime_series,
    regime_map,
    signals,
    backtest_result,
    fee_pct,
    confidence,
    window,
    clusters,
    forward_days,
    verbose,
):
    print("HOPSIM - Crypto Hopping Simulation")
    print("=" * 40)
    print()

    print("TOKENS")
    print("-" * 40)

    for asset in assets:
        token_class = detect_token_class(asset)
        days = len(close_df)
        first = close_df[asset].iloc[0]
        last = close_df[asset].iloc[-1]
        ret = (last / first - 1.0) * 100.0

        print(
            f"  {asset:<8} {token_class:<8} "
            f"{days:>4} days  "
            f"return: {ret:+.1f}%"
        )

    print()

    print("PARAMETERS")
    print("-" * 40)
    print(f"  Correlation window:   {window} days")
    print(f"  Regime clusters:      {clusters}")
    print(f"  Forward lookahead:    {forward_days} days")
    print(f"  Transaction fee:      {fee_pct:.3f}%")
    print(f"  Confidence threshold: {confidence:.0%}")
    print()

    regime_counts = regime_series.value_counts().sort_index()

    print("REGIME DISTRIBUTION")
    print("-" * 40)

    for regime_id, count in regime_counts.items():
        info = regime_map.get(regime_id)

        if info is None:
            print(f"  Regime {regime_id}: {count} days (insufficient samples)")
            continue

        winner = info["predicted_winner"]
        conf = info["confidence"]
        samples = info["sample_count"]

        print(
            f"  Regime {regime_id}: {count:>4} days  "
            f"-> {winner:<6} "
            f"conf: {conf:.0%}  "
            f"({samples} samples)"
        )

    print()

    print("PREDICTED WINNERS BY REGIME")
    print("-" * 40)

    for regime_id in sorted(regime_map.keys()):
        info = regime_map[regime_id]
        probs = info["winner_probabilities"]

        sorted_probs = sorted(
            probs.items(),
            key=lambda x: x[1],
            reverse=True,
        )

        top3 = sorted_probs[:3]

        prob_str = "  ".join(
            f"{a}:{p:.0%}" for a, p in top3
        )

        print(f"  Regime {regime_id}: {prob_str}")

    print()

    print("HOP SIGNALS")
    print("-" * 40)
    print(f"  Total signals generated: {len(signals)}")

    if signals:
        by_target = {}

        for sig in signals:
            target = sig["predicted_winner"]
            by_target[target] = by_target.get(target, 0) + 1

        print("  Signals by target:")

        for target, count in sorted(
            by_target.items(),
            key=lambda x: x[1],
            reverse=True,
        ):
            print(f"    {target:<8} {count:>4}")

    print()

    print("BACKTEST RESULTS")
    print("-" * 40)

    bt = backtest_result

    print(f"  Initial capital:     ${bt['initial_capital']:,.2f}")
    print(f"  Hop strategy value:  ${bt['final_value']:,.2f}")
    print(f"  Strategy return:     {bt['total_return_pct']:+.2f}%")
    print(f"  Buy-hold value:      ${bt['buy_hold_value']:,.2f}")
    print(f"  Buy-hold return:     {bt['buy_hold_return_pct']:+.2f}%")
    print(f"  Total trades:        {bt['total_trades']}")

    diff = bt["total_return_pct"] - bt["buy_hold_return_pct"]

    if diff > 0:
        print(f"  Strategy advantage:  {diff:+.2f}% (outperformed)")
    else:
        print(f"  Strategy advantage:  {diff:+.2f}% (underperformed)")

    print()

    if verbose and bt["hop_log"]:
        print("HOP LOG (last 20)")
        print("-" * 40)

        for entry in bt["hop_log"][-20:]:
            print(
                f"  {entry['date']}  "
                f"{entry['from']:<6} -> {entry['to']:<6}  "
                f"conf: {entry['confidence']:.0%}  "
                f"portfolio: ${entry['portfolio_value']:,.2f}"
            )

        print()


def make_report(
    window=DEFAULT_WINDOW,
    clusters=DEFAULT_CLUSTERS,
    fee_pct=DEFAULT_FEE_PCT,
    confidence=DEFAULT_CONFIDENCE,
    forward_days=DEFAULT_FORWARD_DAYS,
    min_regime_samples=DEFAULT_MIN_REGIME_SAMPLES,
    initial_capital=10000.0,
    verbose=False,
):
    config = load_config()
    data_dir = get_data_dir(config)
    reference = get_reference(config)

    wallet_data = wallet.make_data(config)
    assets = [
        item["asset"]
        for item in wallet_data["assets"]
        if item["enabled"]
    ]

    if len(assets) < 2:
        raise ValueError("At least two enabled tokens required.")

    close_df = build_close_dataframe(
        data_dir, assets, reference
    )

    aligned_assets = list(close_df.columns)

    returns = compute_daily_returns(close_df)

    feature_df, pairs = rolling_correlation_features(
        returns, window
    )

    regime_series, kmeans, scaler = cluster_regimes(
        feature_df, clusters
    )

    forward_returns = compute_forward_returns(
        close_df, forward_days
    )

    regime_map = build_regime_outcome_map(
        regime_series,
        forward_returns,
        aligned_assets,
        min_regime_samples,
    )

    signals = generate_hop_signals(
        regime_series,
        regime_map,
        aligned_assets,
        confidence,
    )

    bt_result = backtest(
        close_df,
        signals,
        aligned_assets,
        fee_pct,
        initial_capital,
    )

    report_buffer_parts = []

    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()

    with redirect_stdout(buf):
        print_report(
            assets=aligned_assets,
            close_df=close_df,
            regime_series=regime_series,
            regime_map=regime_map,
            signals=signals,
            backtest_result=bt_result,
            fee_pct=fee_pct,
            confidence=confidence,
            window=window,
            clusters=clusters,
            forward_days=forward_days,
            verbose=verbose,
        )

    report_text = buf.getvalue().rstrip()

    json_data = {
        "tokens": [
            {
                "asset": asset,
                "class": detect_token_class(asset),
                "days": len(close_df),
                "start_price": float(close_df[asset].iloc[0]),
                "end_price": float(close_df[asset].iloc[-1]),
                "return_pct": float(
                    (close_df[asset].iloc[-1] / close_df[asset].iloc[0] - 1.0)
                    * 100.0
                ),
            }
            for asset in aligned_assets
        ],
        "parameters": {
            "window": window,
            "clusters": clusters,
            "forward_days": forward_days,
            "fee_pct": fee_pct,
            "confidence": confidence,
            "min_regime_samples": min_regime_samples,
        },
        "regimes": {
            str(rid): info
            for rid, info in regime_map.items()
        },
        "signals": signals,
        "backtest": {
            k: v
            for k, v in bt_result.items()
            if k != "hop_log"
        },
    }

    if verbose:
        json_data["hop_log"] = bt_result["hop_log"]

    return {
        "schema": "rvcrypto.report.v1",
        "type": "hopsim",
        "asset": "ALL",
        "reference_currency": reference,
        "report": report_text,
        "json": json_data,
        "display": None,
        "image": None,
    }


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Cryptocurrency hopping-simulation engine. "
            "Finds optimum strategies based on repeating "
            "correlation patterns."
        )
    )

    parser.add_argument(
        "--window",
        type=int,
        default=DEFAULT_WINDOW,
        metavar="DAYS",
        help=(
            "Rolling correlation window in days "
            f"(default: {DEFAULT_WINDOW})."
        ),
    )

    parser.add_argument(
        "--clusters",
        type=int,
        default=DEFAULT_CLUSTERS,
        metavar="N",
        help=(
            "Number of correlation regimes to detect "
            f"(default: {DEFAULT_CLUSTERS})."
        ),
    )

    parser.add_argument(
        "--fee",
        type=float,
        default=DEFAULT_FEE_PCT,
        metavar="PCT",
        help=(
            "Transaction fee percentage per hop "
            f"(default: {DEFAULT_FEE_PCT})."
        ),
    )

    parser.add_argument(
        "--confidence",
        type=float,
        default=DEFAULT_CONFIDENCE,
        metavar="0-1",
        help=(
            "Minimum confidence to generate a hop signal "
            f"(default: {DEFAULT_CONFIDENCE})."
        ),
    )

    parser.add_argument(
        "--forward-days",
        type=int,
        default=DEFAULT_FORWARD_DAYS,
        metavar="DAYS",
        help=(
            "Days ahead to evaluate token performance "
            f"(default: {DEFAULT_FORWARD_DAYS})."
        ),
    )

    parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        metavar="USD",
        help="Starting capital (default: 10000).",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON data.",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include hop log in output.",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.window < 2:
        parser.error("--window must be at least 2.")

    if args.clusters < 2:
        parser.error("--clusters must be at least 2.")

    if args.fee < 0:
        parser.error("--fee cannot be negative.")

    if not 0.0 <= args.confidence <= 1.0:
        parser.error("--confidence must be between 0 and 1.")

    if args.forward_days < 1:
        parser.error("--forward-days must be at least 1.")

    try:
        result = make_report(
            window=args.window,
            clusters=args.clusters,
            fee_pct=args.fee,
            confidence=args.confidence,
            forward_days=args.forward_days,
            initial_capital=args.capital,
            verbose=args.verbose,
        )

        if args.json:
            print(
                json.dumps(
                    result["json"],
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            print(result["report"])

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
