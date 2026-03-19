#!/usr/bin/env python3
"""
addaistorytext.py

Import simple AI terminal transcripts (>>> prompt style)
into the heichalot CMS story format.

Usage:

    python tools/addaistorytext.py transcript.txt
    python tools/addaistorytext.py transcript.txt --story /tmp/story.md
    python tools/addaistorytext.py --debate transcript.txt
    python tools/addaistorytext.py

If no file is given, text is read from stdin (paste mode).
"""

import sys
import os
import argparse
import configparser
from datetime import datetime


def read_config():
    config = configparser.ConfigParser()

    possible_paths = [
        "./heichalotcms/config.ini",
        "./config.ini",
    ]

    for path in possible_paths:
        if os.path.exists(path):
            config.read(path)
            break

    story_filename = "story.md"
    default_tags = []

    if "cms" in config and "story_filename" in config["cms"]:
        story_filename = config["cms"]["story_filename"]

    if "tags" in config and "default_story_tags" in config["tags"]:
        default_tags = [
            t.strip()
            for t in config["tags"]["default_story_tags"].split(",")
            if t.strip()
        ]

    return story_filename, default_tags


def read_input(path):
    if path:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    print("Paste transcript (Ctrl-D to finish):")
    return sys.stdin.read()


def parse_transcript(text):
    lines = text.splitlines()

    blocks = []
    narrator = None
    ai_lines = []

    for line in lines:
        stripped = line.strip()

        if stripped.startswith(">>>"):
            if narrator is not None:
                blocks.append((narrator.strip(), "\n".join(ai_lines).strip()))
                ai_lines = []

            narrator = stripped[3:].strip()
        else:
            if narrator is not None:
                ai_lines.append(line)

    if narrator is not None:
        blocks.append((narrator.strip(), "\n".join(ai_lines).strip()))

    return blocks


def render_blocks(blocks):
    out = []

    for narrator, ai in blocks:
        out.append('"""Narrator')
        out.append(narrator)
        out.append("")
        out.append('"""Ai')
        out.append(ai)
        out.append("")

    return "\n".join(out)


def ensure_tags(path, tags):
    if not tags:
        return

    path = str(path)

    if not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            f.write('"""Tags\n')
            for tag in tags:
                f.write(f"{tag}\n")
            f.write("\n")
        return

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if '"""Tags' in content:
        return

    with open(path, "a", encoding="utf-8") as f:
        f.write('\n"""Tags\n')
        for tag in tags:
            f.write(f"{tag}\n")
        f.write("\n")


def append_story(path, text):
    path = str(path)

    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(path, "a", encoding="utf-8") as f:
        f.write("\n")
        f.write(text)
        f.write("\n")


def write_debate(text):
    os.makedirs("debate", exist_ok=True)

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"debate/{ts}.md"

    with open(filename, "w", encoding="utf-8") as f:
        f.write("---\n")
        f.write("origin: addaistorytext\n")
        f.write(f"timestamp: {datetime.now().isoformat()}\n")
        f.write("---\n\n")
        f.write(text)

    print(f"Wrote debate file: {filename}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file", nargs="?", help="transcript file")
    parser.add_argument("--debate", action="store_true", help="write a new debate file")
    parser.add_argument(
        "--story",
        help="story file path (default from config.ini or story.md)",
    )

    args = parser.parse_args()

    story_filename, tags = read_config()
    story_path = args.story if args.story else story_filename

    text = read_input(args.file)
    blocks = parse_transcript(text)

    if not blocks:
        print("No >>> prompts found.")
        sys.exit(1)

    rendered = render_blocks(blocks)

    if args.debate:
        write_debate(rendered)
        return

    ensure_tags(story_path, tags)
    append_story(story_path, rendered)

    print(f"Appended {len(blocks)} block(s) to {story_path}")


if __name__ == "__main__":
    main()