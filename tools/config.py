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
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
import re
import unicodedata
import yaml
import json
from typing import Any
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Confirm, Prompt
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

console = Console()

APP_NAME = "HeichalotCMS"
APP_DISPLAY_NAME = "Heichalot CMS"
APP_SLUG = "heichalotcms"
APP_DESCRIPTION = "Heichalot Content Management System"
APP_BUNDLE_ID = "tech.heichalot.cms"
APP_PROGRAM_CANDIDATES = ("heichalot-cms.exe", "src/heichalot-cms.py")
CONFIG_FILENAME = "config.ini"
CONFIG_TEMPLATE_NAME = "config.ini.j2"

CONFIG_DIR = Path(__file__).resolve().parent

_PATH_MAP = {
    "cms": "cms_dir",
    "data": "data_dir",
    "cache": "cache_dir",
    "downloads": "download_dir",
    "project": "project_root",
    "config": "config_dir",
}

def _find_location_file() -> Path:
    """Locate the shared location catalogue from any supported config.py copy."""
    candidates = [
        CONFIG_DIR / "data" / "locations-en.yaml",
        CONFIG_DIR.parent / "data" / "locations-en.yaml",
        CONFIG_DIR.parent / "server-side" / "data" / "locations-en.yaml",
        CONFIG_DIR.parent / "src" / "data" / "locations-en.yaml",
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    # Preserve the historically expected path in the eventual error message.
    return candidates[0]


LOCATION_FILE = _find_location_file()

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
    override = os.environ.get("HEICHALOT_CONFIG", "").strip()

    if override:
        return Path(override).expanduser().resolve()

    return platform_config_dir() / CONFIG_FILENAME

def default_config_path() -> Path:
    override = os.environ.get("HEICHALOT_CONFIG", "").strip()

    if override:
        return Path(override).expanduser().resolve()

    for path in platform_config_paths():
        if path.exists():
            return path

    return platform_config_dir() / CONFIG_FILENAME
    

def default_user_cms_dir() -> Path:
    return Path.home() / "Documents" / "Heichalot-CMS" / "cms"

def find_application_program(project_root: str | Path) -> Path | None:
    """Find the preferred desktop entry point in a checkout.

    The packaged Windows executable deliberately wins when both forms are
    present.  A source checkout falls back to ``heichalot-cms.py``.  We do
    not discover or record a Python/Conda interpreter here: a user running
    the source form is responsible for having the .py entry point runnable
    on their operating system.
    """
    root = expand_path(project_root)

    for name in APP_PROGRAM_CANDIDATES:
        candidate = root / name
        if candidate.is_file():
            return candidate

    return None


def _required_application_program(project_root: str | Path) -> Path:
    program = find_application_program(project_root)
    if program is not None:
        return program

    names = ", ".join(APP_PROGRAM_CANDIDATES)
    raise FileNotFoundError(
        f"Cannot register {APP_DISPLAY_NAME}: none of these application "
        f"entry points exists in {expand_path(project_root)}: {names}"
    )


def _find_application_icon(project_root: str | Path) -> Path | None:
    """Return a likely application icon if one is present in the checkout."""
    root = expand_path(project_root)
    candidates = (
        root / "server-side" / "icons" / "heichalot-cms.png",
        root / "server-side" / "icons" / "heichalotcms.png",
        root / "icons" / "heichalot-cms.png",
        root / "icons" / "heichalotcms.png",
        root / "heichalot-cms.png",
    )

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


def _desktop_exec_quote(value: str | Path) -> str:
    """Quote one Desktop Entry Exec argument without invoking a shell."""
    text = str(value)
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("`", "\\`")
    text = text.replace("$", "\\$")
    return f'"{text}"'


def create_linux_application_entry(project_root: str | Path) -> Path:
    """Register Heichalot CMS in the current Linux user's application menu.

    Native executables are launched directly.  Source checkouts use the
    system ``python3`` command to launch ``src/heichalot-cms.py`` so the
    generated Python file itself does not need to be marked executable.
    """
    program = _required_application_program(project_root)
    icon = _find_application_icon(project_root)

    if program.suffix.lower() == ".py":
        exec_line = f"python3 {_desktop_exec_quote(program)}"
        try_exec = "python3"
    else:
        exec_line = _desktop_exec_quote(program)
        try_exec = str(program)

    applications_dir = Path(
        os.environ.get(
            "XDG_DATA_HOME",
            str(Path.home() / ".local" / "share"),
        )
    ).expanduser() / "applications"
    applications_dir.mkdir(parents=True, exist_ok=True)

    desktop_path = applications_dir / "heichalot-cms.desktop"
    lines = [
        "[Desktop Entry]",
        "Version=1.0",
        "Type=Application",
        f"Name={APP_DISPLAY_NAME}",
        f"Comment={APP_DESCRIPTION}",
        f"Exec={exec_line}",
        f"TryExec={try_exec}",
        "Terminal=false",
        "Categories=Office;Development;Utility;",
        "StartupNotify=true",
    ]
    if icon is not None:
        lines.insert(7, f"Icon={icon}")

    desktop_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    desktop_path.chmod(0o755)
    return desktop_path


def register_windows_application(project_root: str | Path) -> str:
    r"""Register Heichalot CMS for the current Windows user.

    This follows Microsoft's per-user App Paths registration model::

        HKCU\Software\Microsoft\Windows\CurrentVersion\App Paths\<program>

    The default REG_SZ value is the fully-qualified path to the discovered
    application entry point.  ``heichalot.exe`` wins over
    ``heichalot-cms.py``.  In source checkouts the .py path is registered
    directly; this function deliberately does not locate Python or Conda.

    Per-user HKCU registration avoids requiring administrator privileges and
    avoids modifying the global PATH.
    """
    if os.name != "nt":
        raise OSError("Windows application registration is only available on Windows")

    import winreg

    program = _required_application_program(project_root)
    key_path = (
        "Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\"
        + program.name
    )

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        key_path,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(
            key,
            "",
            0,
            winreg.REG_SZ,
            str(program),
        )

    return rf"HKCU\{key_path}"


def create_macos_application_entry(project_root: str | Path) -> Path:
    """Create a minimal per-user macOS .app wrapper around the entry point.

    This is intentionally lightweight bootstrap integration rather than a
    packaged installer.  The wrapper executes the discovered program
    directly and does not try to discover a Python/Conda interpreter.
    """
    import plistlib
    import shlex

    program = _required_application_program(project_root)
    app_path = Path.home() / "Applications" / f"{APP_DISPLAY_NAME}.app"
    contents = app_path / "Contents"
    macos_dir = contents / "MacOS"
    macos_dir.mkdir(parents=True, exist_ok=True)

    launcher_name = APP_SLUG
    launcher_path = macos_dir / launcher_name
    launcher_path.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(str(program))} \"$@\"\n",
        encoding="utf-8",
    )
    launcher_path.chmod(0o755)

    plist = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleDisplayName": APP_DISPLAY_NAME,
        "CFBundleExecutable": launcher_name,
        "CFBundleIdentifier": APP_BUNDLE_ID,
        "CFBundleName": APP_DISPLAY_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1",
        "CFBundleShortVersionString": "1.0",
    }
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(plist, handle)

    return app_path


