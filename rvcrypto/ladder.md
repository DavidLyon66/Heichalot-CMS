# ladder.py — Trade Price Ladders

Turn stored peaks into a **ladder of order prices** for a trade
instruction. For a SELL (profit taking) the ladder goes **up** through
peak profit targets; for a BUY (support entries) it goes **down** below
the current price.

Each level carries:

- **price** — the level / order price
- **confidence_pct** — estimated probability the level is reached
- **range_low / range_high** — the margin-of-error order window

## Margin of error

Exchanges may not fill an order if the price drifts even a few cents.
A fixed margin (default **±2%**, configurable with `--margin`) creates a
cushion range around every level. Ranges are forced **non-overlapping**,
so adjacent orders never conflict.

## Confidence

- For **SELL** (above current): confidence comes from the stored peak's
  reach-probability (from `pricelevels.py`); the nearest strong magnet
  ranks highest.
- For **BUY** (below current): confidence decays with depth — shallower
  support is more likely to be touched in a normal pullback.
- If there are fewer stored peaks than requested levels, the ladder is
  back-filled with derived levels whose confidence decays toward a small
  floor, so the ladder is always complete.

## Usage

```
Usage:
    python3 ladder.py ASSET SELL
    python3 ladder.py ASSET BUY
    python3 ladder.py ASSET SELL --levels 8 --margin 3
    python3 ladder.py ASSET BUY   --json
```

| Flag | Meaning |
|------|---------|
| `ASSET SELL|BUY` | Which asset and direction. |
| `--levels N` | Number of ladder levels (default `6`). |
| `--margin PCT` | Margin of error % per level (default `2.0`). |
| `--json` | Emit the ladder as structured JSON. |

## JSON output

The `--json` form is designed for a graphic visualiser:

```json
{
  "schema": "rvcrypto.ladder.v1",
  "type": "ladder",
  "asset": "MMT",
  "side": "SELL",
  "reference_currency": "USDT",
  "current_price": 0.1638,
  "margin_pct": 2.0,
  "levels": [
    {
      "price": 0.1907,
      "confidence_pct": 30.9,
      "source": "peak",
      "source_date": "2026-07-21",
      "range_low": 0.186886,
      "range_high": 0.194514
    }
  ]
}
```

> `trade.py` calls this internally to append a ladder under every BUY
> and SELL instruction.
