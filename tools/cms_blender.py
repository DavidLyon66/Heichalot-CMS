# tools/cms_blender.py
import configparser
import os
from pathlib import Path

CONFIG_PATH = Path.home() / ".heichalotcms" / "config.ini"

def _read_config():
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(str(CONFIG_PATH))
    return cfg

def _find_entry_from_path(p: Path):
    p = p.resolve()
    for parent in [p] + list(p.parents):
        # match .../<repo>/cms/entry-xxxx
        if parent.name.startswith("entry-") and parent.parent.name == "cms":
            return parent
    return None

def get_entry_dir(prefer_blend=True, entry_id=None):
    """
    Returns Path to cms/<entry-id>.

    prefer_blend: if True, use the saved .blend path to locate the entry.
    entry_id: optional explicit entry id, e.g. "entry-0000002"
    """
    # 1) Try derive from .blend location (when saved)
    if prefer_blend:
        try:
            import bpy
            blend_path = bpy.data.filepath
        except Exception:
            blend_path = ""
        if blend_path:
            found = _find_entry_from_path(Path(blend_path))
            if found:
                return found

    # 2) If explicit entry_id provided, use project_root from config
    cfg = _read_config()
    project_root = None
    if cfg.has_section("cms") and cfg.has_option("cms", "project_root"):
        project_root = Path(cfg.get("cms", "project_root")).expanduser()

    if entry_id and project_root:
        candidate = (project_root / "cms" / entry_id).resolve()
        if candidate.is_dir():
            return candidate
        raise RuntimeError(f"Entry not found: {candidate}")

    # 3) Last attempt: if current working directory is inside an entry (rare in Blender, but possible)
    found = _find_entry_from_path(Path.cwd())
    if found:
        return found

    # 4) Fail with instructions
    raise RuntimeError(
        "Could not determine cms entry directory.\n"
        "- Save the .blend somewhere under <project_root>/cms/<entry-id>/ (recommended), or\n"
        "- Add [cms] project_root=... to ~/.heichalotcms/config.ini and pass entry_id.\n"
        f"Config path: {CONFIG_PATH}"
    )

def get_assets_dir(entry_dir: Path):
    assets = entry_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    return assets

def get_story_path(entry_dir: Path):
    return entry_dir / "story.md"