def install_platform_integration(project_root: str | Path) -> Path | str:
    """Register the current checkout as an application for this user.

    Linux creates ``~/.local/share/applications/heichalot-cms.desktop`` (or
    the XDG_DATA_HOME equivalent).  Windows writes the per-user App Paths
    registry key documented by Microsoft.  macOS creates a small .app bundle
    in ``~/Applications``.  This function must only be called after explicit
    user approval.
    """
    if os.name == "nt":
        return register_windows_application(project_root)
    if sys.platform == "darwin":
        return create_macos_application_entry(project_root)
    if sys.platform.startswith("linux"):
        return create_linux_application_entry(project_root)

    raise OSError(f"Application registration is not supported on {sys.platform!r}")


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


def install_initial_config(
    cms_dir: str | Path,
    config_path: Optional[Path] = None,
    *,
    project_root: Optional[Path] = None,
    data_dir: Optional[Path] = None,
) -> configparser.ConfigParser:
    """Create the initial config without prompting.

    This is intended for GUI/web first-run setup. Nothing is written until
    the caller has obtained explicit user approval.
    """
    cfg_path = expand_path(config_path or default_config_path())
    cms_root = expand_path(cms_dir)
    project_root = expand_path(project_root or Path.cwd())
    data_root = expand_path(data_dir or platform_data_dir())

    cfg = render_config_template(
        project_root=project_root,
        cms_dir=cms_root,
        data_dir=data_root,
    )
    ensure_config_defaults(cfg)
    write_config(cfg, cfg_path)
    ensure_directories(cfg, cfg_path)
    return cfg


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


def ensure_config(config_path: Path) -> configparser.ConfigParser:
    cfg_path = expand_path(config_path)

    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Heichalot-CMS is not configured yet: {cfg_path}"
        )

    cfg = read_config(cfg_path)
    ensure_config_defaults(cfg)
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

def resolve_config_path(config_path: Optional[str | Path] = None) -> Path:
    if config_path:
        return expand_path(config_path)
    return default_config_path()

def load_app_config(
    config_path: Optional[str | Path] = None,
    *,
    setup_if_missing: bool = True,
) -> tuple[configparser.ConfigParser, Path, HeichalotPaths]:
    cfg_path = resolve_config_path(config_path)

    if setup_if_missing:
        cfg = ensure_config(cfg_path)
    else:
        cfg = read_config(cfg_path)
        ensure_config_defaults(cfg)

    paths = resolve_paths(cfg, cfg_path)
    return cfg, cfg_path, paths

