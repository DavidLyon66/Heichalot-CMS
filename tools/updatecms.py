#!/usr/bin/env python3
"""
updatecms.py

Download the latest Heichalot-CMS release selected by the server and install it
into the configured local CMS directory.

The client does not need to know whether it is receiving free, members, or
premium content. It asks the server for one manifest:

    https://heichalot.tech/cms/latest.json

The server decides which stream is appropriate and returns a manifest pointing
to the correct archive.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, build_opener

# Allow running directly from tools/ before package installation.
REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(TOOLS_DIR))

try:
    from config import load_app_config
except Exception as exc:  # pragma: no cover - user-facing startup error
    raise SystemExit(
        "ERROR: Could not import tools/config.py. Run from the Heichalot-CMS "
        "repository or install the package with: pip install -e ."
    ) from exc

DEFAULT_UPDATE_URL = "https://heichalot.tech/cms/"
LATEST_JSON_NAME = "latest.json"
DOWNLOADED_ENTRY_START_ID = 1_000_000
VERSION_FILENAME = "updatecms-version.json"


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

        try:
            entry_start_id = int(data.get("entry_start_id", DOWNLOADED_ENTRY_START_ID))
        except (TypeError, ValueError) as exc:
            raise UpdateCMSError("latest.json field entry_start_id must be an integer") from exc

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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download and install the latest Heichalot-CMS content release."
    )
    parser.add_argument("--config", help="Optional override path to config.ini")
    parser.add_argument(
        "--url",
        default=None,
        help=(
            "Base update URL or direct latest.json URL. "
            f"Default: {DEFAULT_UPDATE_URL}"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Install even when the local version already matches latest.json.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch latest.json and show what would be installed, but do not download or extract.",
    )
    return parser


def get_configured_update_url(cfg, explicit_url: Optional[str]) -> str:
    if explicit_url:
        return explicit_url.strip()

    if cfg.has_section("server"):
        for key in ("update_url", "cms_update_url", "base_url"):
            value = cfg.get("server", key, fallback="").strip()
            if value:
                return value

    return DEFAULT_UPDATE_URL


def latest_url_from_base(value: str) -> tuple[str, str]:
    """
    Return (base_url, latest_url).

    The caller may pass either:
      https://heichalot.tech/cms/
    or:
      https://heichalot.tech/cms/latest.json
    """
    if not value:
        value = DEFAULT_UPDATE_URL

    if value.endswith("latest.json"):
        latest_url = value
        base_url = value.rsplit("/", 1)[0] + "/"
    else:
        base_url = value if value.endswith("/") else value + "/"
        latest_url = urljoin(base_url, LATEST_JSON_NAME)

    return base_url, latest_url


def resolve_zip_url(base_url: str, zip_url: str) -> str:
    if zip_url.lower().startswith(("http://", "https://")):
        return zip_url

    # New server design: latest.json may say "cms-YYYY-MM-DD.zip" while
    # Flask serves archives from /cms/archive/<filename>.
    if "/" not in zip_url and "\\" not in zip_url:
        return urljoin(base_url, f"archive/{zip_url}")

    return urljoin(base_url, zip_url)


def build_url_opener():
    return build_opener()


def fetch_json(url: str, opener) -> Dict[str, Any]:
    request = Request(url, headers={"User-Agent": "Heichalot-CMS-Updater/0.2"})
    try:
        with opener.open(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
        return json.loads(raw)
    except HTTPError as exc:
        if exc.code == 404:
            raise UpdateCMSError(
                f"No CMS release manifest was found at {url}. "
                "The server may not have published latest.json yet."
            ) from exc
        raise UpdateCMSError(f"HTTP error fetching JSON from {url}: {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise UpdateCMSError(f"Network error fetching JSON from {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise UpdateCMSError(f"Invalid JSON received from {url}: {exc}") from exc

def download_file(url: str, dest_path: Path, opener) -> None:
    request = Request(url, headers={"User-Agent": "Heichalot-CMS-Updater/0.2"})
    try:
        with opener.open(request, timeout=60) as response, dest_path.open("wb") as out_file:
            shutil.copyfileobj(response, out_file)
    except HTTPError as exc:
        raise UpdateCMSError(f"HTTP error downloading {url}: {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise UpdateCMSError(f"Network error downloading {url}: {exc.reason}") from exc


def version_path(data_dir: Path) -> Path:
    return data_dir / VERSION_FILENAME


def read_local_version(data_dir: Path) -> Optional[str]:
    path = version_path(data_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        version = data.get("version")
        return str(version) if version is not None else None
    except Exception:
        return None


def write_local_version(data_dir: Path, release: ReleaseInfo, latest_url: str, zip_url: str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "version": release.version,
        "entry_start_id": release.entry_start_id,
        "notes": release.notes,
        "latest_url": latest_url,
        "zip_url": zip_url,
    }
    version_path(data_dir).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def parse_entry_number(entry_name: str) -> Optional[int]:
    if not entry_name.startswith("entry-"):
        return None
    suffix = entry_name[6:]
    if not suffix.isdigit():
        return None
    return int(suffix)


def validate_zip_entries(extract_dir: Path, entry_start_id: int) -> list[Path]:
    entry_dirs = [p for p in extract_dir.iterdir() if p.is_dir() and p.name.startswith("entry-")]

    if not entry_dirs:
        raise UpdateCMSError("Downloaded CMS package does not contain any entry-* directories.")

    for entry_dir in entry_dirs:
        entry_num = parse_entry_number(entry_dir.name)
        if entry_num is None:
            raise UpdateCMSError(f"Invalid entry directory in downloaded package: {entry_dir.name}")
        if entry_num < entry_start_id:
            raise UpdateCMSError(
                f"Downloaded entry {entry_dir.name} is below required start id {entry_start_id}."
            )
        if not (entry_dir / "story.md").exists():
            raise UpdateCMSError(f"Downloaded entry is missing story.md: {entry_dir.name}")

    return entry_dirs

def select_required_downloads(
    manifest: dict,
    local_archive_date: str | None = None,
    flush: bool = False,
) -> list[str]:
    latest_full = manifest.get("latest_full")
    updates = sorted(
        manifest.get("updates", []),
        key=lambda row: row.get("date", ""),
    )

    if flush or local_archive_date is None:
        files = []

        if latest_full:
            files.append(latest_full["file"])
            start_date = latest_full["date"]
        else:
            start_date = ""

        files.extend(
            row["file"]
            for row in updates
            if row.get("date", "") > start_date
        )
        return files

    return [
        row["file"]
        for row in updates
        if row.get("date", "") > local_archive_date
    ]

def is_flush_allowed(cfg) -> bool:
    if not cfg.has_section("updatecms"):
        return False

    return cfg.getboolean(
        "updatecms",
        "flush_allowed",
        fallback=False,
    )

def install_release(entry_dirs: list[Path], cms_dir: Path) -> None:
    cms_dir.mkdir(parents=True, exist_ok=True)

    for source in entry_dirs:
        target = cms_dir / source.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)

def delete_downloaded_entries(
    cms_dir: Path,
    entry_start_id: int = DOWNLOADED_ENTRY_START_ID,
) -> list[str]:
    deleted = []

    if not cms_dir.exists():
        return deleted

    for path in sorted(cms_dir.iterdir()):
        if not path.is_dir():
            continue

        entry_num = parse_entry_number(path.name)
        if entry_num is None:
            continue

        if entry_num >= entry_start_id:
            shutil.rmtree(path)
            deleted.append(path.name)

    return deleted

def print_release_info(release: ReleaseInfo, latest_url: str, zip_url: str, cms_dir: Path) -> None:
    print()
    print("Heichalot-CMS updater")
    print("---------------------")
    print(f"Latest URL:       {latest_url}")
    print(f"Version:          {release.version}")
    print(f"Zip URL:          {zip_url}")
    print(f"Entry start ID:   {release.entry_start_id}")
    print(f"Install CMS dir:  {cms_dir}")
    if release.notes:
        print(f"Notes:            {release.notes}")


def run_update(
    config_path: Optional[str],
    update_url: Optional[str],
    force: bool,
    dry_run: bool,
    flush: bool = False,
) -> int:
    cfg, cfg_path, paths = load_app_config(config_path)

    base_url, latest_url = latest_url_from_base(get_configured_update_url(cfg, update_url))
    opener = build_url_opener()

    latest_data = fetch_json(latest_url, opener)

    local_version = read_local_version(paths.data_dir)
    selected_files = select_required_downloads(
        latest_data,
        local_archive_date=local_version,
        flush=flush,
    )

    print()
    print("Heichalot-CMS updater")
    print("---------------------")
    print(f"Latest URL:       {latest_url}")
    print(f"Install CMS dir:  {paths.cms_dir}")
    print(f"Local version:    {local_version or '(none)'}")
    print(f"Required files:   {len(selected_files)}")

    for filename in selected_files:
        print(f"  - {filename}")

    if not selected_files and not force:
        print()
        print("CMS data is already up to date.")
        return 0

    if dry_run:
        print()
        print("Dry run only. No files downloaded or installed.")
        return 0

    if flush:
        if not is_flush_allowed(cfg):
            raise UpdateCMSError(
                "Flush is disabled. Set [updatecms] flush_allowed=true "
                "in config.ini to permit deletion of downloaded CMS entries."
            )

        deleted = delete_downloaded_entries(
            paths.cms_dir,
            entry_start_id=DOWNLOADED_ENTRY_START_ID,
        )

        print()
        print(f"Flush deleted {len(deleted)} downloaded CMS entr{'y' if len(deleted) == 1 else 'ies'}.")

    install_selected_archives(
        selected_files,
        base_url,
        opener,
        paths.cms_dir,
        entry_start_id=DOWNLOADED_ENTRY_START_ID,
    )

    write_local_manifest_version(
        paths.data_dir,
        latest_data,
        latest_url,
        selected_files,
    )

    print()
    print(f"CMS update complete. Installed version {latest_manifest_date(latest_data)}.")
    return 0


def write_local_manifest_version(
    data_dir: Path,
    manifest: dict,
    latest_url: str,
    downloaded_files: list[str],
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "version": latest_manifest_date(manifest),
        "latest_url": latest_url,
        "downloaded_files": downloaded_files,
    }

    version_path(data_dir).write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )

def latest_manifest_date(manifest: dict) -> str:
    dates = []

    latest_full = manifest.get("latest_full")
    if latest_full:
        dates.append(latest_full["date"])

    dates.extend(row["date"] for row in manifest.get("updates", []))

    return max(dates) if dates else ""

def install_selected_archives(
    selected_files: list[str],
    base_url: str,
    opener,
    cms_dir: Path,
    entry_start_id: int = DOWNLOADED_ENTRY_START_ID,
) -> None:
    with tempfile.TemporaryDirectory(prefix="updatecms_") as tmpdir_str:
        tmpdir = Path(tmpdir_str)

        for filename in selected_files:
            zip_url = resolve_zip_url(base_url, filename)
            zip_path = tmpdir / filename
            extract_dir = tmpdir / f"extracted-{filename}"
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
            entry_dirs = validate_zip_entries(extract_dir, entry_start_id)

            print(f"Installing into: {cms_dir}")
            install_release(entry_dirs, cms_dir)

def main() -> int:
    parser = build_arg_parser()
    parser.add_argument(
        "--flush",
        action="store_true",
        help=(
            "Re-download everything"
        ),
    )

    args = parser.parse_args()

    try:
        return run_update(
            config_path=args.config,
            update_url=args.url,
            force=args.force,
            dry_run=args.dry_run,
            flush=args.flush,
        )

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
