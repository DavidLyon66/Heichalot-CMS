#!/usr/bin/env python3
import json
import re
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


def main() -> None:
    cms_root = Path("cms")
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


if __name__ == "__main__":
    main()