def platform_config_paths() -> list[Path]:
    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return [
            Path(appdata) / "HeichalotCMS" / CONFIG_FILENAME,
            Path(appdata) / "heichalotcms" / CONFIG_FILENAME,
        ]

    if sys.platform == "darwin":
        return [
            Path.home() / "Library" / "Application Support" / "HeichalotCMS" / CONFIG_FILENAME,
            Path.home() / "Library" / "Application Support" / "heichalotcms" / CONFIG_FILENAME,
            Path.home() / ".heichalotcms" / CONFIG_FILENAME,
        ]

    return [
        Path.home() / ".heichalotcms" / CONFIG_FILENAME,
    ]


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

def resolve_path(name: str) -> Path:
    try:
        attribute_name = _PATH_MAP[name]
    except KeyError as exc:
        valid_names = ", ".join(sorted(_PATH_MAP))
        raise ValueError(
            f"Unknown path name {name!r}. Valid names: {valid_names}"
        ) from exc

    cfg = read_config()
    paths = resolve_paths(cfg)

    return getattr(paths, attribute_name)
        
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

    llm = detect_llm_system(cfg)

    if not llm["installed"]:
        llm_status = "Not installed"
        model_status = "Unavailable"

    elif not llm["service_running"]:
        llm_status = (
            f"Ollama installed at {llm['executable']}; "
            f"service unavailable at {llm['base_url']}"
        )
        model_status = str(llm["model"])

    else:
        llm_status = (
            f"Ollama  {llm['executable']}, "
            f"{llm['base_url']}"
        )

        configured_model = str(llm["model"])
        installed_models = {
            str(name).split(":", 1)[0]
            for name in llm.get("models", [])
        }

        if configured_model in installed_models:
            model_status = f"{configured_model}  installed"
        else:
            model_status = f"{configured_model}  not installed"

    table.add_row("LLM System", llm_status)
    table.add_row("LLM Model", model_status)

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
        
def install_default_model(cfg: configparser.ConfigParser) -> bool:
    llm = detect_llm_system(cfg)

    if not llm["installed"]:
        console.print(
            "[red]Ollama is not installed.[/red]"
        )
        return False

    if not llm["service_running"]:
        console.print(
            "[red]Ollama is installed but not running.[/red]"
        )
        return False

    model = str(llm["model"]).strip()
    models = {
        str(name).split(":", 1)[0]
        for name in llm.get("models", [])
    }

    if model in models:
        console.print(
            f"[green]Model already installed:[/green] {model}"
        )
        return True

    console.print(
        f"[cyan]Installing Ollama model:[/cyan] {model}"
    )

    payload = json.dumps({
        "model": model,
        "stream": True,
    }).encode("utf-8")

    request = urllib.request.Request(
        f"{llm['base_url']}/api/pull",
        data=payload,
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=3600,
        ) as response:

            for raw_line in response:
                line = raw_line.decode(
                    "utf-8",
                    errors="replace",
                ).strip()

                if not line:
                    continue

                data = json.loads(line)

                status = data.get("status", "")
                completed = data.get("completed")
                total = data.get("total")

                if completed is not None and total:
                    percent = (completed / total) * 100
                    console.print(
                        f"\r{status}: {percent:5.1f}%",
                        end="",
                    )
                elif status:
                    console.print(status)

    except Exception as exc:
        console.print(
            f"[red]Model installation failed:[/red] {exc}"
        )
        return False

    console.print()
    console.print(
        f"[green]Installed model:[/green] {model}"
    )

    return True
    

def get_cms_dir(cfg: configparser.ConfigParser, config_path: Optional[Path] = None) -> Path:
    return resolve_paths(cfg, config_path).cms_dir


def get_project_root(cfg: configparser.ConfigParser, config_path: Optional[Path] = None) -> Path:
    return resolve_paths(cfg, config_path).project_root

def get_story_filename(cfg: configparser.ConfigParser) -> str:
    return get_value(cfg, "cms", "story_filename", "story.md")


def get_current_entry(cfg: configparser.ConfigParser) -> str:
    return get_value(cfg, "cms", "current_entry", "")

def get_template_path(cfg: configparser.ConfigParser, template_name: Optional[str] = None) -> Path:
    name = template_name or get_value(cfg, "new_entry", "template", "story.md.j2")
    return template_dir() / name


def get_entry_prefix(cfg: configparser.ConfigParser) -> str:
    return get_value(cfg, "new_entry", "entry_prefix", "entry-")


def get_entry_pad_width(cfg: configparser.ConfigParser) -> int:
    try:
        return cfg.getint("new_entry", "pad_width", fallback=7)
    except ValueError:
        return 7


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

