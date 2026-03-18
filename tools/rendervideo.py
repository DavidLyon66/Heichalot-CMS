#!/usr/bin/env python3
"""
rendervideo.py

Compile a production's video.md into video.render.json and optionally render it
using Remotion.

Usage:
    python tools/rendervideo.py <production-dir>
    python tools/rendervideo.py <production-dir> --render
    python tools/rendervideo.py <production-dir> --render --output out/custom.mp4
    python tools/rendervideo.py <production-dir> --dry-run

Expected production directory layout:
    <production-dir>/
        video.md
        video.render.json
        assets/
        output/
        cms-entry -> /path/to/heichalotcms/cms/entry-<id>

Assumptions:
- This script lives at: heichalotcms/tools/rendervideo.py
- Remotion project lives at: heichalotcms/videorender/
- Remotion public dir lives at: heichalotcms/videorender/public/
- Your Remotion side expects assets under:
    public/images/<name>.<ext>
    public/sfx/<filename>

Dependencies:
    pip install pyyaml

Notes:
- This is intentionally minimal.
- MUSIC is not implemented yet.
- SHOW / FADE / HOLD targets are resolved to staged images.
- SFX filenames are resolved and staged into public/sfx.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise ImportError("PyYAML is required. Install with: pip install pyyaml") from exc


FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
CUE_RE = re.compile(r"^\[(.+?)\]\s*$")
TRIPLE_QUOTE = '"""'

IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".webp", ".svg"]
SFX_EXTS = [".wav", ".mp3", ".aac", ".m4a", ".ogg"]


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def slugify_words(words: list[str]) -> str:
    text = " ".join(words).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")

def parse_duration_token(token: str) -> dict[str, Any]:
    """
    Parse duration tokens like:
        5s
        150f
    """
    m = re.fullmatch(r"(\d+)([sfSF])", token.strip())
    if not m:
        raise ValueError(f"Invalid duration token: {token}")

    value = int(m.group(1))
    unit = m.group(2).lower()

    return {
        "value": value,
        "unit": unit,
    }


def duration_to_frames(duration: dict[str, Any], fps: int) -> int:
    value = duration["value"]
    unit = duration["unit"]

    if unit == "s":
        return value * fps
    if unit == "f":
        return value

    raise ValueError(f"Unsupported duration unit: {unit}")


def split_duration_clause(tokens: list[str]) -> tuple[list[str], dict[str, Any] | None]:
    """
    Split:
        ["route-map.png", "FOR", "5s"]
    into:
        (["route-map.png"], {"value": 5, "unit": "s"})

    If there is no trailing FOR clause, return (tokens, None).
    """
    if len(tokens) >= 2 and tokens[-2].upper() == "FOR":
        duration = parse_duration_token(tokens[-1])
        return tokens[:-2], duration

    return tokens, None


