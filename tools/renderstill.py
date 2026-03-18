#!/usr/bin/env python3
"""
renderstill.py

Render a single PNG frame from a production directory using Remotion.

Usage:
    python tools/renderstill.py <production-dir>
    python tools/renderstill.py <production-dir> --frame 24
    python tools/renderstill.py <production-dir> --out frame.png
    python tools/renderstill.py <production-dir> --compile

Notes:
- Uses the existing rendervideo.py compiler first by default.
- Expects Remotion project at: <project_root>/videorender
- Expects video.render.json in the production directory.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Render a single still frame from a production")
    parser.add_argument("production_dir", nargs="?", default=".", help="Production directory (default: .)")
    parser.add_argument("--frame", type=int, default=0, help="Frame number to render")
    parser.add_argument("--out", help="Output PNG path")
    parser.add_argument(
        "--compile",
        action="store_true",
        help="Run rendervideo.py first to refresh video.render.json",
    )
    parser.add_argument(
        "--composition",
        default="VideoFromJSON",
        help="Remotion composition ID (default: VideoFromJSON)",
    )
    args = parser.parse_args(argv[1:])

    production_dir = Path(args.production_dir).expanduser().resolve()
    if not production_dir.exists() or not production_dir.is_dir():
        eprint(f"Error: production directory does not exist: {production_dir}")
        return 1

    tools_dir = Path(__file__).resolve().parent
    project_root = tools_dir.parent
    videorender_root = project_root / "videorender"
    render_json = production_dir / "video.render.json"

    if args.compile:
        compile_cmd = [
            sys.executable,
            str(project_root / "tools" / "rendervideo.py"),
            str(production_dir),
        ]
        print("Compiling:")
        print("  " + " ".join(compile_cmd))
        subprocess.run(compile_cmd, check=True)

    if not render_json.exists():
        eprint(f"Error: missing render JSON: {render_json}")
        return 1

    if args.out:
        output_png = Path(args.out).expanduser().resolve()
    else:
        output_png = production_dir / f"frame-{args.frame:04d}.png"

    cmd = [
        "npx",
        "remotion",
        "still",
        "src/index.ts",
        args.composition,
        str(output_png),
        f"--frame={args.frame}",
        f"--props={render_json}",
    ]

    print("Rendering still:")
    print("  " + " ".join(cmd))
    subprocess.run(cmd, cwd=videorender_root, check=True)

    print(f"Wrote: {output_png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))