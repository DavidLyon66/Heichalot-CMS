#!/usr/bin/env python3
from __future__ import annotations
import argparse, html, json, re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(TOOLS_DIR))

from config import (
    default_config_path,
    load_app_config,
    TIMEFRAME_CHOICES,
    location_search_keys_match,
    matches_timeframe,
    resolve_location,
    resolve_path,
)

CONFIG_PATH = default_config_path()

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except Exception:
    Environment = None
    FileSystemLoader = None
    select_autoescape = None

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

DEFAULT_TEMPLATES_DIR = SCRIPT_DIR / "templates"
DEFAULT_CMS_DIR = PROJECT_ROOT / "cms"
DEFAULT_PUBLISHED_JSON = DEFAULT_CMS_DIR / "publishedcms.json"

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render story.md to HTML.")
    p.add_argument("input", nargs="?", default=".", help="Entry directory or story.md file. Default: .")
    p.add_argument("-o", "--output", help="Output HTML file path.")
    p.add_argument("--plain-html", action="store_true", help="Render using the old plain HTML wrapper.")
    p.add_argument("--templates-dir", default=str(DEFAULT_TEMPLATES_DIR), help="Templates directory.")
    p.add_argument("--index", action="store_true", help="Generate an index page from cms/publishedcms.json.")
    p.add_argument("--cms-dir", default=str(DEFAULT_CMS_DIR), help="CMS root.")
    p.add_argument("--published-json", default=str(DEFAULT_PUBLISHED_JSON), help="Path to publishedcms.json.")
    p.add_argument("--site-title", default="Published Stories", help="Title for the generated index page.")
    return p.parse_args()

def split_frontmatter(text: str) -> Tuple[Optional[str], str]:
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm = "\n".join(lines[1:i])
            rest = "\n".join(lines[i + 1 :])
            if text.endswith("\n"):
                rest += "\n"
            return fm, rest
    return None, text

def parse_simple_yaml(block: Optional[str]) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not block:
        return data
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data

def escape_inline(text: str) -> str:
    return html.escape(text, quote=False)

def convert_inline_markup(text: str) -> str:
    text = escape_inline(text)
    text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)',
                  lambda m: f'<img src="{html.escape(m.group(2), quote=True)}" alt="{html.escape(m.group(1), quote=True)}">', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)',
                  lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    return text

DIALOG_OPEN_RE = re.compile(r'^"""([A-Za-z]\w*)\s*(--.*--)?\s*$', re.MULTILINE)
DIALOG_CLOSE_RE = re.compile(r'^"""\s*$', re.MULTILINE)


def has_dialog_blocks(text: str) -> bool:
    """Return True when text contains at least one complete dialogue block."""
    return bool(DIALOG_OPEN_RE.search(text) and DIALOG_CLOSE_RE.search(text))


def preprocess_dialogs(text: str) -> str:
    """Convert CMS dialogue blocks to ordinary Markdown H3 sections."""
    lines = text.splitlines(keepends=True)
    result: List[str] = []
    in_dialog = False
    current_char: Optional[str] = None
    in_paren = False

    for line in lines:
        match = DIALOG_OPEN_RE.match(line)
        if match:
            current_char = match.group(1)
            result.append(f"### {current_char}\n")
            in_dialog = True
            in_paren = False
            continue

        if DIALOG_CLOSE_RE.match(line):
            in_dialog = False
            current_char = None
            in_paren = False
            continue

        if in_dialog and current_char and current_char.lower() == "ai":
            stripped = line.lstrip()
            if in_paren:
                if ")" in stripped:
                    in_paren = False
                continue
            if stripped.startswith("("):
                if ")" not in stripped:
                    in_paren = True
                    continue
                if re.search(r'\)[\.,!?;:]*\s*$', stripped):
                    continue

        result.append(line)

    return "".join(result)


