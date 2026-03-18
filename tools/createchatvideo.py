#!/usr/bin/env python3
"""Compile a restricted `chat.md` spec into `chat.json` and, if present,
invoke `createvideo.py` automatically.

This is intentionally tolerant and production-practical:
- Defaults: input `chat.md`, output `chat.json` in the current working directory.
- Uses a small YAML format with a limited event vocabulary.
- Preserves useful information in JSON so it can be hand-edited if needed.
- If `createvideo.py` cannot be found or fails, the compiled JSON is kept.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import yaml  # type: ignore
except Exception as exc:  # pragma: no cover
    print("ERROR: PyYAML is required for createchatvideo.py", file=sys.stderr)
    raise


ALLOWED_SHOW = {"black", "grey", "gray", "white"}
ALLOWED_CLEAR = {"chat", "all", "anibox"}
ALLOWED_EVENT_KEYS = {"operator", "ai", "anibox", "show", "clear"}
DEFAULT_LEFT_PCT = 65.0
DEFAULT_RIGHT_PCT = 65.0


@dataclass
class CompileWarning:
    message: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile chat.md into chat.json and optionally invoke createvideo.py."
    )
    parser.add_argument("input", nargs="?", default="chat.md", help="Input chat source file (default: chat.md)")
    parser.add_argument("output", nargs="?", default="chat.json", help="Compiled JSON output file (default: chat.json)")
    parser.add_argument(
        "--compile-only",
        action="store_true",
        help="Only compile chat.json; do not invoke createvideo.py",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors where practical.",
    )
    return parser.parse_args()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


PERCENT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*%\s*$")


def parse_percent_or_pixels(value: Any, screen_width: int, field_name: str) -> Tuple[float, int, str]:
    """Return percent, pixels, source_kind where source_kind is 'percent' or 'pixels'."""
    if isinstance(value, (int, float)):
        px = int(round(float(value)))
        require(px > 0, f"{field_name} must be > 0 pixels")
        pct = (px / screen_width) * 100.0
        return pct, px, "pixels"

    if isinstance(value, str):
        m = PERCENT_RE.match(value)
        if m:
            pct = float(m.group(1))
            require(0.0 < pct <= 100.0, f"{field_name} percentage must be between 0 and 100")
            px = int(round(screen_width * (pct / 100.0)))
            require(px > 0, f"{field_name} resolved to 0 pixels")
            return pct, px, "percent"
        if value.strip().isdigit():
            px = int(value.strip())
            require(px > 0, f"{field_name} must be > 0 pixels")
            pct = (px / screen_width) * 100.0
            return pct, px, "pixels"

    raise ValueError(
        f"{field_name} must be a percentage like '65%' or a pixel count like 720"
    )


INLINE_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def parse_inline_spans(text: str) -> List[Dict[str, str]]:
    spans: List[Dict[str, str]] = []
    pos = 0
    for m in INLINE_BOLD_RE.finditer(text):
        if m.start() > pos:
            spans.append({"type": "text", "text": text[pos:m.start()]})
        spans.append({"type": "bold", "text": m.group(1)})
        pos = m.end()
    if pos < len(text):
        spans.append({"type": "text", "text": text[pos:]})
    if not spans:
        spans.append({"type": "text", "text": text})
    return spans


def strip_bold_markup(text: str) -> str:
    return INLINE_BOLD_RE.sub(lambda m: m.group(1), text)


def flush_paragraph(lines: List[str], blocks: List[Dict[str, Any]]) -> None:
    if not lines:
        return
    paragraph = " ".join(line.strip() for line in lines if line.strip())
    if paragraph:
        blocks.append(
            {
                "type": "p",
                "text": strip_bold_markup(paragraph),
                "spans": parse_inline_spans(paragraph),
            }
        )
    lines.clear()


def parse_message_blocks(raw_text: str) -> List[Dict[str, Any]]:
    lines = raw_text.splitlines()
    blocks: List[Dict[str, Any]] = []
    paragraph_lines: List[str] = []

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            flush_paragraph(paragraph_lines, blocks)
            continue

        if stripped.startswith("# "):
            flush_paragraph(paragraph_lines, blocks)
            content = stripped[2:].strip()
            blocks.append({
                "type": "h1",
                "text": strip_bold_markup(content),
                "spans": parse_inline_spans(content),
            })
            continue

        if stripped.startswith("## "):
            flush_paragraph(paragraph_lines, blocks)
            content = stripped[3:].strip()
            blocks.append({
                "type": "h2",
                "text": strip_bold_markup(content),
                "spans": parse_inline_spans(content),
            })
            continue

        if stripped.startswith("- "):
            flush_paragraph(paragraph_lines, blocks)
            content = stripped[2:].strip()
            blocks.append({
                "type": "bullet",
                "text": strip_bold_markup(content),
                "spans": parse_inline_spans(content),
            })
            continue

        paragraph_lines.append(stripped)

    flush_paragraph(paragraph_lines, blocks)

    if not blocks:
        blocks.append({"type": "p", "text": "", "spans": [{"type": "text", "text": ""}]})
    return blocks


def normalize_show_value(value: str) -> str:
    v = value.strip().lower()
    require(v in ALLOWED_SHOW, f"show must be one of: {sorted(ALLOWED_SHOW)}")
    if v == "gray":
        v = "grey"
    return v.upper()


def normalize_clear_value(value: str) -> str:
    v = value.strip().lower()
    require(v in ALLOWED_CLEAR, f"clear must be one of: {sorted(ALLOWED_CLEAR)}")
    return v.upper()


def compile_document(doc: Dict[str, Any], source_name: str) -> Tuple[Dict[str, Any], List[CompileWarning]]:
    warnings: List[CompileWarning] = []

    require(isinstance(doc, dict), "Top-level YAML document must be a mapping")
    unknown_top = set(doc.keys()) - {"title", "config", "background", "events"}
    require(not unknown_top, f"Unknown top-level keys: {sorted(unknown_top)}")

    config = doc.get("config", {}) or {}
    require(isinstance(config, dict), "config must be a mapping")

    screen_width = config.get("screen_width")
    screen_height = config.get("screen_height")
    require(isinstance(screen_width, int) and screen_width > 0, "config.screen_width must be a positive integer")
    require(isinstance(screen_height, int) and screen_height > 0, "config.screen_height must be a positive integer")

    left_raw = config.get("bubble_left_width", f"{DEFAULT_LEFT_PCT}%")
    right_raw = config.get("bubble_right_width", f"{DEFAULT_RIGHT_PCT}%")

    left_pct, left_px, left_kind = parse_percent_or_pixels(left_raw, screen_width, "config.bubble_left_width")
    right_pct, right_px, right_kind = parse_percent_or_pixels(right_raw, screen_width, "config.bubble_right_width")

    if left_px >= screen_width:
        warnings.append(CompileWarning("Left bubble width is >= screen width; clipping may occur."))
    if right_px >= screen_width:
        warnings.append(CompileWarning("Right bubble width is >= screen width; clipping may occur."))

    background = doc.get("background")
    compiled_events: List[Dict[str, Any]] = []
    if background is not None:
        require(isinstance(background, str), "background must be a string")
        compiled_events.append({"cmd": "SHOW", "value": normalize_show_value(background), "source": "background"})

    events = doc.get("events")
    require(isinstance(events, list), "events must be a list")

    for i, event in enumerate(events, start=1):
        require(isinstance(event, dict), f"Event #{i} must be a mapping")
        require(len(event) == 1, f"Event #{i} must contain exactly one command")
        key, value = next(iter(event.items()))
        require(key in ALLOWED_EVENT_KEYS, f"Event #{i} uses unsupported command '{key}'")

        if key in {"operator", "ai"}:
            require(isinstance(value, str), f"Event #{i} '{key}' value must be a string")
            blocks = parse_message_blocks(value)
            compiled_events.append(
                {
                    "cmd": "CHAT",
                    "speaker": key,
                    "side": "right" if key == "operator" else "left",
                    "reveal": "letter" if key == "operator" else "word",
                    "raw_text": value,
                    "blocks": blocks,
                    "event_index": i,
                }
            )
        elif key == "anibox":
            require(isinstance(value, str), f"Event #{i} 'anibox' value must be a string path")
            compiled_events.append(
                {
                    "cmd": "ANIBOX",
                    "image": value,
                    "event_index": i,
                }
            )
        elif key == "show":
            require(isinstance(value, str), f"Event #{i} 'show' value must be a string")
            compiled_events.append(
                {
                    "cmd": "SHOW",
                    "value": normalize_show_value(value),
                    "event_index": i,
                }
            )
        elif key == "clear":
            require(isinstance(value, str), f"Event #{i} 'clear' value must be a string")
            compiled_events.append(
                {
                    "cmd": "CLEAR",
                    "target": normalize_clear_value(value),
                    "event_index": i,
                }
            )

    compiled: Dict[str, Any] = {
        "version": 1,
        "format": "heichalot_chat_video",
        "source": source_name,
        "title": doc.get("title", ""),
        "config": {
            "screen_width": screen_width,
            "screen_height": screen_height,
            "bubble_left_width_pct": round(left_pct, 3),
            "bubble_right_width_pct": round(right_pct, 3),
            "bubble_left_width_px": left_px,
            "bubble_right_width_px": right_px,
            "bubble_left_width_source": left_kind,
            "bubble_right_width_source": right_kind,
            "layout": "messenger",
            "operator_side": "right",
            "ai_side": "left",
            "operator_reveal": "letter",
            "ai_reveal": "word",
            "notes": [
                "Compiled by createchatvideo.py.",
                "If createvideo.py needs a slightly different token shape, edit this JSON manually as needed.",
            ],
        },
        "events": compiled_events,
    }

    return compiled, warnings


def load_yaml(path: Path) -> Dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Input file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML parse error in {path}: {exc}") from exc
    require(data is not None, f"Input file is empty: {path}")
    require(isinstance(data, dict), "Top-level YAML must be a mapping")
    return data


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find_createvideo_candidates(cwd: Path, script_dir: Path) -> List[Path]:
    candidates = [
        cwd / "createvideo.py",
        script_dir / "createvideo.py",
    ]
    deduped: List[Path] = []
    seen = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            deduped.append(candidate)
            seen.add(resolved)
    return deduped


def invoke_createvideo(output_json: Path) -> int:
    cwd = Path.cwd()
    script_dir = Path(__file__).resolve().parent
    for candidate in find_createvideo_candidates(cwd, script_dir):
        if candidate.exists():
            cmd = [sys.executable, str(candidate), str(output_json)]
            print(f"[createchatvideo] Invoking: {' '.join(cmd)}")
            completed = subprocess.run(cmd)
            return completed.returncode

    print(
        "[createchatvideo] createvideo.py was not found in the current working directory "
        "or beside createchatvideo.py. chat.json has been written and kept for manual use.",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    try:
        doc = load_yaml(input_path)
        compiled, warnings = compile_document(doc, input_path.name)
        if warnings:
            for warning in warnings:
                print(f"[createchatvideo] WARNING: {warning.message}", file=sys.stderr)
            if args.strict:
                return 2
        write_json(output_path, compiled)
        print(f"[createchatvideo] Wrote {output_path}")
    except Exception as exc:
        print(f"[createchatvideo] ERROR: {exc}", file=sys.stderr)
        return 1

    if args.compile_only:
        print("[createchatvideo] Compile-only mode enabled; not invoking createvideo.py")
        return 0

    return invoke_createvideo(output_path)


if __name__ == "__main__":
    raise SystemExit(main())
