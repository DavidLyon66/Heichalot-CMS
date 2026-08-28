#!/usr/bin/env python3
"""
ytv2cms.py

Download a YouTube transcript and create a normal Heichalot-CMS entry
through createentry.py.

Typical use:

    python3 tools/ytv2cms.py https://www.youtube.com/watch?v=ywvOgLNGw6s

The normal interactive flow is:

    1. Download transcript.
    2. Ask for the story title.
    3. Ask for tags, e.g.:
           #remote-viewing, #history, #judaism
    4. Ask for timeframe:
           1 = past
           2 = present (default)
           3 = future
    5. Call createentry.create_entry() to allocate and create the CMS entry.
    6. Replace the createentry placeholder with the imported transcript.

The generated entry uses the standard CMS template and config rather than
constructing its own partial YAML header.
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from pathlib import Path
from typing import Sequence

from youtube_transcript_api import YouTubeTranscriptApi


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"

for path in (REPO_ROOT, TOOLS_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from createentry import create_entry


TIMEFRAME_MENU = {
    "1": "past",
    "2": "present",
    "3": "future",
}


def extract_video_id(url_or_id: str) -> str:
    """Accept a normal YouTube URL, youtu.be URL, Shorts URL, or bare ID."""

    value = str(url_or_id).strip()

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value

    patterns = [
        r"[?&]v=([A-Za-z0-9_-]{11})",
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"youtube\.com/shorts/([A-Za-z0-9_-]{11})",
        r"youtube\.com/embed/([A-Za-z0-9_-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group(1)

    raise ValueError("Could not extract YouTube video ID from input.")


def fetch_transcript(video_id: str) -> list[str]:
    """Download the transcript and return plain text lines."""

    api = YouTubeTranscriptApi()
    transcript = api.fetch(video_id)

    return [
        str(entry.text)
        for entry in transcript
        if getattr(entry, "text", None)
    ]


def clean_transcript_lines(lines: Sequence[str]) -> list[str]:
    out: list[str] = []

    for raw in lines:
        if not raw:
            continue

        line = str(raw).replace("\x00", "")
        line = line.replace("\r", " ").replace("\n", " ")
        line = re.sub(r"\s+", " ", line).strip()

        if line:
            out.append(line)

    return out


def split_emotion_cues(lines: Sequence[str]) -> list[str]:
    """
    Split bracketed transcript cues such as [Music] or [laughter] into
    standalone items so paragraph formatting remains readable.
    """

    out: list[str] = []

    for line in lines:
        parts = re.split(r"(\[.*?\])", line)

        for part in parts:
            part = part.strip()
            if part:
                out.append(part)

    return out


def merge_lines_into_paragraphs(
    lines: Sequence[str],
    max_chars: int = 700,
) -> list[str]:
    """
    Merge short caption fragments into readable paragraphs.

    YouTube caption timing often produces very short fragments. This keeps
    the imported story readable without trying to perform speaker
    diarization or semantic rewriting.
    """

    paragraphs: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            paragraphs.append(current.strip())
            current = ""

    for line in lines:
        if line.startswith("[") and line.endswith("]"):
            flush()
            paragraphs.append(line)
            continue

        candidate = f"{current} {line}".strip() if current else line

        if len(candidate) > max_chars:
            flush()
            current = line
        else:
            current = candidate

        if current.endswith((".", "!", "?", '"', ".'", "!'", "?'")):
            flush()

    flush()
    return paragraphs


def wrap_paragraphs(
    paragraphs: Sequence[str],
    width: int = 78,
) -> list[str]:
    wrapped: list[str] = []

    for paragraph in paragraphs:
        if paragraph.startswith("[") and paragraph.endswith("]"):
            wrapped.append(paragraph)
            continue

        wrapped.append(
            "\n".join(
                textwrap.wrap(
                    paragraph,
                    width=width,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
            )
        )

    return wrapped


def parse_tags(text: str) -> list[str]:
    """
    Accept input such as:

        #history, #judaism, #remote-viewing

    Leading # characters are removed before storing the CMS YAML tags.
    Empty values are ignored and duplicates are removed while preserving
    input order.
    """

    raw = str(text or "").strip()
    if not raw:
        return []

    # Commas are the preferred separator. If there are no commas, permit
    # whitespace-separated #tags as a convenience.
    if "," in raw:
        parts = raw.split(",")
    else:
        hashed = re.findall(r"#([^#]+?)(?=\s+#|$)", raw)
        parts = hashed if hashed else [raw]

    tags: list[str] = []
    seen: set[str] = set()

    for part in parts:
        tag = str(part).strip()
        if tag.startswith("#"):
            tag = tag[1:].strip()

        if not tag:
            continue

        key = tag.casefold()
        if key in seen:
            continue

        seen.add(key)
        tags.append(tag)

    return tags


def prompt_title(video_id: str, supplied: str | None = None) -> str:
    if supplied and supplied.strip():
        return supplied.strip()

    while True:
        title = input("Title: ").strip()
        if title:
            return title

        fallback = f"YouTube Import ({video_id})"
        answer = input(f"Use fallback title '{fallback}'? [y/N]: ").strip().lower()
        if answer in {"y", "yes"}:
            return fallback


def prompt_tags(supplied: str | None = None) -> list[str]:
    if supplied is None:
        supplied = input("Enter Tags (with #<tag>, ..): ")

    return parse_tags(supplied)


def prompt_timeframe(supplied: str | None = None) -> str:
    """
    1 = past
    2 = present (default)
    3 = future
    """

    value = str(supplied or "").strip()

    if not value:
        value = input(
            "Timeframe [1=past, 2=present, 3=future] (2): "
        ).strip()

    if not value:
        value = "2"

    # Also accept explicit words for command-line convenience.
    lowered = value.casefold()
    if lowered in {"past", "present", "future"}:
        return lowered

    if value in TIMEFRAME_MENU:
        return TIMEFRAME_MENU[value]

    print("Unknown timeframe choice; using present.")
    return "present"


def transcript_body(paragraphs: Sequence[str]) -> str:
    """Create the imported transcript body used beneath the standard CMS header."""

    body = "\n\n".join(paragraphs).strip()

    return (
        '"""Narrator\n'
        "[Imported from YouTube transcript]\n\n"
        f"{body}\n"
        '"""'
    )


