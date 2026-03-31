#!/usr/bin/env python3
"""
List recent Heichalot-CMS entries.

Default behavior:
- Reads ~/.heichalotcms/config.ini
- Uses [cms] cms_dir from config unless overridden
- Scans entry-* directories
- Computes a "last activity" timestamp from meaningful content files
- Extracts a human title from story.md (or other root .md files)
- Prints newest-first, limited output

Examples:
    python3 tools/lscms.py
    python3 tools/lscms.py --limit 20
    python3 tools/lscms.py --days 14
    python3 tools/lscms.py --long
    python3 tools/lscms.py --cms-dir ~/heichalot-tech/cms
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
from typing import Iterable, List, Optional, Sequence, Tuple

CONFIG_PATH = Path("~/.heichalotcms/config.ini").expanduser()
ENTRY_RE = re.compile(r"^entry-(\d+)$")
YAML_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")

ROOT_PRIORITY_FILES = [
    "story.md",
    "interview.md",
    "chat.md",
    "video.md",
]
ROOT_CONTENT_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml"}
TRACKED_SUBDIRS = ["assets", "debate"]


@dataclass
class EntryInfo:
    entry_id: str
    path: str
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
        "--cms-dir",
        help="Path to cms directory (overrides config.ini)",
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


def load_config(path: Path) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if path.exists():
        cfg.read(path)
    return cfg


def resolve_cms_dir(args: argparse.Namespace, cfg: configparser.ConfigParser) -> Path:
    if args.cms_dir:
        return Path(args.cms_dir).expanduser().resolve()

    try:
        cms_dir = cfg.get("cms", "cms_dir")
    except (configparser.NoSectionError, configparser.NoOptionError):
        raise SystemExit(
            "Could not determine cms_dir. Pass --cms-dir or set [cms] cms_dir in ~/.heichalotcms/config.ini"
        )

    return Path(cms_dir).expanduser().resolve()


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


def build_entry_info(entry_dir: Path, current_entry: Optional[str]) -> EntryInfo:
    modified = choose_activity_timestamp(entry_dir)
    created = choose_created_timestamp(entry_dir)
    entry_id = entry_dir.name
    return EntryInfo(
        entry_id=entry_id,
        path=str(entry_dir),
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


def render_text(entries: List[EntryInfo], long_output: bool, sort_key: str) -> str:
    if not entries:
        return "No matching CMS entries found."

    lines: List[str] = []
    for e in entries:
        marker = "*" if e.current else " "
        when = e.created_iso if sort_key == "created" else e.last_activity_iso
        lines.append(f"{marker} {e.entry_id}  {when}  {e.title}")
        if long_output:
            marker_text = ", ".join(e.markers) if e.markers else "-"
            lines.append(f"    markers: {marker_text}")
            lines.append(f"    path:    {e.path}")
    return "\n".join(lines)


def render_json(entries: List[EntryInfo]) -> str:
    return json.dumps([asdict(e) for e in entries], indent=2)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.limit < 1:
        eprint("--limit must be >= 1")
        return 2
    if args.days is not None and args.days < 0:
        eprint("--days must be >= 0")
        return 2

    cfg = load_config(CONFIG_PATH)
    cms_dir = resolve_cms_dir(args, cfg)
    current_entry = get_current_entry(cfg)

    entries = [build_entry_info(entry_dir, current_entry) for entry_dir in iter_entry_dirs(cms_dir)]
    entries = filter_by_days(entries, args.days, args.by)
    entries = sort_entries(entries, args.by)[: args.limit]

    if args.json:
        print(render_json(entries))
    else:
        print(render_text(entries, args.long_output, args.by))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
