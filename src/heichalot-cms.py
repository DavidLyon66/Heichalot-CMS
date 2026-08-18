from __future__ import annotations

import os
import sqlite3
import yaml
from pathlib import Path
from typing import Optional
from datetime import datetime
import configparser
from io import StringIO
import re
import fnmatch
import random
import json
import threading
import time
import webview
import base64
import sys


from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
    jsonify,
)

from werkzeug.security import check_password_hash, generate_password_hash


import sys
TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

APP_DIR = Path(__file__).resolve().parent

# Use the standard config module to resolve paths
from config import (load_app_config, 
                    resolve_location, 
                    read_config, 
                    default_config_path,
                    detect_llm_system)

try:
    _cfg, _cfg_path, _paths = load_app_config(setup_if_missing=False)
    _content_db = _paths.data_dir / "content.db"
except Exception:
    from config import platform_data_dir
    _content_db = platform_data_dir() / "content.db"

from createentry import create_entry
from rvpreview import generate_preview_images

from renderhtml import story_markdown_to_html

from remoteviewing import (
     generate_remote_view, 
     save_working_session_to_cms,
     load_working_session, 
     append_working_session,
     write_working_session,
     clear_working_session)


CONTENT_DB = _content_db

RVCRYPTO_DIR = Path(__file__).resolve().parent.parent / "rvcrypto"

if str(RVCRYPTO_DIR) not in sys.path:
    sys.path.insert(0, str(RVCRYPTO_DIR))

import wallet 

CRYPTO_AVAILABLE_LAYERS = [
    ("actionstatus", "Current trading action and price-zone status.",),
    ("collecthistory", "Historical daily price data for the asset.",),
    ("addchannel", "Trading channel definition and channel boundaries.",),
    ("today", "Current-day trading signal and channel status.",),
    ("breakdetect", "Detected breaks from the current trading structure.",),
    ("turndetect", "Detected or developing market turning points.", ),
    ("estimatetrades", "Estimated trading opportunities remaining in the current channel.",),
    ("volinfluence", "Volume influence on current price behaviour.", ),
    ("channelprojection", "Projected price path for the current channel.", ),
    ("graph", "Standard historical price graph.", ),
    ("volumespikedetect", "Detected unusual volume spikes.", ),
    ("channelswing", "Price swings detected within the current channel.", ),
    ("mmainfluence", "Moving-average influence on current price behaviour.", ),
    ("channelvolatility","Volatility characteristics of the current channel.", ),
    ("shapedetect", "Detected historical or projected channel shape.", ),
    ("whalecheck",  "Investigation of unusual market activity and possible large-participant influence.", ),
]


IMAGE_DIR = Path(os.environ.get("HEICHALOT_IMAGE_DIR", APP_DIR / "images")).expanduser()
PDF_DIR = Path(os.environ.get("HEICHALOT_PDF_DIR", APP_DIR / "pdfs")).expanduser()

CMS_UPDATE_DIR = Path(
    os.environ.get("HEICHALOT_CMS_UPDATE_DIR", APP_DIR / "content-updates")
).expanduser()



VALID_THEMES = {"light", "dark", "brown", "blue", "spaceship"}
VALID_LANGS = {"en", "he", "ja"}

STREAM_BUTTON_PALETTES = {
    "dark": [
        "#d88a2b",  # warm orange
        "#4f8cff",  # blue
        "#2f9d75",  # green
        "#9b6bd3",  # purple
        "#c75c5c",  # red muted
        "#b89b3c",  # gold
        "#4aa3a3",  # teal
    ],
    "light": [
        "#f4b860",
        "#6fa8dc",
        "#76a879",
        "#b58bd8",
        "#d77a7a",
        "#c9aa4a",
        "#64b6b6",
    ],
}

PER_PAGE = 20

def stream_colour(stream_name, theme="dark"):
    palette = STREAM_BUTTON_PALETTES.get(theme, STREAM_BUTTON_PALETTES["dark"])
    index = sum(ord(c) for c in (stream_name or "default")) % len(palette)
    return palette[index]

DEFAULT_USER_CONFIG = """
[streams]
painting.label = Painting
painting.visible = no
painting.description = House painting jobs, site visits, quotes, before/after photos

collection.label = Collection
collection.visible = no
collection.description = Paintings, art objects, historical artifacts

free.label = Free
free.visible = no

ljh-ostraliye.label = LJH Ostraliye
ljh-ostraliye.visible = Yes
ljh-ostraliye.description = These are entries that relate to the lost Jewish history of Australia.

ljh-asia.label = LJH Asia
ljh-asia.visible = yes
ljh-asia.description = These are entries that relate to the lost Jewish history of the Asian diaspora.

ljh-europe.label = LJH Europe
ljh-europe.visible = no
ljh-europe.description = These are entries that relate to the lost Jewish history of the Europe.

genesis-0.label = Genesis:0
genesis-0.visible = yes
genesis-0.description = These are entries that relate to the Genesis:0 version of Human History.

lsh-japan.label = ShinTo
lsh-japan.visible = yes
lsh-japan.description = These are entries that relate to lost ShinTo History of Japan.

disclosure-day.label = disclosure-day
disclosure-day.visible = yes
disclosure-day.description = These are recreations of the Disclosure Day Files.

remote-viewing.label = Remote-Viewing
remote-viewing.visible = Yes

crypto.label = Crypto
crypto.visible = yes
crypto.location = toolbar
crypto.colour = #A38658
crypto.description = Cryptocurrency research, market analysis and remote-viewing.

[theme]
name = brown
"""

app = Flask(__name__)
app.secret_key = os.environ.get("HEICHALOT_SECRET_KEY", "dev-change-this-secret-key")

