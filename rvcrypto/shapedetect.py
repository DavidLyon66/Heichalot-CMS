#!/usr/bin/env python3
"""
shapedetect.py

Detect a distinctive "four-beat trading phrase" in crypto price series.

The idea
--------
Many (but not all) cryptos follow a recurring, almost musical four-beat
phrase — a blend of music and wave-theory. The shape is:

    0. starting position (flat / low baseline)
    1. a slow rise to a soft peak
    2. a slow falloff
    3. a possible sharp falloff
    4. a spike, then reversal
    5. a secondary, lower spike, then reversal
    6. a prolonged decline

Because no exact set of values works for every coin, this tool models the
phrase as a *parametric template curve* (a series of cubic Bezier segments
defined by anchor points on a normalized 0..1 plane) and then scans an
asset's history in sliding windows, scoring how closely each window
matches the template. The result is a tolerant 0-100 match score, not a
hard yes/no.

How detection works
-------------------
1. Normalize the whole price series to a 0..1 y-range (close price) so
   amplitude and absolute price don't matter.
2. For each candidate window of ~window_days bars, further normalize that
   window to 0..1 on both axes (x = time within window, y = price within
   window's own min..max).
3. Sample the template curve at many points and compute a correlation /
   distance-based score between the template and the observed window.
4. A high score means the observed path traces the phrase's shape
   (rise -> peak -> dual-spike -> decline) in the right order.

Because the template has both a *shape* and a *beat timing* but real
phrases vary in length, the scan is resized to the window length and you
can adjust how strictly timing is enforced with --time-strict and how much
the spike section is weighted with --spike-weight.

Usage
-----
Scan the latest history for matches and report the best ones:

    python3 shapedetect.py MMT --scan
    python3 shapedetect.py MMT --scan --days 120 --window 40

Scan another asset and list its best matches:

    python3 shapedetect.py DGB --scan --days 180 --top 8

Scan every enabled wallet asset over its full history, showing each
asset's best phrase (start -> end) and any strong matches:

    python3 shapedetect.py --all
    python3 shapedetect.py --all --min-score 60 --top 4
    python3 shapedetect.py --all --min-score 0 --top 1 --json

Emit JSON (for visualiser / further analysis):

    python3 shapedetect.py SOL --scan --json
    python3 shapedetect.py --all --json

Each JSON match also carries `points`: the dates the seven phrase beats
(start, soft peak, falloff, spike #1, reversal, spike #2, end) occur.

Per-asset 'best-ever' detection frequency
------------------------------------------
Each asset's strongest single-window match score is tracked as its
`best_min_score` — a measure of how often/strongly that asset does the
shape. It is persisted to `data/shape_scores.json` and reported per
asset in `--all` output (text and JSON).

    python3 shapedetect.py --all                    # update best-ever scores
    python3 shapedetect.py --all --no-update        # report, but never write
    python3 shapedetect.py --all --json             # includes best_min_score

The `--no-update` flag decides whether the scan is allowed to persist.
When an update IS allowed, the stored value is only ever raised (never
lowered), so a short `--days` scan cannot degrade the recorded
best-ever score. This flag only controls persistence of the score; it
does not change the detection algorithm itself.

Cross-reference spike-magnet targets
-------------------------------------
Add `--with-targets` to `--all` to attach each asset's stored
spike-magnet peaks above the current price (from `pricelevels.py`), so a
detected phrase points to the levels worth watching for a return trade:

    python3 shapedetect.py --all --with-targets
    python3 shapedetect.py --all --with-targets --json

Scheduling
----------
`dailyscan.py` runs the shape scan (with targets) plus the daily report
and writes dated output to `data/scan_out/`. It runs once by default,
or forever with `--daemon`; see its docstring for cron and nohup
examples (e.g. once a day at 07:00).

Show/collapse the template:

    python3 shapedetect.py --template
    python3 shapedetect.py --template --json

Tune detection:

    python3 shapedetect.py MMT --scan --window 40 --time-strict 1.0 \\
        --spike-weight 1.5 --top 5

DISCLAIMER: Not financial advice. Experimental tool for research only.
"""