def remove_createentry_placeholder(story_path: Path) -> None:
    """
    create_entry() intentionally inserts 'Write the story here.' for normal
    hand-created entries. For a transcript import we already supplied the
    story body, so remove only that exact standalone placeholder line.
    """

    text = story_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    removed = False
    out: list[str] = []

    for line in lines:
        if not removed and line.strip() == "Write the story here.":
            removed = True
            continue
        out.append(line)

    # Collapse excessive blank lines left by removing the placeholder.
    cleaned = "\n".join(out)
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)

    story_path.write_text(
        cleaned.rstrip() + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download a YouTube transcript and create a CMS entry."
    )

    parser.add_argument(
        "input",
        help="YouTube URL or 11-character video ID",
    )
    parser.add_argument(
        "--title",
        help="Story title. If omitted, prompt after transcript download.",
    )
    parser.add_argument(
        "--tags",
        help='Tags such as "#history, #judaism, #remote-viewing".',
    )
    parser.add_argument(
        "--timeframe",
        choices=["1", "2", "3", "past", "present", "future"],
        help="1=past, 2=present, 3=future. Default interactive choice is present.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional config.ini override passed to createentry.py.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=78,
        help="Transcript text wrapping width (default: 78).",
    )
    parser.add_argument(
        "--max-paragraph",
        type=int,
        default=700,
        help="Approximate maximum paragraph length before splitting (default: 700).",
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        video_id = extract_video_id(args.input)
        print(f"[INFO] Video ID: {video_id}")

        print("[INFO] Downloading transcript...")
        raw_lines = fetch_transcript(video_id)

        if not raw_lines:
            print("[ERROR] Transcript was empty.")
            return 1

        cleaned = clean_transcript_lines(raw_lines)
        split_lines = split_emotion_cues(cleaned)
        paragraphs = merge_lines_into_paragraphs(
            split_lines,
            max_chars=args.max_paragraph,
        )
        paragraphs = wrap_paragraphs(
            paragraphs,
            width=args.width,
        )

        print(
            f"[OK] Transcript downloaded: {len(raw_lines)} caption lines "
            f"→ {len(paragraphs)} paragraphs"
        )
        print()

        title = prompt_title(video_id, args.title)
        tags = prompt_tags(args.tags)
        timeframe = prompt_timeframe(args.timeframe)

        print()
        print(f"[INFO] Title: {title}")
        print(f"[INFO] Tags: {tags if tags else '(none)'}")
        print(f"[INFO] Timeframe: {timeframe}")
        print("[INFO] Creating CMS entry...")

        yaml_fields = {
            "source": "youtube",
            "source_video_id": video_id,
            "source_url": args.input,
            "timeframe": [timeframe],
        }

        entry_id, entry_dir, story_path = create_entry(
            "yt",
            title=title,
            tags=tags,
            body=transcript_body(paragraphs),
            yaml_fields=yaml_fields,
            config_path=args.config,
        )

        remove_createentry_placeholder(story_path)

        print()
        print(f"[OK] Created: {entry_id}")
        print(f"[OK] Entry:   {entry_dir}")
        print(f"[OK] Story:   {story_path}")
        print()
        print("Next:")
        print(f"  cd {entry_dir}")

        return 0

    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130

    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
