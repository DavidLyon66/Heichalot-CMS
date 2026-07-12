#!/usr/bin/env python3
"""
List recent Heichalot-CMS entries.

Default behavior:
- Uses tools/config.py to find config.ini
- Uses [cms] cms_dir from config unless overridden with --cms
- Scans entry-* directories
- Computes a "last activity" timestamp from meaningful content files
- Extracts title/type metadata from story.md, story-members.md, or story-free.md in that order
- Prints newest-first, limited output

Examples:
    python3 tools/lscms.py
    python3 tools/lscms.py --limit 20
    python3 tools/lscms.py --days 14
    python3 tools/lscms.py --long
    python3 tools/lscms.py --cms ~/heichalot-tech/cms
    python3 tools/lscms.py --json
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Sequence
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(TOOLS_DIR))

from config import default_config_path, load_app_config

CONFIG_PATH = default_config_path()
console = Console()
ENTRY_RE = re.compile(r"^entry-(\d+)$")
YAML_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")

STORY_PRIORITY_FILES = [
    "story.md",
    "story-members.md",
    "story-free.md",
]

ROOT_PRIORITY_FILES = [
    *STORY_PRIORITY_FILES,
    "interview.md",
    "chat.md",
    "video.md",
]
ROOT_CONTENT_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml"}
TRACKED_SUBDIRS = ["images", "assets", "debate"]


@dataclass
class EntryInfo:
    entry_id: str
    path: str
    type_code: str
    title: str
    last_activity_iso: str
    last_activity_epoch: float
    created_iso: str
    created_epoch: float
    current: bool
    markers: List[str]


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List recent Heichalot-CMS entries")
    parser.add_argument(
        "--cms",
        "--cms-dir",
        dest="cms_dir",
        help="Path to CMS directory (overrides config.ini).",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional override path to config.ini.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of entries to show (default: 10)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Only show entries active in the last N days",
    )
    parser.add_argument(
        "--by",
        choices=["modified", "created"],
        default="modified",
        help="Sort by modified or created time (default: modified)",
    )
    parser.add_argument(
        "--long",
        action="store_true",
        dest="long_output",
        help="Show markers and entry path",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of text",
    )
    return parser.parse_args(argv)


def resolve_cms_dir(args: argparse.Namespace, paths) -> Path:
    if args.cms_dir:
        return Path(args.cms_dir).expanduser().resolve()
    return paths.cms_dir


def get_current_entry(cfg: configparser.ConfigParser) -> Optional[str]:
    try:
        value = cfg.get("cms", "current_entry").strip()
    except (configparser.NoSectionError, configparser.NoOptionError):
        return None

    if not value:
        return None

    value = value.replace("\\", "/")
    name = Path(value).name
    if ENTRY_RE.match(name):
        return name
    if ENTRY_RE.match(value):
        return value
    if value.isdigit():
        return f"entry-{int(value):07d}"
    return None


def iter_entry_dirs(cms_dir: Path) -> Iterable[Path]:
    if not cms_dir.exists():
        raise SystemExit(f"CMS directory does not exist: {cms_dir}")
    if not cms_dir.is_dir():
        raise SystemExit(f"CMS path is not a directory: {cms_dir}")

    for child in sorted(cms_dir.iterdir()):
        if child.is_dir() and ENTRY_RE.match(child.name):
            yield child


def safe_stat_mtime(path: Path) -> Optional[float]:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def safe_stat_ctime(path: Path) -> Optional[float]:
    try:
        return path.stat().st_ctime
    except OSError:
        return None


def iter_meaningful_files(entry_dir: Path) -> Iterable[Path]:
    seen: set[Path] = set()

    for name in ROOT_PRIORITY_FILES:
        p = entry_dir / name
        if p.is_file():
            seen.add(p)
            yield p

    for p in sorted(entry_dir.iterdir()):
        if p in seen:
            continue
        if p.is_file() and p.suffix.lower() in ROOT_CONTENT_EXTENSIONS:
            seen.add(p)
            yield p

    for subdir_name in TRACKED_SUBDIRS:
        subdir = entry_dir / subdir_name
        if not subdir.is_dir():
            continue
        for root, _dirs, files in os.walk(subdir):
            root_path = Path(root)
            for filename in files:
                p = root_path / filename
                if p not in seen:
                    seen.add(p)
                    yield p


def choose_activity_timestamp(entry_dir: Path) -> float:
    mtimes: List[float] = []
    for p in iter_meaningful_files(entry_dir):
        mtime = safe_stat_mtime(p)
        if mtime is not None:
            mtimes.append(mtime)

    if mtimes:
        return max(mtimes)

    fallback = safe_stat_mtime(entry_dir)
    if fallback is not None:
        return fallback

    return 0.0


def choose_created_timestamp(entry_dir: Path) -> float:
    candidates: List[float] = []

    dir_ctime = safe_stat_ctime(entry_dir)
    if dir_ctime is not None:
        candidates.append(dir_ctime)

    dir_mtime = safe_stat_mtime(entry_dir)
    if dir_mtime is not None:
        candidates.append(dir_mtime)

    for name in ROOT_PRIORITY_FILES:
        p = entry_dir / name
        if p.is_file():
            mtime = safe_stat_mtime(p)
            if mtime is not None:
                candidates.append(mtime)

    if candidates:
        return min(candidates)

    return 0.0


def extract_yaml_title(text: str) -> Optional[str]:
    lines = text.splitlines()
    if not lines:
        return None

    if lines[0].strip() != "---":
        return None

    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        match = YAML_KEY_RE.match(line)
        if match and match.group(1).lower() == "title":
            value = match.group(2).strip().strip('"\'')
            if value:
                return value
    return None


def extract_heading_title(text: str) -> Optional[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                return title
    return None


def extract_first_text_line(text: str) -> Optional[str]:
    in_yaml = False
    for i, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if i == 0 and stripped == "---":
            in_yaml = True
            continue
        if in_yaml:
            if stripped == "---":
                in_yaml = False
            continue
        if not stripped:
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            continue
        if stripped.startswith('"""'):
            continue
        return stripped[:120]
    return None


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def extract_title(entry_dir: Path) -> str:
    candidates = [entry_dir / name for name in ROOT_PRIORITY_FILES if (entry_dir / name).is_file()]

    for path in candidates:
        text = read_text_file(path)
        for extractor in (extract_yaml_title, extract_heading_title, extract_first_text_line):
            title = extractor(text)
            if title:
                return title

    for path in entry_dir.glob("*.md"):
        if path in candidates:
            continue
        text = read_text_file(path)
        for extractor in (extract_yaml_title, extract_heading_title, extract_first_text_line):
            title = extractor(text)
            if title:
                return title

    return "Untitled"


