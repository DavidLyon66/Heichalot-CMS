# tools/cms.py
from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import os
import sys

try:
    import yaml  # pyyaml
except Exception:
    yaml = None

# from tools.cms import CMSFile

ALLOWED_IMAGE_KEYS = {"basemap", "regions", "roads", "water"}
SEARCH_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}

PX_TO_M = 1.0                           # 1 px = 1 m
PLANE_NAME = "GROUND_PLANE"
MAT_NAME = "MAT_GROUND_MAP"

# -----------------------------
# Config path (MATCH setcmscontext.py)
# -----------------------------
def default_config_path() -> Path:
    # Linux (as requested)
    if sys.platform.startswith("linux"):
        return Path.home() / ".heichalotcms" / "config.ini"

    # macOS
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "heichalotcms" / "config.ini"

    # Windows
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            appdata = str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "heichalotcms" / "config.ini"

    # Fallback
    return Path.home() / ".heichalotcms" / "config.ini"


def read_config(path: Optional[Path] = None) -> Tuple[Path, ConfigParser]:
    cfg_path = (path or default_config_path()).expanduser().resolve()
    cfg = ConfigParser()
    if cfg_path.exists():
        cfg.read(str(cfg_path))
    return cfg_path, cfg


def write_config(cfg: ConfigParser, path: Optional[Path] = None) -> Path:
    cfg_path = (path or default_config_path()).expanduser().resolve()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        cfg.write(f)
    return cfg_path


def require_project_root(cfg: ConfigParser, cfg_path: Optional[Path] = None) -> Path:
    cfg_path = cfg_path or default_config_path()
    if not cfg.has_section("cms") or not cfg.has_option("cms", "project_root"):
        raise RuntimeError(f"Missing [cms] project_root in {cfg_path}")
    return Path(cfg.get("cms", "project_root")).expanduser().resolve()


def get_current_entry(cfg: ConfigParser) -> Optional[str]:
    if cfg.has_section("cms") and cfg.has_option("cms", "current_entry"):
        v = cfg.get("cms", "current_entry").strip()
        return v or None
    return None

def set_current_entry(cfg: ConfigParser, entry_id: str) -> None:
    if not cfg.has_section("cms"):
        cfg.add_section("cms")
    cfg.set("cms", "current_entry", entry_id)

# -----------------------------
# Locating the original basemap
# -----------------------------

def _find_single_basemap_candidate(entry_dir: Path) -> Path:
    candidates = [p for p in entry_dir.iterdir()
                  if p.is_file() and p.suffix.lower() in SEARCH_EXTS]

    if len(candidates) == 0:
        raise RuntimeError(
            f"No basemap candidate found:\n  {entry_dir}\n"
            "Put ONE basemap image in entry directory/ (png/jpg/tif) OR set base_map in story.md."
        )
    if len(candidates) > 1:
        msg = "Multiple image candidates in entry directory/. For first import, leave only ONE, or set base_map:\n"
        for p in candidates:
            msg += f"  - {p.name}\n"
        raise RuntimeError(msg)

    return candidates[0]

# -----------------------------
# New entry rules + counter
# -----------------------------
def get_new_entry_rules(cfg: ConfigParser) -> Tuple[str, int, str, str]:
    """
    Returns: (entry_prefix, pad_width, cms_dir_name, template_name)
    All optional; sensible defaults if absent.
    """
    prefix = "entry-"
    pad_width = 7
    cms_dir_name = "cms"
    template_name = "story.md.j2"

    if cfg.has_section("new_entry"):
        prefix = cfg.get("new_entry", "entry_prefix", fallback=prefix)
        pad_width = cfg.getint("new_entry", "pad_width", fallback=pad_width)
        cms_dir_name = cfg.get("new_entry", "cms_dir", fallback=cms_dir_name)
        template_name = cfg.get("new_entry", "template", fallback=template_name)

    return prefix, pad_width, cms_dir_name, template_name


def get_last_id(cfg: ConfigParser) -> int:
    if cfg.has_section("cms") and cfg.has_option("cms", "last_id"):
        try:
            return int(cfg.get("cms", "last_id"))
        except ValueError:
            return 0
    return 0


