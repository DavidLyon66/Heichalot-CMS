#!/usr/bin/env python3
from pathlib import Path
import argparse
import sys
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(TOOLS_DIR))

from config import (
    load_app_config,
    get_entry_prefix,
    get_entry_pad_width,
    get_template_path,
    get_last_id,
    set_last_id,
    resolve_entry_kind,
)


def prompt_if_missing(val: str | None, prompt_text: str) -> str:
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

def entry_type_defaults(cfg, entry_type: str) -> dict:
    entry_type = str(entry_type).strip().casefold()
    kind = resolve_entry_kind(cfg, entry_type)

    defaults = {
        "kind": kind,
    }

    if entry_type == "rv":
        defaults.update({
            "kind": "remote_viewing",
            "tags": ["remote-viewing"],
            "status": "Draft",
        })

    elif entry_type == "st":
        defaults.update({
            "kind": "historic_site",
            "tags": ["historic-site"],
            "status": "Draft",
        })

    elif entry_type == "v":
        defaults.update({
            "kind": "video",
            "tags": ["video"],
            "status": "Draft",
        })

    return defaults
    
def create_entry(
    entry_type: str,
    fields: dict | None = None,
    *,
    config_path: str | Path | None = None,
    prefix: str | None = None,
    pad_width: int | None = None,
) -> tuple[str, Path, Path]:

    cfg, resolved_config_path, paths = load_app_config(config_path)

    cms_dir = paths.cms_dir
    cms_dir.mkdir(parents=True, exist_ok=True)

    resolved_prefix = prefix or get_entry_prefix(cfg)
    resolved_pad = pad_width or get_entry_pad_width(cfg)

    last_id = get_last_id(cfg)
    next_id_num = last_id + 1
    entry_id = f"{resolved_prefix}{next_id_num:0{resolved_pad}d}"

    entry_dir = (cms_dir / entry_id).resolve()

    if entry_dir.exists():
        raise FileExistsError(f"Entry already exists: {entry_dir}")

    final_fields = build_entry_fields(
        cfg,
        entry_type,
        fields,
    )

    now = datetime.now(timezone.utc)

    final_fields["entry_id"] = entry_id
    final_fields["created_utc"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    final_fields["entry_type"] = entry_type

    if not final_fields.get("year"):
        final_fields["year"] = now.year

    if not final_fields.get("datetime"):
        final_fields["datetime"] = (
            f"{int(final_fields['year']):04d}-01-01"
        )

    template_path = get_template_path(cfg)

    if not template_path.exists():
        raise FileNotFoundError(
            f"Template not found: {template_path}"
        )

    images_dir = entry_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=False)

    story_path = entry_dir / "story.md"

    story_text = render_story(
        template_path,
        final_fields,
    )

    story_path.write_text(
        story_text,
        encoding="utf-8",
    )

    set_last_id(
        cfg,
        next_id_num,
        resolved_config_path,
    )

    return entry_id, entry_dir, story_path
    

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Create a new CMS entry directory using the Heichalot-CMS config."
    )
    ap.add_argument("entry_type", nargs="?", help="Short entry type code such as n, rv, v, yt, st")
    ap.add_argument("title", nargs="?", help="Entry title")
    ap.add_argument("--location", help="Location text")
    ap.add_argument("--year", type=int, help="Year only, e.g. 1857")
    ap.add_argument("--config", default=None, help="Optional override path to config.ini")
    ap.add_argument("--prefix", default=None, help="Entry prefix override")
    ap.add_argument("--pad", type=int, default=None, help="Numeric padding width override")
    args = ap.parse_args()

    cfg, cfg_path, paths = load_app_config(args.config)

    cms_dir = paths.cms_dir
    cms_dir.mkdir(parents=True, exist_ok=True)

    prefix = args.prefix or get_entry_prefix(cfg)
    pad_width = args.pad or get_entry_pad_width(cfg)

    last_id = get_last_id(cfg)
    next_id_num = last_id + 1
    entry_id = f"{prefix}{next_id_num:0{pad_width}d}"
    entry_dir = (cms_dir / entry_id).resolve()

    if entry_dir.exists():
        raise SystemExit(f"ERROR: Entry already exists: {entry_dir}")

    images_dir = entry_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    template_path = get_template_path(cfg)
    if not template_path.exists():
        raise SystemExit(f"ERROR: Template not found: {template_path}")

    entry_kind = resolve_entry_kind(cfg, args.entry_type)

    entry_title = (
        args.title.strip()
        if args.title
        else cfg.get("new_entry", "default_title", fallback="Title")
    )

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

    story_text = render_story(
        template_path,
        {
            "entry_id": entry_id,
            "created_utc": created_utc,
            "location_text": location_text,
            "datetime": datetime_iso,
            "year": year_val,
            "kind": entry_kind,
            "title": entry_title,
            "entry_type": args.entry_type or "",
            "base_map": "",
        },
    )

    (entry_dir / "story.md").write_text(story_text, encoding="utf-8")

    set_last_id(cfg, next_id_num, cfg_path)

    print(entry_id)
    print(f"Created: {entry_dir}")
    print(f"Images:  {images_dir}")
    print(f"Kind:    {entry_kind}")
    print(f"Title:   {entry_title}")
    print(f"Updated {cfg_path}: last_id = {next_id_num}")
    print("\nNext:")
    print(f"cd {entry_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