# Exposed to every Jinja template through inject_globals().
# Only the hosted server presents account/login/registration controls.
SERVER_VARIANT = "desktop"
AUTH_UI_ENABLED = SERVER_VARIANT == "hosted"

def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def content_db() -> sqlite3.Connection:
    return connect(CONTENT_DB)


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}



def current_user() -> Optional[sqlite3.Row]:
    user_id = session.get("user_id")
    if not user_id:
        return None
    conn = members_db()
    try:
        return conn.execute(
            """
            SELECT user_id, email, access_level, is_active, created_utc, config
            FROM users
            WHERE user_id = ? AND is_active = 1
            """,
            (user_id,),
        ).fetchone()
    finally:
        conn.close()

def user_config(user) -> dict:
    if not user or "config" not in user.keys() or not user["config"]:
        return {}
    try:
        return yaml.safe_load(user["config"]) or {}
    except Exception:
        return {}

def current_lang() -> str:
    user = current_user()
    cfg = user_config(user)
    lang = str(cfg.get("lang", "en")).strip().lower()
    return lang if lang in VALID_LANGS else "en"

def current_theme() -> str:
    user = current_user()
    cfg = user_config_parser(user)

    theme = "dark"
    if cfg.has_section("theme"):
        theme = cfg.get("theme", "name", fallback="dark")

    theme = theme.strip().lower()
    return theme if theme in VALID_THEMES else "dark"


def select_html(row: sqlite3.Row, user_level: str) -> str:
    if user_level == "premium":
        return row["html_premium"] or row["html_members"] or row["html_free"] or ""
    if user_level == "members":
        return row["html_members"] or row["html_free"] or ""
    return row["html_free"] or ""

def require_admin():
    user = current_user()
    if not user or user["email"] not in ADMIN_EMAILS:
        abort(403)
    return user

def normalise_filter_value(value: object) -> str:
    """Return a stable case-insensitive comparison value."""
    value = str(value or "").strip().casefold()
    value = value.replace("_", "-")
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-")


def parse_tags(value) -> set[str]:
    """Parse YAML, sequence, newline-separated, or comma-separated tags."""
    if value in (None, ""):
        return set()

    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        raw = str(value).strip()
        if not raw:
            return set()
        try:
            parsed = yaml.safe_load(raw)
        except yaml.YAMLError:
            parsed = raw
        if isinstance(parsed, (list, tuple, set)):
            items = parsed
        else:
            items = re.split(r"[\n,]+", str(parsed))

    return {
        normalise_filter_value(item)
        for item in items
        if normalise_filter_value(item)
    }


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().casefold() in {
        "1", "true", "yes", "y", "on",
    }


def extract_subject_year(data: dict) -> int | None:
    raw_year = data.get("year")
    if raw_year not in (None, ""):
        try:
            return int(str(raw_year).strip())
        except (TypeError, ValueError):
            return None

    raw_date = data.get("datetime") or data.get("date")
    if raw_date in (None, ""):
        return None

    match = re.match(r"^\s*(-?\d{1,6})", str(raw_date))
    if not match:
        return None

    try:
        return int(match.group(1))
    except ValueError:
        return None

def extract_temporal_profile(yaml_header: str):
    if not yaml_header:
        return None
    try:
        data = yaml.safe_load(yaml_header)
        return data.get("temporal_profile")
    except Exception:
        return None


def parse_yaml_header(yaml_header: str):
    if not yaml_header:
        return {}
    try:
        return yaml.safe_load(yaml_header) or {}
    except Exception:
        return {}



def entry_metadata(entry: dict) -> dict:
    """Cache YAML metadata and normalized fields used by filters."""
    data = entry.get("_metadata")
    if not isinstance(data, dict):
        data = parse_yaml_header(entry.get("yaml_header"))
        entry["_metadata"] = data

    entry["_tags"] = parse_tags(data.get("tags")) | parse_tags(entry.get("tags"))
    entry["_kind"] = normalise_filter_value(
        data.get("kind")
        or data.get("type")
        or entry.get("kind")
        or entry.get("type")
        or ""
    )
    entry["_year"] = extract_subject_year(data)
    entry["_futurist"] = parse_bool(data.get("futurist"))
    return data

def normalise_location_filter(value: str | None) -> str:
    value = str(value or "").strip().casefold()
    value = re.sub(r"[\s_]+", "-", value)
    value = re.sub(r"-+", "-", value)
    return value.strip("-")


def matches_location_filter(
    entry: dict,
    location: str | None = None,
) -> bool:
    """Match one key or every component of a slash-delimited location path."""
    raw = str(location or "").strip()
    if not raw:
        return True

    wanted = {
        normalise_location_filter(part)
        for part in raw.split("/")
        if part.strip()
    }
    available = {
        normalise_location_filter(key)
        for key in entry.get("location_search_keys", ())
        if key
    }
    return bool(wanted) and wanted.issubset(available)


def matches_kind_filter(entry: dict, wanted_kind: str | None) -> bool:
    wanted = normalise_filter_value(wanted_kind)
    if not wanted:
        return True

    aliases = {
        "rv": "remote-viewing",
        "remoteviewing": "remote-viewing",
        "remote-viewing": "remote-viewing",
        "vd": "video",
        "yt": "youtube",
        "st": "site",
        "n": "note",
    }
    entry_metadata(entry)
    actual = aliases.get(entry.get("_kind", ""), entry.get("_kind", ""))
    return actual == aliases.get(wanted, wanted)


def tag_matches(tags: set[str], pattern: str) -> bool:
    pattern = normalise_filter_value(pattern)
    return not pattern or any(
        fnmatch.fnmatchcase(tag, pattern)
        for tag in tags
    )


