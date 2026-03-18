#!/usr/bin/env python3
"""
startproduction.py

Create a lightweight VideoRender production workspace for a CMS entry.

Usage:
    python tools/startproduction.py <cms-entry-id> <production-name>

Behavior:
- Reads ~/.heichalotcms/config.ini
- Uses [paths] productions_dir and cms_root
- Creates:
    <productions_dir>/<production-name>/
        video.md
        video.render.json
        assets/
        output/
        cms-entry -> <cms_root>/cms/entry-<id>
- Prefills files from Jinja2 templates if present:
    <cms_root>/tools/templates/video.md.j2
    <cms_root>/tools/templates/video.render.json.j2
- Falls back to built-in defaults if templates do not exist

Notes:
- Fails if the target production directory already exists
- Uses symlink for cms-entry on Unix-like systems
- Jinja2 is optional only if template files are absent; if .j2 templates exist,
  Jinja2 must be installed.
"""

from __future__ import annotations

import configparser
import json
import sys
from pathlib import Path
from typing import Any

try:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
except ImportError:
    Environment = None
    FileSystemLoader = None
    StrictUndefined = None


CONFIG_PATH = Path.home() / ".heichalotcms" / "config.ini"


DEFAULT_VIDEO_MD_TEMPLATE = """---
kind: video
entry_id: {{ entry_id }}
production_name: {{ production_name }}
renderer: remotion
---

# {{ production_title }}

[SHOW HERO IMAGE]

\"\"\"NARRATOR
Replace this with the opening narration for the production.
\"\"\"

[FADE TO EVIDENCE OVERLAY]

\"\"\"NARRATOR
Replace this with the next block of narration.
\"\"\"
"""

DEFAULT_VIDEO_RENDER_JSON_TEMPLATE = """{
  "entry_id": "{{ entry_id }}",
  "production_name": "{{ production_name }}",
  "renderer": "remotion",
  "duration": 30,
  "fps": 30,
  "events": []
}
"""


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def slug_to_title(text: str) -> str:
    parts = text.strip().replace("_", "-").split("-")
    return " ".join(p.capitalize() for p in parts if p)


def read_config(config_path: Path) -> tuple[Path, Path]:
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            "Create it with:\n"
            "[paths]\n"
            "productions_dir = /path/to/productions\n"
            "cms_root = /path/to/heichalotcms"
        )

    parser = configparser.ConfigParser()
    parser.read(config_path)

    if "video_renderer" not in parser:
        raise ValueError(f"Missing [video_renderer] section in {config_path}")

    productions_dir_raw = parser["video_renderer"].get("productions_dir", "").strip()
    cms_root_raw = parser["cms"].get("cms_dir", "").strip()

    if not productions_dir_raw:
        raise ValueError(f"Missing video_renderer.productions_dir in {config_path}")
    if not cms_root_raw:
        raise ValueError(f"Missing cms.cms_dir in {config_path}")

    productions_dir = Path(productions_dir_raw).expanduser().resolve()
    cms_root = Path(cms_root_raw).expanduser().resolve()

    return productions_dir, cms_root


def validate_production_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Production name must not be empty.")

    if cleaned in {".", ".."}:
        raise ValueError("Production name must not be '.' or '..'.")

    if "/" in cleaned or "\\" in cleaned:
        raise ValueError("Production name must not contain path separators.")

    return cleaned


def find_entry_dir(cms_root: Path, entry_id: str) -> Path:
    entry_dir = cms_root / f"entry-{entry_id}"
    if not entry_dir.exists():
        raise FileNotFoundError(f"CMS entry directory not found: {entry_dir}")
    if not entry_dir.is_dir():
        raise NotADirectoryError(f"CMS entry path is not a directory: {entry_dir}")
    return entry_dir


def build_template_context(entry_id: str, production_name: str) -> dict[str, Any]:
    return {
        "entry_id": entry_id,
        "production_name": production_name,
        "production_title": slug_to_title(production_name),
    }


def make_jinja_env(templates_dir: Path):
    if Environment is None or FileSystemLoader is None or StrictUndefined is None:
        raise ImportError(
            "Jinja2 is required for .j2 templates. Install it with:\n"
            "  pip install jinja2"
        )

    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=False,
        lstrip_blocks=False,
    )


