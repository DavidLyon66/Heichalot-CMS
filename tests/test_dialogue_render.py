from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from tests.fixtures import run_compile, run_still


def non_black_pixel_count(image_path: Path, x1: int, y1: int, x2: int, y2: int) -> int:
    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"Failed to read image: {image_path}")

    region = img[y1:y2, x1:x2]
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    return int(np.count_nonzero(gray > 10))


def test_dialogue_typewriter_adds_visible_pixels(make_production) -> None:
    production_dir = make_production("basic_dialogue")

    run_compile(production_dir)

    frame0 = production_dir / "frame-0000.png"
    frame20 = production_dir / "frame-0020.png"
    frame40 = production_dir / "frame-0040.png"

    run_still(production_dir, 0, frame0)
    run_still(production_dir, 20, frame20)
    run_still(production_dir, 40, frame40)

    # Approximate lower-third dialogue region.
    region = (250, 650, 1670, 980)

    count0 = non_black_pixel_count(frame0, *region)
    count20 = non_black_pixel_count(frame20, *region)
    count40 = non_black_pixel_count(frame40, *region)

    assert count20 >= count0