def collect_markers(entry_dir: Path) -> List[str]:
    markers: List[str] = []

    for name in ROOT_PRIORITY_FILES:
        if (entry_dir / name).is_file():
            markers.append(Path(name).stem)

    for subdir_name in TRACKED_SUBDIRS:
        subdir = entry_dir / subdir_name
        if subdir.is_dir():
            try:
                has_files = any(p.is_file() for p in subdir.rglob("*"))
            except OSError:
                has_files = False
            if has_files:
                markers.append(subdir_name)

    return markers


def fmt_iso(epoch: float) -> str:
    if epoch <= 0:
        return "1970-01-01 00:00"
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")

def build_entry_info(
    entry_dir: Path,
    current_entry: Optional[str],
    type_map: Optional[dict[str, str]] = None,
) -> EntryInfo:

    modified = choose_activity_timestamp(entry_dir)
    created = choose_created_timestamp(entry_dir)
    entry_id = entry_dir.name
    return EntryInfo(
        entry_id=entry_id,
        path=str(entry_dir),
        type_code=extract_type(entry_dir, type_map or {}),
        title=extract_title(entry_dir),
        last_activity_iso=fmt_iso(modified),
        last_activity_epoch=modified,
        created_iso=fmt_iso(created),
        created_epoch=created,
        current=(current_entry == entry_id),
        markers=collect_markers(entry_dir),
    )