def matches_tag_filter(entry: dict, wanted_tags) -> bool:
    """Apply repeated tag filters with AND semantics and wildcard support."""
    if not wanted_tags:
        return True

    entry_metadata(entry)
    patterns = []
    for value in wanted_tags:
        if value in (None, ""):
            continue
        parsed = parse_tags(value)
        patterns.extend(parsed or {normalise_filter_value(value)})

    return all(tag_matches(entry.get("_tags", set()), p) for p in patterns)


def matches_collection_filter(entry: dict, collection: str | None) -> bool:
    """Match broad UI collections, then fall back to stream/tag/kind."""
    wanted = normalise_filter_value(collection)
    if not wanted:
        return True

    entry_metadata(entry)
    tags = entry.get("_tags", set())
    kind = entry.get("_kind", "")
    stream = normalise_filter_value(entry.get("stream_name"))

    if wanted in {"remote-viewing", "remoteviewing", "rv"}:
        return (
            kind in {"remote-viewing", "remoteviewing", "rv"}
            or "remote-viewing" in tags
            or "rv" in tags
            or stream == "remote-viewing"
        )

    if wanted == "ljh":
        return (
            stream == "ljh"
            or stream.startswith("ljh-")
            or any(tag == "ljh" or tag.startswith("ljh-") for tag in tags)
        )

    return stream == wanted or wanted in tags or kind == wanted


def matches_timeframe_filter(
    entry: dict,
    timeframe: str | None,
    *,
    current_year: int | None = None,
) -> bool:
    """Match ancient, past, present, or explicitly marked future entries."""
    wanted = normalise_filter_value(timeframe)
    if not wanted:
        return True
    if wanted not in {"ancient", "past", "present", "future"}:
        return False

    entry_metadata(entry)
    futurist = bool(entry.get("_futurist"))

    if wanted == "future":
        return futurist
    if futurist:
        return False

    year = entry.get("_year")
    if year is None:
        return False

    current_year = current_year or datetime.now().year
    ancient_cutoff = current_year - 1500
    present_start = current_year - 5

    if wanted == "ancient":
        return year <= ancient_cutoff
    if wanted == "past":
        return ancient_cutoff < year < present_start
    return present_start <= year <= current_year


def entry_matches_filters(
    entry: dict,
    *,
    location: str | None = None,
    collection: str | None = None,
    kind: str | None = None,
    tags=None,
    timeframe: str | None = None,
) -> bool:
    return (
        matches_location_filter(entry, location)
        and matches_collection_filter(entry, collection)
        and matches_kind_filter(entry, kind)
        and matches_tag_filter(entry, tags)
        and matches_timeframe_filter(entry, timeframe)
    )


def enrich_location(row: dict) -> dict:
    """
    Resolve an entry's imperfect location metadata.

    The original CMS location text is retained. Additional fields are added
    for templates and later map/filter support.
    """

    data = entry_metadata(row)

    # Prefer the explicit database value, then the newer YAML fields.
    location_text = (
        row.get("location")
        or data.get("location_key")
        or data.get("location_text")
        or data.get("location")
        or ""
    )

    location_text = str(location_text).strip()

    latitude = (
        data.get("latitude")
        or data.get("lat")
        or data.get("gps_latitude")
    )

    longitude = (
        data.get("longitude")
        or data.get("lon")
        or data.get("lng")
        or data.get("gps_longitude")
    )

    result = resolve_location(
        location_text or None,
        latitude=latitude,
        longitude=longitude,
    )

    row["location_text"] = location_text
    row["resolved_location"] = result

    # New flat-search fields. The YAML catalogue remains hierarchical, but
    # runtime filtering can test simple membership against these canonical keys.
    row["location_matched_keys"] = list(result.get("matched_keys", ()))
    row["location_search_keys"] = list(result.get("search_keys", ()))
    row["location_components"] = list(result.get("components", ()))
    row["location_unmatched_components"] = list(
        result.get("unmatched_components", ())
    )

    if result.get("status") == "matched":
        row["location_region_key"] = result.get("region_key")
        row["location_region_label"] = result.get("region_label")
        row["location_place_key"] = result.get("place_key")
        row["location_place_label"] = result.get("place_label")
        row["location_town_key"] = result.get("town_key")
        row["location_town_label"] = result.get("town_label")

        row["location_key"] = "/".join(
            part
            for part in (
                result.get("region_key"),
                result.get("place_key"),
                result.get("town_key"),
            )
            if part
        )

        row["location_label"] = " / ".join(
            part
            for part in (
                result.get("place_label"),
                result.get("town_label"),
            )
            if part
        )

        row["location_latitude"] = result.get("centre_lat")
        row["location_longitude"] = result.get("centre_lon")
        row["location_radius_km"] = result.get("radius_km")
    else:
        # Keep unresolved values visible rather than losing them.
        row["location_region_key"] = None
        row["location_region_label"] = None
        row["location_place_key"] = None
        row["location_place_label"] = None
        row["location_town_key"] = None
        row["location_town_label"] = None
        row["location_key"] = None
        row["location_label"] = location_text
        row["location_latitude"] = None
        row["location_longitude"] = None
        row["location_radius_km"] = None

    return row
    
def build_temporal_profile(row):
    data = parse_yaml_header(row.get("yaml_header"))

    profile = data.get("temporal_profile")
    if profile:
        return profile

    year = data.get("year")
    if year not in (None, ""):
        try:
            year = int(year)
            return [
                [year - 1, 0],
                [year, 100],
                [year + 1, 0],
            ]
        except Exception:
            pass

    return None

def compute_extents(entries):
    years = []

    for e in entries:
        if not e.get("temporal_profile"):
            continue
        for y, _ in e["temporal_profile"]:
            years.append(y)

    if not years:
        return None, None

    return min(years), max(years)