def markdown_to_html(md_text: str) -> Tuple[str, Optional[str]]:
    lines = md_text.splitlines()
    blocks: List[str] = []
    paragraph_lines: List[str] = []
    list_items: List[str] = []
    in_code = False
    code_lines: List[str] = []
    first_h1: Optional[str] = None

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if paragraph_lines:
            para = " ".join(x.strip() for x in paragraph_lines if x.strip())
            if para:
                blocks.append(f"<p>{convert_inline_markup(para)}</p>")
            paragraph_lines = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            items_html = "".join(f"<li>{convert_inline_markup(item)}</li>" for item in list_items)
            blocks.append(f"<ul>{items_html}</ul>")
            list_items = []

    def flush_code() -> None:
        nonlocal code_lines
        if code_lines:
            code = "\n".join(code_lines)
            blocks.append(f"<pre><code>{html.escape(code)}</code></pre>")
            code_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph(); flush_list()
            if in_code:
                flush_code(); in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(line); continue
        if not stripped:
            flush_paragraph(); flush_list(); continue
        if stripped.startswith("### "):
            flush_paragraph(); flush_list()
            blocks.append(f"<h3>{convert_inline_markup(stripped[4:].strip())}</h3>"); continue
        if stripped.startswith("## "):
            flush_paragraph(); flush_list()
            blocks.append(f"<h2>{convert_inline_markup(stripped[3:].strip())}</h2>"); continue
        if stripped.startswith("# "):
            flush_paragraph(); flush_list()
            heading = stripped[2:].strip()
            if first_h1 is None:
                first_h1 = heading
            blocks.append(f"<h1>{convert_inline_markup(heading)}</h1>"); continue
        if stripped.startswith(">"):
            flush_paragraph(); flush_list()
            blocks.append(f"<blockquote>{convert_inline_markup(stripped[1:].strip())}</blockquote>"); continue
        if stripped in ("---", "***"):
            flush_paragraph(); flush_list(); blocks.append("<hr>"); continue
        if stripped.startswith(("- ", "* ")):
            flush_paragraph(); list_items.append(stripped[2:].strip()); continue
        paragraph_lines.append(line)

    flush_paragraph(); flush_list()
    if in_code:
        flush_code()
    return "\n".join(blocks), first_h1

def story_markdown_to_html(
    entry_id: str,
    filename: str | None = None,
    *,
    cms_dir: Path | str | None = None,
) -> dict[str, str]:
    """
    Find and render story Markdown files for one CMS entry.

    Parameters
    ----------
    entry_id:
        CMS entry directory name, such as ``entry-0000147``.

    filename:
        Optional specific basename, such as ``story.md``.
        When omitted, every ``story*.md`` file in the entry
        directory is rendered.

    cms_dir:
        Optional CMS-root override, primarily for tests.
        When omitted, the CMS directory is resolved through config.py.

    Returns
    -------
    dict[str, str]
        Mapping of source filename to rendered HTML fragment.

        Example::

            {
                "story.md": "<h1>...</h1><p>...</p>",
                "story-free.md": "<h1>...</h1><p>...</p>",
            }
    """

    entry_id = str(entry_id).strip()

    if not entry_id:
        raise ValueError("entry_id cannot be empty")

    # Entry IDs must be directory names, not paths supplied by callers.
    if Path(entry_id).name != entry_id:
        raise ValueError(
            f"entry_id must be a directory name, not a path: {entry_id!r}"
        )

    cms_root = (
        Path(cms_dir).expanduser().resolve()
        if cms_dir is not None
        else resolve_path("cms")
    )

    entry_dir = cms_root / entry_id

    if not entry_dir.is_dir():
        raise FileNotFoundError(
            f"CMS entry directory not found: {entry_dir}"
        )

    if filename is not None:
        filename = str(filename).strip()

        if not filename:
            raise ValueError("filename cannot be empty")

        if Path(filename).name != filename:
            raise ValueError(
                f"filename must be a basename, not a path: {filename!r}"
            )

        candidates = [entry_dir / filename]

    else:
        candidates = sorted(
            path
            for path in entry_dir.glob("story*.md")
            if path.is_file()
        )

    rendered: dict[str, str] = {}

    for story_path in candidates:
        if not story_path.is_file():
            continue

        story_text = story_path.read_text(encoding="utf-8")

        _frontmatter, markdown_body = split_frontmatter(story_text)

        if has_dialog_blocks(markdown_body):
            markdown_body = preprocess_dialogs(markdown_body)

        body_html, _first_h1 = markdown_to_html(markdown_body)

        rendered[story_path.name] = body_html

    return rendered