import argparse
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import wallet

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
QUOTE = "USDT"

# ---------------------------------------------------------------------------
# The four-beat template
# ---------------------------------------------------------------------------
# Anchor points on the normalized (x,y) plane, x in [0,1] (time across the
# phrase), y in [0,1] (price across the phrase's own range). These describe
# the phrase: rise -> soft peak -> falloff -> sharp falloff -> spike ->
# lower spike -> prolonged decline. Editable to experiment.
#
# (x, y). Each pair is a cubic-Bezier *break point*; segments run between
# consecutive anchors. y is in "price range" units.
TEMPLATE_ANCHORS = [
    (0.00, 0.35),   # starting position (low-ish baseline)
    (0.10, 0.38),   # gentle lift starting
    (0.24, 0.72),   # slow rise
    (0.34, 0.95),   # soft peak (upper turning point)
    (0.44, 0.78),   # slow falloff
    (0.56, 0.62),   # falloff continues
    (0.66, 0.44),   # possible sharp falloff
    (0.71, 0.85),   # spike #1 (up) ...
    (0.75, 0.40),   # ... and reversal
    (0.79, 0.62),   # secondary (lower) spike + reversal
    (0.85, 0.25),   # post-spike decline begins
    (1.00, 0.05),   # prolonged decline ends low
]

N_TEMPLATE_SAMPLES = 120   # how many points we sample along the template
DEFAULT_WINDOW = 40        # default bars per scanned window (phrase length)
CONFIDENCE_SAMPLES = 80
SCORES_PATH = DATA / "shape_scores.json"   # persisted per-asset best-ever scores


# ---------------------------------------------------------------------------
# Loading / normalizing (reused from the capture half)
# ---------------------------------------------------------------------------

