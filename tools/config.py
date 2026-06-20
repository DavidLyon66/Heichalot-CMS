#!/usr/bin/env python3
"""
Heichalot-CMS configuration support.

Responsibilities:
- choose OS-appropriate config/data locations
- create first-run config.ini
- load/save config.ini
- expose common project paths
- keep individual tools from guessing paths independently
"""

from __future__ import annotations

import configparser
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Confirm, Prompt

console = Console()

APP_NAME = "HeichalotCMS"
APP_SLUG = "heichalotcms"
CONFIG_FILENAME = "config.ini"
CONFIG_TEMPLATE_NAME = "config.ini.j2"

@dataclass(frozen=True)
class HeichalotPaths:
    config_path: Path
    config_dir: Path
    data_dir: Path
    cache_dir: Path
    cms_dir: Path
    download_dir: Path
    project_root: Path


def expand_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def platform_config_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME

    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_SLUG

    return Path.home() / ".config" / APP_SLUG


def platform_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_SLUG

    return Path.home() / ".local" / "share" / APP_SLUG


def default_config_path() -> Path:
    return platform_config_dir() / CONFIG_FILENAME

def default_user_cms_dir() -> Path:
    return Path.home() / "Documents" / "heichalot-cms" / "cms"

def read_config(path: Optional[Path] = None) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg_path = expand_path(path or default_config_path())
    if cfg_path.exists():
        cfg.read(cfg_path, encoding="utf-8")
    return cfg


def write_config(cfg: configparser.ConfigParser, path: Optional[Path] = None) -> Path:
    cfg_path = expand_path(path or default_config_path())
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg_path.open("w", encoding="utf-8") as f:
        cfg.write(f)
    return cfg_path


def config_exists(path: Optional[Path] = None) -> bool:
    return expand_path(path or default_config_path()).exists()


def get_value(
    cfg: configparser.ConfigParser,
    section: str,
    option: str,
    fallback: str,
) -> str:
    if cfg.has_section(section) and cfg.has_option(section, option):
        value = cfg.get(section, option).strip()
        if value:
            return value
    return fallback


def set_default(cfg: configparser.ConfigParser, section: str, option: str, value: str) -> None:
    if not cfg.has_section(section):
        cfg.add_section(section)
    if not cfg.has_option(section, option) or not cfg.get(section, option).strip():
        cfg.set(section, option, value)


def build_default_config(
    *,
    project_root: Optional[Path] = None,
    cms_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()

    data_root = expand_path(data_dir or platform_data_dir())
    cms_root = expand_path(cms_dir or default_user_cms_dir())

    if project_root is None:
        project_root = Path.cwd()

    project_root = expand_path(project_root)

    cfg["cms"] = {
        "project_root": str(project_root),
        "cms_dir": str(cms_root),
        "current_entry": "",
        "last_id": "0",
        "story_filename": "story.md",
    }

    cfg["paths"] = {
        "data_dir": str(data_root),
        "download_dir": str(data_root / "downloads"),
        "cache_dir": str(data_root / "cache"),
    }

    cfg["server"] = {
        "public_url": "https://heichalot.tech/cms/public/",
        "subscriber_url": "https://heichalot.tech/cms/subscriber/",
        "channel": "public",
        "email": "",
    }

    cfg["new_entry"] = {
        "entry_prefix": "entry-",
        "pad_width": "7",
        "default_kind": "note",
        "default_title": "Title",
        "template": "story.md.j2",
    }

    cfg["entry_types"] = {
        "n": "note",
        "rv": "remote-viewing",
        "vd": "video",
        "yt": "youtube",
        "st": "site",
    }

    cfg["tags"] = {
        "default_story_tags": "",
    }

    cfg["addaistory"] = {
        "image_mode": "move",
    }

    return cfg

def template_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def config_template_path() -> Path:
    return template_dir() / CONFIG_TEMPLATE_NAME


def render_config_template(
    *,
    project_root: Path,
    cms_dir: Path,
    data_dir: Path,
) -> configparser.ConfigParser:
    template_path = config_template_path()

    if not template_path.exists():
        # Safe fallback while developing.
        return build_default_config(
            project_root=project_root,
            cms_dir=cms_dir,
            data_dir=data_dir,
        )

    try:
        from jinja2 import Environment, FileSystemLoader
    except Exception as exc:
        raise SystemExit("ERROR: jinja2 not installed. Install with: pip install jinja2") from exc

    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        keep_trailing_newline=True,
        autoescape=False,
    )

    rendered = env.get_template(template_path.name).render(
        project_root=str(project_root),
        cms_dir=str(cms_dir),
        data_dir=str(data_dir),
        download_dir=str(data_dir / "downloads"),
        cache_dir=str(data_dir / "cache"),
    )

    cfg = configparser.ConfigParser()
    cfg.read_string(rendered)
    return cfg