def set_last_id(cfg: ConfigParser, last_id: int) -> None:
    if not cfg.has_section("cms"):
        cfg.add_section("cms")
    cfg.set("cms", "last_id", str(int(last_id)))


def next_entry_id(cfg: ConfigParser) -> str:
    prefix, pad_width, _, _ = get_new_entry_rules(cfg)
    n = get_last_id(cfg) + 1
    return f"{prefix}{n:0{pad_width}d}"

# -----------------------------
# CMS entry object
# -----------------------------
@dataclass
class CMSFile:
    project_root: Path
    entry_dir: Path
    cfg_path: Optional[Path] = None

    @property
    def entry_id(self) -> str:
        return self.entry_dir.name

    @property
    def story_path(self) -> Path:
        return self.entry_dir / "story.md"

    @property
    def assets_dir(self) -> Path:
        p = self.entry_dir / "assets"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def assets_path(self, filename: str) -> Path:
        return self.assets_dir / filename

    # ---------- locating ----------
    @staticmethod
    def find_entry_dir_from_path(p: Path) -> Optional[Path]:
        p = p.resolve()
        for parent in [p] + list(p.parents):
            if parent.name.startswith("entry-") and parent.parent.name == "cms":
                return parent
        return None

    @staticmethod
    def normalize_entry_id(entry_id, cfg: ConfigParser) -> str:
        """
        Accept:
            3
            "3"
            "entry-0000003"

        Return canonical form:
            entry-0000003
        """

        prefix, pad_width, _, _ = get_new_entry_rules(cfg)

        # Already canonical
        if isinstance(entry_id, str) and entry_id.startswith(prefix):
            return entry_id

        # Convert to integer
        try:
            n = int(entry_id)
        except Exception:
            raise ValueError(f"Invalid entry_id: {entry_id}")

        return f"{prefix}{n:0{pad_width}d}"

    @staticmethod
    def from_entry_id(entry_id, cfg_path: Optional[Path] = None) -> "CMSFile":
        cfg_path2, cfg = read_config(cfg_path)
        project_root = require_project_root(cfg, cfg_path2)

        entry_id = CMSFile.normalize_entry_id(entry_id, cfg)

        _, _, cms_dir_name, _ = get_new_entry_rules(cfg)

        entry_dir = (project_root / cms_dir_name / entry_id).resolve()

        if not entry_dir.is_dir():
            raise FileNotFoundError(f"Entry directory not found: {entry_dir}")

        return CMSFile(project_root=project_root, entry_dir=entry_dir, cfg_path=cfg_path2)

    @staticmethod
    def from_cwd_or_config(entry_id: Optional[str] = None) -> "CMSFile":
        """
        Resolution order:
          1) explicit entry_id (best for CLI from repo root)
          2) current working directory inside cms/<entry-id> (good when user cd's there)
          3) config.ini cms.current_entry (useful for Blender/unsaved sessions)
        """
        
        cfg_path2, cfg = read_config(default_config_path())
        project_root = require_project_root(cfg, cfg_path2)
        _, _, cms_dir_name, _ = get_new_entry_rules(cfg)

        if entry_id:
            return CMSFile.from_entry_id(entry_id, cfg_path=cfg_path2)
        else:
            prefix, pad_width, _, _ = get_new_entry_rules(cfg)
            entry_id = f"{prefix}{n:0{pad_width}d}"

        found = CMSFile.find_entry_dir_from_path(Path.cwd())
        if found:
            return CMSFile(project_root=project_root, entry_dir=found, cfg_path=cfg_path2)

        cur = get_current_entry(cfg)
        if cur:
            entry_dir = (project_root / cms_dir_name / cur).resolve()
            if entry_dir.is_dir():
                return CMSFile(project_root=project_root, entry_dir=entry_dir, cfg_path=cfg_path2)

        raise RuntimeError(
            "Could not determine cms entry directory.\n"
            "- Run with --entry-id entry-xxxxxxx, OR\n"
            "- Run from within cms/<entry-id>/, OR\n"
            "- Set [cms] current_entry in config.ini."
        )

    # ---------- story read/write ----------
    def read_story_metadata(self) -> Dict[str, Any]:
        if not self.story_path.exists():
            return {}
        text = self.story_path.read_text(encoding="utf-8")
        meta, _ = _split_story_frontmatter(text)
        return meta

    def read_story_body(self) -> str:
        if not self.story_path.exists():
            return ""
        text = self.story_path.read_text(encoding="utf-8")
        _, body = _split_story_frontmatter(text)
        return body

    def read_story(self) -> Tuple[Dict[str, Any], str]:
        """
        Returns (metadata, body)
        """
        if not self.story_path.exists():
            return {}, ""
        text = self.story_path.read_text(encoding="utf-8")
            return _split_story_frontmatter(text)

    def _split_story_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
        """
        Returns (metadata_dict, markdown_body)

        If no frontmatter is present, returns ({}, full_text).
        """
        if yaml is None:
            raise RuntimeError("PyYAML not installed. Install with: pip install pyyaml")

        m = FRONTMATTER_RE.match(text)
        if not m:
            return {}, text

        meta_text = m.group(1)
        body = text[m.end():]

        data = yaml.safe_load(meta_text) or {}
        if not isinstance(data, dict):
            raise RuntimeError("story.md frontmatter must be a YAML mapping.")

        return data, body

    def write_story(self, metadata: Dict[str, Any], body: str = "") -> None:
        if yaml is None:
            raise RuntimeError("PyYAML not installed. Install with: pip install pyyaml")

        frontmatter = yaml.safe_dump(
            metadata,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=100,
        ).strip()

        text = f"---\n{frontmatter}\n---\n"
        if body:
            if not body.startswith("\n"):
                text += "\n"
            text += body

        self.story_path.write_text(text, encoding="utf-8")

    def update_story(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        metadata, body = self.read_story()
        metadata.update(patch)
        self.write_story(metadata, body)
        return metadata

    def ensure_story_exists(self) -> None:
        if not self.story_path.exists():
            self.write_story({}, "# Title\n\nWrite the story here.\n")

    # ---------- common metadata helpers ----------
    def remember_asset(self, key: str, filename: str) -> None:
        data = self.read_story()
        ga = data.get("generated_assets")
        if not isinstance(ga, dict):
            ga = {}
        ga[key] = filename
        data["generated_assets"] = ga
        self.write_story(data)

    def set_base_map_if_missing(self, filename: str) -> None:
        data = self.read_story()
        if not data.get("base_map"):
            data["base_map"] = filename
            self.write_story(data)

    # ---------- basemap resolution ----------
    def resolve_basemap_path(
        self,
        cli_image: Optional[str] = None,
        copy_into_assets_as: Optional[str] = None,
        require_exists: bool = True,
    ) -> Path:
        """
        Rules:
          - If cli_image provided:
              use that path (relative to entry_dir or absolute).
              If story.base_map missing, set it (optionally copying into assets).
          - Else:
              if story.base_map set: use assets/<base_map>
              else:
                  try assets/basemap.png then assets/basemap.jpg
                  else error (if require_exists)

        If copy_into_assets_as is provided AND cli_image is provided:
          copy the file into assets/<copy_into_assets_as> and use that.
          (This is optional; many times you'll want to keep original filename.)
        """
        data = self.read_story()
        base_map = (data.get("base_map") or "").strip() if isinstance(data.get("base_map"), str) else ""

        # Helper to ensure a path is under assets for story references
        def _assets_ref(path_in_assets: Path) -> Path:
            return path_in_assets

        # 1) CLI image wins
        if cli_image:
            p = Path(cli_image)
            if not p.is_absolute():
                # allow running from entry dir or repo root; interpret relative to entry_dir
                p = (self.entry_dir / p).resolve()
            if require_exists and not p.exists():
                raise FileNotFoundError(f"Basemap image not found: {p}")

            if copy_into_assets_as:
                dest = (self.assets_dir / copy_into_assets_as).resolve()
                if p.resolve() != dest:
                    dest.write_bytes(p.read_bytes())
                # store story reference if missing
                self.set_base_map_if_missing(dest.name)
                return dest

            # If user gave a file already inside assets, store its name
            try:
                rel = p.resolve().relative_to(self.assets_dir.resolve())
                self.set_base_map_if_missing(rel.as_posix())
            except Exception:
                # Otherwise store the filename only (assumes user will copy later) OR leave unset.
                # Minimal behavior: store only if missing, using the basename.
                self.set_base_map_if_missing(p.name)

            return p

        # 2) Story base_map
        if base_map:
            candidate = (self.assets_dir / base_map).resolve()
            if require_exists and not candidate.exists():
                raise FileNotFoundError(f"story.md base_map points to missing file: {candidate}")
            return candidate

        # 3) Defaults in assets
        for fn in ("basemap.png", "basemap.jpg", "basemap.jpeg"):
            candidate = (self.assets_dir / fn).resolve()
            if candidate.exists():
                self.set_base_map_if_missing(fn)
                return candidate

        if require_exists:
            raise FileNotFoundError(
                "No basemap found. Provide an image filename or place basemap.png/jpg in assets/ "
                "or set base_map in story.md."
            )

        # If not required, return the preferred default location
        return (self.assets_dir / "basemap.png").resolve()

# -----------------------------
# Misc helpers useful to tools
# -----------------------------
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _create_ground_plane_with_uv(img_path: Path):
    import bpy

    img = bpy.data.images.load(str(img_path), check_existing=True)
    w_px, h_px = img.size[0], img.size[1]
    w_m, h_m = w_px * PX_TO_M, h_px * PX_TO_M

    old = bpy.data.objects.get(PLANE_NAME)
    if old:
        bpy.data.objects.remove(old, do_unlink=True)

    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.0, 0.0, 0.0))
    plane = bpy.context.active_object
    plane.name = PLANE_NAME
    plane.dimensions = (w_m, h_m, 0.0)

    mesh = plane.data
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")
    uv_layer = mesh.uv_layers.active.data

    verts = mesh.vertices
    min_x = min(v.co.x for v in verts)
    max_x = max(v.co.x for v in verts)
    min_y = min(v.co.y for v in verts)
    max_y = max(v.co.y for v in verts)

    for poly in mesh.polygons:
        for li in poly.loop_indices:
            vi = mesh.loops[li].vertex_index
            v = verts[vi].co
            u = (v.x - min_x) / (max_x - min_x) if max_x != min_x else 0.0
            vv = (v.y - min_y) / (max_y - min_y) if max_y != min_y else 0.0
            uv_layer[li].uv = (u, vv)

    mat = bpy.data.materials.get(MAT_NAME)
    if mat is None:
        mat = bpy.data.materials.new(MAT_NAME)
    mat.use_nodes = True

    nt = mat.node_tree
    nodes = nt.nodes
    links = nt.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Linear"

    tex.location = (-400, 200)
    bsdf.location = (-150, 200)
    out.location = (120, 200)

    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    if plane.data.materials:
        plane.data.materials[0] = mat
    else:
        plane.data.materials.append(mat)

    print(f"Created {PLANE_NAME}: {w_m}m x {h_m}m from {img_path.name}")
    print("Tip: Viewport -> Material Preview OR Solid shading dropdown -> Color=Texture")
    return plane


