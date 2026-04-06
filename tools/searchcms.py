#!/usr/bin/env python3
import json
import re
import os
import sys
from difflib import SequenceMatcher
from pathlib import Path
from configparser import ConfigParser
from typing import Optional, Tuple
import argparse

from dateutil.parser import isoparse
from dateutil.relativedelta import relativedelta


def default_config_path() -> Path:
    # Linux (as requested)
    if sys.platform.startswith("linux"):
        return Path.home() / ".heichalotcms" / "config.ini"

    # macOS
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "heichalotcms" / "config.ini"

    # Windows
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            appdata = str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / "heichalotcms" / "config.ini"

    # Fallback
    return Path.home() / ".heichalotcms" / "config.ini"


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


def fulltext_score(query: str, story_path: str) -> float:
    """
    Full-text scoring for story.md.

    Rules:
    - exact phrase match -> strong score
    - all query words within a small window -> medium score
    - otherwise no score

    Case-insensitive.
    """
    try:
        with open(story_path, "r", encoding="utf-8") as f:
            text = f.read()

        text_lower = text.lower()
        q = query.lower().strip()
        if not q:
            return 0.0

        # 1. Exact phrase match
        if q in text_lower:
            return 0.80

        # 2. Proximity match: all words appear within a limited character window
        words = [w for w in re.findall(r"\w+", q) if w]
        if not words:
            return 0.0

        positions_by_word = []
        for w in words:
            positions = [m.start() for m in re.finditer(re.escape(w), text_lower)]
            if not positions:
                return 0.0
            positions_by_word.append(positions)

        # Try all anchor positions from the first word and see whether the others
        # can be found nearby. This keeps it simple and good enough for v1.
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


def read_cms_config(path: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (location_text, datetime_iso) from config.ini if present.
    """
    if not path.exists():
        return None, None
    cfg = ConfigParser()
    cfg.read(path)
    if "cms" not in cfg:
        return None, None
    loc = cfg["cms"].get("location_text", "").strip() or None
    dt = cfg["cms"].get("datetime", "").strip() or None
    return loc, dt


def compute_window(time_center: Optional[str], pre_days: int, post_days: int) -> Tuple[Optional[str], Optional[str]]:
    """
    Compute ISO date window start/end from center ± days.
    Returns (start_iso, end_iso) or (None, None) if no center.
    """
    if not time_center:
        return None, None
    try:
        center = isoparse(time_center).date()
        start = center - relativedelta(days=pre_days)
        end = center + relativedelta(days=post_days)
        return start.isoformat(), end.isoformat()
    except Exception:
        return None, None


def extract_snippet(query: str, story_path: str, max_len: int = 180) -> str:
    """
    Return a short snippet around the best match in story.md.

    Priority:
    1. exact phrase
    2. closest cluster of all query words
    3. first single-word fallback
    """
    try:
        with open(story_path, "r", encoding="utf-8") as f:
            text = f.read()

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

        # 1. Exact phrase
        idx = text_lower.find(q)
        if idx != -1:
            return make_snippet(idx, idx + len(q))

        # 2. Closest cluster of all query words
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
                    return make_snippet(best_start, best_end)

        # 3. Fallback to first single-word hit
        for w in re.findall(r"\w+", q):
            m = re.search(re.escape(w), text_lower)
            if m:
                return make_snippet(m.start(), m.end())

    except Exception:
        pass

    return ""


def main():
    ap = argparse.ArgumentParser(description="Search Heichalot CMS entries (no DB).")
    ap.add_argument("query", nargs="?", default=None, help="Search query. With --use-config, defaults to config location_text.")
    ap.add_argument("--k", type=int, default=15, help="Top K results")
    ap.add_argument("--use-config", action="store_true", help="Use OS-specific config.ini for default query + world datetime")
    ap.add_argument("--config", default=None, help="Override config.ini path")
    ap.add_argument("--fulltext", action="store_true", help="Enable case-insensitive full-text search inside story.md")
    args = ap.parse_args()

    # Load index.json
    idx_path = Path("cms/index.json")
    if not idx_path.exists():
        raise SystemExit("Missing cms/index.json. Run indexcms.py first.")

    # Read config if requested
    cfg_path = Path(args.config) if args.config else default_config_path()
    cfg_loc, cfg_dt = (None, None)
    if args.use_config:
        cfg_loc, cfg_dt = read_cms_config(cfg_path)

    # Decide query
    query = args.query
    if (not query) and args.use_config:
        query = cfg_loc

    if not query:
        raise SystemExit("No query provided. Provide a query, or run with --use-config after setcmsdatetime.py sets location_text.")

    qn = norm(query)
    q_plain = query.lower().strip()

    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    scored = []
    for rec in idx.get("records", []):
        s = score_record(qn, rec)
        snippet = ""

        if args.fulltext:
            ft = fulltext_score(query, rec.get("story_path", ""))
            if ft > 0:
                snippet = extract_snippet(query, rec.get("story_path", ""))
                if s >= 0.45:
                    s += ft
                else:
                    s = ft

        if s >= 0.45:
            scored.append((s, rec, snippet))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Header showing world context
    if args.use_config:
        print(f"[Config] {cfg_path}")
        print(f"[World Context] location_text={cfg_loc or '(unset)'}  datetime={cfg_dt or '(unset)'}")
    print(f"[Search] query='{query}'  normalized='{qn}'  matches={len(scored)}\n")

    # Print results (no time filtering yet)
    for s, rec, snippet in scored[: args.k]:
        center = rec.get("time_center")
        pre = int(rec.get("time_pre_days") or 0)
        post = int(rec.get("time_post_days") or 0)
        w_start, w_end = compute_window(center, pre, post)

        loc_key = rec.get("location_key") or ""
        aliases = ", ".join(rec.get("aliases") or [])
        tags = ", ".join(rec.get("tags") or [])


        print(f"{s:0.3f}  {rec['id']}  {rec['title']}  ({rec.get('type','')})")
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
        print(f"       path:    {rec['story_path']}\n")


if __name__ == "__main__":
    main()