# tests/test_updatecms.py

from configparser import ConfigParser
from types import SimpleNamespace

import pytest
import zipfile

from tools.updatecms import select_required_downloads
from tools.updatecms import is_flush_allowed
from tools.updatecms import latest_manifest_date
from tools.updatecms import write_local_manifest_version, read_local_version
from tools.updatecms import install_selected_archives
from tools.updatecms import UpdateCMSError, run_update


def test_select_required_downloads_without_local_archive_gets_latest_full():
    manifest = {
        "latest_full": {
            "date": "2026-06-01",
            "file": "cms-full-2026-06-01.zip",
        },
        "updates": [
            {"date": "2026-06-02", "file": "cms-update-2026-06-02.zip"},
        ],
    }

    assert select_required_downloads(manifest, None) == [
        "cms-full-2026-06-01.zip",
        "cms-update-2026-06-02.zip",
    ]


def test_select_required_downloads_with_local_date_gets_newer_updates_only():
    manifest = {
        "latest_full": {
            "date": "2026-06-01",
            "file": "cms-full-2026-06-01.zip",
        },
        "updates": [
            {"date": "2026-06-02", "file": "cms-update-2026-06-02.zip"},
            {"date": "2026-06-03", "file": "cms-update-2026-06-03.zip"},
        ],
    }

    assert select_required_downloads(manifest, "2026-06-02") == [
        "cms-update-2026-06-03.zip",
    ]


def test_select_required_downloads_returns_empty_when_up_to_date():
    manifest = {
        "latest_full": {
            "date": "2026-06-01",
            "file": "cms-full-2026-06-01.zip",
        },
        "updates": [
            {"date": "2026-06-02", "file": "cms-update-2026-06-02.zip"},
        ],
    }

    assert select_required_downloads(manifest, "2026-06-02") == []

def test_select_required_downloads_flush_gets_latest_full_and_updates():
    manifest = {
        "latest_full": {
            "date": "2026-06-01",
            "file": "cms-full-2026-06-01.zip",
        },
        "updates": [
            {"date": "2026-06-02", "file": "cms-update-2026-06-02.zip"},
            {"date": "2026-06-03", "file": "cms-update-2026-06-03.zip"},
        ],
    }

    assert select_required_downloads(
        manifest,
        "2026-06-03",
        flush=True,
    ) == [
        "cms-full-2026-06-01.zip",
        "cms-update-2026-06-02.zip",
        "cms-update-2026-06-03.zip",
    ]

def test_is_flush_allowed_defaults_false():
    cfg = ConfigParser()

    assert is_flush_allowed(cfg) is False


def test_is_flush_allowed_reads_config_true():
    cfg = ConfigParser()
    cfg.add_section("updatecms")
    cfg.set("updatecms", "flush_allowed", "true")

    assert is_flush_allowed(cfg) is True


def test_is_flush_allowed_reads_config_false():
    cfg = ConfigParser()
    cfg.add_section("updatecms")
    cfg.set("updatecms", "flush_allowed", "false")

    assert is_flush_allowed(cfg) is False

def test_latest_manifest_date_returns_newest_update_date():
    manifest = {
        "latest_full": {"date": "2026-06-01", "file": "cms-full-2026-06-01.zip"},
        "updates": [
            {"date": "2026-06-02", "file": "cms-update-2026-06-02.zip"},
            {"date": "2026-06-03", "file": "cms-update-2026-06-03.zip"},
        ],
    }

    assert latest_manifest_date(manifest) == "2026-06-03"


def test_write_local_manifest_version_records_latest_manifest_date(tmp_path):
    manifest = {
        "latest_full": {"date": "2026-06-01", "file": "cms-full-2026-06-01.zip"},
        "updates": [
            {"date": "2026-06-02", "file": "cms-update-2026-06-02.zip"},
        ],
    }

    write_local_manifest_version(
        tmp_path,
        manifest,
        "https://example.com/cms/latest.json",
        ["cms-full-2026-06-01.zip", "cms-update-2026-06-02.zip"],
    )

    assert read_local_version(tmp_path) == "2026-06-02"


def make_entry_zip(zip_path, entry_name, story_text):
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{entry_name}/story.md", story_text)