def filter_by_days(entries: List[EntryInfo], days: Optional[int], sort_key: str) -> List[EntryInfo]:
    if days is None:
        return entries
    cutoff = datetime.now() - timedelta(days=days)
    cutoff_epoch = cutoff.timestamp()
    if sort_key == "created":
        return [e for e in entries if e.created_epoch >= cutoff_epoch]
    return [e for e in entries if e.last_activity_epoch >= cutoff_epoch]


def sort_entries(entries: List[EntryInfo], sort_key: str) -> List[EntryInfo]:
    if sort_key == "created":
        return sorted(entries, key=lambda e: (e.created_epoch, e.entry_id), reverse=True)
    return sorted(entries, key=lambda e: (e.last_activity_epoch, e.entry_id), reverse=True)


def render_json(entries: List[EntryInfo]) -> str:
    return json.dumps([asdict(e) for e in entries], indent=2)

def render_rich(entries: List[EntryInfo], long_output: bool, sort_key: str, cms_dir: Path) -> None:
    if not entries:
        console.print(Panel("[yellow]No matching CMS entries found.[/yellow]", title="Heichalot-CMS Entries"))
        return

    table = Table(show_header=True)
    table.add_column("Entry")
    table.add_column("When")
    table.add_column("Type")
    table.add_column("Title")

    if long_output:
        table.add_column("Markers")
        table.add_column("Path")

    for e in entries:
        when = e.created_iso if sort_key == "created" else e.last_activity_iso
        row = [
            e.entry_id,
            when,
            e.type_code,
            e.title,
        ]

        if long_output:
            row.extend([
                ", ".join(e.markers) if e.markers else "-",
                e.path,
            ])

        table.add_row(*row)

    console.print()
    console.print(
        Panel(
            table,
            title=f"Heichalot-CMS Entries — {len(entries)} shown",
            subtitle=str(cms_dir),
            expand=False,
        )
    )


def find_primary_story_file(entry_dir: Path) -> Optional[Path]:
    """Return the highest-priority story file available for listing metadata."""
    for name in STORY_PRIORITY_FILES:
        candidate = entry_dir / name
        if candidate.is_file():
            return candidate
    return None


def extract_type(entry_dir: Path, type_map: dict[str, str]) -> str:
    story = find_primary_story_file(entry_dir)
    if story is None:
        return "?"

    try:
        lines = story.read_text(encoding="utf-8").splitlines()
    except Exception:
        return "?"

    if not lines or lines[0].strip() != "---":
        return "?"

    values: dict[str, str] = {}

    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        values[key.strip().lower()] = value.strip().strip('"').strip("'")

    raw_kind = (
        values.get("type")
        or values.get("kind")
        or ""
    ).strip().lower()

    if not raw_kind:
        return "?"

    return type_map.get(raw_kind, raw_kind)

def load_entry_type_map(cfg):
    out = {}

    if not cfg.has_section("entry_types"):
        return out

    for short_name, long_name in cfg.items("entry_types"):
        out[long_name.strip().lower()] = short_name.strip()

    return out

def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.limit < 1:
        eprint("--limit must be >= 1")
        return 2
    if args.days is not None and args.days < 0:
        eprint("--days must be >= 0")
        return 2

    config_path = args.config if args.config is not None else str(CONFIG_PATH)
    cfg, cfg_path, paths = load_app_config(config_path)
    cms_dir = resolve_cms_dir(args, paths)
    current_entry = get_current_entry(cfg)
    type_map = load_entry_type_map(cfg)

    entries = [
        build_entry_info(entry_dir, current_entry, type_map)
        for entry_dir in iter_entry_dirs(cms_dir)
    ]
    entries = filter_by_days(entries, args.days, args.by)
    entries = sort_entries(entries, args.by)[: args.limit]

    if args.json:
        print(render_json(entries))
    else:
        render_rich(entries, args.long_output, args.by, cms_dir)        

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