def resolve_story_path(input_value: str) -> Path:
    path = Path(input_value)
    return path / "story.md" if path.is_dir() else path

def build_plain_html(title: str, body_html: str) -> str:
    return f"""<html>
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
</head>
<body>
{body_html}
</body>
</html>
"""

def get_jinja_env(templates_dir: Path):
    if Environment is None:
        raise RuntimeError("Jinja2 is not installed. Install jinja2 or use --plain-html.")
    return Environment(loader=FileSystemLoader(str(templates_dir)),
                       autoescape=select_autoescape(["html", "xml"]))

def render_story_with_template(*, templates_dir: Path, page_title: str, body_html: str,
                               metadata: Dict[str, str], back_link: Optional[str]) -> str:
    env = get_jinja_env(templates_dir)
    t = env.get_template("story.html.j2")
    return t.render(page_title=page_title, body_html=body_html, metadata=metadata, back_link=back_link)

def render_index_with_template(*, templates_dir: Path, page_title: str, items: List[Dict[str, str]]) -> str:
    env = get_jinja_env(templates_dir)
    t = env.get_template("index.html.j2")
    return t.render(page_title=page_title, index_title=page_title, items=items)

def render_index_plain(page_title: str, items: List[Dict[str, str]]) -> str:
    lines = ["<html>", "<head>", '  <meta charset="utf-8">', f"  <title>{html.escape(page_title)}</title>",
             "</head>", "<body>", f"  <h1>{html.escape(page_title)}</h1>", "  <ul>"]
    for item in items:
        title = html.escape(item["title"])
        href = html.escape(item["href"], quote=True)
        entry_id = html.escape(item["entry_id"])
        dp = html.escape(item.get("date_published", ""))
        suffix = f" — {dp}" if dp else ""
        lines.append(f'    <li><a href="{href}">{title}</a> <small>({entry_id}{suffix})</small></li>')
    lines += ["  </ul>", "</body>", "</html>"]
    return "\n".join(lines)