def parse_show_tokens(tokens: list[str], fps: int) -> dict[str, Any]:
    """
    Parse:
        SHOW route-map.png FOR 5s ENTER FADE FROM BLACK LEAVE FADE TO BLACK
        SHOW route-map.png FOR 5s MOTION ZOOM IN
    """
    if not tokens:
        raise ValueError("SHOW cue missing filename")

    file = tokens[0]
    i = 1

    duration_frames: int | None = None
    enter: dict[str, Any] | None = None
    leave: dict[str, Any] | None = None
    motion: dict[str, Any] | None = None

    while i < len(tokens):
        token = tokens[i].upper()

        if token == "FOR":
            if i + 1 >= len(tokens):
                raise ValueError("SHOW FOR missing duration")
            duration_frames = duration_to_frames(parse_duration_token(tokens[i + 1]), fps)
            i += 2
            continue

        if token == "ENTER":
            if i + 1 >= len(tokens):
                raise ValueError("SHOW ENTER missing mode")

            mode = tokens[i + 1].lower()

            if mode == "fade":
                enter = {"type": "fade"}
                i += 2
                if i + 1 < len(tokens) and tokens[i].upper() == "FROM" and tokens[i + 1].upper() == "BLACK":
                    enter["from"] = "black"
                    i += 2
                continue

            if mode == "zoom":
                enter = {"type": "zoom"}
                i += 2
                continue

            if mode == "slide":
                enter = {"type": "slide"}
                i += 2
                continue

            raise ValueError(f"Unsupported SHOW ENTER mode: {tokens[i + 1]}")

        if token == "LEAVE":
            if i + 1 >= len(tokens):
                raise ValueError("SHOW LEAVE missing mode")

            mode = tokens[i + 1].lower()

            if mode == "fade":
                leave = {"type": "fade"}
                i += 2
                if i + 1 < len(tokens) and tokens[i].upper() == "TO" and tokens[i + 1].upper() == "BLACK":
                    leave["to"] = "black"
                    i += 2
                continue

            if mode == "zoom":
                leave = {"type": "zoom"}
                i += 2
                continue

            if mode == "slide":
                leave = {"type": "slide"}
                i += 2
                continue

            raise ValueError(f"Unsupported SHOW LEAVE mode: {tokens[i + 1]}")

        if token == "MOTION":
            if i + 2 >= len(tokens):
                raise ValueError("SHOW MOTION missing mode")

            mode1 = tokens[i + 1].upper()
            mode2 = tokens[i + 2].upper()

            if mode1 == "ZOOM" and mode2 == "IN":
                motion = {"type": "zoom_in"}
                i += 3
                continue

            if mode1 == "ZOOM" and mode2 == "OUT":
                motion = {"type": "zoom_out"}
                i += 3
                continue

            if mode1 == "SCROLL" and mode2 == "UP":
                motion = {"type": "scroll_up"}
                i += 3
                continue

            if mode1 == "SCROLL" and mode2 == "DOWN":
                motion = {"type": "scroll_down"}
                i += 3
                continue

            raise ValueError(f"Unsupported SHOW MOTION mode: {tokens[i + 1]} {tokens[i + 2]}")

        raise ValueError(f"Unrecognized SHOW token sequence near: {' '.join(tokens[i:])}")

    event: dict[str, Any] = {
        "type": "show",
        "file": file,
    }

    if duration_frames is not None:
        event["durationFrames"] = duration_frames
    if enter is not None:
        event["enter"] = enter
    if leave is not None:
        event["leave"] = leave
    if motion is not None:
        event["motion"] = motion

    return event

def parse_anibox_tokens(tokens: list[str], fps: int) -> dict[str, Any]:
    """
    Parse:
        ANIBOX harbour.png AT 1s FOR 3s
        ANIBOX harbour.png STARTING 45f FOR 120f
        ANIBOX harbour.png AT 1s FOR 3s ENTER FADE LEAVE ZOOM
    """
    if not tokens:
        raise ValueError("ANIBOX cue missing filename")

    file = tokens[0]
    i = 1

    at_frames: int | None = None
    duration_frames: int | None = None
    enter: str | None = None
    leave: str | None = None

    while i < len(tokens):
        token = tokens[i].upper()

        if token in {"AT", "STARTING"}:
            if i + 1 >= len(tokens):
                raise ValueError(f"ANIBOX {token} missing duration")
            at_frames = duration_to_frames(parse_duration_token(tokens[i + 1]), fps)
            i += 2
            continue

        if token == "FOR":
            if i + 1 >= len(tokens):
                raise ValueError("ANIBOX FOR missing duration")
            duration_frames = duration_to_frames(parse_duration_token(tokens[i + 1]), fps)
            i += 2
            continue

        if token == "ENTER":
            if i + 1 >= len(tokens):
                raise ValueError("ANIBOX ENTER missing mode")
            mode = tokens[i + 1].lower()
            if mode not in {"fade", "zoom", "slide"}:
                raise ValueError(f"Unsupported ANIBOX ENTER mode: {tokens[i + 1]}")
            enter = mode
            i += 2
            continue

        if token == "LEAVE":
            if i + 1 >= len(tokens):
                raise ValueError("ANIBOX LEAVE missing mode")
            mode = tokens[i + 1].lower()
            if mode not in {"fade", "zoom", "slide"}:
                raise ValueError(f"Unsupported ANIBOX LEAVE mode: {tokens[i + 1]}")
            leave = mode
            i += 2
            continue

        raise ValueError(f"Unrecognized ANIBOX token sequence near: {' '.join(tokens[i:])}")

    event: dict[str, Any] = {
        "type": "anibox",
        "file": file,
    }

    if at_frames is not None:
        event["atFrames"] = at_frames

    if duration_frames is not None:
        event["durationFrames"] = duration_frames

    if enter is not None:
        event["enter"] = enter

    if leave is not None:
        event["leave"] = leave

    return event

