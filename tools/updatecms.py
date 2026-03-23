#!/usr/bin/env python3
"""
updatecms.py

Downloads the latest public or subscriber CMS data release from heichalot.tech
and installs it into the local CMS data area.

Current design goals:
- keep logic simple
- downloaded CMS entries are separate from user-generated entries
- downloaded entries begin at entry_id >= 1000000
- public and subscriber releases are stored separately
- each release is distributed as a zip file
"""

from __future__ import annotations

import getpass
import json
import os
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, build_opener, HTTPBasicAuthHandler, HTTPPasswordMgrWithDefaultRealm


BASE_PUBLIC_URL = "https://heichalot.tech/cms/public/"
BASE_SUBSCRIBER_URL = "https://heichalot.tech/cms/subscriber/"

LATEST_JSON_NAME = "latest.json"
DOWNLOADED_ENTRY_START_ID = 1_000_000

# Simple early-stage auth.
# Later this can be replaced by per-user tokens, certs, signed URLs, etc.
SUBSCRIBER_USERNAME = "subscriber"
SUBSCRIBER_PASSWORD = "A9F3-3A-5Q-37-X8C1"

# Local storage layout.
DEFAULT_LOCAL_DATA_ROOT = Path("cms_data")
PUBLIC_DIRNAME = "public"
SUBSCRIBER_DIRNAME = "subscriber"
ENTRIES_DIRNAME = "entries"
VERSION_FILENAME = "version.json"


class UpdateCMSError(Exception):
    """Raised when CMS update fails."""


@dataclass
class ReleaseInfo:
    version: str
    zip_url: str
    entry_start_id: int = DOWNLOADED_ENTRY_START_ID
    notes: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReleaseInfo":
        if "version" not in data:
            raise UpdateCMSError("latest.json is missing required field: version")
        if "zip_url" not in data:
            raise UpdateCMSError("latest.json is missing required field: zip_url")

        entry_start_id = int(data.get("entry_start_id", DOWNLOADED_ENTRY_START_ID))
        if entry_start_id < DOWNLOADED_ENTRY_START_ID:
            raise UpdateCMSError(
                f"entry_start_id must be >= {DOWNLOADED_ENTRY_START_ID}, got {entry_start_id}"
            )

        return cls(
            version=str(data["version"]),
            zip_url=str(data["zip_url"]),
            entry_start_id=entry_start_id,
            notes=str(data.get("notes", "")),
        )


def prompt_user_email() -> str:
    print("Heichalot-CMS updater")
    print("---------------------")
    print("Press Enter for the free public CMS data.")
    print("Enter your email to try subscriber CMS data.")
    print()
    return input("Email: ").strip()


def choose_channel(email: str) -> str:
    return "subscriber" if email else "public"


def get_channel_url(channel: str) -> str:
    if channel == "public":
        return BASE_PUBLIC_URL
    if channel == "subscriber":
        return BASE_SUBSCRIBER_URL
    raise UpdateCMSError(f"Unknown channel: {channel}")


def get_channel_local_dir(data_root: Path, channel: str) -> Path:
    dirname = PUBLIC_DIRNAME if channel == "public" else SUBSCRIBER_DIRNAME
    return data_root / dirname


def make_url(base_url: str, name: str) -> str:
    return urljoin(base_url, name)


def build_url_opener(channel: str):
    """
    Build a urllib opener.
    Public channel uses no auth.
    Subscriber channel uses simple global HTTP Basic Auth for now.
    """
    if channel == "public":
        return build_opener()

    password_mgr = HTTPPasswordMgrWithDefaultRealm()
    password_mgr.add_password(
        realm=None,
        uri=BASE_SUBSCRIBER_URL,
        user=SUBSCRIBER_USERNAME,
        passwd=SUBSCRIBER_PASSWORD,
    )
    auth_handler = HTTPBasicAuthHandler(password_mgr)
    return build_opener(auth_handler)


