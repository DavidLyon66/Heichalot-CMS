from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "tools"


def run_compile(production_dir: Path) -> None:
    cmd = [
        sys.executable,
        str(TOOLS_DIR / "rendervideo.py"),
        str(production_dir),
    ]
    subprocess.run(cmd, check=True)


def run_still(production_dir: Path, frame: int, out_path: Path) -> None:
    cmd = [
        sys.executable,
        str(TOOLS_DIR / "renderstill.py"),
        str(production_dir),
        "--frame",
        str(frame),
        "--out",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)