def display_time_label(row):
    data = parse_yaml_header(row.get("yaml_header"))

    # 1. explicit year → always wins
    year = data.get("year")
    if year not in (None, ""):
        try:
            return str(int(year))
        except Exception:
            pass

    # 2. temporal profile → show range if meaningful
    profile = data.get("temporal_profile")
    if profile and len(profile) >= 2:
        try:
            start = int(profile[0][0])
            end = int(profile[-1][0])

            if start == end:
                return str(start)
            return f"{start} → {end}"
        except Exception:
            pass

    # 3. nothing
    return ""

def user_streams(user):
    cfg = user_config_parser(user)

    if not cfg.has_section("streams"):
        return []

    streams = []
    seen = set()

    for key, value in cfg.items("streams"):
        if not key.endswith(".label"):
            continue

        tag = key[:-6]

        if tag in seen:
            continue
        seen.add(tag)

        visible = cfg.get("streams", f"{tag}.visible", fallback="yes")

        if not config_bool(visible):
            continue

        streams.append({
            "key": tag,
            "label": value,
            "description": cfg.get("streams", f"{tag}.description", fallback=""),
            "thumbnail": cfg.get("streams", f"{tag}.thumbnail", fallback=None),
        })

    return streams

def user_config_parser(user=None) -> configparser.ConfigParser:
    """
    Return stream/theme settings through one ConfigParser interface.

    Hosted:
        read the logged-in user's users.config text.

    Desktop/terminal:
        read the ordinary local config.ini.
    """

    return read_config()
    

@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "server_variant": SERVER_VARIANT,
        "auth_ui_enabled": AUTH_UI_ENABLED,
        "site_theme": current_theme(),
        "user_lang": current_lang(),
        "content_db": str(CONTENT_DB),
    }



@app.route("/")
def index():
    conn = content_db()
    try:
        try:
            page = max(1, int(request.args.get("page", "1")))
        except (TypeError, ValueError):
            page = 1
        offset = (page - 1) * PER_PAGE

        location_filter = (
            request.args.get("location")
            or request.args.get("region")
            or ""
        ).strip()
        collection_filter = request.args.get("collection", "").strip()
        kind_filter = (
            request.args.get("kind")
            or request.args.get("type")
            or ""
        ).strip()
        tag_filters = request.args.getlist("tag")
        timeframe_filter = (
            request.args.get("timeframe")
            or request.args.get("period")
            or ""
        ).strip()

        rows = conn.execute(
            """
            SELECT entry_id, title, stream_name, yaml_header, tags,
                   access_level, location, published_utc
            FROM entries
            ORDER BY published_utc DESC, entry_id DESC
            """
        ).fetchall()

        matching_entries = []

        for r in rows:
            d = dict(r)
            entry_metadata(d)
            d["temporal_profile"] = build_temporal_profile(d)
            d["time_label"] = display_time_label(d)
            enrich_location(d)

            if not entry_matches_filters(
                d,
                location=location_filter,
                collection=collection_filter,
                kind=kind_filter,
                tags=tag_filters,
                timeframe=timeframe_filter,
            ):
                continue

            matching_entries.append(d)

            if location_filter:
                print(
                    "[LOCATION]",
                    d["entry_id"],
                    repr(d["location_text"]),
                    "=>",
                    d["resolved_location"].get("status"),
                    d.get("location_key"),
                    d.get("location_label"),
                )

        total = len(matching_entries)
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

        if page > total_pages:
            page = total_pages
            offset = (page - 1) * PER_PAGE

        entries = matching_entries[offset:offset + PER_PAGE]
        min_year, max_year = compute_extents(matching_entries)

    finally:
        conn.close()

    return render_template(
        "index.html",
        entries=entries,
        section_name="CMS Articles",
        stream_tag=None,
        min_year=min_year,
        max_year=max_year,
        user_streams=user_streams(current_user()),
        page=page,
        total_pages=total_pages,
        total_entries=total,
        active_location=location_filter,
        active_collection=collection_filter,
        active_kind=kind_filter,
        active_tags=tag_filters,
        active_timeframe=timeframe_filter,
    )


@app.route("/entry/<entry_id>")
def entry(entry_id: str):
    user = current_user()
    user_level = user["access_level"] if user else "free"

    conn = content_db()
    try:
        row = conn.execute(
            """
            SELECT entry_id, title, stream_name, access_level, yaml_header,
                   html
            FROM entries
            WHERE entry_id = ? 
            """,
            (entry_id,),
        ).fetchone()

        if not row:
            abort(404)

        links = parse_links_from_yaml_header(row["yaml_header"])

        related = []
        for linked_id in links:
            r = conn.execute(
                """
                SELECT entry_id, title
                FROM entries
                WHERE entry_id = ? 
                """,
                (linked_id,),
            ).fetchone()
            if r:
                related.append(r)

    finally:
        conn.close()

    html = row["html"]

    if not html:

        rendered_stories = story_markdown_to_html(entry_id)
        if len(rendered_stories) == 0:
            html = f"<h1>{row['title']}</h1><p>No HTML stored.</p>"
        else:
            html = next(iter(rendered_stories.values()))
    
    return render_template(
        "entry.html",
        entry=row,
        rendered_html=html,
        user_level=user_level,
        required_level=row["access_level"],
        related=related,
    )

@app.get("/entry/<entry_id>/image/<filename>")
def entry_image(entry_id: str, filename: str):

    _cfg, _cfg_path, paths = load_app_config(
        default_config_path()
    )

    entry_dir = (
        paths.cms_dir
        / Path(entry_id).name
    )

    return send_from_directory(
        entry_dir,
        Path(filename).name,
    )
    
