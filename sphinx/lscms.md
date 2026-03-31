# lscms.py

**List recent CMS entries**

`lscms.py` is a lightweight utility for quickly viewing the most recent or active entries in the Heichalot-CMS. It is designed as a fast “working set” view rather than a full search or index tool.

---

## Purpose

The tool answers a simple question:

> *“What have I been working on recently?”*

It scans the CMS entry directories and lists the most recently **modified** or **created** entries, showing their ID, timestamp, and title.

---

## Basic Usage

```bash
python3 tools/lscms.py

Example output:

* entry-0000042  2026-04-01 10:12  Tokyo Station Remote-viewing
  entry-0000041  2026-03-31 18:44  Karvellah population scan
* indicates the current entry (from config.ini)
Entries are sorted newest-first
Default limit: 10 entries
Configuration

The tool reads:

~/.heichalotcms/config.ini

Expected section:

[cms]
cms_dir = /path/to/cms
current_entry = entry-0000042

You can override the CMS directory:

python3 tools/lscms.py --cms-dir /custom/path
How “Recent” Is Determined

By default, entries are sorted by last meaningful modification time.

This includes:

story.md
interview.md
chat.md
video.md
other root .md/.txt files
anything inside:
assets/
debate/

This avoids unreliable directory timestamps and focuses on actual content activity.

Title Detection

The title is extracted in this order:

YAML field: title:
First Markdown heading (# Heading)
First non-empty text line
Fallback: Untitled
Command Line Options
Limit results
--limit 20

Show more entries (default: 10)

Filter by recent days
--days 7

Only show entries active within the last N days

Sort mode
--by modified
--by created
modified (default): last content change
created: directory creation time
Long format
--long

Shows additional structure info:

entry-0000042  2026-04-01 10:12  Tokyo Station Remote-viewing
  files: story.md, assets, debate
JSON output
--json

Outputs structured data:

[
  {
    "entry": "entry-0000042",
    "timestamp": "2026-04-01T10:12:00",
    "title": "Tokyo Station Remote-viewing",
    "is_current": true,
    "files": ["story.md", "assets", "debate"]
  }
]
Design Notes
Filesystem-based: does not depend on index.json
Fast and robust: works even if indexing is incomplete
Focused scope: not a search tool, not a browser — just “recent work”
Typical Workflow
# Quick check of current work
python3 tools/lscms.py

# Show more context
python3 tools/lscms.py --limit 20

# See only last week's activity
python3 tools/lscms.py --days 7

# Inspect structure
python3 tools/lscms.py --long
Future Extensions (Optional)
--all to disable limit
coloured output (highlight current entry)
integration with index.json for hybrid mode
--filter tag=...
“recently imported” vs “recently edited” distinction
Summary

lscms.py is a simple but essential utility:

A fast, reliable way to see the active edge of your CMS.