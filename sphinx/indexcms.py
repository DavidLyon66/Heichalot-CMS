#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    import yaml
except ImportError:
    raise SystemExit("Missing dependency: pyyaml. Install with: pip install pyyaml")

FRONTMATTER_RE = re.compile(r"^\s*---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(md_text: str) -> Dict[str, Any]:
    m = FRONTMATTER_RE.match(md_text)
    if not m:
        return {}
    data = yaml.safe_load(m.group(1)) or {}
    return data if isinstance(data, dict) else {}


def norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[\W_]+", " ", s)  # punctuation -> spaces
    s = re.sub(r"\s+", " ", s).strip()
    return s


def as_str_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if x is not None and str(x).strip() != ""]
    return [str(v)]


def as_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except Exception:
        return default


def as_opt_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def build_index(cms_root: Path) -> int:
    if not cms_root.exists():
        raise SystemExit("Expected ./cms directory. Run from project root.")

    records = []
    for story_path in sorted(cms_root.glob("*/story.md")):
        text = story_path.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)

        entry_dir = story_path.parent
        entry_id = str(fm.get("id") or entry_dir.name).strip()
        title = str(fm.get("title") or entry_dir.name).strip()
        entry_type = str(fm.get("type") or "entry").strip()

        aliases = as_str_list(fm.get("aliases"))
        tags = as_str_list(fm.get("tags"))

        # Location/time fields (stored, not interpreted here)
        location_key = as_opt_str(fm.get("location_key"))
        time_center = as_opt_str(fm.get("time_center"))
        time_pre_days = as_int(fm.get("time_pre_days"), 0)
        time_post_days = as_int(fm.get("time_post_days"), 0)

        # Search terms
        terms = [title, entry_id, *aliases, *tags]
        if location_key:
            terms.append(location_key)

        terms_norm = sorted({norm(t) for t in terms if t and norm(t)})

        records.append(
            {
                "id": entry_id,
                "dir": str(entry_dir.as_posix()),
                "story_path": str(story_path.as_posix()),
                "title": title,
                "type": entry_type,
                "aliases": aliases,
                "tags": tags,
                "location_key": location_key,
                "time_center": time_center,
                "time_pre_days": time_pre_days,
                "time_post_days": time_post_days,
                "terms_norm": terms_norm,
            }
        )

    out = {"version": 2, "count": len(records), "records": records}
    out_path = cms_root / "index.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path} with {len(records)} records.")
    return len(records)


class CMSChangeHandler:
    def __init__(self, cms_root: Path, script_path: Path, debounce_seconds: float = 1.0):
        self.cms_root = cms_root
        self.script_path = script_path
        self.debounce_seconds = debounce_seconds
        self.last_run = 0.0

    def should_trigger(self, path: str) -> bool:
        p = Path(path)
        return p.name == "story.md" and p.parent.name.startswith("entry-")

    def _handle_path(self, path: str) -> None:
        if not self.should_trigger(path):
            return

        now = time.time()
        if now - self.last_run < self.debounce_seconds:
            return

        self.last_run = now

        print(f"[monitor] change detected: {path}")
        print("[monitor] rebuilding index...")

        try:
            subprocess.run([sys.executable, str(self.script_path)], check=True)
            print("[monitor] index updated\n")
        except subprocess.CalledProcessError as e:
            print(f"[monitor] index failed with exit code {e.returncode}\n")
        except Exception as e:
            print(f"[monitor] index failed: {e}\n")

    def on_modified(self, event):
        if not getattr(event, "is_directory", False):
            self._handle_path(event.src_path)

    def on_created(self, event):
        if not getattr(event, "is_directory", False):
            self._handle_path(event.src_path)

    def on_moved(self, event):
        if not getattr(event, "is_directory", False):
            src_path = getattr(event, "src_path", "")
            dest_path = getattr(event, "dest_path", "")
            if src_path:
                self._handle_path(src_path)
            if dest_path:
                self._handle_path(dest_path)


def run_monitor(cms_root: Path, debounce_seconds: float = 1.0) -> None:
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        raise SystemExit("Missing dependency: watchdog. Install with: pip install watchdog")

    script_path = Path(__file__).resolve()
    base_handler = CMSChangeHandler(cms_root=cms_root, script_path=script_path, debounce_seconds=debounce_seconds)

    class WatchdogHandler(FileSystemEventHandler):
        def on_modified(self, event):
            base_handler.on_modified(event)

        def on_created(self, event):
            base_handler.on_created(event)

        def on_moved(self, event):
            base_handler.on_moved(event)

    observer = Observer()
    observer.schedule(WatchdogHandler(), str(cms_root), recursive=True)

    print(f"[monitor] watching {cms_root} ... (Ctrl+C to stop)")
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[monitor] stopping...")
        observer.stop()

    observer.join()


def parse_args():
    ap = argparse.ArgumentParser(description="Build Heichalot CMS search index.")
    ap.add_argument("--monitor", action="store_true", help="Watch cms/ for story.md changes and auto-reindex")
    ap.add_argument("--debounce", type=float, default=1.0, help="Debounce interval in seconds for monitor mode")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    cms_root = Path("cms")

    if args.monitor:
        run_monitor(cms_root, debounce_seconds=args.debounce)
        return

    build_index(cms_root)


if __name__ == "__main__":
    main()