@app.route("/modal/downloadpdf/<entry_id>")
def modal_downloadpdf(entry_id):

    pdf_path = PDF_DIR / f"{entry_id}.pdf"

    if pdf_path.exists():
        return f"""
        <script>
            window.location.href='/cms/pdf/{entry_id}';
        </script>
        """

    return render_template(
        "modals/pdf_not_ready.html.j2",
        entry_id=entry_id,
    )

@app.route("/pdf/<entry_id>")
def download_pdf(entry_id):
    filename = f"{entry_id}.pdf"
    return send_from_directory(PDF_DIR, filename, as_attachment=True)


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()

    conn = content_db()
    try:
        rows = conn.execute(
            """
            SELECT entry_id, title, stream_name, yaml_header, tags,
                   access_level, location, published_utc
            FROM entries
            WHERE title LIKE ?
            ORDER BY published_utc DESC
            """,
            (f"%{q}%",),
        ).fetchall()

        entries = []

        for r in rows:
            d = dict(r)
            d["temporal_profile"] = build_temporal_profile(d)
            d["time_label"] = display_time_label(d)
            enrich_location(d)
            entries.append(d)
    
        min_year, max_year = compute_extents(entries)

    finally:
        conn.close()

    return render_template(
        "index.html",
        entries=entries,
        section_name="Search Results",
        stream_name=q,
        stream_tag=None,
        min_year=min_year,
        max_year=max_year,
    )


@app.route("/tag/<tag>")
def tag_page(tag):
    user = current_user()
    info = stream_info(user, tag)

    conn = content_db()
    try:
        rows = conn.execute(
            """
            SELECT entry_id, title, stream_name, yaml_header, tags,
                   access_level, location, published_utc
            FROM entries
            ORDER BY published_utc DESC, entry_id DESC
            """
        ).fetchall()

        entries = []

        for r in rows:
            d = dict(r)
            entry_metadata(d)

            if not matches_tag_filter(d, [tag]):
                continue

            d["temporal_profile"] = build_temporal_profile(d)
            d["time_label"] = display_time_label(d)
            enrich_location(d)
            entries.append(d)

        min_year, max_year = compute_extents(entries)

    finally:
        conn.close()

    return render_template(
        "index.html",
        entries=entries,
        section_name="CMS Articles",
        stream_name=info["label"],
        stream_tag=tag,
        stream_description=info["description"],
        user_streams=user_streams(user),
        min_year=min_year,
        max_year=max_year,
    )

@app.errorhandler(500)
def internal_server_error(error):
    app.logger.error(
        "Internal server error: %s",
        error,
        exc_info=True,
    )

    return render_template("500.html"), 500

@app.route("/login")
def login():
    return redirect(url_for("index"))

@app.route("/register")
def register():
    return redirect(url_for("index"))

@app.route("/logout")
def logout():
    return redirect(url_for("index"))

@app.route("/account")
def account():
    return redirect(url_for("index"))


def make_remote_view_status(
    text: str,
    level: str = "outline",
) -> dict[str, str]:
    allowed_levels = {
        "primary",
        "secondary",
        "accent",
        "info",
        "success",
        "warning",
        "error",
        "neutral",
        "ghost",
        "outline",
    }

    level = str(level).strip().lower()

    if level not in allowed_levels:
        level = "outline"

    return {
        "text": str(text).strip() or "System status unavailable",
        "level": level,
    }
    
@app.route("/remote-view", methods=["GET", "POST"])
def remote_view():

    backend = get_remote_view_backend()
    conversation = load_working_session()
    print(f"[REMOTE VIEW] backend={backend!r}")

    if request.method == "POST":
        message = request.form.get("message", "").strip()

        if backend != "mock":
            backend = "ollama"

        if message:
            result = generate_remote_view(
                prompt=message,
                conversation=conversation,
                api=backend,
            )

            answer = result["text"]

            append_working_session(
                role="Narrator",
                content=message,
            )

            append_working_session(
                role="Ai",
                content=answer,
            )
            
            conversation = load_working_session()            

    latest_answer = next(
        (
            item["content"]
            for item in reversed(conversation)
            if str(item.get("role", "")).casefold() == "ai"
        ),
        None,
    )

    status = make_remote_view_status(
        text="System: Demo",
        level="warning",
    )

    if backend == "ollama":
        status = {
            "text": "Ollama Live",
            "level": "success",
        }
    else:
        status = {
            "text": "System: Demo",
            "level": "warning",
        }
    
    return render_template(
        "remote_view.html",
        conversation=conversation,
        latest_answer=latest_answer,
        remote_view_status=status,
        remote_view_backend=backend,
        remote_view_models=[],
    )
 
@app.route("/remote-view/backend", methods=["POST"])
def remote_view_backend():
    selected = request.form.get("backend", "mock").strip().casefold()

    if selected not in {"mock", "ollama"}:
        abort(400)

    cfg, config_path, _paths = load_app_config(
        default_config_path(),
        setup_if_missing=True,
    )

    if not cfg.has_section("remoteviewing"):
        cfg.add_section("remoteviewing")

    cfg.set("remoteviewing", "api", selected)

    with config_path.open("w", encoding="utf-8") as handle:
        cfg.write(handle)

    return redirect(url_for("remote_view"))
    
def get_remote_view_backend() -> str:
    cfg, _config_path, _paths = load_app_config(
        default_config_path(),
        setup_if_missing=True,
    )

    backend = cfg.get(
        "remoteviewing",
        "api",
        fallback="mock",
    ).strip().casefold()

    return backend if backend in {"mock", "ollama"} else "mock"

@app.post("/remote-view/reset")
def remote_view_reset():
    clear_working_session()
    return redirect(url_for("remote_view"))