_LOCATION_YAML = """
regions:
  asia:
    label: Asia
    places:
      japan:
        label: Japan
        aliases: [japan, nippon]
        towns:
          tokyo:
            label: Tokyo
            aliases: [tokyo]
            centre:
              lat: 35.6764
              lon: 139.6500
              reference: Tokyo Station
            radius_km: 35

          kyoto:
            label: Kyoto
            aliases: [kyoto]
            centre:
              lat: 35.0116
              lon: 135.7681
              reference: Kyoto City Hall
            radius_km: 18

          kobe:
            label: Kobe
            aliases: [kobe]
            centre:
              lat: 34.6901
              lon: 135.1955
              reference: Kobe City Hall
            radius_km: 18

      thailand:
        label: Thailand
        aliases: [thailand, siam]
        towns:
          bangkok:
            label: Bangkok
            aliases: [bangkok, krung thep]
            centre:
              lat: 13.7563
              lon: 100.5018
              reference: Bangkok City Hall
            radius_km: 30

          ayutthaya:
            label: Ayutthaya
            aliases: [ayutthaya, phra nakhon si ayutthaya]
            centre:
              lat: 14.3532
              lon: 100.5689
              reference: Ayutthaya city centre
            radius_km: 10

      indonesia:
        label: Indonesia
        aliases: [indonesia, dutch east indies]
        towns:
          semarang:
            label: Semarang
            aliases: [semarang]
            centre:
              lat: -6.9667
              lon: 110.4167
              reference: Semarang city centre
            radius_km: 18

          jakarta:
            label: Jakarta
            aliases: [jakarta, batavia]
            centre:
              lat: -6.1754
              lon: 106.8272
              reference: Jakarta city centre
            radius_km: 30

          surabaya:
            label: Surabaya
            aliases: [surabaya]
            centre:
              lat: -7.2575
              lon: 112.7521
              reference: Surabaya city centre
            radius_km: 20

  australia:
    label: Australia
    aliases: [australia]
    places:
      new-south-wales:
        label: New South Wales
        aliases: [new south wales, nsw]
        towns:
          sydney:
            label: Sydney
            aliases: [sydney, sydney nsw]
            centre:
              lat: -33.8732
              lon: 151.2069
              reference: Sydney Town Hall
            radius_km: 35

          newcastle:
            label: Newcastle
            aliases: [newcastle, newcastle nsw]
            centre:
              lat: -32.9272
              lon: 151.7727
              reference: Newcastle City Hall
            radius_km: 15

          wollongong:
            label: Wollongong
            aliases: [wollongong]
            centre:
              lat: -34.4278
              lon: 150.8931
              reference: Wollongong Town Hall
            radius_km: 15

          bondi:
            label: Bondi
            aliases: [bondi, bondi junction, bondi beach]
            centre:
              lat: -33.8915
              lon: 151.2767
              reference: Bondi Junction
            radius_km: 6

          ballarat:
            label: Ballarat
            aliases: [ballarat]
            centre:
              lat: -37.5621
              lon: 143.8503
              reference: Ballarat Hebrew Congregation
            radius_km: 12
"""


def _normalise_location_text(value: str | None) -> str:
    """Return a conservative comparison form for imperfect location text."""

    if not value:
        return ""

    value = unicodedata.normalize("NFKC", str(value)).casefold()
    value = value.replace("&", " and ")

    # Convert punctuation and separators to spaces.
    value = re.sub(r"[/_,;:|()\[\]{}]+", " ", value)
    value = re.sub(r"[-–—]+", " ", value)

    # Remove remaining punctuation, but retain letters and numbers.
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip()

    return value


def _haversine_km(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
) -> float:
    """Calculate the approximate great-circle distance in kilometres."""

    earth_radius_km = 6371.0088

    lat_1 = radians(latitude_1)
    lon_1 = radians(longitude_1)
    lat_2 = radians(latitude_2)
    lon_2 = radians(longitude_2)

    delta_lat = lat_2 - lat_1
    delta_lon = lon_2 - lon_1

    value = (
        sin(delta_lat / 2) ** 2
        + cos(lat_1) * cos(lat_2) * sin(delta_lon / 2) ** 2
    )

    return 2 * earth_radius_km * asin(sqrt(value))


@lru_cache(maxsize=1)
def _load_location_catalogue() -> dict[str, Any]:
    """Load and validate the external location catalogue once."""

    _location_debug(f"loading catalogue: {LOCATION_FILE}")
    catalogue = load_location_catalogue()
    regions = catalogue.get("regions")
    _location_debug(f"catalogue regions: {list(regions or {})}")

    if not isinstance(regions, dict):
        raise ValueError(
            f"{LOCATION_FILE} must contain a 'regions' mapping"
        )

    return regions
    