def fetch_json(url: str, opener) -> Dict[str, Any]:
    request = Request(url, headers={"User-Agent": "Heichalot-CMS-Updater/0.1"})
    try:
        with opener.open(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
        return json.loads(raw)
    except HTTPError as exc:
        raise UpdateCMSError(f"HTTP error fetching JSON from {url}: {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise UpdateCMSError(f"Network error fetching JSON from {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise UpdateCMSError(f"Invalid JSON received from {url}: {exc}") from exc


def download_file(url: str, dest_path: Path, opener) -> None:
    request = Request(url, headers={"User-Agent": "Heichalot-CMS-Updater/0.1"})
    try:
        with opener.open(request, timeout=60) as response, dest_path.open("wb") as out_file:
            shutil.copyfileobj(response, out_file)
    except HTTPError as exc:
        raise UpdateCMSError(f"HTTP error downloading {url}: {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise UpdateCMSError(f"Network error downloading {url}: {exc.reason}") from exc


def read_local_version(channel_dir: Path) -> Optional[str]:
    version_path = channel_dir / VERSION_FILENAME
    if not version_path.exists():
        return None

    try:
        data = json.loads(version_path.read_text(encoding="utf-8"))
        version = data.get("version")
        return str(version) if version is not None else None
    except Exception:
        return None


def write_local_version(channel_dir: Path, release: ReleaseInfo) -> None:
    version_path = channel_dir / VERSION_FILENAME
    data = {
        "version": release.version,
        "entry_start_id": release.entry_start_id,
        "notes": release.notes,
    }
    version_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def validate_zip_entries(extract_dir: Path, entry_start_id: int) -> None:
    """
    Light validation only.
    We assume CMS entry files are JSON files somewhere under the extracted tree.
    If they are named as numeric IDs, ensure they begin at >= entry_start_id.
    """
    json_files = list(extract_dir.rglob("*.json"))
    if not json_files:
        print("Warning: no JSON files found in downloaded CMS package.")
        return

    for path in json_files:
        stem = path.stem
        if stem.isdigit():
            entry_id = int(stem)
            if entry_id < entry_start_id:
                raise UpdateCMSError(
                    f"Downloaded entry file {path.name} has entry_id {entry_id}, "
                    f"which is below required start id {entry_start_id}."
                )


def clear_entries_dir(channel_dir: Path) -> None:
    entries_dir = channel_dir / ENTRIES_DIRNAME
    if entries_dir.exists():
        shutil.rmtree(entries_dir)
    entries_dir.mkdir(parents=True, exist_ok=True)


def install_release(extract_dir: Path, channel_dir: Path) -> None:
    """
    Copy extracted files into channel_dir/entries.
    Keeps public/subscriber downloads separate from local user entries.
    """
    entries_dir = channel_dir / ENTRIES_DIRNAME
    clear_entries_dir(channel_dir)

    for item in extract_dir.iterdir():
        target = entries_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def print_release_info(channel: str, release: ReleaseInfo) -> None:
    print()
    print(f"Channel:          {channel}")
    print(f"Version:          {release.version}")
    print(f"Zip URL:          {release.zip_url}")
    print(f"Entry start ID:   {release.entry_start_id}")
    if release.notes:
        print(f"Notes:            {release.notes}")


def run_update(data_root: Path) -> int:
    email = prompt_user_email()
    channel = choose_channel(email)
    base_url = get_channel_url(channel)
    channel_dir = get_channel_local_dir(data_root, channel)
    channel_dir.mkdir(parents=True, exist_ok=True)

    if channel == "subscriber":
        print()
        print("Attempting subscriber CMS update.")
        print()

    opener = build_url_opener(channel)

    latest_url = make_url(base_url, LATEST_JSON_NAME)
    latest_data = fetch_json(latest_url, opener)
    release = ReleaseInfo.from_dict(latest_data)

    print_release_info(channel, release)

    local_version = read_local_version(channel_dir)
    if local_version == release.version:
        print()
        print("CMS data is already up to date.")
        return 0

    zip_url = release.zip_url
    if not zip_url.lower().startswith(("http://", "https://")):
        zip_url = make_url(base_url, zip_url)

    with tempfile.TemporaryDirectory(prefix="updatecms_") as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        zip_path = tmpdir / "cms_release.zip"
        extract_dir = tmpdir / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)

        print()
        print(f"Downloading release from: {zip_url}")
        download_file(zip_url, zip_path, opener)

        print("Extracting zip...")
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)
        except zipfile.BadZipFile as exc:
            raise UpdateCMSError(f"Downloaded file is not a valid zip: {zip_path}") from exc

        print("Validating package...")
        validate_zip_entries(extract_dir, release.entry_start_id)

        print(f"Installing into: {channel_dir / ENTRIES_DIRNAME}")
        install_release(extract_dir, channel_dir)

    write_local_version(channel_dir, release)

    print()
    print(f"CMS update complete. Installed version {release.version}.")
    return 0


def main() -> int:
    try:
        # Run relative to project root by default.
        data_root = DEFAULT_LOCAL_DATA_ROOT
        return run_update(data_root)
    except KeyboardInterrupt:
        print("\nUpdate cancelled.")
        return 1
    except UpdateCMSError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"\nUnexpected error: {exc}", file=sys.stderr)
        return 99


if __name__ == "__main__":
    raise SystemExit(main())