#!/usr/bin/env python3
"""
dailyscan.py

A platform-independent daily scanner for the spike/shape research tools.
It runs the four-beat shape scan (with spike-magnet cross-reference) and the
daily report as subprocesses, capturing dated output under data/scan_out/.

Usage
-----
Run once:

    python3 dailyscan.py
    python3 dailyscan.py --no-update --json --conservative

Run forever in the background, waking every N hours:

    python3 dailyscan.py --daemon --interval-hours 24
    nohup python3 dailyscan.py --daemon > /tmp/dailyscan_nohup.log 2>&1 &

One-shot / daemon are equivalent single runs of:

    shapedetect.py --all --min-score 0 --top 2 --with-targets [--no-update]
    shapedetect.py --all --min-score 0 --top 1 --with-targets [--no-update] --json
    dailyreport.py [--conservative]

Scheduling without a shell script: on most systems a cron or systemd timer can
just call `python3 path/to/dailyscan.py` directly. Example cron entry
(once a day at 07:00):

    0 7 * * * cd /path/to/rvcrypto && python3 dailyscan.py >> data/scan_out/dailyscan.log 2>&1

DISCLAIMER: Not financial advice. Experimental research tool only.
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEFAULT_OUTDIR = BASE / "data" / "scan_out"
DAEMON_LOG = "dailyscan.log"


def _stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _run(argv, outfile=None, quiet=False):
    """Run a child CLI program, optionally tee-ing its output to <outfile>."""
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, cwd=str(BASE))
    with proc.stdout:
        for line in proc.stdout:
            print(line, end="", flush=True)
            if outfile is not None:
                outfile.write(line)
                outfile.flush()
    rc = proc.wait()
    if rc != 0 and not quiet:
        print(f"[dailyscan] warning: {argv[0]} exited with code {rc}", flush=True)
    return rc


def scan_once(outdir, no_update, conservative, json_out):
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()

    base = [sys.executable, str(BASE / "shapedetect.py"), "--all",
            "--min-score", "0", "--top", "2", "--with-targets"]
    if no_update:
        base.append("--no-update")

    print(f"=== daily scan {stamp} ===", flush=True)
    print("\n--- shape scan (updates best-ever score) ---", flush=True)
    with open(outdir / f"{stamp}_shape.txt", "w") as f:
        _run(base, outfile=f)

    if json_out:
        with open(outdir / f"{stamp}_shape.json", "w") as f:
            _run(base + ["--top", "1", "--json"], outfile=f)
        print(f"wrote: {outdir / (stamp + '_shape.json')}", flush=True)

    print("\n--- daily report ---", flush=True)
    report = [sys.executable, str(BASE / "dailyreport.py")]
    if conservative:
        report.append("--conservative")
    with open(outdir / f"{stamp}_report.txt", "w") as f:
        _run(report, outfile=f)

    print(f"\nwrote:\n  {outdir / (stamp + '_shape.txt')}\n"
          f"  {outdir / (stamp + '_report.txt')}", flush=True)
    return stamp


def _scan_and_append(outdir, no_update, conservative, json_out):
    """Run one scan, appending a dated banner + the report to the daemon log."""
    log = outdir / DAEMON_LOG
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    with open(log, "a") as logf:
        logf.write(f"\n===== daily scan {stamp} =====\n")
        report = [sys.executable, str(BASE / "dailyreport.py")]
        if conservative:
            report.append("--conservative")
        _run(report, outfile=logf, quiet=True)
    return stamp


def main():
    ap = argparse.ArgumentParser(
        description="Run the daily shape + spike-magnet scan and report.",
    )
    ap.add_argument("--daemon", action="store_true",
                    help="Run forever in the background, re-scanning every "
                         "--interval-hours.")
    ap.add_argument("--interval-hours", type=float, default=24.0,
                    help="Daemon wake interval in hours (default 24).")
    ap.add_argument("--no-update", action="store_true",
                    help="Pass --no-update to shapedetect: report stored best-ever "
                         "scores but never write them.")
    ap.add_argument("--conservative", action="store_true",
                    help="Run the daily report in conservative mode.")
    ap.add_argument("--json", action="store_true",
                    help="Also write the dated shape-scan JSON output.")
    ap.add_argument("--outdir", default=None,
                    help="Output directory (default data/scan_out).")
    a = ap.parse_args()

    outdir = Path(a.outdir).expanduser() if a.outdir else DEFAULT_OUTDIR

    if a.daemon:
        print(f"[dailyscan] daemon mode: scanning now, then every "
              f"{a.interval_hours:g}h (log -> {outdir / DAEMON_LOG})", flush=True)
        while True:
            _scan_and_append(outdir, a.no_update, a.conservative, a.json)
            next_run = time.time() + a.interval_hours * 3600
            wait_m = int((next_run - time.time()) / 60)
            print(f"[dailyscan] next scan in ~{wait_m} min", flush=True)
            time.sleep(max(0.0, next_run - time.time()))
    else:
        scan_once(outdir, a.no_update, a.conservative, a.json)


if __name__ == "__main__":
    main()
