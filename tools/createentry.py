#!/usr/bin/env python3
from configparser import ConfigParser
from pathlib import Path
import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def default_config_path() -> Path:
    if sys.platform.startswith("linux"):
        return Path.home() / ".heichalotcms" / "config.ini"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "heichalotcms" / "config.ini"
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            appdata = str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "heichalotcms" / "config.ini"
    return Path.home() / ".heichalotcms" / "config.ini"


def read_config(path: Path) -> ConfigParser:
    cfg = ConfigParser()
    if path.exists():
        cfg.read(str(path))
    return cfg


def write_config(path: Path, cfg: ConfigParser) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        cfg.write(f)


def prompt_if_missing(val: str, prompt_text: str) -> str:
    if val is not None and str(val).strip():
        return str(val).strip()
    return input(prompt_text).strip()


def render_story(template_path: Path, context: dict) -> str:
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except Exception as e:
        raise SystemExit("ERROR: jinja2 not installed. Install with: pip install jinja2") from e

    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=select_autoescape(enabled_extensions=()),
        keep_trailing_newline=True,
    )
    tmpl = env.get_template(template_path.name)
    return tmpl.render(**context)


def resolve_entry_kind(cfg: ConfigParser, short_code: Optional[str]) -> str:
    if short_code is None or not str(short_code).strip():
        return cfg.get("new_entry", "default_kind", fallback="note") if cfg.has_section("new_entry") else "note"
    short_code = short_code.strip()
    if cfg.has_section("entry_types"):
        mapped = cfg.get("entry_types", short_code, fallback="").strip()
        if mapped:
            return mapped
    return short_code


def main():
    ap = argparse.ArgumentParser(description="Create a new cms entry directory (uses last_id counter in config.ini).")
    ap.add_argument("entry_type", nargs="?", help="Short entry type code such as n, rv, vd, yt")
    ap.add_argument("title", nargs="?", help="Entry title")
    ap.add_argument("--location", help="e.g. singapore (stored in story.md; prompted if missing)")
    ap.add_argument("--year", type=int, help="Year only, e.g. 1857 (stored as YYYY-01-01 in story.md; prompted if missing)")
    ap.add_argument("--config", default=None, help="Optional override path to config.ini")
    ap.add_argument("--prefix", default=None, help="Entry prefix (default from config new_entry.entry_prefix or 'entry-')")
    ap.add_argument("--pad", type=int, default=None, help="Numeric padding width (default from config or 7)")
    args = ap.parse_args()

    cfg_path = Path(args.config).expanduser().resolve() if args.config else default_config_path()
    cfg = read_config(cfg_path)

    if not cfg.has_section("cms") or not cfg.has_option("cms", "project_root"):
        raise SystemExit(f"ERROR: Missing [cms] project_root in {cfg_path}")

    project_root = Path(cfg.get("cms", "project_root")).expanduser().resolve()

    prefix = args.prefix
    pad_width = args.pad
    if prefix is None:
        prefix = cfg.get("new_entry", "entry_prefix", fallback="entry-") if cfg.has_section("new_entry") else "entry-"
    if pad_width is None:
        pad_width = cfg.getint("new_entry", "pad_width", fallback=7) if cfg.has_section("new_entry") else 7

    cms_dir_name = cfg.get("new_entry", "cms_dir", fallback="cms") if cfg.has_section("new_entry") else "cms"
    template_name = cfg.get("new_entry", "template", fallback="story.md.j2") if cfg.has_section("new_entry") else "story.md.j2"

    cms_dir = project_root / cms_dir_name
    cms_dir.mkdir(parents=True, exist_ok=True)

    last_id = 0
    if cfg.has_option("cms", "last_id"):
        try:
            last_id = int(cfg.get("cms", "last_id"))
        except ValueError:
            last_id = 0

    next_id_num = last_id + 1
    entry_id = f"{prefix}{next_id_num:0{pad_width}d}"
    entry_dir = (cms_dir / entry_id).resolve()

    if entry_dir.exists():
        raise SystemExit(f"ERROR: Entry already exists: {entry_dir}")

    assets_dir = entry_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    template_path = project_root / "tools" / "templates" / template_name
    if not template_path.exists():
        raise SystemExit(f"ERROR: Template not found: {template_path}")

    entry_kind = resolve_entry_kind(cfg, args.entry_type)
    entry_title = args.title.strip() if args.title else cfg.get("new_entry", "default_title", fallback="Title")

    location_text = prompt_if_missing(args.location, "Location (e.g. singapore): ")
    year_val = args.year
    if year_val is None:
        year_str = prompt_if_missing(None, "Year (e.g. 1857): ")
        try:
            year_val = int(year_str)
        except ValueError:
            raise SystemExit("ERROR: Year must be an integer like 1857")

    datetime_iso = f"{year_val:04d}-01-01"
    created_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    story_text = render_story(template_path, {
        "entry_id": entry_id,
        "created_utc": created_utc,
        "location_text": location_text,
        "datetime": datetime_iso,
        "year": year_val,
        "kind": entry_kind,
        "title": entry_title,
        "entry_type": args.entry_type or "",
    })
    (entry_dir / "story.md").write_text(story_text, encoding="utf-8")

    if not cfg.has_section("cms"):
        cfg.add_section("cms")
    cfg.set("cms", "last_id", str(next_id_num))
    write_config(cfg_path, cfg)

    print(entry_id)
    print(f"Created: {entry_dir}")
    print(f"Assets:  {assets_dir}")
    print(f"Kind:    {entry_kind}")
    print(f"Title:   {entry_title}")
    print(f"Updated {cfg_path}: last_id = {next_id_num}")
    print("\nNext:")
    print(f"cd {entry_dir}")


if __name__ == "__main__":
    main()