def build_index_items(cms_dir: Path, published_json: Path) -> List[Dict[str, str]]:
    if not published_json.exists():
        raise FileNotFoundError(f"Missing publishedcms.json: {published_json}")
    data = json.loads(published_json.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("published.json must contain a list.")
    items: List[Dict[str, str]] = []
    for obj in data:
        if not isinstance(obj, dict):
            continue
        entry_id = str(obj.get("entry", "")).strip()
        if not entry_id:
            continue
        story_md = cms_dir / entry_id / "story.md"
        if not story_md.exists():
            continue
        story_text = story_md.read_text(encoding="utf-8")
        frontmatter, remainder = split_frontmatter(story_text)
        metadata = parse_simple_yaml(frontmatter)
        if has_dialog_blocks(remainder):
            remainder = preprocess_dialogs(remainder)
        _, first_h1 = markdown_to_html(remainder)
        title = first_h1 or metadata.get("title") or entry_id
        items.append({"entry_id": entry_id, "title": title, "href": f"{entry_id}.html",
                      "date_published": str(obj.get("date_published", "")).strip()})
    items.sort(key=lambda x: x.get("date_published", ""), reverse=True)
    return items


def safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', str(value))
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip('.')
    return cleaned or 'story'


def parse_story(story_text: str):
    frontmatter, remainder = split_frontmatter(story_text)
    metadata = parse_simple_yaml(frontmatter)
    title = metadata.get('title', '')
    body_lines = []
    for line in remainder.splitlines():
        if not title and line.startswith('# '):
            title = line[2:].strip()
            continue
        body_lines.append(line)
    return metadata, title or 'Story', body_lines


def select_header_items(metadata: Dict[str, str], header_fields: Optional[List[str]] = None) -> List[Tuple[str, str]]:
    labels = {'location':'Location','location_text':'Location','source':'Source','datetime':'Date','date':'Date','created_utc':'Created','published_utc':'Published','status':'Status'}
    keys = header_fields or ['location_text','location','datetime','source']
    out=[]
    for key in keys:
        value=str(metadata.get(key,'')).strip()
        if value:
            out.append((labels.get(key,key.replace('_',' ').title()), value))
    return out


def find_illustration_image(story_file: Path | str) -> Optional[Path]:
    story_path=Path(story_file)
    entry_dir=story_path.parent
    for name in ('illustration.png','illustration.jpg','illustration.jpeg','illustration.webp','illustration.gif'):
        p=entry_dir/name
        if p.exists(): return p
    exts={'.png','.jpg','.jpeg','.webp','.gif','.svg'}
    candidates=[p for p in sorted(entry_dir.iterdir()) if p.is_file() and p.suffix.lower() in exts]
    return candidates[0] if len(candidates)==1 else None


INLINE_IMAGE_RE = re.compile(r'^!\[([^\]]*)\]\(([^)]+)\)(?:\{([^}]*)\})?\s*$')


def parse_inline_image(line: str):
    m=INLINE_IMAGE_RE.match(line.strip())
    if not m: return None
    caption=m.group(1).strip(); filename=m.group(2).strip(); raw=m.group(3) or ''
    options={}
    for token in raw.split():
        if '=' not in token: continue
        key,value=token.split('=',1); key=key.strip().lower(); value=value.strip().strip('"').strip("'")
        if key=='height':
            try: options['height_px']=int(value)
            except ValueError: pass
        elif key=='align' and value in {'left','right','center'}:
            options['align']=value
    return caption, filename, options


def resolve_inline_image_path(story_file: Path | str, filename: str) -> Path:
    story_path=Path(story_file)
    direct=story_path.parent/filename
    if direct.exists(): return direct
    return story_path.parent/'images'/filename


def _inline_image_html(story_file: Path, caption: str, filename: str, options: Dict[str, object]) -> str:
    image_path=resolve_inline_image_path(story_file, filename)
    try: src=image_path.relative_to(story_file.parent).as_posix()
    except ValueError: src=image_path.as_posix()
    styles=[]
    h=options.get('height_px')
    if isinstance(h,int): styles.append(f'max-height:{h}px')
    align=options.get('align')
    if align=='right': styles += ['display:block','margin:0 0 1em auto']
    elif align=='left': styles += ['display:block','margin:0 auto 1em 0']
    elif align=='center': styles += ['display:block','margin:0 auto 1em auto']
    style_attr=f' style="{html.escape(";".join(styles), quote=True)}"' if styles else ''
    return f'<figure class="story-inline-image"><img src="{html.escape(src,quote=True)}" alt="{html.escape(caption,quote=True)}"{style_attr}><figcaption>{html.escape(caption)}</figcaption></figure>'


def _compat_story_body_html(story_file: Path, body_text: str) -> str:
    if has_dialog_blocks(body_text): body_text=preprocess_dialogs(body_text)
    out=[]; para=[]; items=[]
    def flush_para():
        nonlocal para
        if para:
            content=' '.join(x.strip() for x in para if x.strip())
            if content: out.append(f'<p class="story-paragraph">{convert_inline_markup(content)}</p>')
            para=[]
    def flush_items():
        nonlocal items
        if items:
            out.append('<ul>'+''.join(f'<li>{convert_inline_markup(i)}</li>' for i in items)+'</ul>')
            items=[]
    for line in body_text.splitlines():
        s=line.strip()
        if not s: flush_para(); flush_items(); continue
        parsed=parse_inline_image(s)
        if parsed:
            flush_para(); flush_items(); out.append(_inline_image_html(story_file,*parsed)); continue
        if s.startswith('### '): flush_para(); flush_items(); out.append(f'<h2>{convert_inline_markup(s[4:].strip())}</h2>'); continue
        if s.startswith('## '): flush_para(); flush_items(); out.append(f'<h2>{convert_inline_markup(s[3:].strip())}</h2>'); continue
        if s.startswith('# '): flush_para(); flush_items(); continue
        if s.startswith(('- ','* ')): flush_para(); items.append(s[2:].strip()); continue
        para.append(line)
    flush_para(); flush_items(); return '\n'.join(out)

def generate_html(story_file: Path | str | None = None, *, output: Path | str | None = None, fragment: bool = False, header_fields: Optional[List[str]] = None) -> str:
    story_path=Path(story_file or 'story.md').expanduser().resolve()
    if story_path.is_dir(): story_path=story_path/'story.md'
    if not story_path.exists(): raise FileNotFoundError(f'Missing story.md: {story_path}')
    story_text=story_path.read_text(encoding='utf-8')
    metadata,title,_=parse_story(story_text)
    _,remainder=split_frontmatter(story_text)
    body_html=_compat_story_body_html(story_path,remainder)
    header_items=select_header_items(metadata,header_fields)
    header_html=''
    if header_items:
        header_html='<dl class="story-metadata">'+''.join(f'<dt>{html.escape(l)}</dt><dd>{html.escape(v)}</dd>' for l,v in header_items)+'</dl>'
    article=f'<article class="story"><h1>{html.escape(title)}</h1>{header_html}{body_html}</article>'
    html_text=article if fragment else f'<!doctype html>\n<html>\n<head>\n  <meta charset="utf-8">\n  <title>{html.escape(title)}</title>\n</head>\n<body>\n{article}\n</body>\n</html>\n'
    output_path=Path(output).expanduser().resolve() if output is not None else story_path.parent/f'{safe_filename(title)}.html'
    output_path.write_text(html_text,encoding='utf-8')
    return str(output_path)

def main() -> int:
    args = parse_args()
    templates_dir = Path(args.templates_dir).expanduser().resolve()
    cms_dir = Path(args.cms_dir).expanduser().resolve()
    published_json = Path(args.published_json).expanduser().resolve()

    if args.index:
        items = build_index_items(cms_dir, published_json)
        output_path = Path(args.output) if args.output else Path("index.html")
        html_text = render_index_plain(args.site_title, items) if args.plain_html else \
                    render_index_with_template(templates_dir=templates_dir, page_title=args.site_title, items=items)
        output_path.write_text(html_text, encoding="utf-8")
        print(f"Wrote: {output_path}")
        print(f"Entries: {len(items)}")
        return 0

    story_path = resolve_story_path(args.input).expanduser().resolve()
    if not story_path.exists():
        raise FileNotFoundError(f"Missing story.md: {story_path}")
    story_text = story_path.read_text(encoding="utf-8")
    frontmatter, remainder = split_frontmatter(story_text)
    metadata = parse_simple_yaml(frontmatter)
    if has_dialog_blocks(remainder):
        remainder = preprocess_dialogs(remainder)
    body_html, first_h1 = markdown_to_html(remainder)
    story_title = first_h1 or metadata.get("title") or story_path.parent.name or "Story"
    output_path = Path(args.output) if args.output else story_path.with_suffix(".html")
    html_text = build_plain_html(story_title, body_html) if args.plain_html else \
                render_story_with_template(templates_dir=templates_dir, page_title=story_title,
                                           body_html=body_html, metadata=metadata,
                                           back_link="/")
    output_path.write_text(html_text, encoding="utf-8")
    print(f"Wrote: {output_path}")
    return 0
    
if __name__ == "__main__":
    raise SystemExit(main())
