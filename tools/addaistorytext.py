#!/usr/bin/env python3
"""
addaistorytext.py

Import simple AI terminal transcripts (>>> / ... prompt style)
into one or more Heichalot CMS story files.

By default, an entry may contain:

    story-free.md
    story-members.md
    story.md

When more than one of those files exists, the user is asked which files should
receive the pasted transcript before stdin is read.
"""

from __future__ import annotations

import argparse
import configparser
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Sequence

try:
    from rich.console import Console
    from rich.prompt import Confirm
except Exception:  # pragma: no cover - plain-terminal fallback
    Console = None
    Confirm = None


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_STORY_FILENAMES = (
    "story-free.md",
    "story-members.md",
    "story.md",
)

console = Console() if Console is not None else None


@dataclass(frozen=True)
class AddAIStorySettings:
    story_filenames: tuple[str, ...]
    default_tags: tuple[str, ...]
    image_mode: str = "move"


def _candidate_config_paths() -> list[Path]:
    paths: list[Path] = []

    # Preferred shared configuration location.
    try:
        from config import default_config_path
        paths.append(Path(default_config_path()).expanduser())
    except Exception:
        paths.append(Path.home() / ".heichalotcms" / "config.ini")

    # Retain the historical local fallbacks for tests and portable checkouts.
    paths.extend(
        [
            Path("./heichalotcms/config.ini"),
            Path("./config.ini"),
        ]
    )

    out: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.expanduser()
        if resolved not in seen:
            out.append(resolved)
            seen.add(resolved)
    return out


def _load_config_parser() -> tuple[configparser.ConfigParser, Path | None]:
    config = configparser.ConfigParser()

    for path in _candidate_config_paths():
        if path.exists():
            config.read(path, encoding="utf-8")
            return config, path

    return config, None


def _split_story_filenames(value: str) -> tuple[str, ...]:
    names = tuple(
        item.strip()
        for item in value.split(",")
        if item.strip()
    )
    return names or DEFAULT_STORY_FILENAMES


def read_settings() -> AddAIStorySettings:
    """Read shared configuration while retaining sensible standalone defaults."""
    config, _config_path = _load_config_parser()

    story_filenames: tuple[str, ...] = DEFAULT_STORY_FILENAMES
    default_tags: tuple[str, ...] = ()
    image_mode = "move"

    if "cms" in config:
        cms = config["cms"]

        # New plural form, suitable for the three publishing levels.
        plural = cms.get("story_filenames", "").strip()
        if plural:
            story_filenames = _split_story_filenames(plural)
        else:
            # Historical singular override remains supported.
            singular = cms.get("story_filename", "").strip()
            if singular:
                story_filenames = (singular,)

    if "tags" in config and "default_story_tags" in config["tags"]:
        default_tags = tuple(
            tag.strip()
            for tag in config["tags"]["default_story_tags"].split(",")
            if tag.strip()
        )

    if "addaistory" in config:
        value = config["addaistory"].get("image_mode", "move").strip().lower()
        if value in {"move", "copy"}:
            image_mode = value

        configured_files = config["addaistory"].get("story_filenames", "").strip()
        if configured_files:
            story_filenames = _split_story_filenames(configured_files)

    return AddAIStorySettings(
        story_filenames=story_filenames,
        default_tags=default_tags,
        image_mode=image_mode,
    )


def read_config():
    """Legacy two-value API retained for existing callers and tests."""
    settings = read_settings()
    story_filename = (
        settings.story_filenames[0]
        if len(settings.story_filenames) == 1
        else "story.md"
    )
    return story_filename, list(settings.default_tags)


def read_input(path):
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()

    if console:
        console.print("[bold]Paste transcript[/bold] [dim](Ctrl-D to finish)[/dim]:")
    else:
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
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('"""Tags\n')
            for tag in tags:
                handle.write(f"{tag}\n")
            handle.write("\n")
        return

    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read()

    if '"""Tags' in content:
        return

    with open(path, "a", encoding="utf-8") as handle:
        handle.write('\n"""Tags\n')
        for tag in tags:
            handle.write(f"{tag}\n")
        handle.write("\n")


def append_story(path, text):
    path = str(path)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n")
        handle.write(text)
        handle.write("\n")


def has_top_level_image(target_dir):
    target = Path(target_dir)
    if not target.exists():
        return False
    return any(
        item.is_file() and item.suffix.lower() in IMAGE_EXTS
        for item in target.iterdir()
    )


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

    if console:
        console.print(f"[green]{action}[/green] image to {dest}")
    else:
        print(f"{action} image to {dest}")
    return str(dest)


