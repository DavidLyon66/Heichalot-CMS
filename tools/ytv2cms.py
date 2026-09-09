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
import configparser
import re
import shutil
import sys
import textwrap
from pathlib import Path
from typing import Sequence

from youtube_transcript_api import YouTubeTranscriptApi

try:
    import yt_dlp
except ImportError:
    yt_dlp = None


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


def fetch_video_title(url_or_id: str, supplied: str | None = None) -> str:
    """Return an explicit title override or fetch the YouTube title with yt-dlp."""

    if supplied and supplied.strip():
        return supplied.strip()

    if yt_dlp is None:
        raise RuntimeError(
            "yt-dlp is not installed for this Python. Install it with: "
            "python3 -m pip install yt-dlp"
        )

    target = str(url_or_id).strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", target):
        target = f"https://www.youtube.com/watch?v={target}"

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(target, download=False)

    title = str((info or {}).get("title") or "").strip()
    if not title:
        raise RuntimeError("yt-dlp did not return a YouTube title.")

    return title


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


def prompt_stream() -> str:
    """Prompt for the CMS stream YAML field."""

    while True:
        stream = input("Stream: ").strip()
        if stream:
            return stream

        print("Stream cannot be empty.")


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


def get_screenshot_dir(config_path: str | None = None) -> Path:
    """
    Return the configured screenshot directory, falling back to
    ~/Pictures/Screenshots.

    Recognised config keys (in any section):
        screenshot_dir
        screenshots_dir
        screenshot_directory
        screenshots_directory
    """

    default_dir = Path("~/Pictures/Screenshots").expanduser()

    candidates: list[Path] = []
    if config_path:
        candidates.append(Path(config_path).expanduser())
    else:
        candidates.append(REPO_ROOT / "config.ini")

    config_file = next((path for path in candidates if path.is_file()), None)
    if config_file is None:
        return default_dir

    parser = configparser.ConfigParser()
    try:
        parser.read(config_file, encoding="utf-8")
    except Exception:
        return default_dir

    keys = (
        "screenshot_dir",
        "screenshots_dir",
        "screenshot_directory",
        "screenshots_directory",
    )

    for key in keys:
        value = parser.defaults().get(key)
        if value and value.strip():
            return Path(value.strip()).expanduser()

    for section in parser.sections():
        for key in keys:
            value = parser[section].get(key)
            if value and value.strip():
                return Path(value.strip()).expanduser()

    return default_dir


def newest_file(directory: Path) -> Path:
    """Return the most recently modified regular file in directory."""

    if not directory.is_dir():
        raise FileNotFoundError(f"Screenshot directory not found: {directory}")

    files = [path for path in directory.iterdir() if path.is_file()]
    if not files:
        raise FileNotFoundError(f"No screenshot files found in: {directory}")

    return max(files, key=lambda path: path.stat().st_mtime)


def resolve_image_source(args: argparse.Namespace) -> tuple[Path | None, bool]:
    """
    Resolve an optional image source.

    Returns:
        (source_path, move_source)

    --image copies the explicitly supplied absolute path.
    --last-screenshot moves the newest file from the screenshot directory.
    """

    if args.image:
        source = Path(args.image).expanduser()
        if not source.is_absolute():
            raise ValueError("--image requires the full (absolute) path to the image file.")
        if not source.is_file():
            raise FileNotFoundError(f"Image file not found: {source}")
        return source, False

    if args.last_screenshot:
        screenshot_dir = get_screenshot_dir(args.config)
        source = newest_file(screenshot_dir)
        return source, True

    return None, False


def unique_destination(directory: Path, filename: str) -> Path:
    """Choose a destination without overwriting an existing asset."""

    destination = directory / filename
    if not destination.exists():
        return destination

    source_name = Path(filename)
    stem = source_name.stem
    suffix = source_name.suffix
    counter = 2

    while True:
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def add_entry_image(entry_dir: Path, source: Path, move_source: bool) -> Path:
    """Copy or move an image into the entry root for use as the thumbnail."""

    entry_dir = Path(entry_dir)
    destination = unique_destination(entry_dir, source.name)

    if move_source:
        shutil.move(str(source), str(destination))
    else:
        shutil.copy2(source, destination)

    return destination


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

    image_group = parser.add_mutually_exclusive_group()
    image_group.add_argument(
        "--image",
        help=(
            "Full path to an image to copy into the new entry directory as its thumbnail. "
            "The original file is left in place."
        ),
    )
    image_group.add_argument(
        "--last-screenshot",
        action="store_true",
        help=(
            "Move the most recently modified file from the configured screenshot "
            "directory into the new entry directory as its thumbnail."
        ),
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    try:
        image_source, move_image = resolve_image_source(args)
        if image_source is not None:
            action = "move" if move_image else "copy"
            print(f"[INFO] Image ({action}): {image_source}")

        if sys.version_info < (3, 10):
            raise RuntimeError(
                "ytv2cms.py requires Python 3.10 or later. "
                "Python 3.9 and earlier are no longer supported."
            )

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

        title = fetch_video_title(args.input, args.title)
        tags = prompt_tags(args.tags)
        timeframe = prompt_timeframe(args.timeframe)
        stream = prompt_stream()

        print()
        print(f"[INFO] Title: {title}")
        print(f"[INFO] Tags: {tags if tags else '(none)'}")
        print(f"[INFO] Timeframe: {timeframe}")
        print(f"[INFO] Stream: {stream}")
        print("[INFO] Creating CMS entry...")

        yaml_fields = {
            "source": "youtube",
            "source_video_id": video_id,
            "source_url": args.input,
            "timeframe": [timeframe],
            "stream": stream,
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

        image_path = None
        if image_source is not None:
            image_path = add_entry_image(Path(entry_dir), image_source, move_image)

        print()
        print(f"[OK] Created: {entry_id}")
        print(f"[OK] Entry:   {entry_dir}")
        print(f"[OK] Story:   {story_path}")
        if image_path is not None:
            print(f"[OK] Image:   {image_path}")
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
