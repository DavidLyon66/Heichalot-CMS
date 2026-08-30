# Cryptocurrency Trading Support System — Overview

A set of Python command-line tools that help you find and trade
**10–20% spike/movement opportunities** in cryptocurrency. The system
currently runs against **test data** as a proof-of-concept.

The end goal is software that identifies tradeable setups for someone
who is *not* a skilled trader. The core market observation the system
is built around:

> **When prices spike, they often return to previous peaks.**

So instead of trying to predict a spike's start, we focus on the
**spike-magnet levels** — price zones where a spike is likely to pull
price back up to — and give you a concrete ladder of order prices to
profit from the return.

> **DISCLAIMER:** Not financial advice. This is test software. Use at
> your own discretion, with money you can afford to lose.

---

## The workflow (big picture)

```
        collecthistory  →  per-asset OHLCV JSON files (+ peak markers)
                 │
                 ▼
   pricelevels   →  detect & STORE recent peaks (~3 months) + targets
                 │
                 ▼
       ladder    →  turn peaks into a price-ladder (BUY down / SELL up)
                 │          with confidence % and margin-of-error ranges
                 ▼
        trade    →  BUY/SELL instructions + fee estimate + JSON output
                 │
                 ▼
     dailyreport →  one combined daily report (portfolio, spikes,
                     targets, recommendation, conservative mode)
```

The tools all read the same per-asset JSON data files under `data/`
(e.g. `MMT_USDT.json`), so they compose cleanly.

---

## Data files

All an asset's history lives in a single JSON document per pair:

| File | Purpose |
|------|---------|
| `data/<ASSET>_USDT.json` | OHLCV rows plus marker arrays |
| `data/<ASSET>_USDT_spike_labels.json` | Ground-truth spike labels (validation) |
| `data/trade_holdings.json` | Quantities you hold per asset |
| `data/trade_log.json` | Executed-trade log |
| `data/recommendations.json` | Logged daily recommendations |

Each asset document carries marker arrays used across the tools:

- `daily-channel-markers` / `weekly-…` / `monthly-…`
- `daily-spike-markers` / `weekly-…` / `monthly-…`
- **`daily-peak-markers`** — the stored prior-high (peak) levels used for
  spike targets and price-ladders (see `pricelevels.md`)

---

## Program guide

| Program | What it does |
|---------|--------------|
| **`collecthistory.py`** | Fetches/collates OHLCV history into the per-asset JSON files; defines the document schema including marker arrays. |
| **`pricelevels.py`** | Scans history, persists recent peaks (last ~3 months) into `daily-peak-markers`, and computes spike-target probabilities from them. |
| **`ladder.py`** | Builds a ladder of trade levels (BUY down / SELL up), each with a confidence % and a margin-of-error order range. |
| **`trade.py`** | Generates BUY/SELL instructions (with ladders), spike-based sell alerts, budget split, fee estimate, and machine-readable JSON. |
| **`dailyreport.py`** | One combined daily report: portfolio, price overview, spike detection, calendar awareness, hopsim regime, spike targets, recommendation. Has a `--conservative` mode. |
| **`wallet.py`** | Asset registry & spike summary/history/sort commands. |
| **`spikedetect.py`** | Spike detection API (score 0–100, volume ratio, pullback). Used by trade/dailyreport. |
| **`hopsim.py`** | Correlation/regime signal analysis (BUY/CONSIDER/HOLD). |
| *(plus channel/turn/volume/shape/mma/whale tools)* | Earlier signal tools — not part of the current spike-trading workflow. |

---

## Spike scoring model

Spike detection produces a 0–100 score used to gate trades:

| Score | Meaning |
|-------|---------|
| **75+** | **SELL** — spike is hot, take profits before the pullback. |
| 50–74 | SPIKE LIKELY — watch. |
| 25–49 | WATCH — avoid fresh buys near a spike. |
| 0–24 | NO SPIKE — safe, may buy if oversold. |

Two rules gate `trade.py`:

1. **Spike-based SELL**: a held token scoring ≥75 triggers a SELL.
2. **Spike cooldown**: a buy candidate with a spike in the last ~3 days is
   skipped (wait for the pullback to finish).

---

## Conservative mode

`dailyreport.py --conservative` applies a capital-preservation tilt:

- Sell only if the held asset scores **≥65**.
- Avoid buying assets scoring **≥40**.
- Buy only if spike score is **<15** **and** price is **down ≥8% over 7d**.
- Keep a **30% cash reserve**.

---

## Token classes

- **Safe:** BTC, ETH, BNB
- **Unsafe (higher risk):** MMT, DGB, DOGE, SOL

The current wallet reference currency is **USDT**.

---

## Quick start

```bash
# 1. Store recent peaks once per asset (do this periodically)
python3 pricelevels.py MMT --scan --days 90

# 2. View the trade targets (probabilities) from the stored peaks
python3 pricelevels.py MMT --targets

# 3. Build a price-ladder for a monkey SELL or BUY
python3 ladder.py MMT SELL
python3 ladder.py MMT BUY

# 4. Generate trade instructions (with ladders) — human or JSON
python3 trade.py
python3 trade.py --json

# 5. Get the combined daily report (+ conservative variant)
python3 dailyreport.py
python3 dailyreport.py --conservative
```

See each program's own doc file for full usage:
[`pricelevels.md`](pricelevels.md), [`ladder.md`](ladder.md),
[`trade.md`](trade.md), [`dailyreport.md`](dailyreport.md).