def load(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


def history_path(asset):
    return DATA / f"{asset}_{QUOTE}.json"


def shapes_path(asset):
    return DATA / f"{asset}_{QUOTE}_shapes.json"


def history(asset):
    rows = load(history_path(asset)).get("data", [])
    out = []
    for r in rows:
        try:
            out.append({
                "date": str(r["date"]),
                "close": float(r["close"]),
                "volume": float(r.get("volume", 0.0)),
            })
        except Exception:
            pass
    out.sort(key=lambda r: r["date"])
    if not out:
        raise ValueError("No usable history")
    return out


def normalize_series(rows):
    """Normalize an entire series keeping y per-point; returns (xs, ys, lo, hi)."""
    d0 = date.fromisoformat(rows[0]["date"])
    d1 = date.fromisoformat(rows[-1]["date"])
    days = max(1, (d1 - d0).days)
    closes = [r["close"] for r in rows]
    lo, hi = min(closes), max(closes)
    span = hi - lo
    xs = [(date.fromisoformat(r["date"]) - d0).days / days for r in rows]
    ys = [(r["close"] - lo) / span if span else 0.5 for r in rows]
    return xs, ys, lo, hi


# ---------------------------------------------------------------------------
# Cubic Bezier helpers
# ---------------------------------------------------------------------------

def _bezier(p0, p1, p2, p3, t):
    """Evaluate a cubic Bezier at parameter t in [0,1]."""
    mt = 1 - t
    a = mt * mt * mt
    b = 3 * mt * mt * t
    c = 3 * mt * t * t
    d = t * t * t
    return a * p0 + b * p1 + c * p2 + d * p3


def _segment_control(anchors, i):
    """Return the four control points for bezier segment i (between
    anchors[i] and anchors[i+1]) with clamped tangents so the curve is
    smooth but doesn't overshoot wildly."""
    (x0, y0) = anchors[i]
    (x1, y1) = anchors[i + 1]

    # neighbour-based tangents
    xm, ym = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    if i > 0:
        px, py = anchors[i - 1]
        c1x = x0 + (xm - px) * 0.33
        c1y = y0 + (ym - py) * 0.33
    else:
        c1x, c1y = x0 + 0.2, y0
    if i + 2 < len(anchors):
        nx, ny = anchors[i + 2]
        c2x = x1 - (nx - xm) * 0.33
        c2y = y1 - (ny - ym) * 0.33
    else:
        c2x, c2y = x1 - 0.2, y1
    return (x0, y0), (c1x, c1y), (c2x, c2y), (x1, y1)


def sample_template(anchors=None, n=N_TEMPLATE_SAMPLES):
    """Sample the template curve into a list of (x, y) points."""
    if anchors is None:
        anchors = TEMPLATE_ANCHORS
    segs = len(anchors) - 1
    pts = []
    per_seg = max(2, n // segs)
    for i in range(segs):
        p0, p1, p2, p3 = _segment_control(anchors, i)
        steps = per_seg if i < segs - 1 else per_seg + (n % segs)
        for k in range(steps):
            t = k / steps
            pts.append((_bezier(p0[0], p1[0], p2[0], p3[0], t),
                        _bezier(p0[1], p1[1], p2[1], p3[1], t)))
    # ensure monotonic-ish x ordering by sampling param, keep simple
    return pts


# ---------------------------------------------------------------------------
# Scoring a single window against the template
# ---------------------------------------------------------------------------

def _normalize_window(ys):
    """Normalize a window's y-values to 0..1 (own min..max)."""
    lo, hi = min(ys), max(ys)
    span = hi - lo
    if span <= 1e-12:
        return [0.5] * len(ys)
    return [(y - lo) / span for y in ys]


def _resample(xs, ys, m):
    """Resample a window (xs monotonic in [0,1], ys) onto m evenly spaced
    x-points using linear interpolation, so both template and window share
    the same x sampling."""
    out = []
    for k in range(m):
        tx = k / (m - 1)
        # find bracketing window points
        lo_i = 0
        while lo_i < len(xs) - 2 and xs[lo_i + 1] < tx:
            lo_i += 1
        hi_i = lo_i + 1
        x0, x1 = xs[lo_i], xs[min(hi_i, len(xs) - 1)]
        if x1 <= x0:
            out.append(ys[lo_i])
        else:
            f = (tx - x0) / (x1 - x0)
            out.append(ys[lo_i] * (1 - f) + ys[min(hi_i, len(xs) - 1)] * f)
    return out


def _score_window(template_ys, window_ys, spike_weight=1.0, time_strict=1.0):
    """Score how well `window_ys` (a list of floats, y-aligned [0,1]) follows
    a template y-series `template_ys` (also floats, same length).

    Returns (score_0_100, mae). Uses a blend of:
      - shape correlation (Pearson) -> how well the *pattern* of ups/downs
        matches, invariant to vertical offset/scale
      - mean absolute error on the normalized curves (timing fidelity)
    """
    n = min(len(template_ys), len(window_ys))
    if n < 4:
        return 0.0, 1.0

    ty = template_ys[:n]
    wy = window_ys[:n]

    # Pearson correlation between template y and window y
    mt, mw = sum(ty) / n, sum(wy) / n
    cov = sum((ty[i] - mt) * (wy[i] - mw) for i in range(n))
    vt = math.sqrt(sum((ty[i] - mt) ** 2 for i in range(n)))
    vw = math.sqrt(sum((wy[i] - mw) ** 2 for i in range(n)))
    corr = cov / (vt * vw) if (vt * vw) > 1e-12 else 0.0
    corr = max(-1.0, min(1.0, corr))
    corr_scaled = max(0.0, corr)  # we only care about positively-correlated shapes

    # Mean absolute error in normalized amplitude-space
    mae = sum(abs(ty[i] - wy[i]) for i in range(n)) / n

    # The spike section is the distinctive part; weigh errors there more.
    # Spike is around x in [0.68, 0.80] of the phrase.
    spike_start = int(n * 0.66)
    spike_end = min(n, int(n * 0.82))
    spike_mae = 0.0
    if spike_end > spike_start:
        spike_mae = sum(abs(ty[i] - wy[i])
                        for i in range(spike_start, spike_end)) / (spike_end - spike_start)

    # Combine: high correlation good, low error good.
    # weight the errors; spike_weight emphasises matching the double-spike.
    err = mae + (spike_mae * (spike_weight - 1.0))
    err *= (1.0 + (time_strict - 1.0) * 0.5)

    # Convert to a 0-100 score. corr in [0,1], err in [0,~1].
    score = corr_scaled * 100.0 - err * 60.0
    score = max(0.0, min(100.0, score))
    return round(score, 1), round(mae, 4)


# ---------------------------------------------------------------------------
# Seven "beat" landmarks
# ---------------------------------------------------------------------------
# The phrase is described by seven reference points (x fraction through the
# phrase, plus a label). For a matched window we find the actual bar that
# lands nearest each anchor's x fraction, giving concrete dates for when
# each beat of the shape occurred.
SEVEN_BEATS = [
    ("start",           0.00),
    ("soft_peak",       0.34),
    ("post_falloff",    0.66),
    ("spike_1",         0.71),
    ("reversal_1",      0.75),
    ("spike_2",         0.79),
    ("end",             0.99),
]


def _extract_seven(wxn, wy, dates):
    """Map the seven phrase beats onto a matched window.

    wxn    : window x-fractions in [0,1] (same length as wy and dates)
    wy     : window y-values (0..1, whole series normalized)
    dates  : window bar dates (same length)

    Returns a list of {beat, x, date, y} for each of the seven landmarks.
    """
    out = []
    for label, tx in SEVEN_BEATS:
        if not wxn:
            break
        idx = min(range(len(wxn)), key=lambda j: abs(wxn[j] - tx))
        out.append({
            "beat": label,
            "x": round(wxn[idx], 4),
            "date": dates[idx],
            "y": round(wy[idx], 4),
        })
    return out


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def scan_asset(asset, window=DEFAULT_WINDOW, max_days=None, spike_weight=1.0,
               time_strict=1.0, step=1):
    """Scan an asset's history, sliding a window, and return matches.

    Returns a list of dicts: {date, end_date, score, rmse, index}.
    Sorted by score descending.
    """
    rows = history(asset)
    if max_days:
        cutoff = (date.fromisoformat(rows[-1]["date"])
                  - timedelta(days=max_days)).isoformat()
        rows = [r for r in rows if r["date"] >= cutoff]
        if len(rows) < window + 1:
            return []

    xs, ys, lo, hi = normalize_series(rows)
    m = CONFIDENCE_SAMPLES
    template_ys = _resample_tw(sample_template(), m)

    matches = []
    n = len(rows)
    for i in range(0, n - window + 1, step):
        wx = xs[i:i + window]
        wy = ys[i:i + window]
        wxn = [(x - wx[0]) / (wx[-1] - wx[0]) if wx[-1] > wx[0] else 0.0
               for x in wx]
        wy_s = _resample(wxn, _normalize_window(wy), m)
        score, rmse = _score_window(template_ys, wy_s, spike_weight, time_strict)
        matches.append({
            "date": rows[i]["date"],
            "end_date": rows[i + window - 1]["date"],
            "score": score,
            "rmse": rmse,
            "index": i,
            "points": _extract_seven(wxn, wy, [r["date"] for r in rows[i:i + window]]),
        })
    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches


def _resample_tw(template, m):
    """Template sampled onto m evenly spaced x in [0,1]."""
    pts = sorted(template, key=lambda p: p[0])
    # drop non-increasing x duplicates / glitches from bezier tangents
    cleaned = []
    for p in pts:
        if not cleaned or p[0] > cleaned[-1][0]:
            cleaned.append(p)
        else:
            cleaned.append((cleaned[-1][0] + 1e-6, p[1]))
    return _resample([p[0] for p in cleaned], [p[1] for p in cleaned], m)


def _print_scan(asset, matches, top):
    print(f"SHAPE SCAN: {asset}/{QUOTE}  ('four-beat phrase' template)")
    print("=" * 66)
    if not matches:
        print("  No windows big enough to scan.")
        print()
        return
    print(f"  {len(matches)} windows scored; showing best {top}:\n")
    print(f"  {'#':<4} {'SCORE':<8} {'START':<12} {'END':<12} {'RMSE'}")
    print("  " + "-" * 52)
    for idx, m in enumerate(matches[:top], 1):
        bar = "#" * int(round(m["score"] / 5))
        print(
            f"  {idx:<4} {m['score']:>5.1f}/100{'':<2} "
            f"{m['date']:<12} {m['end_date']:<12} "
            f"{m['rmse']:<8.3f}{bar}"
        )
    print()
    best = matches[0]
    print(f"  Best match: {best['date']} -> {best['end_date']} "
          f"(score {best['score']}/100)")
    print("  A high score means the price traced the phrase's shape "
          "(rise -> peak -> dual spike -> decline).")
    print()


def _print_template():
    pts = sample_template()
    print(f"FOUR-BEAT PHRASE TEMPLATE ({len(pts)} sampled points)")
    print("=" * 66)
    for name, y in zip(
        ["start", "rise-start", "rise", "soft-peak", "falloff", "falloff-2",
         "sharp-falloff", "spike#1", "reversal#1", "spike#2", "decline", "end"],
        TEMPLATE_ANCHORS,
    ):
        print(f"  {name:<14} (x={y[0]:.2f}, y={y[1]:.2f})")
    print("\n  Bezier control points (anchors):")
    for a in TEMPLATE_ANCHORS:
        print(f"    ({a[0]:.2f}, {a[1]:.2f})")
    print()


# ---------------------------------------------------------------------------
# Capture / list / show (kept from original tool)
# ---------------------------------------------------------------------------

def select(rows, start, end):
    if date.fromisoformat(end) < date.fromisoformat(start):
        raise ValueError("end date is before start date")
    out = [r for r in rows if start <= r["date"] <= end]
    if len(out) < 2:
        raise ValueError("Need at least two points")
    return out


def normalize(rows):
    d0 = date.fromisoformat(rows[0]["date"])
    d1 = date.fromisoformat(rows[-1]["date"])
    days = max(1, (d1 - d0).days)
    closes = [r["close"] for r in rows]
    lo, hi = min(closes), max(closes)
    span = hi - lo
    pts = []
    for r in rows:
        x = (date.fromisoformat(r["date"]) - d0).days / days
        y = (r["close"] - lo) / span if span else 0.5
        pts.append({"x": round(x, 8), "y": round(y, 8)})
    return pts, lo, hi


def svg_path(points, w=1000, h=400):
    coords = [f"{pt['x'] * w:.2f},{ (1 - pt['y']) * h:.2f}" for pt in points]
    return "M " + " L ".join(coords)


def load_shapes(asset):
    path = shapes_path(asset)
    if not path.exists():
        return {"asset": asset, "reference_currency": QUOTE, "shapes": []}
    doc = load(path)
    doc.setdefault("shapes", [])
    return doc


def add_shape(asset, start, end, label, description=""):
    rows = select(history(asset), start, end)
    pts, lo, hi = normalize(rows)
    shape = {
        "label": label,
        "description": description,
        "source_start": rows[0]["date"],
        "source_end": rows[-1]["date"],
        "source_days": (date.fromisoformat(rows[-1]["date"]) - date.fromisoformat(rows[0]["date"])).days + 1,
        "source_points": len(rows),
        "source_low": lo,
        "source_high": hi,
        "normalization": {"x": "0..1 elapsed time", "y": "0..1 close-price range"},
        "points": pts,
        "source_data": [{"date": r["date"], "close": r["close"], "volume": r["volume"]} for r in rows],
        "svg": {"width": 1000, "height": 400, "path": svg_path(pts)},
    }
    doc = load_shapes(asset)
    replaced = False
    for i, s in enumerate(doc["shapes"]):
        if str(s.get("label", "")).casefold() == label.casefold():
            doc["shapes"][i] = shape
            replaced = True
            break
    if not replaced:
        doc["shapes"].append(shape)
    save(shapes_path(asset), doc)
    return shape, replaced


def find_shape(asset, label):
    for s in load_shapes(asset)["shapes"]:
        if str(s.get("label", "")).casefold() == label.casefold():
            return s
    raise ValueError(f'No shape labelled "{label}"')


def list_shapes(asset):
    ss = load_shapes(asset)["shapes"]
    if not ss:
        print(f"No saved shapes for {asset}/{QUOTE}.")
        return
    print(f"{asset}/{QUOTE} SHAPES\n")
    for s in ss:
        print(f"{s.get('label', '(unlabelled)'):<24} {s.get('source_start', '?')} -> {s.get('source_end', '?')}  {s.get('source_points', '?')} points")
        if s.get("description"):
            print("  " + s["description"])


def show_shape(asset, label):
    s = find_shape(asset, label)
    print(f"{asset}/{QUOTE}")
    print(f"Shape:       {s['label']}")
    print(f"Period:      {s['source_start']} -> {s['source_end']}")
    print(f"Points:      {s['source_points']}")
    print(f"Source low:  {s['source_low']}")
    print(f"Source high: {s['source_high']}")
    if s.get("description"):
        print(f"Description: {s['description']}")
    print("\nNORMALIZED POINTS\n-----------------")
    for pt in s["points"]:
        print(f"x={pt['x']:.4f}  y={pt['y']:.4f}")
    print("\nSVG PATH\n--------")
    print(s["svg"]["path"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _wallet_assets():
    """List enabled asset symbols from the wallet (uses USDT reference)."""
    config = wallet.load_config()
    data = wallet.make_data(config)
    assets = []
    for item in data["assets"]:
        if item.get("enabled", True):
            a = str(item.get("asset", "")).strip().upper()
            if a and (DATA / f"{a}_{QUOTE}.json").exists():
                assets.append(a)
    return assets


def _load_scores(path=None):
    """Load the persisted per-asset 'best-ever' score dict.

    `path` overrides the default SCORES_PATH (used by tests to isolate
    to a temp directory).
    """
    path = path or SCORES_PATH
    if not path.exists():
        return {}
    try:
        doc = load(path)
        return doc.get("assets", {})
    except Exception:
        return {}


def _save_scores(scores, path=None):
    """Persist the per-asset 'best-ever' score dict.

    `path` overrides the default SCORES_PATH (used by tests to isolate
    to a temp directory).
    """
    path = path or SCORES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    save(path, {
        "schema": "rvcrypto.shape_scores.v1",
        "type": "shape_scores",
        "note": "best_min_score = highest single-window match score an asset "
                "has achieved. Updated on each --all scan unless --no-update.",
        "assets": scores,
    })


def _spike_targets(asset, max_targets=5):
    """Cross-reference this asset's stored spike-magnet peaks.

    Returns a compact list of targets above the current price (probability
    descending), computed with the same defaults as `pricelevels --targets`.
    Empty list if the asset has no stored peaks or data.
    """
    try:
        import pricelevels
    except Exception:
        return []
    try:
        _doc, peaks = pricelevels.load_peaks(DATA, asset, QUOTE)
        rows = _doc.get("data", [])
        if not rows or not peaks:
            return []
        current_price = rows[-1]["close"]
        targets = pricelevels.compute_targets(
            peaks, rows, current_price,
            pricelevels.DEFAULT_SPIKE_PROB,
            pricelevels.DEFAULT_MIN_GAIN,
            pricelevels.DEFAULT_MAX_GAIN,
        )
        return [
            {k: t[k] for k in ("peak_date", "peak_price", "gain_pct",
                               "probability_pct")}
            for t in targets[:max_targets]
        ]
    except Exception:
        return []


def _merge_best_score(scores, asset, run_best_score, has_match, update):
    """Apply the 'raise-only, monotonic-up' update rule for one asset.

    Returns the new (scores, best_min_score, changed) tuple.

    - `scores` is the persisted per-asset best-ever dict (mutated in place).
    - `run_best_score` is this run's strongest score (0 if no match).
    - `has_match` is False when the run produced no match for the asset.
    - When `update` is False (i.e. --no-update) the stored value is left
      untouched but still reported.
    - When `update` is True the stored value is only ever raised, never
      lowered (a restricted --days scan cannot degrade the best-ever).
    """
    best_min_score = float(scores.get(asset, 0.0))
    changed = False
    if update and has_match and run_best_score > best_min_score:
        scores[asset] = run_best_score
        best_min_score = run_best_score
        changed = True
    return scores, best_min_score, changed


def _scan_all(window, min_score, top, spike_weight, time_strict, days,
              update=True, with_targets=False):
    """Scan every enabled wallet asset and return per-asset results.

    Returns a list of dicts:
        {asset, windows, best: {...}, best_min_score: float,
         targets: [...], matches:[...]}
    where `best` is the strongest match this run, `best_min_score` is the
    asset's stored best-ever score (may be from a previous run), `targets`
    (only when with_targets) lists the spike-magnet levels above current
    price drawn from the stored peaks, and matches contains all windows at
    or above min_score (best first).

    When `update` is True the stored best-ever score is raised to this
    run's strongest score (only ever up, never down). When `update` is
    False the stored value is left untouched but still reported.
    """
    scores = _load_scores()
    changed = False
    results = []
    for a in _wallet_assets():
        matches = scan_asset(a, window=window, max_days=days,
                             spike_weight=spike_weight, time_strict=time_strict)
        run_best = matches[0] if matches else None
        run_best_score = run_best["score"] if run_best else 0.0

        # always report the stored (best-ever) value, regardless of update;
        # monotonic up: only raise when this run finds something better.
        scores, best_min_score, changed_asset = _merge_best_score(
            scores, a, run_best_score, run_best is not None, update)
        if changed_asset:
            changed = True

        over = [x for x in matches if x["score"] >= min_score]
        result = {
            "asset": a,
            "windows": len(matches),
            "best_min_score": best_min_score,
            "best": ({k: run_best[k] for k in ("date", "end_date", "score", "rmse")}
                     if run_best else None),
            "matches": over[:top] if top else over,
        }
        if with_targets:
            result["targets"] = _spike_targets(a)
        results.append(result)

    if changed:
        _save_scores(scores)
    return results


def _print_all(results):
    print("SHAPE SCAN: ALL WALLET ASSETS  ('four-beat phrase' template)")
    print("=" * 70)
    if not results:
        print("  No scan results.")
        print()
        return
    print(f"  {'ASSET':<7} {'WINDOWS':>8} {'BEST':>9}  BEST PHRASE (start -> end)")
    print("  " + "-" * 62)
    for r in results:
        if r["best"]:
            b = r["best"]
            best_s = f"{b['score']:.0f} (best-ever {r['best_min_score']:.0f})  {b['date']} -> {b['end_date']}"
        else:
            best_s = f"   no match (best-ever {r['best_min_score']:.0f})"
        print(f"  {r['asset']:<7} {r['windows']:>8}  {best_s}")
    print()
    print("  Strong matches (at or above --min-score) per asset:")
    for r in results:
        if not r["matches"]:
            continue
        print(f"  {r['asset']}:")
        for m in r["matches"]:
            print(f"      {m['score']:>5.1f}  {m['date']} -> {m['end_date']}")
    print()
    if results and "targets" in results[0]:
        print("  Spike-magnet levels above current price (from stored peaks):")
        for r in results:
            if not r.get("targets"):
                continue
            print(f"  {r['asset']}:")
            for t in r["targets"]:
                print(f"      {t['peak_price']:<12} gain {t['gain_pct']:>5.1f}%  "
                      f"reach {t['probability_pct']:>4.1f}%  ({t['peak_date']})")
        print()
    print()


def main():
    ap = argparse.ArgumentParser(
        description="Detect the four-beat trading phrase shape in a crypto's price history.",
    )
    ap.add_argument("asset", nargs="?", help="Asset symbol, e.g. MMT.")
    ap.add_argument("start_date", nargs="?")
    ap.add_argument("end_date", nargs="?")
    ap.add_argument("--label")
    ap.add_argument("--description", default="")

    # Capture / list / show (keep existing)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--show", metavar="LABEL")

    # Scan (new detection)
    ap.add_argument("--scan", action="store_true",
                    help="Scan history for the phrase shape and report best matches.")
    ap.add_argument("--all", action="store_true",
                    help="Scan every enabled wallet asset over its full history and "
                         "print each asset's best (or strong) matches.")
    ap.add_argument("--days", type=int, default=None,
                    help="Only scan the most recent N days of history.")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                    help=f"Bars per window (phrase length). Default {DEFAULT_WINDOW}.")
    ap.add_argument("--top", type=int, default=8,
                    help="How many best matches to print. Default 8.")
    ap.add_argument("--min-score", type=float, default=0.0,
                    help="With --all, only report matches at or above this score.")
    ap.add_argument("--no-update", action="store_true",
                    help="Do not overwrite the stored per-asset 'best-ever' score "
                         "during this --all scan.")
    ap.add_argument("--with-targets", action="store_true",
                    help="With --all, cross-reference stored spike-magnet peaks and "
                         "report the levels above current price for each asset.")
    ap.add_argument("--spike-weight", type=float, default=1.0,
                    help="Weight the double-spike section of the match. >1 emphasises it.")
    ap.add_argument("--time-strict", type=float, default=1.0,
                    help="Strictness of beat timing. >1 punishes timing drift.")
    ap.add_argument("--template", action="store_true",
                    help="Print the current template anchors.")
    ap.add_argument("--json", action="store_true",
                    help="Emit scan output as JSON.")

    a = ap.parse_args()

    try:
        if a.template:
            if a.json:
                print(json.dumps({"schema": "rvcrypto.shape_TEMPLATE.v1",
                                  "anchors": TEMPLATE_ANCHORS}, indent=2))
            else:
                _print_template()
            return

        if a.all:
            results = _scan_all(
                window=a.window,
                min_score=a.min_score,
                top=a.top,
                spike_weight=a.spike_weight,
                time_strict=a.time_strict,
                days=a.days,
                update=not a.no_update,
                with_targets=a.with_targets,
            )
            if a.json:
                print(json.dumps({
                    "schema": "rvcrypto.shape_all.v1",
                    "template": "four-beat phrase",
                    "window": a.window,
                    "min_score": a.min_score,
                    "reference_currency": QUOTE,
                    "include_targets": a.with_targets,
                    "assets": results,
                }, indent=2))
            else:
                _print_all(results)
            return

        asset = (a.asset or "").upper()
        if not asset:
            ap.error("an asset is required (or use --all)")

        if a.list:
            return list_shapes(asset)
        if a.show:
            return show_shape(asset, a.show)
        if a.scan:
            matches = scan_asset(
                asset, window=a.window, max_days=a.days,
                spike_weight=a.spike_weight, time_strict=a.time_strict,
            )
            if a.json:
                print(json.dumps({
                    "schema": "rvcrypto.shape_scan.v1",
                    "asset": asset,
                    "reference_currency": QUOTE,
                    "template": "four-beat phrase",
                    "window": a.window,
                    "matches": matches[:a.top],
                }, indent=2))
            else:
                _print_scan(asset, matches, a.top)
            return

        # capture mode
        if not (a.start_date and a.end_date and a.label):
            ap.error("capture mode requires start_date, end_date and --label")
        s, replaced = add_shape(asset, a.start_date, a.end_date, a.label, a.description)
        print(f"{'Updated' if replaced else 'Added'} shape: {s['label']}")
        print(f"Asset:       {asset}/{QUOTE}")
        print(f"Period:      {s['source_start']} -> {s['source_end']}")
        print(f"Points:      {s['source_points']}")
        print(f"Stored in:   {shapes_path(asset)}")
        print("\nSVG path generated for later manual smoothing/editing.")

    except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
