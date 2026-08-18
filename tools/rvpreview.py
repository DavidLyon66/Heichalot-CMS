#!/usr/bin/env python3

"""
rvpreview.py

Generate quick visual "impressions" from a remote-viewing prompt.

This is an experimental preview tool. The generated images are NOT
remote-viewing results; they are only visualisations derived from the
user's original question.
"""

from __future__ import annotations

import argparse
import os
import random
import re
import urllib.parse
from datetime import datetime
from pathlib import Path

import requests


FILLER_PHRASES = (
    "could you please",
    "can you please",
    "would you please",
    "please",
    "let's remote-view",
    "lets remote-view",
    "remote-viewing",
    "remote viewing",
    "remote-view",
    "remote view",
    "tell me",
    "can you tell me",
    "what do you see",
    "what can you see",
)


def reduce_prompt(prompt: str) -> str:
    """
    Remove obvious conversational/request wording while retaining
    the subject and descriptive information.
    """

    text = " ".join(str(prompt).split())

    for phrase in FILLER_PHRASES:
        text = re.sub(
            re.escape(phrase),
            " ",
            text,
            flags=re.IGNORECASE,
        )

    text = re.sub(r"\s+", " ", text)
    text = text.strip(" ,.?")

    return text


def make_preview_prompt(prompt: str) -> str:
    """
    Convert a remote-viewing request into a simple image-generation prompt.
    """

    subject = reduce_prompt(prompt)

    return (
        "atmospheric visual impression, "
        "cinematic concept image, "
        "dreamlike uncertain details, "
        "natural lighting, "
        "no text, no labels, "
        f"{subject}"
    )


def generate_image(
    prompt: str,
    save_path: Path,
    width: int = 768,
    height: int = 512,
    enhance: bool = True,
    api: str = "pollinations",
) -> Path | None:
    """Generate one preview image using the selected provider."""

    api = str(api or "pollinations").strip().casefold()
    if api != "pollinations":
        raise ValueError(f"Unsupported rvpreview api: {api!r}")

    params = {
        "safe": True,
        "seed": random.randint(1, 999999999),
        "width": width,
        "height": height,
        "nologo": True,
        "private": True,
        "model": "flux",
        "enhance": enhance,
        "referrer": "rvpreview.py",
    }

    encoded_prompt = urllib.parse.quote(prompt)
    query_params = urllib.parse.urlencode(params)
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?{query_params}"

    save_path = Path(save_path)
    save_path.mkdir(parents=True, exist_ok=True)

    try:
        response = requests.get(
            url=url,
            timeout=60,
        )

        if response.status_code != 200:
            print(
                f"Failed to generate image. Status code: "
                f"{response.status_code}."
            )
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        image_save_name = f"rvpreview_{timestamp}.png"
        image_save_path = save_path / image_save_name

        with image_save_path.open("wb") as f:
            f.write(response.content)

        return image_save_path

    except requests.RequestException as exc:
        print(f"Request failed: {exc}.")
        return None


def generate_preview_images(
    prompt: str,
    output_dir: Path,
    count: int = 4,
    api: str = "pollinations",
) -> list[Path]:
    """
    Generate preview images using Pollinations.
    """

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    preview_prompt = make_preview_prompt(prompt)

    print()
    print("Remote-viewing prompt:")
    print(prompt)

    print()
    print("Preview prompt:")
    print(preview_prompt)

    print()
    print(f"Generating {count} preview image(s)...")

    saved_paths: list[Path] = []

    for number in range(1, count + 1):
        print(
            f"  generating {number}/{count}...",
            flush=True,
        )

        output_path = generate_image(
            preview_prompt,
            output_dir,
            api=api,
        )

        if output_path is not None:
            saved_paths.append(output_path)
            print(f"  saved: {output_path}")

    return saved_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate quick AI preview images from a "
            "remote-viewing request."
        )
    )

    parser.add_argument(
        "prompt",
        help="Remote-viewing question or target.",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("."),
        help=(
            "Directory for generated preview images. "
            "Default: current directory."
        ),
    )

    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=4,
        help="Number of preview images. Default: 4.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.count < 1:
        raise SystemExit("--count must be at least 1")

    try:
        images = generate_preview_images(
            prompt=args.prompt,
            output_dir=args.output,
            count=args.count,
        )

    except KeyboardInterrupt:
        print()
        print("rvpreview: cancelled")
        return 130

    except Exception as exc:
        print()
        print(f"rvpreview: generation failed: {exc}")
        return 1

    print()
    print(f"Generated {len(images)} preview image(s).")

    for image in images:
        print(image)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