def prompt_path(label: str, default: Path) -> Path:
    value = Prompt.ask(
        f"[bold cyan]{label}[/bold cyan]",
        default=str(default),
    ).strip()
    return expand_path(value)


def run_first_time_setup(config_path: Optional[Path] = None) -> configparser.ConfigParser:
    cfg_path = expand_path(config_path or default_config_path())

    existing = cfg_path.exists()

    if existing:
        cfg = read_config(cfg_path)
        ensure_config_defaults(cfg)
        existing_paths = resolve_paths(cfg, cfg_path)
    else:
        cfg = configparser.ConfigParser()
        existing_paths = None

    console.print()
    console.print(
        Panel(
            f"[bold]Config file:[/bold]\n{cfg_path}",
            title="Heichalot-CMS Setup",
            expand=False,
        )
    )

    if existing:
        console.print("[green]Existing configuration found.[/green]")
        console.print("[dim]Press Enter to keep the current value.[/dim]\n")

    default_cms_dir = (
        existing_paths.cms_dir
        if existing_paths
        else default_user_cms_dir()
    )

    default_data_dir = (
        existing_paths.data_dir
        if existing_paths
        else platform_data_dir()
    )

    default_project_root = (
        existing_paths.project_root
        if existing_paths
        else Path.cwd()
    )

    cms_dir = prompt_path(
        "Where should your editable CMS entries be stored?",
        default_cms_dir,
    )

    data_dir = prompt_path(
        "Where should downloaded/cache data be stored?",
        default_data_dir,
    )

    project_root = prompt_path(
        "Where is the Heichalot-CMS project/tool directory?",
        default_project_root,
    )

    if existing:
        if not cfg.has_section("cms"):
            cfg.add_section("cms")
        if not cfg.has_section("paths"):
            cfg.add_section("paths")

        cfg.set("cms", "project_root", str(project_root))
        cfg.set("cms", "cms_dir", str(cms_dir))

        cfg.set("paths", "data_dir", str(data_dir))
        cfg.set("paths", "download_dir", str(data_dir / "downloads"))
        cfg.set("paths", "cache_dir", str(data_dir / "cache"))

        ensure_config_defaults(cfg)
    else:
        cfg = render_config_template(
            project_root=project_root,
            cms_dir=cms_dir,
            data_dir=data_dir,
        )

    table = Table(show_header=False, box=None)
    table.add_row("config", str(cfg_path))
    table.add_row("project", str(project_root))
    table.add_row("cms_dir", str(cms_dir))
    table.add_row("data_dir", str(data_dir))

    console.print()
    console.print(
        Panel(
            table,
            title="About to Save",
            expand=False,
        )
    )

    if not Confirm.ask("Save configuration?", default=True):
        raise SystemExit("Setup cancelled.")

    write_config(cfg, cfg_path)
    ensure_directories(cfg, cfg_path)

    console.print()
    console.print(f"[green]Wrote config:[/green] {cfg_path}")

    return cfg


def ensure_config(config_path: Optional[Path] = None) -> configparser.ConfigParser:
    cfg_path = expand_path(config_path or default_config_path())
    if not cfg_path.exists():
        return run_first_time_setup(cfg_path)

    cfg = read_config(cfg_path)
    ensure_config_defaults(cfg)
    write_config(cfg, cfg_path)
    ensure_directories(cfg, cfg_path)
    return cfg


def ensure_config_defaults(cfg: configparser.ConfigParser) -> None:
    defaults = build_default_config()

    for section in defaults.sections():
        if not cfg.has_section(section):
            cfg.add_section(section)
        for option, value in defaults.items(section):
            if not cfg.has_option(section, option):
                cfg.set(section, option, value)


def ensure_directories(cfg: configparser.ConfigParser, config_path: Optional[Path] = None) -> None:
    paths = resolve_paths(cfg, config_path)

    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.cache_dir.mkdir(parents=True, exist_ok=True)
    paths.download_dir.mkdir(parents=True, exist_ok=True)
    paths.cms_dir.mkdir(parents=True, exist_ok=True)

def legacy_config_paths() -> list[Path]:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return [
            Path(appdata) / "heichalotcms" / CONFIG_FILENAME,
            Path(appdata) / "HeichalotCMS" / CONFIG_FILENAME,
        ]

    if sys.platform == "darwin":
        return [
            Path.home() / "Library" / "Application Support" / "heichalotcms" / CONFIG_FILENAME,
            Path.home() / "Library" / "Application Support" / "HeichalotCMS" / CONFIG_FILENAME,
            Path.home() / ".heichalotcms" / CONFIG_FILENAME,
        ]

    return [
        Path.home() / ".heichalotcms" / CONFIG_FILENAME,
    ]


