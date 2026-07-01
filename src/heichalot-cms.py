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

import threading
import time
import webview
import base64

APP_DIR = Path(__file__).resolve().parent

import sys
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root / "tools"))
from config import load_app_config
try:
    _cfg, _cfg_path, _paths = load_app_config(setup_if_missing=False)
    _content_db = _paths.data_dir / "content.db"
except Exception:
    from config import platform_data_dir
    _content_db = platform_data_dir() / "content.db"
CONTENT_DB = Path(os.environ.get("HEICHALOT_CONTENT_DB", str(_content_db))).expanduser()
del _repo_root, _content_db

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

[theme]
name = brown
"""

app = Flask(__name__)
app.secret_key = os.environ.get("HEICHALOT_SECRET_KEY", "dev-change-this-secret-key")

@app.errorhandler(sqlite3.OperationalError)
def handle_db_error(e):
    return render_template("error.html",
        title="Database Error",
        message="The content database could not be opened. "
                "Please ensure an update has been downloaded by running <code>heichalot-update</code>.",
    )

def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def content_db() -> sqlite3.Connection:
    return connect(CONTENT_DB)


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}



def current_user():
    return None

def current_lang() -> str:
    return "en"

def current_theme() -> str:
    cfg = user_config_parser()
    theme = cfg.get("theme", "name", fallback="dark") if cfg.has_section("theme") else "dark"
    theme = theme.strip().lower()
    return theme if theme in VALID_THEMES else "dark"

def current_cms_stream() -> str:
    return "free"
def select_html(row: sqlite3.Row, user_level: str) -> str:
    return row["html"] or ""


def parse_tags(text):
    if not text:
        return set()
    return {line.strip() for line in text.splitlines() if line.strip()}

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

def user_config_parser(user=None):
    cfg = configparser.ConfigParser()

    try:
        cfg.read_file(StringIO(DEFAULT_USER_CONFIG))
    except configparser.Error:
        cfg.read_file(StringIO(DEFAULT_USER_CONFIG))

    return cfg

@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "site_theme": current_theme(),
        "user_lang": current_lang(),
        "content_db": str(CONTENT_DB),
    }



@app.route("/")
def index():
    conn = content_db()
    try:

        page = max(1, int(request.args.get("page", "1")))
        offset = (page - 1) * PER_PAGE

        total = conn.execute(
            """
            SELECT COUNT(*)
            FROM entries
            WHERE status = 'published'
            """
        ).fetchone()[0]

        rows = conn.execute(
            """
            SELECT entry_id, title, stream_name, yaml_header, location, published_utc
            FROM entries
            WHERE status = 'published'
            ORDER BY published_utc DESC, entry_id DESC
            LIMIT ? OFFSET ?
            """,
            (PER_PAGE, offset),
        ).fetchall()

        entries = []
        for r in rows:
            d = dict(r)
            d["temporal_profile"] = build_temporal_profile(d)
            d["time_label"] = display_time_label(d)
            entries.append(d)

        min_year, max_year = compute_extents(entries)
        total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

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
        )


@app.route("/entry/<entry_id>")
def entry(entry_id: str):
    user = current_user()
    user_level = user["access_level"] if user else "free"

    conn = content_db()
    try:
        row = conn.execute(
            """
            SELECT entry_id, title, stream_name, yaml_header,
                   html
            FROM entries
            WHERE entry_id = ? AND status = 'published'
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
                WHERE entry_id = ? AND status = 'published'
                """,
                (linked_id,),
            ).fetchone()
            if r:
                related.append(r)

    finally:
        conn.close()

    html = select_html(row, user_level)
    if not html:
        html = f"<h1>{row['title']}</h1><p>No HTML stored.</p>"

    return render_template(
        "entry.html",
        entry=row,
        rendered_html=html,
        user_level=user_level,
        required_level="free",
        related=related,
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
            SELECT entry_id, title, stream_name, yaml_header            FROM entries
            WHERE status = 'published'
              AND title LIKE ?
            ORDER BY published_utc DESC
            """,
            (f"%{q}%",),
        ).fetchall()

        entries = []

        for r in rows:
            d = dict(r)
            d["temporal_profile"] = build_temporal_profile(d)
            d["time_label"] = display_time_label(d)
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

    try:
        conn = content_db()
        rows = conn.execute(
            """
            SELECT entry_id, title, stream_name, yaml_header
            FROM entries
            WHERE tags LIKE ?
            ORDER BY published_utc DESC
            """,
            (f"%{tag}%",)
        ).fetchall()

        entries = []
        for r in rows:
            d = dict(r)
            d["temporal_profile"] = build_temporal_profile(d)
            d["time_label"] = display_time_label(d)
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


def run_flask():
    app.run(
        host="127.0.0.1",
        port=8765,
        debug=False,
        use_reloader=False,
    )

def check_content_db(path: Path) -> str | None:
    if not path.exists():
        return f"Database not found at: {path}"
    try:
        conn = sqlite3.connect(str(path))
        conn.execute("SELECT 1 FROM entries LIMIT 1")
        conn.close()
        return None
    except sqlite3.DatabaseError as e:
        return f"Could not read database at {path}: {e}"

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    time.sleep(1)

    if os.environ.get("HEICHALOT_NO_GUI"):
        print("HEICHALOT_NO_GUI set — running Flask server only. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return

    err = check_content_db(CONTENT_DB)
    if err:
        print(err)
        window = webview.create_window(
            "Heichalot CMS — Error",
            f"data:text/html,<html><body style='font-family:sans-serif;padding:40px;background:#1a1a2e;color:#e0e0e0'><h1 style='color:#e94560'>Database Error</h1><p>{err}</p><p>Please run <b>heichalot-update</b> to download content.</p></body></html>",
            width=800,
            height=600,
        )
        webview.start(gui="qt")
        return

    webview.create_window(
        "Heichalot CMS",
        "http://127.0.0.1:8765",
        width=1280,
        height=850,
    )
    webview.start(gui="qt")


if __name__ == "__main__":
    main()