@app.get("/remote-view/finish")
def remote_view_finish():
    conversation = load_working_session()

    return render_template(
        "remote_view_finish.html",
        conversation=conversation,
    )
        
@app.post("/remote-view/finish/save")
def remote_view_finish_save():
    title = request.form.get(
        "title",
        "Remote-Viewing Session",
    ).strip()

    entry_id, _story_path = save_working_session_to_cms(
        fields={
            "title": title or "Remote-Viewing Session",
        },
    )

    return redirect(
        url_for(
            "entry",
            entry_id=entry_id,
        )
    )

@app.post("/remote-view/finish/discard")
def remote_view_finish_discard():
    clear_working_session()
    return redirect(url_for("remote_view"))

@app.get("/api/remote-view/session")
def api_remote_view_session():

    pairs = working_session_pairs()

    return jsonify({
        "ok": True,
        "count": len(pairs),
        "pairs": [
            {
                "pair_id": pair["pair_id"],
                "prompt": pair["prompt"],
                "response": pair["response"],
            }
            for pair in pairs
        ],
    })

@app.post("/api/remote-view/session")
def api_remote_view_session_save():

    data = request.get_json(
        silent=True
    ) or {}

    title = str(
        data.get("title", "")
    ).strip()

    entry_type = str(
        data.get("type", "rv")
    ).strip() or "rv"

    tags = str(
        data.get("tags", "")
    ).strip()

    location = str(
        data.get("location", "")
    ).strip()

    images = data.get("images", []) or []
    if not isinstance(images, list):
        return jsonify({"ok": False, "error": "Invalid image list."}), 400

    images = [str(value).strip() for value in images if str(value).strip()]

    primary_image = images[0] if images else None
    additional_images = images[1:] if len(images) > 1 else []

    selected = data.get(
        "selected",
        [],
    )

    if not title:
        return jsonify({
            "ok": False,
            "error": "A story title is required.",
        }), 400

    try:
        pair_ids = [
            int(value)
            for value in selected
        ]
    except (TypeError, ValueError):
        return jsonify({
            "ok": False,
            "error": "Invalid session selection.",
        }), 400

    if not pair_ids:
        return jsonify({
            "ok": False,
            "error": "Select at least one prompt/response pair.",
        }), 400

    fields = {
        "title": title,
    }

    if tags:
        fields["tags"] = tags

    if location:
        fields["location_text"] = location

    try:
        entry_id, story_path = (
            save_selected_working_session_to_cms(
                pair_ids,
                fields=fields,
                entry_type=entry_type,
                image=primary_image,
                images=additional_images,
            )
        )
        
        #
        # Refresh the local SQLite view of the CMS.
        # The filesystem is authoritative; the database is the local server index.
        #
        load_local_entries()

    except ValueError as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 400

    return jsonify({
        "ok": True,
        "entry_id": entry_id,
        "story_path": str(story_path),
        "remaining": len(
            working_session_pairs()
        ),
    })

@app.post("/api/remote-view/preview")
def api_remote_view_preview():
    data = request.get_json(silent=True) or {}
    prompt = str(data.get("prompt", "")).strip()

    if not prompt:
        return jsonify({"ok": False, "error": "A preview prompt is required."}), 400

    try:
        count = int(data.get("count", 1))
    except (TypeError, ValueError):
        count = 1

    count = max(1, min(count, 4))

    try:
        _cfg, _cfg_path, paths = load_app_config(setup_if_missing=False)
        output_dir = paths.cache_dir / "rvpreview"
        generated = generate_preview_images(
            prompt=prompt,
            output_dir=output_dir,
            count=count,
            api="pollinations",
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({
        "ok": True,
        "images": [str(path) for path in generated],
    })


def working_session_pairs(
    conversation: list[dict] | None = None,
) -> list[dict]:
    """
    Convert the working session into prompt/response pairs.

    pair_id is temporary and refers to the current working-session.json.
    message_indexes identifies the original records so selected pairs can
    later be removed safely.
    """

    if conversation is None:
        conversation = load_working_session()

    pairs = []
    pending_prompt = None
    pending_index = None

    human_roles = {
        "human",
        "user",
        "narrator",
    }

    ai_roles = {
        "ai",
        "assistant",
    }

    for index, message in enumerate(conversation):
        role = str(
            message.get("role", "")
        ).strip().casefold()

        content = str(
            message.get("content", "")
        ).strip()

        if not content:
            continue

        if role in human_roles:
            pending_prompt = content
            pending_index = index
            continue

        if role in ai_roles and pending_prompt is not None:
            pairs.append({
                "pair_id": len(pairs),
                "prompt": pending_prompt,
                "response": content,
                "message_indexes": [
                    pending_index,
                    index,
                ],
            })

            pending_prompt = None
            pending_index = None

    return pairs

def save_selected_working_session_to_cms(
    pair_ids: list[int],
    fields: dict | None = None,
    entry_type: str = "rv",
    *,
    image: str | Path | None = None,
    images: list[str | Path] | None = None,
) -> tuple[str, Path]:
     
    """
    Save selected prompt/response pairs into a new CMS entry and remove
    those pairs from working-session.json.
    """

    conversation = load_working_session()

    if not conversation:
        raise ValueError(
            "There is no working remote-viewing session"
        )

    pairs = working_session_pairs(conversation)

    wanted = set(pair_ids)

    selected_pairs = [
        pair
        for pair in pairs
        if pair["pair_id"] in wanted
    ]

    if not selected_pairs:
        raise ValueError(
            "No remote-viewing items were selected"
        )

    selected_indexes = set()
    selected_conversation = []

    for pair in selected_pairs:
        for index in pair["message_indexes"]:
            selected_indexes.add(index)
            selected_conversation.append(
                conversation[index]
            )

    entry_fields = dict(fields or {})

    entry_id, _entry_dir, story_path = create_entry(
        entry_type,
        fields=entry_fields,
        conversation=selected_conversation,
        image=image,
        images=images,
    )

    remaining = [
        message
        for index, message in enumerate(conversation)
        if index not in selected_indexes
    ]

    write_working_session(remaining)

    return entry_id, story_path

@app.get("/api/remote-view/preview-image/<filename>")
def api_remote_view_preview_image(filename: str):

    _cfg, _cfg_path, paths = load_app_config(
        default_config_path()
    )

    preview_dir = (
        paths.cache_dir
        / "rvpreview"
    )

    return send_from_directory(
        preview_dir,
        Path(filename).name,
    )
                
@app.route("/crypto")
def crypto():
    return render_template("crypto.html")
    
@app.route("/crypto/api/wallet")
def crypto_api_wallet():
    return jsonify(wallet.make_data())

@app.route(
    "/crypto/api/wallet/add",
    methods=["POST"],
)
def crypto_api_wallet_add():

    payload = request.get_json(
        silent=True
    ) or {}

    asset = str(
        payload.get("asset", "")
    ).strip().upper()

    if not asset:
        return jsonify({
            "error": "asset is required"
        }), 400

    config = wallet.load_config()

    wallet.add_asset(
        config=config,
        asset=asset,
    )

    return jsonify(
        wallet.make_data(config)
    )

CRYPTO_DEFAULT_DAYS = 14

def crypto_data_dir():
    config = wallet.load_config()
    return wallet.get_data_dir(config)


def crypto_wallet_asset(asset):
    """
    Return canonical wallet entry for ASSET.
    """
    asset = asset.strip().upper()

    data = wallet.make_data()

    for item in data.get("assets", []):
        if item.get("asset", "").upper() == asset:
            return item

    return None


def crypto_load_history(asset, reference_currency):
    """
    Load canonical collecthistory.py data.
    """
    asset = asset.upper()
    reference_currency = reference_currency.upper()

    path = (
        crypto_data_dir()
        / f"{asset}_{reference_currency}.json"
    )

    if not path.exists():
        raise FileNotFoundError(
            f"No history exists for {asset}/{reference_currency}"
        )

    with path.open("r", encoding="utf-8") as f:
        document = json.load(f)

    rows = document.get("data", [])

    if not isinstance(rows, list):
        raise ValueError(
            f"{path} has no valid data array"
        )

    rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("date")
    ]

    rows.sort(
        key=lambda row: row["date"]
    )

    return document, rows


