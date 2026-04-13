#!/usr/bin/env python3
"""
addaistorytext.py

Import simple AI terminal transcripts (>>> / ... prompt style)
into the heichalot CMS story format.

Usage:

    python tools/addaistorytext.py
    python tools/addaistorytext.py cms/entry-0000038
    python tools/addaistorytext.py cms/entry-0000038 --image ~/Screenshots/shot.png
    python tools/addaistorytext.py cms/entry-0000038 --input-file transcript.txt

Transcript input is read from stdin by default.
"""

import sys
import os
import argparse
import configparser
import shutil
from pathlib import Path
from datetime import datetime

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


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
    image_mode = "move"

    if "cms" in config and "story_filename" in config["cms"]:
        story_filename = config["cms"]["story_filename"]

    if "tags" in config and "default_story_tags" in config["tags"]:
        default_tags = [
            t.strip()
            for t in config["tags"]["default_story_tags"].split(",")
            if t.strip()
        ]

    if "addaistory" in config and "image_mode" in config["addaistory"]:
        value = config["addaistory"]["image_mode"].strip().lower()
        if value in {"move", "copy"}:
            image_mode = value

    return story_filename, default_tags, image_mode


def read_input(path):
    if path:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    print("Paste transcript (Ctrl-D to finish):")
    return sys.stdin.read()


def append_continuation(base, continuation):
    if not base:
        return continuation
    if not continuation:
        return base

    trailing_token = base.split()[-1] if base.split() else ""
    if len(trailing_token) == 1:
        return base + continuation
    return base + " " + continuation


def parse_transcript(text):
    lines = text.splitlines()
    blocks = []
    narrator_text = None
    ai_lines = []
    in_ai = False

    for line in lines:
        stripped = line.strip()

        if stripped.startswith(">>>"):
            if narrator_text is not None:
                blocks.append((narrator_text.strip(), "\n".join(ai_lines).strip()))
            narrator_text = stripped[3:].strip()
            ai_lines = []
            in_ai = False
            continue

        if stripped.startswith("...") and narrator_text is not None and not in_ai:
            continuation = stripped[3:].lstrip()
            narrator_text = append_continuation(narrator_text, continuation)
            continue

        if narrator_text is not None:
            in_ai = True
            ai_lines.append(line)

    if narrator_text is not None:
        blocks.append((narrator_text.strip(), "\n".join(ai_lines).strip()))

    return blocks


def render_blocks(blocks):
    out = []
    for narrator, ai in blocks:
        out.append('"""Narrator')
        out.append(narrator)
        out.append('"""')
        out.append("")
        out.append('"""Ai')
        out.append(ai)
        out.append('"""')
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


def has_top_level_image(target_dir):
    target = Path(target_dir)
    if not target.exists():
        return False
    for item in target.iterdir():
        if item.is_file() and item.suffix.lower() in IMAGE_EXTS:
            return True
    return False


def unique_destination(path):
    path = Path(path)
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def import_image(image_path, target_dir, image_mode="move"):
    source = Path(image_path).expanduser()
    if not source.exists():
        raise FileNotFoundError(f"Image file not found: {source}")

    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    if has_top_level_image(target_dir):
        dest_dir = target_dir / "images"
        dest_dir.mkdir(parents=True, exist_ok=True)
    else:
        dest_dir = target_dir

    dest = unique_destination(dest_dir / source.name)

    if image_mode == "copy":
        shutil.copy2(source, dest)
        action = "Copied"
    else:
        shutil.move(str(source), str(dest))
        action = "Moved"

    print(f"{action} image to {dest}")
    return str(dest)


def resolve_story_path(target_dir, story_filename):
    return str(Path(target_dir) / story_filename)


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
    parser.add_argument("target_dir", nargs="?", default=".", help="target CMS entry directory")
    parser.add_argument("--input-file", help="read transcript from file instead of stdin")
    parser.add_argument("--image", help="import image into the target entry directory")
    parser.add_argument("--debate", action="store_true", help="write a new debate file")
    args = parser.parse_args()

    story_filename, tags, image_mode = read_config()
    story_path = resolve_story_path(args.target_dir, story_filename)

    text = read_input(args.input_file)
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

    if args.image:
        import_image(args.image, args.target_dir, image_mode)

    print(f"Appended {len(blocks)} block(s) to {story_path}")


if __name__ == "__main__":
    main()