def main():
#   cms = CMSFile.from_cwd_or_config(entry_id=args.entry_id)

    cms = CMSFile.from_entry_id(3)
    
    story = cms.read_story()

    #if RESET_BASEMAP:
    #    story["base_map"] = ""
    #    cms.write_story(story)
    #    print("Reset base_map in story.md")

    base_map = (story.get("base_map") or "").strip() if isinstance(story.get("base_map"), str) else ""

    # Case A: base_map already set -> use it, don't guess
    if base_map:
        img_path = (cms.assets_dir / base_map).resolve()
        if not img_path.exists():
            raise RuntimeError(
                f"story.md base_map is set to '{base_map}' but file does not exist:\n  {img_path}\n"
                "Fix by placing the file in assets/, or clear base_map to re-auto-detect."
            )
        _create_ground_plane_with_uv(img_path)
        print("Rebuilt ground plane from story.md base_map.")
        return

    # Case B: base_map not set -> auto-detect ONE candidate, store, proceed
    candidate = _find_single_basemap_candidate(cms.entry_dir)
    print("Auto-detected basemap candidate:", candidate)

    # dest = _copy_into_assets(cms, candidate)

    # Set base_map now that we have a canonical copy in assets/
    story["base_map"] = os.path.basename(candidate)
    cms.write_story(story)
    print(f"Updated story.md base_map: {os.path.basename(candidate)}")

    _create_ground_plane_with_uv(dest)
    print("Imported basemap and created ground plane.")

    
main()
