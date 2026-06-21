#!/usr/bin/env python3
"""
Search Heichalot-CMS entries using cms/index.json and optional full-text search.

Uses tools/config.py so it works with the configured CMS directory on Linux,
macOS, and Windows. --cms / --cms-dir remains available as an override.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple

from dateutil.parser import isoparse
from dateutil.relativedelta import relativedelta

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(TOOLS_DIR))

from config import load_app_config  # noqa: E402


class SearchCMSError(Exception):
    """Raised when CMS search cannot proceed."""


@dataclass
class RuntimeConfig:
    cfg_path: Path
    cms_dir: Path
    index_path: Path
    location_text: Optional[str]
    datetime_iso: Optional[str]


def norm(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[\W_]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def score_record(qn: str, rec: dict) -> float:
    best = 0.0
    for t in rec.get("terms_norm", []):
        if not t:
            continue
        if qn == t:
            best = max(best, 1.00)
        elif qn in t or t in qn:
            best = max(best, 0.90)
        else:
            r = SequenceMatcher(None, qn, t).ratio()
            best = max(best, r * 0.85)
    return best


def candidate_story_path(cms_dir: Path, rec: dict) -> Path:
    """
    Resolve the best story.md path for a search-index record.

    Older indexes may contain absolute story_path values from another machine.
    If that path does not exist, fall back to cms_dir/<entry-id>/story.md.
    """
    raw = str(rec.get("story_path", "")).strip()
    if raw:
        p = Path(raw).expanduser()
        if p.exists():
            return p

    entry_id = str(rec.get("id") or rec.get("entry_id") or "").strip()
    if entry_id:
        return cms_dir / entry_id / "story.md"

    return Path(raw) if raw else cms_dir / "missing-story.md"


def fulltext_score(query: str, story_path: Path) -> float:
    """
    Full-text scoring for story.md.

    Rules:
    - exact phrase match -> strong score
    - all query words within a small window -> medium score
    - otherwise no score
    """
    try:
        text = story_path.read_text(encoding="utf-8")

        text_lower = text.lower()
        q = query.lower().strip()
        if not q:
            return 0.0

        if q in text_lower:
            return 0.80

        words = [w for w in re.findall(r"\w+", q) if w]
        if not words:
            return 0.0

        positions_by_word = []
        for w in words:
            positions = [m.start() for m in re.finditer(re.escape(w), text_lower)]
            if not positions:
                return 0.0
            positions_by_word.append(positions)

        window = 120
        for anchor in positions_by_word[0]:
            matched = [anchor]
            ok = True
            for plist in positions_by_word[1:]:
                nearby = [p for p in plist if abs(p - anchor) <= window]
                if not nearby:
                    ok = False
                    break
                matched.append(min(nearby, key=lambda p: abs(p - anchor)))
            if ok:
                span = max(matched) - min(matched)
                if span <= 40:
                    return 0.72
                return 0.60

    except Exception:
        pass

    return 0.0


def compute_window(time_center: Optional[str], pre_days: int, post_days: int) -> Tuple[Optional[str], Optional[str]]:
    if not time_center:
        return None, None
    try:
        center = isoparse(time_center).date()
        start = center - relativedelta(days=pre_days)
        end = center + relativedelta(days=post_days)
        return start.isoformat(), end.isoformat()
    except Exception:
        return None, None


def extract_snippet(query: str, story_path: Path, max_len: int = 180) -> str:
    try:
        text = story_path.read_text(encoding="utf-8")

        text_lower = text.lower()
        q = query.lower().strip()
        if not q:
            return ""

        def make_snippet(center_start: int, center_end: int) -> str:
            start = max(0, center_start - max_len // 2)
            end = min(len(text), center_end + max_len // 2)
            snippet = text[start:end].replace("\n", " ").strip()
            if start > 0:
                snippet = "..." + snippet
            if end < len(text):
                snippet = snippet + "..."
            return snippet

        idx = text_lower.find(q)
        if idx != -1:
            return make_snippet(idx, idx + len(q))

        words = [w for w in re.findall(r"\w+", q) if w]
        if words:
            positions_by_word = []
            for w in words:
                plist = [m.start() for m in re.finditer(re.escape(w), text_lower)]
                if not plist:
                    positions_by_word = []
                    break
                positions_by_word.append((w, plist))

            if positions_by_word:
                best_span = None
                best_start = None
                best_end = None
                window = 120

                for anchor in positions_by_word[0][1]:
                    chosen = [anchor]
                    ok = True
                    for _, plist in positions_by_word[1:]:
                        nearby = [p for p in plist if abs(p - anchor) <= window]
                        if not nearby:
                            ok = False
                            break
                        chosen.append(min(nearby, key=lambda p: abs(p - anchor)))
                    if ok:
                        s = min(chosen)
                        e = max(chosen)
                        span = e - s
                        if best_span is None or span < best_span:
                            best_span = span
                            best_start = s
                            best_end = e + len(words[-1])

                if best_start is not None:
                    return make_snippet(best_start, best_end or best_start)

        for w in re.findall(r"\w+", q):
            m = re.search(re.escape(w), text_lower)
            if m:
                return make_snippet(m.start(), m.end())

    except Exception:
        pass

    return ""


def read_world_context(cfg: Any) -> tuple[Optional[str], Optional[str]]:
    if not cfg.has_section("cms"):
        return None, None
    loc = cfg.get("cms", "location_text", fallback="").strip() or None
    dt = cfg.get("cms", "datetime", fallback="").strip() or None
    return loc, dt


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Search Heichalot CMS entries (no DB).")
    ap.add_argument("query", nargs="?", default=None, help="Search query. With --use-config, defaults to config location_text.")
    ap.add_argument("--k", type=int, default=15, help="Top K results")
    ap.add_argument("--use-config", action="store_true", help="Use config.ini for default query + world datetime")
    ap.add_argument("--config", default=None, help="Override config.ini path")
    ap.add_argument("--cms", "--cms-dir", dest="cms_dir", default=None, help="Override CMS directory")
    ap.add_argument("--index", default=None, help="Override index.json path")
    ap.add_argument("--fulltext", action="store_true", help="Enable case-insensitive full-text search inside story.md")
    return ap.parse_args(argv)


def load_runtime(args: argparse.Namespace) -> RuntimeConfig:
    cfg, cfg_path, paths = load_app_config(args.config)

    cms_dir = Path(args.cms_dir).expanduser().resolve() if args.cms_dir else paths.cms_dir
    index_path = Path(args.index).expanduser().resolve() if args.index else cms_dir / "index.json"
    cfg_loc, cfg_dt = read_world_context(cfg)

    return RuntimeConfig(
        cfg_path=cfg_path,
        cms_dir=cms_dir,
        index_path=index_path,
        location_text=cfg_loc,
        datetime_iso=cfg_dt,
    )


def load_index(index_path: Path) -> dict:
    if not index_path.exists():
        raise SearchCMSError(f"Missing index.json: {index_path}. Run indexcms.py first.")

    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SearchCMSError(f"Invalid JSON in {index_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise SearchCMSError(f"Index must contain a JSON object: {index_path}")

    return data


def print_result(score: float, rec: dict, snippet: str) -> None:
    center = rec.get("time_center")
    pre = int(rec.get("time_pre_days") or 0)
    post = int(rec.get("time_post_days") or 0)
    w_start, w_end = compute_window(center, pre, post)

    loc_key = rec.get("location_key") or ""
    aliases = ", ".join(rec.get("aliases") or [])
    tags = ", ".join(rec.get("tags") or [])

    print(f"{score:0.3f}  {rec.get('id', '')}  {rec.get('title', '')}  ({rec.get('type', '')})")
    if loc_key:
        print(f"       location_key: {loc_key}")
    if center:
        print(f"       time_center: {center}  pre_days={pre}  post_days={post}")
        if w_start and w_end:
            print(f"       time_window: {w_start} .. {w_end}")
    if snippet:
        print(f"       snippet: {snippet}")

    print(f"       aliases: {aliases[:160]}")
    print(f"       tags:    {tags[:160]}")
    print(f"       path:    {rec.get('story_path', '')}\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if args.k < 1:
        raise SystemExit("--k must be >= 1")

    try:
        runtime = load_runtime(args)
        idx = load_index(runtime.index_path)

        query = args.query
        if (not query) and args.use_config:
            query = runtime.location_text

        if not query:
            raise SearchCMSError("No query provided. Provide a query, or run with --use-config after setting location_text.")

        qn = norm(query)
        scored = []

        for rec in idx.get("records", []):
            if not isinstance(rec, dict):
                continue

            score = score_record(qn, rec)
            snippet = ""
            story_path = candidate_story_path(runtime.cms_dir, rec)

            if args.fulltext:
                ft = fulltext_score(query, story_path)
                if ft > 0:
                    snippet = extract_snippet(query, story_path)
                    if score >= 0.45:
                        score += ft
                    else:
                        score = ft

            if score >= 0.45:
                scored.append((score, rec, snippet))

        scored.sort(key=lambda x: x[0], reverse=True)

        if args.use_config:
            print(f"[Config] {runtime.cfg_path}")
            print(f"[World Context] location_text={runtime.location_text or '(unset)'}  datetime={runtime.datetime_iso or '(unset)'}")

        print(f"[CMS] {runtime.cms_dir}")
        print(f"[Index] {runtime.index_path}")
        print(f"[Search] query='{query}'  normalized='{qn}'  matches={len(scored)}\n")

        for score, rec, snippet in scored[: args.k]:
            print_result(score, rec, snippet)

        return 0

    except KeyboardInterrupt:
        print("\nSearch cancelled.", file=sys.stderr)
        return 1
    except SearchCMSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
