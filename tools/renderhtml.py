#!/usr/bin/env python3
"""Render a simple HTML page or fragment from a story.md file.

Supported input:
- a path to story.md
- a path to a CMS entry directory containing story.md

Default output:
- story.md input      -> story.html beside the source file
- CMS entry directory -> output/story.html inside the entry directory

The renderer intentionally keeps the HTML simple so that downstream web
systems can apply their own headers, footers, layout, and CSS.
"""

from __future__ import annotations

import argparse
import html
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class StoryBlock:
    speaker: str
    content: str


@dataclass
class StoryDocument:
    metadata: Dict[str, str]
    title: str
    blocks: List[StoryBlock]


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
BLOCK_RE = re.compile(r'"""([^\n]*)\n(.*?)\n"""', re.DOTALL)
BULLET_RE = re.compile(r"^\s*([*-])\s+(.*)$")
STRONG_RE = re.compile(r"\*\*(.+?)\*\*")
EM_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")


def parse_simple_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    metadata: Dict[str, str] = {}
    match = FRONTMATTER_RE.match(text)
    if not match:
        return metadata, text

    frontmatter = match.group(1)
    body = text[match.end():]

    for line in frontmatter.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        metadata[key.strip()] = value.strip()

    return metadata, body


def parse_story(text: str) -> StoryDocument:
    metadata, body = parse_simple_frontmatter(text)

    title_match = TITLE_RE.search(body)
    title = title_match.group(1).strip() if title_match else metadata.get("title", "Untitled Story")

    blocks: List[StoryBlock] = []
    for match in BLOCK_RE.finditer(body):
        speaker = match.group(1).strip() or "Unknown"
        content = match.group(2).strip()
        blocks.append(StoryBlock(speaker=speaker, content=content))

    return StoryDocument(metadata=metadata, title=title, blocks=blocks)


def slugify_speaker(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "unknown"


def apply_inline_markup(text: str) -> str:
    escaped = html.escape(text)
    escaped = STRONG_RE.sub(r"<strong>\1</strong>", escaped)
    escaped = EM_RE.sub(r"<em>\1</em>", escaped)
    return escaped


def content_to_html(content: str) -> str:
    """Render story block content with paragraph grouping.

    Rules:
    - consecutive text lines are grouped into a single <p>
    - blank lines terminate the current paragraph or bullet list
    - lines starting with '*' or '-' become <li> items inside <ul>
    """
    lines = content.splitlines()
    parts: List[str] = []
    paragraph_lines: List[str] = []
    bullet_items: List[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if not paragraph_lines:
            return
        text = " ".join(line.strip() for line in paragraph_lines if line.strip())
        if text:
            parts.append(f"<p>{apply_inline_markup(text)}</p>")
        paragraph_lines = []

    def flush_bullets() -> None:
        nonlocal bullet_items
        if not bullet_items:
            return
        items_html = "\n".join(f"  <li>{apply_inline_markup(item)}</li>" for item in bullet_items)
        parts.append(f"<ul>\n{items_html}\n</ul>")
        bullet_items = []

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            flush_bullets()
            continue

        bullet_match = BULLET_RE.match(line)
        if bullet_match:
            flush_paragraph()
            bullet_items.append(bullet_match.group(2).strip())
            continue

        if bullet_items:
            flush_bullets()

        paragraph_lines.append(stripped)

    flush_paragraph()
    flush_bullets()
    return "\n".join(parts)


def indent_html(text: str, level: int) -> str:
    if not text:
        return ""
    prefix = " " * level
    return "\n".join(prefix + line if line else line for line in text.splitlines())


def render_story_html(doc: StoryDocument, full_page: bool = True) -> str:
    metadata_html = ""
    if doc.metadata:
        items = []
        for key, value in doc.metadata.items():
            if not value:
                continue
            items.append(f"  <li><strong>{html.escape(key)}:</strong> {html.escape(value)}</li>")
        if items:
            metadata_html = (
                '<section class="story-metadata">\n'
                ' <h2>Metadata</h2>\n'
                ' <ul>\n'
                + "\n".join(items)
                + '\n </ul>\n'
                '</section>\n'
            )

    block_html = []
    for block in doc.blocks:
        speaker_slug = slugify_speaker(block.speaker)
        block_html.append(
            f'<section class="story-block speaker-{speaker_slug}\">\n'
            f' <h2>{html.escape(block.speaker)}</h2>\n'
            f'{indent_html(content_to_html(block.content), 1)}\n'
            f'</section>'
        )

    article_inner = []
    article_inner.append(f' <h1>{html.escape(doc.title)}</h1>')
    if metadata_html:
        article_inner.append(indent_html(metadata_html.rstrip(), 1))
    article_inner.extend(block_html)

    article = '<article class="story-entry">\n' + "\n".join(article_inner) + '\n</article>'

    if not full_page:
        return article + "\n"

    title = html.escape(doc.title)
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
</head>
<body>
{article}
</body>
</html>
'''


def resolve_input_path(input_path: str) -> Tuple[str, str]:
    input_path = os.path.abspath(input_path)
    if os.path.isdir(input_path):
        story_path = os.path.join(input_path, "story.md")
        if not os.path.exists(story_path):
            raise FileNotFoundError(f"No story.md found in directory: {input_path}")
        default_output = os.path.join(input_path, "output", "story.html")
        return story_path, default_output

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input path not found: {input_path}")

    if os.path.basename(input_path).lower() != "story.md":
        raise ValueError("Input file must be named story.md, or pass a CMS entry directory.")

    base_dir = os.path.dirname(input_path)
    default_output = os.path.join(base_dir, "story.html")
    return input_path, default_output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render story.md to HTML.")
    parser.add_argument("input", help="Path to story.md or a CMS entry directory.")
    parser.add_argument("-o", "--output", help="Output HTML path.")
    parser.add_argument(
        "--fragment",
        action="store_true",
        help="Render only the <article> fragment instead of a full HTML page.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    story_path, default_output = resolve_input_path(args.input)
    output_path = os.path.abspath(args.output) if args.output else default_output

    with open(story_path, "r", encoding="utf-8") as f:
        text = f.read()

    doc = parse_story(text)
    rendered = render_story_html(doc, full_page=not args.fragment)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(rendered)

    print(f"Wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