def crypto_active_channel(asset):
    """
    Look for the latest channel for ASSET which has no close/end date.

    This is intentionally tolerant because the channel schema is still
    developing.
    """
    asset = asset.strip().upper()

    path = (
        crypto_data_dir()
        / "tradingchannels.json"
    )

    if not path.exists():
        return None

    with path.open("r", encoding="utf-8") as f:
        document = json.load(f)

    channels = document.get(
        "channels",
        []
    )

    candidates = []

    for channel in channels:

        if not isinstance(channel, dict):
            continue

        if (
            str(channel.get("asset", "")).upper()
            != asset
        ):
            continue

        # Accept the likely names while the channel schema settles.
        end_date = (
            channel.get("end_date")
            or channel.get("close_date")
            or channel.get("closed")
        )

        if end_date:
            continue

        start_date = (
            channel.get("start_date")
            or channel.get("open_date")
        )

        if not start_date:
            continue

        candidates.append(channel)

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item.get("start_date")
            or item.get("open_date")
            or ""
        )
    )

    return candidates[-1]


def crypto_open_dataset(
    asset,
    fallback_days=CRYPTO_DEFAULT_DAYS,
):
    """
    Build the basic dataset needed when an asset tile is opened.

    Preference:
        ACTIVE channel
        otherwise latest 14 daily records
    """
    asset = asset.strip().upper()

    wallet_asset = crypto_wallet_asset(
        asset
    )

    if wallet_asset is None:
        raise ValueError(
            f"{asset} is not in the wallet"
        )

    reference = wallet_asset.get(
        "reference_currency",
        "USDT",
    ).upper()

    document, history = (
        crypto_load_history(
            asset,
            reference,
        )
    )

    active_channel = (
        crypto_active_channel(asset)
    )

    if active_channel:

        start_date = (
            active_channel.get("start_date")
            or active_channel.get("open_date")
        )

        selected = [
            row
            for row in history
            if row["date"] >= start_date
        ]

        window = {
            "mode": "ACTIVE",
            "start_date": start_date,
            "end_date": (
                selected[-1]["date"]
                if selected
                else None
            ),
        }

    else:

        selected = history[
            -fallback_days:
        ]

        window = {
            "mode": "RECENT",
            "days": fallback_days,
            "start_date": (
                selected[0]["date"]
                if selected
                else None
            ),
            "end_date": (
                selected[-1]["date"]
                if selected
                else None
            ),
        }

    return {
        "schema": "rvcrypto.open.v1",

        "asset": asset,

        "reference_currency":
            reference,

        "window": window,

        "active_channel":
            active_channel,
            
        "available_layers": [
            {
                "name": name,
                "description": description,
            }
            for name, description
            in CRYPTO_AVAILABLE_LAYERS
        ],            

        "history": selected,
        
        "display": {
                    "command": "ADD_ASSET_LAYER",
                    "value": {
                        "asset": asset,
                        "reference_currency": reference,

                        "data": [
                            {
                                "date": row["date"],
                                "close": row["close"],
                            }
                            for row in selected
                        ],
                    },
        },
        
    }
                