def test_install_selected_archives_installs_multiple_zips(tmp_path, monkeypatch):
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    zip1 = source_dir / "cms-full-2026-06-01.zip"
    zip2 = source_dir / "cms-update-2026-06-02.zip"

    make_entry_zip(zip1, "entry-1000001", "# Entry 1\n")
    make_entry_zip(zip2, "entry-1000002", "# Entry 2\n")

    cms_dir = tmp_path / "cms"

    def fake_download_file(url, dest_path, opener):
        filename = url.rsplit("/", 1)[-1]
        source_path = source_dir / filename
        dest_path.write_bytes(source_path.read_bytes())

    monkeypatch.setattr(
        "tools.updatecms.download_file",
        fake_download_file,
    )

    install_selected_archives(
        [
            "cms-full-2026-06-01.zip",
            "cms-update-2026-06-02.zip",
        ],
        base_url="https://example.com/cms/",
        opener=None,
        cms_dir=cms_dir,
    )

    assert (cms_dir / "entry-1000001" / "story.md").read_text(encoding="utf-8") == "# Entry 1\n"
    assert (cms_dir / "entry-1000002" / "story.md").read_text(encoding="utf-8") == "# Entry 2\n"


def test_run_update_refuses_flush_when_not_allowed(tmp_path, monkeypatch):
    cfg = ConfigParser()
    cfg.add_section("server")
    cfg.set("server", "update_url", "https://example.com/cms/")

    paths = SimpleNamespace(
        cms_dir=tmp_path / "cms",
        data_dir=tmp_path / "data",
    )

    manifest = {
        "latest_full": {
            "date": "2026-06-01",
            "file": "cms-full-2026-06-01.zip",
        },
        "updates": [],
    }

    monkeypatch.setattr(
        "tools.updatecms.load_app_config",
        lambda config_path: (cfg, tmp_path / "config.ini", paths),
    )
    monkeypatch.setattr(
        "tools.updatecms.build_url_opener",
        lambda: None,
    )
    monkeypatch.setattr(
        "tools.updatecms.fetch_json",
        lambda latest_url, opener: manifest,
    )

    with pytest.raises(UpdateCMSError, match="Flush is disabled"):
        run_update(
            config_path=None,
            update_url=None,
            force=False,
            dry_run=False,
            flush=True,
        )

def test_run_update_flush_allowed_deletes_1m_entries_and_installs_archive(tmp_path, monkeypatch):
    cfg = ConfigParser()
    cfg.add_section("server")
    cfg.set("server", "update_url", "https://example.com/cms/")
    cfg.add_section("updatecms")
    cfg.set("updatecms", "flush_allowed", "true")

    cms_dir = tmp_path / "cms"
    data_dir = tmp_path / "data"
    cms_dir.mkdir()

    keep_entry = cms_dir / "entry-0000123"
    delete_entry = cms_dir / "entry-1000001"
    keep_entry.mkdir()
    delete_entry.mkdir()
    (keep_entry / "story.md").write_text("# Keep\n", encoding="utf-8")
    (delete_entry / "story.md").write_text("# Delete\n", encoding="utf-8")

    paths = SimpleNamespace(
        cms_dir=cms_dir,
        data_dir=data_dir,
    )

    manifest = {
        "latest_full": {
            "date": "2026-06-01",
            "file": "cms-full-2026-06-01.zip",
        },
        "updates": [],
    }

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_zip = source_dir / "cms-full-2026-06-01.zip"
    make_entry_zip(source_zip, "entry-1000002", "# Installed\n")

    def fake_download_file(url, dest_path, opener):
        filename = url.rsplit("/", 1)[-1]
        dest_path.write_bytes((source_dir / filename).read_bytes())

    monkeypatch.setattr(
        "tools.updatecms.load_app_config",
        lambda config_path: (cfg, tmp_path / "config.ini", paths),
    )
    monkeypatch.setattr("tools.updatecms.build_url_opener", lambda: None)
    monkeypatch.setattr("tools.updatecms.fetch_json", lambda latest_url, opener: manifest)
    monkeypatch.setattr("tools.updatecms.download_file", fake_download_file)

    result = run_update(
        config_path=None,
        update_url=None,
        force=False,
        dry_run=False,
        flush=True,
    )

    assert result == 0
    assert keep_entry.exists()
    assert not delete_entry.exists()
    assert (cms_dir / "entry-1000002" / "story.md").read_text(encoding="utf-8") == "# Installed\n"
    assert (data_dir / "updatecms-version.json").exists()

def test_install_archive_to_entries_db_imports_story_md(tmp_path):
    import sqlite3
    import zipfile

    from tools.updatecms import install_archive_to_entries_db

    zip_path = tmp_path / "cms-update-2026-06-23.zip"
    db_path = tmp_path / "content.db"

    story = """---
entry_id: entry-1000001
title: Test Entry
tags:
  - remote-viewing
access: free
status: Published
---

# Test Entry

Body text.
"""

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("entry-1000001/story.md", story)

    install_archive_to_entries_db(zip_path, db_path)

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT entry_id, title, status, story_md
            FROM entries
            WHERE entry_id = ?
            """,
            ("entry-1000001",),
        ).fetchone()
    finally:
        conn.close()

    assert row == (
        "entry-1000001",
        "Test Entry",
        "published",
        story,
    )