def render_template_file(
    templates_dir: Path,
    template_name: str,
    context: dict[str, Any],
    fallback_template_text: str,
) -> str:
    template_path = templates_dir / template_name

    if template_path.exists():
        env = make_jinja_env(templates_dir)
        template = env.get_template(template_name)
        return template.render(**context)

    if Environment is None:
        raise ImportError(
            "Jinja2 is required even for built-in template rendering in this script.\n"
            "Install it with:\n"
            "  pip install jinja2"
        )

    env = Environment(
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=False,
        lstrip_blocks=False,
    )
    template = env.from_string(fallback_template_text)
    return template.render(**context)


def render_video_md(
    templates_dir: Path,
    entry_id: str,
    production_name: str,
) -> str:
    context = build_template_context(entry_id, production_name)
    return render_template_file(
        templates_dir=templates_dir,
        template_name="video.md.j2",
        context=context,
        fallback_template_text=DEFAULT_VIDEO_MD_TEMPLATE,
    )


def render_video_render_json(
    templates_dir: Path,
    entry_id: str,
    production_name: str,
) -> dict[str, Any]:
    context = build_template_context(entry_id, production_name)
    rendered = render_template_file(
        templates_dir=templates_dir,
        template_name="video.render.json.j2",
        context=context,
        fallback_template_text=DEFAULT_VIDEO_RENDER_JSON_TEMPLATE,
    )

    try:
        data = json.loads(rendered)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Rendered video.render.json.j2 is not valid JSON: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError("Rendered video.render.json must be a JSON object.")

    data.setdefault("entry_id", entry_id)
    data.setdefault("production_name", production_name)
    data.setdefault("renderer", "remotion")
    data.setdefault("duration", 30)
    data.setdefault("fps", 30)
    data.setdefault("events", [])

    return data


def safe_symlink(target: Path, link_path: Path) -> None:
    if link_path.exists() or link_path.is_symlink():
        raise FileExistsError(f"Refusing to overwrite existing link/path: {link_path}")

    try:
        link_path.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        raise OSError(
            f"Could not create symlink:\n"
            f"  link:   {link_path}\n"
            f"  target: {target}\n"
            f"{exc}"
        ) from exc


def create_production(
    entry_id: str,
    production_name: str,
    productions_dir: Path,
    cms_root: Path,
) -> Path:
    production_name = validate_production_name(production_name)
    entry_dir = find_entry_dir(cms_root, entry_id)

    target_dir = productions_dir / production_name
    if target_dir.exists():
        raise FileExistsError(f"Production directory already exists: {target_dir}")

    templates_dir = cms_root / "tools" / "templates"

    video_md = render_video_md(
        templates_dir=templates_dir,
        entry_id=entry_id,
        production_name=production_name,
    )

    video_render_json = render_video_render_json(
        templates_dir=templates_dir,
        entry_id=entry_id,
        production_name=production_name,
    )

    target_dir.mkdir(parents=True, exist_ok=False)
    (target_dir / "assets").mkdir()
    (target_dir / "output").mkdir()

    (target_dir / "video.md").write_text(video_md, encoding="utf-8")
    (target_dir / "video.render.json").write_text(
        json.dumps(video_render_json, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    safe_symlink(entry_dir, target_dir / "cms-entry")

    return target_dir


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        eprint("Usage:")
        eprint("  python tools/startproduction.py <cms-entry-id> <production-name>")
        return 2

    entry_id = argv[1].strip()
    production_name = argv[2].strip()

    if not entry_id:
        eprint("Error: cms-entry-id must not be empty.")
        return 2

    try:
        productions_dir, cms_root = read_config(CONFIG_PATH)
        productions_dir.mkdir(parents=True, exist_ok=True)

        production_dir = create_production(
            entry_id=entry_id,
            production_name=production_name,
            productions_dir=productions_dir,
            cms_root=cms_root,
        )

        print("Production created successfully.")
        print(f"Production directory: {production_dir}")
        print(f"Video script:         {production_dir / 'video.md'}")
        print(f"Render JSON:          {production_dir / 'video.render.json'}")
        print(f"Assets directory:     {production_dir / 'assets'}")
        print(f"Output directory:     {production_dir / 'output'}")
        print(f"CMS entry link:       {production_dir / 'cms-entry'}")
        return 0

    except Exception as exc:
        eprint(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))