@app.route(
    "/crypto/api/wallet/remove/<asset>",
    methods=["POST"],
)
def crypto_api_wallet_remove(asset):

    config = wallet.load_config()

    wallet.remove_asset(
        config=config,
        asset=asset,
    )

    return jsonify(
        wallet.make_data(config)
    )


@app.route(
    "/crypto/api/wallet/update-history",
    methods=["POST"],
)
def crypto_api_wallet_update_history():

    config = wallet.load_config()

    wallet.update_history(
        config
    )

    return jsonify({
        "ok": True,
        "wallet": wallet.make_data(config),
    })


@app.route(
    "/crypto/api/channel/<asset>"
)
def crypto_api_channel(asset):

    channel = crypto_active_channel(
        asset
    )

    return jsonify({
        "asset": asset.upper(),
        "active": channel is not None,
        "channel": channel,
    })


@app.route(
    "/crypto/api/open/<asset>"
)
def crypto_api_open(asset):

    try:
        return jsonify(
            crypto_open_dataset(asset)
        )

    except (
        FileNotFoundError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:

        return jsonify({
            "error": str(exc)
        }), 404
                        
@app.get("/api/llm-status")
def api_llm_status():
    llm = detect_llm_system()

    return jsonify({
        "system": llm["system"],
        "installed": llm["installed"],
        "running": llm["service_running"],
        "model": llm["model"],
        "base_url": llm["base_url"],
        "models": llm["models"],
    })
                   
@app.route("/maplinks/<entry_id>")
def maplinks(entry_id):
    linked_sites = [
        {
            "entry_id": "entry-1000057",
            "title": "Ballarat Site",
            "lat": -37.5622,
            "lon": 143.8503,
            "note": "Possible historical site connection in Australia.",
            "image": "/cms/images/entry-1000057-2026-04-24-100112.png"
        },
        {
            "entry_id": "entry-1000061",
            "title": "Portugal Site",
            "lat": 38.7223,
            "lon": -9.1393,
        },
    ]

    user_level = 'archivist'

    return render_template("maplinks_popups_open_fixed.html", 
        entry=entry, 
        linked_sites=linked_sites,
        user_level=user_level,
    )

@app.route("/modal/pdf/<entry_id>")
def modal_pdf(entry_id):
    entry = get_entry(entry_id)
    return render_template("modals/pdf.html.j2", entry=entry)


@app.route("/modal/fullstory/<entry_id>")
def modal_fullstory(entry_id):
    entry = get_entry(entry_id)
    return render_template("modals/fullstory.html.j2", entry=entry)

@app.route("/cms/images/<path:filename>")
def cms_images(filename: str):
    return send_from_directory(IMAGE_DIR, filename)

@app.route("/images/<path:filename>")
def images(filename: str):
    return send_from_directory(IMAGE_DIR, filename)







def parse_links_from_yaml_header(yaml_header: str | None) -> list[str]:
    if not yaml_header:
        return []

    for raw in yaml_header.splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue

        key, value = line.split(":", 1)
        if key.strip() not in ("links-to", "links_to"):
            continue

        value = value.strip()

        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1]
            return [
                p.strip().strip("'").strip('"')
                for p in inner.split(",")
                if p.strip()
            ]

        return [p.strip() for p in value.split(",") if p.strip()]

    return []

def get_entry(entry_id):
    conn = sqlite3.connect(CONTENT_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM entries WHERE entry_id = ?",
        (entry_id,)
    ).fetchone()
    conn.close()

    if not row:
        abort(404)

    return dict(row)

def config_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "yes", "true", "on"}

def stream_info(user, tag):
    for stream in user_streams(user):
        if stream["key"] == tag:
            return stream
    return {
        "key": tag,
        "label": tag.replace("-", " ").title(),
        "description": "",
        "thumbnail": None,
    }

# block-desktop-load-local-entries.py

from lscms import export_entries_json

LOCAL_ENTRY_LIMIT = 1_000_000

def entry_number(entry_id: str) -> int | None:
    match = re.fullmatch(r"entry-(\d+)", str(entry_id).strip())
    if not match:
        return None
    return int(match.group(1))


def load_local_entries() -> None:
    print("Loading local CMS entries...", CONTENT_DB)

    rows = export_entries_json()

    conn = content_db()

    try:
        conn.execute("BEGIN")

        local_rows = []

        conn.execute(
            """
            DELETE FROM entries
            """,
        )

        for row in rows:
            number = entry_number(row.get("entry_id", ""))

            local_rows.append(row)

        conn.executemany(
            """
            INSERT INTO entries (
                entry_id,
                title,
                stream_name,
                tags,
                status,
                access_level,
                location,
                yaml_header,
                story_md,
                created_utc,
                updated_utc
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                (
                    row["entry_id"],
                    row.get("title", ""),
                    row.get("stream_name", ""),
                    yaml.safe_dump(row.get("tags", [])),
                    row.get("status", ""),
                    row.get("access_level", ""),
                    row.get("location_text", ""),
                    row.get("yaml_header", ""),
                    row.get("story_md", ""),
                    row.get("created_iso", ""),
                    row.get("last_activity_iso", ""),
                )
                for row in local_rows
            ],
        )

        conn.commit()

        print(f"Loaded {len(local_rows)} local entries.")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        
from updatecms import ensure_entries_db

ensure_entries_db(CONTENT_DB)
load_local_entries()


def run_flask():
    app.run(
        host="127.0.0.1",
        port=8765,
        debug=False,
        use_reloader=False,
    )

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    time.sleep(1)

    webview.create_window(
        "Heichalot CMS",
        "http://127.0.0.1:8765",
        width=1280,
        height=850,
    )
    webview.start(gui="qt")


if __name__ == "__main__":
    main()