def default_config_path() -> Path:
    for path in legacy_config_paths():
        if path.exists():
            return path

    return platform_config_dir() / CONFIG_FILENAME


def resolve_paths(
    cfg: configparser.ConfigParser,
    config_path: Optional[Path] = None,
) -> HeichalotPaths:
    cfg_path = expand_path(config_path or default_config_path())

    project_root = expand_path(
        get_value(cfg, "cms", "project_root", str(Path.cwd()))
    )

    cms_dir = expand_path(
        get_value(cfg, "cms", "cms_dir", str(default_user_cms_dir()))
    )

    data_dir = expand_path(
        get_value(cfg, "paths", "data_dir", str(platform_data_dir()))
    )

    cache_dir = expand_path(
        get_value(cfg, "paths", "cache_dir", str(data_dir / "cache"))
    )

    download_dir = expand_path(
        get_value(cfg, "paths", "download_dir", str(data_dir / "downloads"))
    )

    return HeichalotPaths(
        config_path=cfg_path,
        config_dir=cfg_path.parent,
        data_dir=data_dir,
        cache_dir=cache_dir,
        cms_dir=cms_dir,
        download_dir=download_dir,
        project_root=project_root,
    )

def show_config_status(config_path: Optional[Path] = None) -> None:

    cfg_path = expand_path(config_path or default_config_path())
    exists = cfg_path.exists()

    if exists:
        cfg = read_config(cfg_path)
    else:
        cfg = build_default_config()

    paths = resolve_paths(cfg, cfg_path)

    table = Table(show_header=False, box=None)
    table.add_row("Config exists", "yes" if exists else "no")
    table.add_row("Config path", str(paths.config_path))
    table.add_row("Project root", str(paths.project_root) if exists else "")
    table.add_row("CMS dir", str(paths.cms_dir) if exists else "")
    table.add_row("Data dir", str(paths.data_dir) if exists else "")
    table.add_row("Download dir", str(paths.download_dir) if exists else "")
    table.add_row("Cache dir", str(paths.cache_dir) if exists else "")

    console.print()
    console.print(
        Panel(
            table,
            title="Heichalot-CMS Configuration",
            expand=False,
        )
    )

    if not exists:
        console.print()
        console.print("[yellow]No config.ini found.[/yellow]")
        console.print("Run setup with:")
        console.print("  [bold]heichalot-config --setup[/bold]")


def get_cms_dir(cfg: configparser.ConfigParser) -> Path:
    return resolve_paths(cfg).cms_dir


def get_project_root(cfg: configparser.ConfigParser) -> Path:
    return resolve_paths(cfg).project_root


def get_story_filename(cfg: configparser.ConfigParser) -> str:
    return get_value(cfg, "cms", "story_filename", "story.md")


def get_current_entry(cfg: configparser.ConfigParser) -> str:
    return get_value(cfg, "cms", "current_entry", "")


def set_current_entry(
    cfg: configparser.ConfigParser,
    entry_id_or_path: str,
    config_path: Optional[Path] = None,
) -> None:
    if not cfg.has_section("cms"):
        cfg.add_section("cms")
    cfg.set("cms", "current_entry", entry_id_or_path)
    write_config(cfg, config_path)


def get_last_id(cfg: configparser.ConfigParser) -> int:
    try:
        return cfg.getint("cms", "last_id", fallback=0)
    except ValueError:
        return 0


def set_last_id(
    cfg: configparser.ConfigParser,
    value: int,
    config_path: Optional[Path] = None,
) -> None:
    if not cfg.has_section("cms"):
        cfg.add_section("cms")
    cfg.set("cms", "last_id", str(value))
    write_config(cfg, config_path)


def resolve_entry_kind(cfg: configparser.ConfigParser, short_code: Optional[str]) -> str:
    if short_code is None or not str(short_code).strip():
        return get_value(cfg, "new_entry", "default_kind", "note")

    code = short_code.strip()

    if cfg.has_section("entry_types"):
        mapped = cfg.get("entry_types", code, fallback="").strip()
        if mapped:
            return mapped

    return code



def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Create or inspect Heichalot-CMS configuration.")
    parser.add_argument("--config", help="Override config path")
    parser.add_argument("--setup", action="store_true", help="Run first-time setup")
    parser.add_argument("--show", action="store_true", help="Show resolved paths")
    args = parser.parse_args()

    cfg_path = expand_path(args.config) if args.config else default_config_path()

    # Default action is --show
    show_requested = args.show or not args.setup

    if args.setup:
        run_first_time_setup(cfg_path)
        return 0

    if show_requested:
        show_config_status(cfg_path)
        return 0

    return 0

if __name__ == "__main__":
    raise SystemExit(main())