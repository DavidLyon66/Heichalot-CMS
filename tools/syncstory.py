
#!/usr/bin/env python3
"""
syncstory.py

Transfer a local CMS story.md to a repository controller.

Usage:
    python3 tools/syncstory.py 192.168.1.100 cms/entry-0000209
    python3 tools/syncstory.py 192.168.1.100 cms/entry-0000209 --port 8765
"""

from __future__ import annotations

import argparse
import json
import socket
from datetime import datetime, timezone
import re
import sys
from pathlib import Path

import requests

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from createentry import set_yaml_fields


def read_entry_id(story_text: str) -> str:
    """Read entry_id from the story's YAML frontmatter."""
    lines = story_text.splitlines()

    if not lines or lines[0].strip() != "---":
        raise ValueError("story.md has no YAML frontmatter")

    for line in lines[1:]:
        if line.strip() == "---":
            break

        match = re.match(r"^entry_id:\s*['\"]?([^'\"\s]+)", line)
        if match:
            return match.group(1)

    raise ValueError("story.md has no entry_id")



def write_transfer_records(entry_dir: Path, old_id: str, new_id: str,
                           repository_ip: str, port: int) -> None:
    """Keep machine-local transfer history and a publish.json marker."""
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    event = {
        "datetime": timestamp,
        "text": "Entry transferred to repository",
        "original_entry_id": old_id,
        "entry_id": new_id,
        "source_node": socket.gethostname(),
        "repository": f"{repository_ip}:{port}",
    }

    private_dir = entry_dir / "private"
    private_dir.mkdir(parents=True, exist_ok=True)
    history_path = private_dir / "transfer-history.json"
    if history_path.exists():
        history = json.loads(history_path.read_text(encoding="utf-8"))
        if not isinstance(history, list):
            raise ValueError(f"Expected JSON list in {history_path}")
    else:
        history = []
    history.append(event)
    history_path.write_text(
        json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Match publishentry.py's publish.json structure without publishing.
    publish_path = entry_dir / "publish.json"
    if publish_path.exists():
        publish = json.loads(publish_path.read_text(encoding="utf-8"))
        if not isinstance(publish, dict):
            raise ValueError(f"Expected JSON object in {publish_path}")
    else:
        publish = {"free": True, "members": True, "premium": True}
    log = publish.get("log", [])
    if not isinstance(log, list):
        log = []
    log.append(event.copy())
    publish["log"] = log
    publish_path.write_text(
        json.dumps(publish, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def transfer_story(
    repository_ip: str,
    entry_dir: Path,
    port: int = 8765,
) -> None:

    entry_dir = entry_dir.expanduser().resolve()
    story_path = entry_dir / "story.md"

    if not entry_dir.is_dir():
        raise ValueError(f"Not a directory: {entry_dir}")

    if not story_path.is_file():
        raise FileNotFoundError(f"Missing story.md: {story_path}")

    story_text = story_path.read_text(encoding="utf-8")
    old_id = read_entry_id(story_text)

    url = f"http://{repository_ip}:{port}/api/cms/transfer"

    print(f"Source:     {entry_dir}")
    print(f"Entry:      {old_id}")
    print(f"Repository: {url}")
    print("Transferring...")

    response = requests.post(
        url,
        json={
            "story": story_text,
            "source_node": socket.gethostname(),
            "source_directory": str(entry_dir),
        },
        timeout=30,
    )

    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Repository returned invalid JSON (HTTP {response.status_code})"
        ) from exc

    if not response.ok or not result.get("ok"):
        raise RuntimeError(
            result.get("error", f"HTTP {response.status_code}")
        )

    new_id = result.get("entry_id")

    if not isinstance(new_id, str) or not re.fullmatch(
        r"entry-\d+", new_id
    ):
        raise RuntimeError(f"Invalid entry_id returned: {new_id!r}")

    new_dir = entry_dir.with_name(new_id)

    if new_dir != entry_dir and new_dir.exists():
        raise FileExistsError(
            f"Cannot rename: destination already exists: {new_dir}"
        )

    # The server has acknowledged the transfer.
    # Update the local YAML using the existing CMS routine.
    set_yaml_fields(
        story_path,
        {
            "entry_id": new_id,
            "status": "Transferred",
        },
    )

    # Rename the local entry directory.
    if new_dir != entry_dir:
        entry_dir.rename(new_dir)

    write_transfer_records(new_dir, old_id, new_id, repository_ip, port)

    print()
    print("Transfer successful.")
    print(f"Repository entry: {new_id}")
    print(f"Local directory:  {new_dir}")
    print("Local status:     Transferred")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transfer a CMS story to a repository controller."
    )
    parser.add_argument(
        "repository_ip",
        help="IP address of the repository controller",
    )
    parser.add_argument(
        "entry_dir",
        type=Path,
        help="Directory containing story.md",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="CharacterIF API port (default: 8765)",
    )

    args = parser.parse_args()

    try:
        transfer_story(
            args.repository_ip,
            args.entry_dir,
            args.port,
        )
    except (OSError, ValueError, requests.RequestException, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