def resolve_story_path(target_dir, story_filename):
    return str(Path(target_dir) / story_filename)


def write_debate(text):
    os.makedirs("debate", exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"debate/{ts}.md"

    with open(filename, "w", encoding="utf-8") as handle:
        handle.write("---\n")
        handle.write("origin: addaistorytext\n")
        handle.write(f"timestamp: {datetime.now().isoformat()}\n")
        handle.write("---\n\n")
        handle.write(text)

    if console:
        console.print(f"[green]Wrote debate file:[/green] {filename}")
    else:
        print(f"Wrote debate file: {filename}")


def discover_story_files(
    target_dir: Path | str,
    story_filenames: Sequence[str] = DEFAULT_STORY_FILENAMES,
) -> list[Path]:
    target = Path(target_dir)
    return [
        target / filename
        for filename in story_filenames
        if (target / filename).is_file()
    ]


def _confirm_update(path: Path) -> bool:
    prompt = f"Update {path.name}?"

    if Confirm is not None:
        return Confirm.ask(prompt, default=False)

    response = input(f"{prompt} [y/N]: ").strip().lower()
    return response in {"y", "yes"}


def select_story_files(
    target_dir: Path | str,
    story_filenames: Sequence[str] = DEFAULT_STORY_FILENAMES,
    *,
    confirm_fn=None,
) -> list[Path]:
    """Prompt for each existing story level before transcript input is read."""
    target = Path(target_dir)
    existing = discover_story_files(target, story_filenames)

    if not existing:
        fallback_name = (
            story_filenames[-1]
            if story_filenames
            else "story.md"
        )
        fallback = target / fallback_name
        if console:
            console.print(
                f"[yellow]No configured story files exist.[/yellow] "
                f"Creating {fallback.name}."
            )
        else:
            print(f"No configured story files exist. Creating {fallback.name}.")
        return [fallback]

    ask = confirm_fn or _confirm_update
    selected = [path for path in existing if ask(path)]

    if not selected:
        raise SystemExit("No story files selected.")

    return selected


def _resolve_cli_paths(args) -> tuple[Path, str | None]:
    """Support both the historical target-dir CLI and older test/file usage."""
    positional = Path(args.target_or_input).expanduser()

    if args.story:
        story_path = Path(args.story).expanduser().resolve()
        input_file = args.input_file

        if input_file is None and positional != Path(".") and positional.is_file():
            input_file = str(positional)

        return story_path.parent, input_file

    if args.input_file:
        return positional.resolve(), args.input_file

    if positional.is_file():
        return Path.cwd().resolve(), str(positional.resolve())

    return positional.resolve(), None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "target_or_input",
        nargs="?",
        default=".",
        help="target CMS entry directory, or transcript file when --story is used",
    )
    parser.add_argument("--input-file", help="read transcript from file instead of stdin")
    parser.add_argument("--story", help="write only to this explicit story file")
    parser.add_argument("--image", help="import image into the target entry directory")
    parser.add_argument("--debate", action="store_true", help="write a new debate file")
    args = parser.parse_args()

    settings = read_settings()

    # Preserve compatibility with callers and tests that override read_config()
    # when --story selects one explicit destination file.
    if args.story:
        _legacy_story_filename, legacy_tags = read_config()
        settings = AddAIStorySettings(
            story_filenames=settings.story_filenames,
            default_tags=tuple(legacy_tags),
            image_mode=settings.image_mode,
        )

    target_dir, input_file = _resolve_cli_paths(args)

    if args.story:
        selected_story_paths = [Path(args.story).expanduser().resolve()]
    elif args.debate:
        selected_story_paths = []
    else:
        selected_story_paths = select_story_files(
            target_dir,
            settings.story_filenames,
        )

    # Selection happens before prompting for pasted stdin.
    text = read_input(input_file)
    blocks = parse_transcript(text)

    if not blocks:
        print("No >>> prompts found.")
        raise SystemExit(1)

    rendered = render_blocks(blocks)

    if args.debate:
        write_debate(rendered)
        return

    for story_path in selected_story_paths:
        ensure_tags(story_path, settings.default_tags)
        append_story(story_path, rendered)

    if args.image:
        import_image(args.image, target_dir, settings.image_mode)

    names = ", ".join(str(path) for path in selected_story_paths)
    if console:
        console.print(
            f"[green]Appended {len(blocks)} block(s)[/green] to {names}"
        )
    else:
        print(f"Appended {len(blocks)} block(s) to {names}")

if __name__ == "__main__":
    main()
