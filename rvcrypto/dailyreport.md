# dailyreport.py — Combined Daily Report

One command produces a single daily report covering the whole trading
picture: portfolio, prices, spike detection, calendar awareness, hopsim
regime, spike-magnet targets, and a trading recommendation.

```
Usage:
    python3 dailyreport.py
    python3 dailyreport.py --json
    python3 dailyreport.py --conservative
    python3 dailyreport.py --history
    python3 dailyreport.py --history-days 14
    python3 dailyreport.py --budget 100
```

## Options

| Flag | Meaning |
|------|---------|
| `--budget USD` | Budget used in the recommendation (default `100`). |
| `--json` | Emit a structured JSON report (via `generate_json_report`). |
| `--conservative` | Capital-preservation mode (see below). |
| `--history` | Show past logged recommendations. |
| `--history-days N` | How many days of history to show (default `30`). |

## Sections in the report

1. **PORTFOLIO** — holdings with quantity, price, value, 7-day change.
2. **PRICE OVERVIEW** — each asset across 1/7/14/30-day windows + volume.
3. **SPIKE DETECTION** — 0–100 scores with status legend.
4. **CALENDAR AWARENESS** — month-end / weekend volatility notes.
5. **HOPSIM REGIME SIGNAL** — correlation-based BUY/regime signal.
6. **SPIKE TARGET PRICE POINTS** — likely pull-back target levels for
   each *held* asset.
7. **TRADING RECOMMENDATION** — BUY candidates / HOLD-watch / sell notes.

## Spike Target Price Points (section 6)

- Scoped to assets you currently **hold** (not the whole wallet).
- The levels are "spike-magnet" pull-back targets above the current
  price, taken from the stored `daily-peak-markers` in the asset's data
  file — the same source as `pricelevels.py --targets`.
- Each level shows its projected gain and the estimated probability of
  being reached *if a spike occurs*, computed by
  `pricelevels.compute_targets` using the default gain band and spike
  probability. The highest-probability magnet is called out as the likely
  pull-back target.
- If an asset has no stored peaks above price, it prints a hint to run:
  `python3 pricelevels.py ASSET --scan --days 90`

## Conservative mode

`--conservative` tilts every decision toward preserving capital:

- Sell only if the held asset spike score ≥ **65**.
- Avoid buying assets with a spike score ≥ **40**.
- Buy only if spike score **<15** **and** price is down ≥ **8% over 7d**.
- Keep a **30% cash reserve**.

## JSON output

`--json` emits the machine-readable report produced by
`generate_json_report()`:

- `generated_utc` — ISO timestamp.
- `budget` — the `--budget` value.
- `total_value` — summed holding value.
- `portfolio` — per held asset: `qty`, `price`, `value`, `change_7d`.
- `assets` — per-asset spike/price detail used by the analysis.

Note: the console flags like `--conservative` and `--history` only affect
the printed output, not the JSON structure; the JSON always uses the
current settings.

## Recommendation history

The TRADING RECOMMENDATION is logged to `data/recommendations.json` with
a date/time and the mode used (`normal` or `conservative`) for later
analysis. Use `--history` to view the logged recommendations.

## Scheduling

For a daily automated run (shape scan + this report, with dated output),
see `dailyscan.py` — it invokes `dailyreport.py` and writes results under
`data/scan_out/`.