def extract_front_matter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text

    yaml_text = match.group(1)
    body = text[match.end():]

    try:
        metadata = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML front matter: {exc}") from exc

    if not isinstance(metadata, dict):
        raise ValueError("YAML front matter must parse to a dictionary/object.")

    return metadata, body


def parse_dialogue_block(
    lines: list[str],
    start_index: int,
    fps: int,
) -> tuple[dict[str, Any], int]:
    """
    Consumes a triple-quoted dialogue block.

    Accepted forms:

        \"\"\"NARRATOR
        Text...
        \"\"\"

    or

        \"\"\"
        NARRATOR
        Text...
        \"\"\"

    and now also:

        \"\"\"NARRATOR
        Text...
        \"\"\" FOR 3s

        \"\"\"
        NARRATOR
        Text...
        \"\"\" FOR 90f
    """
    first_line = lines[start_index]
    content_lines: list[str] = []

    opening_remainder = first_line[len(TRIPLE_QUOTE):]
    i = start_index + 1

    if opening_remainder.strip():
        content_lines.append(opening_remainder)

    found_closing = False
    duration_frames: int | None = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith(TRIPLE_QUOTE):
            found_closing = True

            closing_remainder = stripped[len(TRIPLE_QUOTE):].strip()

            if closing_remainder:
                tokens = closing_remainder.split()
                if len(tokens) == 2 and tokens[0].upper() == "FOR":
                    duration = parse_duration_token(tokens[1])
                    duration_frames = duration_to_frames(duration, fps)
                else:
                    raise ValueError(
                        f"Invalid dialogue closing clause at line {i + 1}: {line}"
                    )

            i += 1
            break

        content_lines.append(line)
        i += 1

    if not found_closing:
        raise ValueError(
            f"Unterminated dialogue block starting at line {start_index + 1}"
        )

    while content_lines and not content_lines[0].strip():
        content_lines.pop(0)
    while content_lines and not content_lines[-1].strip():
        content_lines.pop()

    if not content_lines:
        raise ValueError(
            f"Dialogue block starting at line {start_index + 1} is empty"
        )

    speaker = content_lines[0].strip()
    text_lines = content_lines[1:]

    while text_lines and not text_lines[0].strip():
        text_lines.pop(0)

    text = "\n".join(text_lines).strip()

    if not speaker:
        raise ValueError(
            f"Dialogue block starting at line {start_index + 1} has no speaker"
        )

    event: dict[str, Any] = {
        "type": "dialogue",
        "speaker": speaker,
        "text": text,
    }

    if duration_frames is not None:
        event["durationFrames"] = duration_frames

    return event, i

def parse_cue(cue_text: str, fps: int) -> dict[str, Any]:
    tokens = cue_text.split()
    if not tokens:
        raise ValueError("Encountered empty cue")

    head = tokens[0].upper()
    rest = tokens[1:]

    if head == "CHAPTER":
        if not rest:
            raise ValueError("CHAPTER cue missing title")
        return {
            "type": "chapter",
            "title": " ".join(rest),
        }

    if head == "SFX":
        if not rest:
            raise ValueError(f"SFX cue missing filename: [{cue_text}]")
        return {
            "type": "sfx",
            "file": " ".join(rest),
        }

    if head == "SHOW":
        return parse_show_tokens(rest, fps)

    if head == "ANIBOX":
        return parse_anibox_tokens(rest, fps)

    if head == "FADE":
        rest, duration = split_duration_clause(rest)
        if not rest:
            raise ValueError(f"FADE cue missing target: [{cue_text}]")

        if rest[0].upper() == "TO":
            rest = rest[1:]

        event = {
            "type": "fade",
            "target": slugify_words(rest),
        }
        if duration is not None:
            event["duration"] = duration
        return event

    if head == "HOLD":
        rest, duration = split_duration_clause(rest)
        if not rest:
            raise ValueError(f"HOLD cue missing target: [{cue_text}]")

        if rest[0].upper() == "ON":
            rest = rest[1:]

        event = {
            "type": "hold",
            "target": slugify_words(rest),
        }
        if duration is not None:
            event["duration"] = duration
        return event

    return {
        "type": "cue",
        "command": head.lower(),
        "raw": cue_text,
        "args": rest,
    }

