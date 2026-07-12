# tests/test_uploadcms_latest_json.py

import json
from datetime import datetime
from pathlib import Path

from toolscms.uploadcms import (
    build_latest_json,
    write_latest_json,
    today_zip_name,
    UploadConfig,
    archive_zip_name,
    build_publish_plan,
    run_upload,
)

class FakeFTPPublisher:
    uploads = []

    def __init__(self, config):
        self.config = config

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def upload_file(self, local_path, remote_filename):
        self.uploads.append((Path(local_path).name, remote_filename))

def test_run_upload_writes_stream_latest_json(tmp_path, monkeypatch):
    cms_dir = tmp_path / "cms"
    entry_dir = cms_dir / "entry-1000001"
    entry_dir.mkdir(parents=True)

    (entry_dir / "story.md").write_text("# Premium story\n", encoding="utf-8")

    publish_json = cms_dir / "publishcms.json"
    publish_json.write_text(
        '[{"entry": "entry-1000001", "title": "Test Entry"}]\n',
        encoding="utf-8",
    )

    config = UploadConfig(
        config_path=tmp_path / "config.ini",
        cms_dir=cms_dir,
        publish_json=publish_json,
        published_json=cms_dir / "publishedcms.json",
        latest_json=cms_dir / "latest.json",
        published_dir=cms_dir / "published",
        ftp_host="example.com",
        ftp_port=21,
        ftp_user="user",
        ftp_password="pass",
        ftp_remote_dir="/cms",
    )

    monkeypatch.setattr(
        "toolscms.uploadcms.FTPPublisher",
        FakeFTPPublisher,
    )

    FakeFTPPublisher.uploads = []

    plan = build_publish_plan(
        config,
        archive_date=datetime(2026, 6, 22),
    )

    result = run_upload(config, plan)

    assert result == 0

    latest_path = cms_dir / "published" / "premium" / "latest.json"
    assert latest_path.exists()

    data = json.loads(latest_path.read_text(encoding="utf-8"))

    assert data["channel"] == "premium"
    assert data["latest_full"] is None
    assert data["updates"] == [
        {
            "date": "2026-06-22",
            "file": "cms-update-2026-06-22.zip",
        }
    ]

    zip_path = cms_dir / "published" / "premium" / "cms-update-2026-06-22.zip"
    assert zip_path.exists()

    assert (
        "cms-update-2026-06-22.zip",
        "premium/cms-update-2026-06-22.zip",
    ) in FakeFTPPublisher.uploads

    assert (
        "latest.json",
        "premium/latest.json",
    ) in FakeFTPPublisher.uploads


def test_build_latest_json_splits_full_and_update_archives():
    files = [
        "cms-full-2026-06-01.zip",
        "cms-update-2026-06-02.zip",
        "cms-update-2026-06-03.zip",
    ]

    result = build_latest_json(files, channel="free")

    assert result["channel"] == "free"
    assert result["latest_full"] == {
        "date": "2026-06-01",
        "file": "cms-full-2026-06-01.zip",
    }
    assert result["full_archives"] == [
        {"date": "2026-06-01", "file": "cms-full-2026-06-01.zip"}
    ]
    assert result["updates"] == [
        {"date": "2026-06-02", "file": "cms-update-2026-06-02.zip"},
        {"date": "2026-06-03", "file": "cms-update-2026-06-03.zip"},
    ]


def test_build_latest_json_ignores_old_single_archive_names():
    files = [
        "cms-2026-06-01.zip",
        "latest.json",
        "notes.txt",
        "cms-update-2026-06-02.zip",
    ]

    result = build_latest_json(files)

    assert result["full_archives"] == []
    assert result["updates"] == [
        {"date": "2026-06-02", "file": "cms-update-2026-06-02.zip"}
    ]


def test_build_latest_json_sorts_by_date():
    files = [
        "cms-update-2026-06-03.zip",
        "cms-full-2026-06-01.zip",
        "cms-update-2026-06-02.zip",
        "cms-full-2026-05-01.zip",
    ]

    result = build_latest_json(files)

    assert result["latest_full"] == {
        "date": "2026-06-01",
        "file": "cms-full-2026-06-01.zip",
    }

    assert [r["date"] for r in result["full_archives"]] == [
        "2026-05-01",
        "2026-06-01",
    ]

    assert [r["date"] for r in result["updates"]] == [
        "2026-06-02",
        "2026-06-03",
    ]

def test_write_latest_json_writes_manifest_file(tmp_path):
    latest_path = tmp_path / "latest.json"

    write_latest_json(
        latest_path,
        [
            "cms-full-2026-06-01.zip",
            "cms-update-2026-06-02.zip",
        ],
        channel="members",
    )

    data = json.loads(latest_path.read_text(encoding="utf-8"))

    assert data["channel"] == "members"
    assert data["latest_full"]["file"] == "cms-full-2026-06-01.zip"
    assert data["updates"] == [
        {"date": "2026-06-02", "file": "cms-update-2026-06-02.zip"}
    ]

def test_today_zip_name_uses_update_prefix_by_default():
    assert today_zip_name(datetime(2026, 6, 22)) == "cms-update-2026-06-22.zip"


def test_today_zip_name_can_make_full_archive_name():
    assert today_zip_name(datetime(2026, 6, 22), kind="full") == "cms-full-2026-06-22.zip"

def test_archive_zip_name_accepts_date_override():
    assert archive_zip_name(
        datetime(2026, 6, 22),
        kind="update",
    ) == "cms-update-2026-06-22.zip"

def test_uploadweb_defaults_to_web_queue(tmp_path):
    cms = tmp_path / "cms"
    cms.mkdir()

    write_json(cms / "publishweb.json", [])
    write_json(cms / "publishedweb.json", [])

    paths = resolve_build_paths(args)

    assert paths.publish_json.name == "publishweb.json"
    assert paths.published_json.name == "publishedweb.json"
    