@lru_cache(maxsize=1)
def _build_location_records() -> tuple[dict[str, Any], ...]:
    """Compile the maintained YAML tree into one flat record per node."""

    records: list[dict[str, Any]] = []

    def add_record(
        *,
        key: str,
        node: dict[str, Any],
        kind: str,
        path_keys: tuple[str, ...],
        path_labels: tuple[str, ...],
        region_key: str | None = None,
        region_label: str | None = None,
        place_key: str | None = None,
        place_label: str | None = None,
        town_key: str | None = None,
        town_label: str | None = None,
    ) -> None:
        label = str(node.get("label", key))
        aliases = {
            _normalise_location_text(key),
            _normalise_location_text(label),
        }
        aliases.update(
            _normalise_location_text(alias)
            for alias in node.get("aliases", [])
        )

        centre = node.get("centre") or {}
        centre_lat = centre.get("lat")
        centre_lon = centre.get("lon")

        records.append(
            {
                "key": key,
                "label": label,
                "kind": kind,
                "aliases": frozenset(filter(None, aliases)),
                "path_keys": path_keys,
                "path_labels": path_labels,
                "region_key": region_key,
                "region_label": region_label,
                "place_key": place_key,
                "place_label": place_label,
                "town_key": town_key,
                "town_label": town_label,
                "centre_lat": float(centre_lat) if centre_lat is not None else None,
                "centre_lon": float(centre_lon) if centre_lon is not None else None,
                "reference": centre.get("reference"),
                "radius_km": float(node.get("radius_km", 0) or 0),
            }
        )

    for region_key, region in _load_location_catalogue().items():
        if not isinstance(region, dict):
            continue

        region_label = str(region.get("label", region_key))
        add_record(
            key=region_key,
            node=region,
            kind="region",
            path_keys=(region_key,),
            path_labels=(region_label,),
            region_key=region_key,
            region_label=region_label,
        )

        for place_key, place in (region.get("places") or {}).items():
            if not isinstance(place, dict):
                continue

            place_label = str(place.get("label", place_key))
            add_record(
                key=place_key,
                node=place,
                kind="place",
                path_keys=(region_key, place_key),
                path_labels=(region_label, place_label),
                region_key=region_key,
                region_label=region_label,
                place_key=place_key,
                place_label=place_label,
            )

            for town_key, town in (place.get("towns") or {}).items():
                if not isinstance(town, dict):
                    continue

                town_label = str(town.get("label", town_key))
                add_record(
                    key=town_key,
                    node=town,
                    kind="town",
                    path_keys=(region_key, place_key, town_key),
                    path_labels=(region_label, place_label, town_label),
                    region_key=region_key,
                    region_label=region_label,
                    place_key=place_key,
                    place_label=place_label,
                    town_key=town_key,
                    town_label=town_label,
                )

    return tuple(records)


@lru_cache(maxsize=1)
def _build_location_lookup() -> dict[str, tuple[dict[str, Any], ...]]:
    """Map every normalized key, label and alias to candidate records."""

    lookup: dict[str, list[dict[str, Any]]] = {}

    for record in _build_location_records():
        for alias in record["aliases"]:
            lookup.setdefault(alias, []).append(record)

    return {
        alias: tuple(candidates)
        for alias, candidates in lookup.items()
    }


def _split_location_components(location_text: str | None) -> list[str]:
    """Split CMS location paths while preserving multi-word place names."""

    if not location_text:
        return []

    return [
        component.strip()
        for component in str(location_text).split("/")
        if component.strip()
    ]


def _record_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": record["key"],
        "label": record["label"],
        "kind": record["kind"],
        "path_keys": list(record["path_keys"]),
        "path_labels": list(record["path_labels"]),
    }


def _choose_component_candidate(
    candidates: tuple[dict[str, Any], ...],
    established_search_keys: set[str],
) -> dict[str, Any] | None:
    """Use already-resolved path context to narrow duplicate names."""

    if len(candidates) == 1:
        return candidates[0]

    compatible = [
        record
        for record in candidates
        if established_search_keys.intersection(record["path_keys"])
    ]

    if len(compatible) == 1:
        return compatible[0]

    return None


def _make_component_result(
    matched_records: list[dict[str, Any]],
    components: list[dict[str, Any]],
    *,
    original_text: str | None,
    unmatched_components: list[str],
    ambiguous_components: list[dict[str, Any]],
    match_method: str = "component-lookup",
    confidence: float = 1.0,
    distance_km: float | None = None,
) -> dict[str, Any]:
    """Create the public result from independently resolved path components."""

    search_keys: set[str] = set()
    matched_keys: list[str] = []

    for record in matched_records:
        matched_keys.append(record["key"])
        search_keys.update(record["path_keys"])

    deepest = max(matched_records, key=lambda record: len(record["path_keys"]))

    status = "matched"
    if ambiguous_components and not matched_records:
        status = "ambiguous"

    result = {
        "status": status,
        "match_method": match_method,
        "confidence": confidence,
        "original_text": original_text,
        "components": components,
        "matched_keys": matched_keys,
        "search_keys": sorted(search_keys),
        "unmatched_components": unmatched_components,
        "ambiguous_components": ambiguous_components,
        # Compatibility fields retained while server and templates migrate.
        "region_key": deepest.get("region_key"),
        "region_label": deepest.get("region_label"),
        "place_key": deepest.get("place_key"),
        "place_label": deepest.get("place_label"),
        "town_key": deepest.get("town_key"),
        "town_label": deepest.get("town_label"),
        "centre_lat": deepest.get("centre_lat"),
        "centre_lon": deepest.get("centre_lon"),
        "reference": deepest.get("reference"),
        "radius_km": deepest.get("radius_km"),
    }

    if distance_km is not None:
        result["distance_km"] = round(distance_km, 3)

    return result