def parse_video_body(body: str, fps: int) -> list[dict[str, Any]]:
    lines = body.splitlines()
    events: list[dict[str, Any]] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith(TRIPLE_QUOTE):
            block, i = parse_dialogue_block(lines, i, fps)
            events.append(block)
            continue        

        cue_match = CUE_RE.match(line.strip())
        if cue_match:
            cue_text = cue_match.group(1).strip()
            events.append(parse_cue(cue_text, fps))
            i += 1
            continue

        i += 1

    return events


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")

    return data

def normalize_event_durations(events: list[dict[str, Any]], fps: int) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []

    for event in events:
        event = dict(event)

        duration = event.pop("duration", None)
        if duration is not None:
            value = duration["value"]
            unit = duration["unit"]

            if unit == "s":
                event["durationFrames"] = value * fps
            elif unit == "f":
                event["durationFrames"] = value
            else:
                raise ValueError(f"Unsupported duration unit: {unit}")

        normalized.append(event)

    return normalized

def normalize_anibox_scene_offsets(events: list[dict[str, Any]], fps: int) -> list[dict[str, Any]]:
    """
    Keep ANIBOX timing relative to the current scene.
    STARTING and AT are normalized into atFrames.
    No global timeline conversion here.
    """
    normalized: list[dict[str, Any]] = []

    for event in events:
        event = dict(event)

        if event.get("type") == "anibox":
            if "startFrames" in event and "atFrames" not in event:
                event["atFrames"] = event.pop("startFrames")

            event.setdefault("atFrames", 0)

        normalized.append(event)

    return normalized

def build_scenes_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scenes: list[dict[str, Any]] = []
    current_scene: dict[str, Any] | None = None

    for event in events:
        event_type = event.get("type")

        if event_type == "show":
            if current_scene is not None:
                scenes.append(current_scene)

            duration_frames = event.get("durationFrames")
            if not isinstance(duration_frames, int):
                raise ValueError("SHOW events must have durationFrames before scene compilation")

            current_scene = {
                "type": "scene",
                "background": {
                    "type": "show",
                    "file": event["file"],
                    **({"enter": event["enter"]} if "enter" in event else {}),
                    **({"leave": event["leave"]} if "leave" in event else {}),
                    **({"motion": event["motion"]} if "motion" in event else {}),
                    **({"line": event["line"]} if "line" in event else {}),
                },
                "durationFrames": duration_frames,
                "events": [],
            }
            continue

        # Ignore non-SHOW events until first SHOW.
        # They still remain in compiled["events"] for parser tests,
        # but do not participate in scene building.
        if current_scene is None:
            continue

        current_scene["events"].append(event)

    if current_scene is not None:
        scenes.append(current_scene)

    return scenes

