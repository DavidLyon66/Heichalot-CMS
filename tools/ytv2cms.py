#!/usr/bin/env python3

import os
import re
import argparse
import textwrap
from youtube_transcript_api import YouTubeTranscriptApi
from tools.extensions import registry


def extract_video_id(url_or_id):
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url_or_id):
        return url_or_id

    match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url_or_id)
    if match:
        return match.group(1)

    raise ValueError("Could not extract video ID from input.")

def fetch_transcript(video_id):
    api = YouTubeTranscriptApi()
    transcript = api.fetch(video_id)
    return [entry.text for entry in transcript]


def transcript_to_story_md(video_id, lines):
    title = f"YouTube Import ({video_id})"

    body = "\n\n".join(lines)

    return f"""---
kind: story
source: youtube
source_video_id: {video_id}
---

# {title}

\"\"\" NARRATOR
[Imported from YouTube transcript]

{body}
\"\"\"
"""

def write_story(out_dir, story_md):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "story.md")

    with open(path, "w", encoding="utf-8") as f:
        f.write(story_md)

    return path


def fetch_transcript(video_id):
    api = YouTubeTranscriptApi()
    transcript = api.fetch(video_id)
    return [entry.text for entry in transcript]


def clean_transcript_lines(lines):
    out = []

    for line in lines:
        if not line:
            continue

        line = line.replace("\x00", "")
        line = re.sub(r'\s*>>\s*', ' ', line)
        line = line.replace("\r", " ").replace("\n", " ")
        line = re.sub(r"\s+", " ", line).strip()

        if not line:
            continue

        out.append(line)

    return out


def merge_lines_into_paragraphs(lines, max_chars=500):
    paragraphs = []
    current = ""

    def flush():
        nonlocal current
        if current.strip():
            paragraphs.append(current.strip())
            current = ""

    for line in lines:
        # Speaker/interviewer marker starts a fresh paragraph
        if line.startswith(">>"):
            flush()
            current = line
            flush()
            continue

        # Bracket cues like [laughter], [Music] stand alone
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

        # End paragraph after sentence-ending punctuation
        if current.endswith((".", "!", "?", "\"", ".'", "!'","?'")):
            flush()

    flush()
    return paragraphs


def wrap_paragraphs(paragraphs, width=60):
    wrapped = []

    for p in paragraphs:
        if p.startswith("[") and p.endswith("]"):
            wrapped.append(p)
            continue

        wrapped.append(
            "\n".join(
                textwrap.wrap(
                    p,
                    width=width,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
            )
        )

    return wrapped


def wrap_paragraphs(paragraphs, width=60):
    wrapped = []

    for p in paragraphs:
        if p.startswith("[") and p.endswith("]"):
            wrapped.append(p)
            continue

        wrapped.append(
            "\n".join(
                textwrap.wrap(
                    p,
                    width=width,
                    break_long_words=False,
                    break_on_hyphens=False,
                )
            )
        )

    return wrapped


def split_emotion_cues(lines):
    """
    Splits lines so that bracketed cues like [laughter]
    become their own standalone lines.
    """
    out = []

    for line in lines:
        # Split while keeping the brackets
        parts = re.split(r'(\[.*?\])', line)

        for part in parts:
            part = part.strip()
            if not part:
                continue
            out.append(part)

    return out


def main():
    parser = argparse.ArgumentParser(description="Minimal YouTube → CMS importer")
    parser.add_argument("input", help="YouTube URL or video ID")
    parser.add_argument("out", help="Output directory")

    args = parser.parse_args()

    registry.ensure_loaded()

    try:

        video_id = extract_video_id(args.input)
        print(f"[INFO] Video ID: {video_id}")

        lines = fetch_transcript(video_id)
        cleaned = clean_transcript_lines(lines)
        split_lines = split_emotion_cues(cleaned)
        paragraphs = merge_lines_into_paragraphs(split_lines)
        paragraphs = wrap_paragraphs(paragraphs, width=60)


        print(f"[INFO] Transcript lines {len(lines)} converted to {len(paragraphs)} paragraphs.")

        if registry.has_capability("diarization"):
            # Use advanced extension
            diarize = registry.get_capability("diarization")
            story_md = diarize(audio_path)
        else:
            story_md = transcript_to_story_md(video_id, paragraphs)

        path = write_story(args.out, story_md)
        print(f"[OK] Written: {path}")

    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()