def resolve_location(
    location_text: str | None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict[str, Any]:
    """
    Resolve slash-delimited CMS location components against a flat alias index.

    The catalogue remains a tree for maintenance. At runtime every node is
    indexed by key, label and aliases. Each slash-delimited component is looked
    up independently, and every matched node contributes its complete ancestry
    to ``search_keys``.
    """

    original_text = location_text
    lookup = _build_location_lookup()
    raw_components = _split_location_components(location_text)
    _location_debug(
        f"resolve input={location_text!r} components={raw_components!r} "
        f"lookup_aliases={len(lookup)}"
    )

    matched_records: list[dict[str, Any]] = []
    component_results: list[dict[str, Any]] = []
    unmatched_components: list[str] = []
    ambiguous_components: list[dict[str, Any]] = []
    established_search_keys: set[str] = set()

    for component in raw_components:
        normalised = _normalise_location_text(component)
        candidates = lookup.get(normalised, ())
        chosen = _choose_component_candidate(candidates, established_search_keys)
        _location_debug(
            f"component={component!r} normalised={normalised!r} "
            f"candidates={[record['path_keys'] for record in candidates]!r} "
            f"chosen={(chosen or {}).get('path_keys')!r}"
        )

        if chosen is not None:
            matched_records.append(chosen)
            established_search_keys.update(chosen["path_keys"])
            component_results.append(
                {
                    "text": component,
                    "normalised": normalised,
                    "status": "matched",
                    **_record_summary(chosen),
                }
            )
        elif candidates:
            detail = {
                "text": component,
                "normalised": normalised,
                "status": "ambiguous",
                "candidates": [_record_summary(record) for record in candidates],
            }
            ambiguous_components.append(detail)
            component_results.append(detail)
        else:
            unmatched_components.append(component)
            component_results.append(
                {
                    "text": component,
                    "normalised": normalised,
                    "status": "unmatched",
                }
            )

    if matched_records:
        return _make_component_result(
            matched_records,
            component_results,
            original_text=original_text,
            unmatched_components=unmatched_components,
            ambiguous_components=ambiguous_components,
        )

    # Compatibility fallback for non-slash prose such as
    # "near Bondi Junction" or separator variants used by older entries.
    normalised_text = _normalise_location_text(location_text)
    if normalised_text:
        text_matches: list[tuple[int, dict[str, Any]]] = []

        for alias, candidates in lookup.items():
            if not _contains_phrase(normalised_text, alias):
                continue
            for record in candidates:
                text_matches.append((len(alias), record))

        if text_matches:
            longest = max(length for length, _ in text_matches)
            candidates = tuple(
                record for length, record in text_matches if length == longest
            )
            chosen = _choose_component_candidate(candidates, set())

            if chosen is not None:
                return _make_component_result(
                    [chosen],
                    [
                        {
                            "text": original_text,
                            "normalised": normalised_text,
                            "status": "matched",
                            **_record_summary(chosen),
                        }
                    ],
                    original_text=original_text,
                    unmatched_components=[],
                    ambiguous_components=[],
                    match_method="compound-text",
                    confidence=0.92,
                )

    # GPS applies only to records with coordinates and a positive radius.
    if latitude is not None and longitude is not None:
        try:
            latitude_value = float(latitude)
            longitude_value = float(longitude)
        except (TypeError, ValueError):
            return {
                "status": "unresolved",
                "reason": "invalid-gps",
                "original_text": original_text,
                "components": component_results,
                "matched_keys": [],
                "search_keys": [],
                "unmatched_components": unmatched_components,
                "ambiguous_components": ambiguous_components,
                "latitude": latitude,
                "longitude": longitude,
            }

        gps_matches: list[tuple[float, dict[str, Any]]] = []
        for record in _build_location_records():
            if (
                record["centre_lat"] is None
                or record["centre_lon"] is None
                or record["radius_km"] <= 0
            ):
                continue

            distance = _haversine_km(
                latitude_value,
                longitude_value,
                record["centre_lat"],
                record["centre_lon"],
            )
            if distance <= record["radius_km"]:
                gps_matches.append((distance, record))

        gps_matches.sort(key=lambda item: item[0])
        if gps_matches:
            nearest_distance, nearest_record = gps_matches[0]
            if len(gps_matches) == 1 or gps_matches[1][0] - nearest_distance >= 2.0:
                return _make_component_result(
                    [nearest_record],
                    component_results,
                    original_text=original_text,
                    unmatched_components=unmatched_components,
                    ambiguous_components=ambiguous_components,
                    match_method="gps-nearest",
                    confidence=0.85,
                    distance_km=nearest_distance,
                )

            return {
                "status": "ambiguous",
                "match_method": "gps-radius",
                "original_text": original_text,
                "components": component_results,
                "matched_keys": [],
                "search_keys": [],
                "unmatched_components": unmatched_components,
                "ambiguous_components": ambiguous_components,
                "candidates": [
                    {
                        **_record_summary(record),
                        "distance_km": round(distance, 3),
                        "radius_km": record["radius_km"],
                    }
                    for distance, record in gps_matches
                ],
            }

    if ambiguous_components:
        return {
            "status": "ambiguous",
            "match_method": "component-lookup",
            "original_text": original_text,
            "components": component_results,
            "matched_keys": [],
            "search_keys": [],
            "unmatched_components": unmatched_components,
            "ambiguous_components": ambiguous_components,
        }

    return {
        "status": "unresolved",
        "reason": "no-match",
        "original_text": original_text,
        "normalised_text": _normalise_location_text(location_text),
        "components": component_results,
        "matched_keys": [],
        "search_keys": [],
        "unmatched_components": unmatched_components,
        "ambiguous_components": [],
        "latitude": latitude,
        "longitude": longitude,
    }


def normalise_location_filter(value: str | None) -> str:
    """Return the canonical key form used by location filters."""

    value = _normalise_location_text(value)
    return re.sub(r"\s+", "-", value).strip("-")


def location_filter_keys(value: str | None) -> set[str]:
    """Resolve a user-supplied location or alias into canonical filter keys."""

    fallback = normalise_location_filter(value)
    if not fallback:
        return set()

    resolved = resolve_location(value)
    matched = {
        normalise_location_filter(key)
        for key in resolved.get("matched_keys", ())
        if key
    }

    return matched or {fallback}


def location_search_keys_match(
    search_keys: Iterable[str] | None,
    wanted_location: str | None,
) -> bool:
    """Return whether flattened entry search keys match a location filter."""

    wanted_keys = location_filter_keys(wanted_location)
    if not wanted_keys:
        return True

    available = {
        normalise_location_filter(key)
        for key in (search_keys or ())
        if key
    }
    return bool(available.intersection(wanted_keys))


def location_matches(
    location_text: str | None,
    wanted_location: str | None,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
) -> bool:
    """Resolve entry location text and test it against a location filter."""

    if not normalise_location_filter(wanted_location):
        return True

    resolved = resolve_location(
        location_text,
        latitude=latitude,
        longitude=longitude,
    )
    return location_search_keys_match(
        resolved.get("search_keys", ()),
        wanted_location,
    )

def kind_matches(entry_kind, wanted_kind, type_map):
    if not wanted_kind:
        return True

    entry = str(entry_kind).strip().casefold()
    wanted = str(wanted_kind).strip().casefold()

    # short -> long
    wanted = type_map.get(wanted, wanted)

    # long -> short
    reverse = {v.casefold(): k.casefold() for k, v in type_map.items()}

    return (
        entry == wanted
        or entry == reverse.get(wanted, "")
    )
    

TIMEFRAME_CHOICES = ("ancient", "past", "present", "future")


def normalise_timeframe(value: str | None) -> str | None:
    """Return a validated broad timeframe name."""

    if value is None:
        return None

    timeframe = str(value).strip().casefold()
    if not timeframe:
        return None

    if timeframe not in TIMEFRAME_CHOICES:
        choices = ", ".join(TIMEFRAME_CHOICES)
        raise ValueError(
            f"Unknown timeframe {value!r}; expected one of: {choices}"
        )

    return timeframe


def _timeframe_bool(value: object) -> bool:
    """Interpret common YAML/config representations of a boolean."""

    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0

    return str(value).strip().casefold() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def _timeframe_year(entry: object) -> int | None:
    """Extract a subject year from a mapping or entry-like object."""

    if isinstance(entry, dict):
        raw_year = entry.get("year")
        raw_date = entry.get("datetime") or entry.get("date")
    else:
        raw_year = getattr(entry, "year", None)
        raw_date = (
            getattr(entry, "datetime", None)
            or getattr(entry, "date", None)
        )

    if raw_year not in (None, ""):
        try:
            return int(str(raw_year).strip())
        except (TypeError, ValueError):
            return None

    if raw_date in (None, ""):
        return None

    match = re.match(r"^\s*(-?\d{1,6})", str(raw_date))
    if not match:
        return None

    try:
        return int(match.group(1))
    except ValueError:
        return None


def matches_timeframe(
    entry: object,
    timeframe: str | None,
    *,
    current_year: int | None = None,
) -> bool:
    """
    Match one of the four deliberately broad editorial timeframes.

    ``ancient`` is at least 1,500 years before the current year.
    ``past`` is older than the five-year present window but not ancient.
    ``present`` covers the current year and previous five years.
    ``future`` requires an explicit ``futurist: true`` marker.
    """

    wanted = normalise_timeframe(timeframe)
    if wanted is None:
        return True

    if isinstance(entry, dict):
        futurist = _timeframe_bool(entry.get("futurist"))
    else:
        futurist = _timeframe_bool(getattr(entry, "futurist", False))

    if wanted == "future":
        return futurist

    # Keep the four buckets non-overlapping.
    if futurist:
        return False

    year = _timeframe_year(entry)
    if year is None:
        return False

    if current_year is None:
        from datetime import datetime
        current_year = datetime.now().year

    ancient_cutoff = current_year - 1500
    present_start = current_year - 5

    if wanted == "ancient":
        return year <= ancient_cutoff
    if wanted == "past":
        return ancient_cutoff < year < present_start
    if wanted == "present":
        return present_start <= year <= current_year

    return False


def _contains_phrase(text: str, phrase: str) -> bool:
    """Match a normalized phrase on word boundaries."""

    if not phrase:
        return False

    pattern = rf"(?:^|\s){re.escape(phrase)}(?:$|\s)"
    return re.search(pattern, text) is not None


@lru_cache(maxsize=1)
def load_location_catalogue() -> dict[str, Any]:
    with LOCATION_FILE.open(
        "r",
        encoding="utf-8",
    ) as handle:
        catalogue = yaml.safe_load(handle) or {}

    regions = catalogue.get("regions")

    if not isinstance(regions, dict):
        raise ValueError(
            f"{LOCATION_FILE} does not contain a regions mapping"
        )

    return catalogue

def _location_debug(message: str) -> None:
    """Write location diagnostics when explicitly enabled."""

    enabled = os.environ.get(
        "HEICHALOT_LOCATION_DEBUG",
        "",
    ).strip().lower()

    if enabled in {"1", "true", "yes", "on"}:
        print(
            f"[location-debug/config] {message}",
            file=sys.stderr,
        )

def detect_llm_system(
    cfg: configparser.ConfigParser | None = None,
) -> dict[str, object]:
    """
    Detect the configured local LLM system.

    This currently supports Ollama only. Installation, service
    availability, and installed models are reported separately.
    """

    if cfg is None:
        cfg = read_config()

    base_url = cfg.get(
        "ollama-interface",
        "base_url",
        fallback="http://localhost:11434",
    ).strip().rstrip("/")

    model = cfg.get(
        "ollama-interface",
        "model",
        fallback="gemma3",
    ).strip()

    executable = shutil.which("ollama")

    result: dict[str, object] = {
        "system": "ollama",
        "installed": executable is not None,
        "executable": executable,
        "base_url": base_url,
        "model": model,
        "service_running": False,
        "models": [],
        "configured_model_present": False,
        "error": None,
    }

    if executable is None:
        return result

    try:
        with urlopen(
            f"{base_url}/api/tags",
            timeout=1.5,
        ) as response:
            data = json.load(response)

        models = [
            str(item.get("name", "")).strip()
            for item in data.get("models", [])
            if item.get("name")
        ]

        result["service_running"] = True
        result["models"] = models

        configured_model = model.casefold()

        result["configured_model_present"] = any(
            installed.casefold() == configured_model
            or installed.casefold().split(":", 1)[0] == configured_model
            for installed in models
        )

    except Exception as exc:
        result["error"] = str(exc)

    return result
                
def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Create or inspect Heichalot-CMS configuration.")
    parser.add_argument("--config", help="Override config path")
    parser.add_argument("--setup", action="store_true", help="Run first-time setup")
    parser.add_argument("--show", action="store_true", help="Show resolved paths")
    parser.add_argument(
        "--register-application",
        action="store_true",
        help="Create or repair per-user OS application registration",
    )
    args = parser.parse_args()

    cfg_path = expand_path(args.config) if args.config else default_config_path()

    # Default action is --show
    show_requested = args.show or not (args.setup or args.register_application)

    if args.setup:
        run_first_time_setup(cfg_path)
        return 0

    if args.register_application:
        cfg = read_config(cfg_path)
        paths = resolve_paths(cfg, cfg_path)
        registered = install_platform_integration(paths.project_root)
        console.print(f"[green]Application registration:[/green] {registered}")
        return 0

    if show_requested:
        show_config_status(cfg_path)
        return 0

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
    