def assign_scene_event_offsets(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Assign scene-local atFrames for events that do not already specify one.

    Rules:
    - dialogue defaults to sequential placement
    - anibox keeps explicit atFrames if provided
    - anibox without explicit atFrames aligns with the most recent timed anchor
      (typically the most recent dialogue start)
    - explicit anibox timing does not push the dialogue cursor
    """
    normalized: list[dict[str, Any]] = []

    for scene in scenes:
        scene = dict(scene)
        events = [dict(event) for event in scene.get("events", [])]

        cursor = 0
        last_anchor_start = 0

        for event in events:
            event_type = event.get("type")
            explicit_at = "atFrames" in event

            if event_type == "dialogue":
                if not explicit_at:
                    event["atFrames"] = cursor

                at_frames = event.get("atFrames", 0)
                duration = event.get("durationFrames")

                if isinstance(at_frames, int):
                    last_anchor_start = at_frames

                if isinstance(duration, int) and isinstance(at_frames, int):
                    cursor = max(cursor, at_frames + duration)

                continue

            if event_type == "anibox":
                if not explicit_at:
                    event["atFrames"] = last_anchor_start
                # anibox does not advance cursor unless you decide later that it should
                continue

            # Fallback for any other event type
            if not explicit_at:
                event["atFrames"] = cursor

            at_frames = event.get("atFrames", 0)
            duration = event.get("durationFrames")

            if isinstance(at_frames, int):
                last_anchor_start = at_frames

            if isinstance(duration, int) and isinstance(at_frames, int):
                cursor = max(cursor, at_frames + duration)

        scene["events"] = events
        normalized.append(scene)

    return normalized

def compile_production(production_dir: Path) -> dict[str, Any]:
    video_md_path = production_dir / "video.md"
    render_json_path = production_dir / "video.render.json"

    if not video_md_path.exists():
        raise FileNotFoundError(f"Missing file: {video_md_path}")

    source_text = video_md_path.read_text(encoding="utf-8")
    metadata, body = extract_front_matter(source_text)

    existing = load_json(render_json_path)
    compiled: dict[str, Any] = dict(existing)

    fps = metadata.get("fps", existing.get("fps", 30))
    if not isinstance(fps, int):
        raise ValueError(f"fps must be an integer, got: {fps!r}")

    events = parse_video_body(body, fps)
    events = normalize_event_durations(events, fps)
    events = normalize_anibox_scene_offsets(events, fps)

    scenes = build_scenes_from_events(events)
    scenes = assign_scene_event_offsets(scenes)

    compiled.setdefault("renderer", "remotion")
    compiled.setdefault("duration", metadata.get("duration", 30))
    compiled.setdefault("fps", fps)

    for key, value in metadata.items():
        compiled[key] = value

    compiled["events"] = events  # optional, keep for debugging during transition
    compiled["scenes"] = scenes
    compiled["source"] = {
        "video_md": str(video_md_path),
        "production_dir": str(production_dir),
        "assets_dir": str(production_dir / "assets"),
    }

    cms_entry_link = production_dir / "cms-entry"
    if cms_entry_link.exists():
        try:
            compiled["source"]["cms_entry"] = str(cms_entry_link.resolve())
        except OSError:
            compiled["source"]["cms_entry"] = str(cms_entry_link)

    return compiled


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def find_candidate_dirs(production_dir: Path) -> list[Path]:
    dirs: list[Path] = []

    prod_assets = production_dir / "assets"
    if prod_assets.exists():
        dirs.append(prod_assets)
        if (prod_assets / "images").exists():
            dirs.append(prod_assets / "images")
        if (prod_assets / "sfx").exists():
            dirs.append(prod_assets / "sfx")

    cms_entry = production_dir / "cms-entry"
    if cms_entry.exists():
        dirs.append(cms_entry)
        if (cms_entry / "assets").exists():
            dirs.append(cms_entry / "assets")
        if (cms_entry / "images").exists():
            dirs.append(cms_entry / "images")
        if (cms_entry / "sfx").exists():
            dirs.append(cms_entry / "sfx")

    # unique, preserving order
    seen: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        key = str(d.resolve()) if d.exists() else str(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def resolve_image_for_target(production_dir: Path, target: str) -> Path:
    candidate_dirs = find_candidate_dirs(production_dir)

    for directory in candidate_dirs:
        for ext in IMAGE_EXTS:
            candidate = directory / f"{target}{ext}"
            if candidate.exists():
                return candidate

    raise FileNotFoundError(
        f"Could not resolve image target '{target}'. Looked in: "
        + ", ".join(str(d) for d in candidate_dirs)
    )


def resolve_sfx_file(production_dir: Path, filename: str) -> Path:
    raw = Path(filename)
    if raw.is_absolute() and raw.exists():
        return raw

    candidate_dirs = find_candidate_dirs(production_dir)

    for directory in candidate_dirs:
        candidate = directory / filename
        if candidate.exists():
            return candidate

    if raw.suffix:
        raise FileNotFoundError(
            f"Could not resolve SFX file '{filename}'. Looked in: "
            + ", ".join(str(d) for d in candidate_dirs)
        )

    for directory in candidate_dirs:
        for ext in SFX_EXTS:
            candidate = directory / f"{filename}{ext}"
            if candidate.exists():
                return candidate

    raise FileNotFoundError(
        f"Could not resolve SFX file '{filename}'. Looked in: "
        + ", ".join(str(d) for d in candidate_dirs)
    )


def copy_if_needed(src: Path, dst: Path) -> None:
    ensure_dir(dst.parent)
    if dst.exists():
        src_bytes = src.read_bytes()
        dst_bytes = dst.read_bytes()
        if src_bytes == dst_bytes:
            return
    shutil.copy2(src, dst)


def stage_assets(production_dir: Path, compiled: dict[str, Any], videorender_root: Path) -> dict[str, Any]:
    public_dir = videorender_root / "public"
    public_images = public_dir / "images"
    public_sfx = public_dir / "sfx"

    ensure_dir(public_images)
    ensure_dir(public_sfx)

    staged_images: dict[str, str] = {}
    staged_sfx: dict[str, str] = {}

    for event in compiled.get("events", []):
        event_type = event.get("type")

        if event_type in {"show", "fade", "hold"}:
            target = event.get("target")
            if not isinstance(target, str) or not target:
                continue

            if target not in staged_images:
                src = resolve_image_for_target(production_dir, target)
                dst = public_images / src.name
                copy_if_needed(src, dst)
                staged_images[target] = f"images/{src.name}"

        elif event_type == "sfx":
            filename = event.get("file")
            if not isinstance(filename, str) or not filename:
                continue

            if filename not in staged_sfx:
                src = resolve_sfx_file(production_dir, filename)
                dst = public_sfx / src.name
                copy_if_needed(src, dst)
                staged_sfx[filename] = src.name

    compiled["staged_assets"] = {
        "images": staged_images,
        "sfx": staged_sfx,
    }
    return compiled


def write_render_json(compiled: dict[str, Any], output_path: Path) -> None:
    output_path.write_text(
        json.dumps(compiled, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run_remotion_render(
    videorender_root: Path,
    props_file: Path,
    output_video: Path,
    composition_id: str = "VideoFromJSON",
) -> None:
    ensure_dir(output_video.parent)

    cmd = [
        "npx",
        "remotion",
        "render",
        "src/index.ts",
        composition_id,
        str(output_video),
        f"--props={props_file}",
    ]

    print("Running:")
    print("  " + " ".join(cmd))
    subprocess.run(cmd, cwd=videorender_root, check=True)

def resolve_output_video(production_dir: Path, args) -> Path:

    # explicit path overrides everything
    if args.output:
        return Path(args.output).expanduser().resolve()

    project_name = production_dir.name

    return production_dir / f"{project_name}.mp4"

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Compile and optionally render a production video")
    parser.add_argument("production_dir", help="Path to the production directory")
    parser.add_argument("--dry-run", action="store_true", help="Print compiled JSON to stdout")
    parser.add_argument("--render", action="store_true", help="Run Remotion after compiling")
    parser.add_argument("--output-dir", action="store_true", help="Write rendered video into ./output directory instead of CWD",)
    parser.add_argument("--output", help="Explicit output file path (overrides default behavior)", )
    parser.add_argument("--composition", default="VideoFromJSON", help="Remotion composition ID (default: VideoFromJSON)", )
    args = parser.parse_args(argv[1:])

    production_dir = Path(args.production_dir).expanduser().resolve()
    if not production_dir.exists() or not production_dir.is_dir():
        eprint(f"Error: production directory does not exist or is not a directory: {production_dir}")
        return 1

    tools_dir = Path(__file__).resolve().parent
    heichalotcms_root = tools_dir.parent
    videorender_root = heichalotcms_root / "videorender"

    if not videorender_root.exists():
        eprint(f"Error: videorender directory not found: {videorender_root}")
        return 1

    render_json_path = production_dir / "video.render.json"
    output_video = resolve_output_video(production_dir, args)

    try:
        compiled = compile_production(production_dir)
        compiled = stage_assets(production_dir, compiled, videorender_root)

        rendered_json = json.dumps(compiled, indent=2, ensure_ascii=False) + "\n"

        if args.dry_run:
            print(rendered_json, end="")
            return 0

        write_render_json(compiled, render_json_path)
        print(f"Wrote:  {render_json_path}")
        print(f"Events: {len(compiled.get('events', []))}")

        if args.render:
            run_remotion_render(
                videorender_root=videorender_root,
                props_file=render_json_path,
                output_video=output_video,
                composition_id=args.composition,
            )
            print(f"Video:  {output_video}")

        return 0

    except subprocess.CalledProcessError as exc:
        eprint(f"Render command failed with exit code {exc.returncode}")
        return exc.returncode or 1
    except Exception as exc:
        eprint(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))