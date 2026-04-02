from pathlib import Path
import re
import html
import sys

INLINE_IMAGE_RE = re.compile(r'^!\[(.*?)\]\(([^/\\]+)\)(?:\{([^}]*)\})?$')


def strip_front_matter(text):
    if text.startswith('---'):
        m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
        if m:
            return m.group(1), text[m.end():]
    return '', text


def parse_front_matter(front_matter_text):
    metadata = {}
    for raw_line in front_matter_text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith('#') or ':' not in line:
            continue
        key, value = line.split(':', 1)
        metadata[key.strip()] = value.strip()
    return metadata


def parse_story(text):
    front_matter_text, body_plus = strip_front_matter(text)
    metadata = parse_front_matter(front_matter_text)

    title_match = re.search(r'^# (.+)', body_plus, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else 'story'

    raw_blocks = re.findall(r'"""(.*?)\n(.*?)"""', body_plus, re.DOTALL)
    if raw_blocks:
        blocks = [(speaker.strip(), content.strip()) for speaker, content in raw_blocks]
        return metadata, title, blocks

    body = re.sub(r'^# .+\n?', '', body_plus, count=1, flags=re.MULTILINE).strip()
    if body:
        return metadata, title, [('', body)]
    return metadata, title, []


def safe_filename(title, max_length=120):
    name = re.sub(r'[\\/*?:"<>|]', '', title or '')
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > max_length:
        name = name[:max_length].rstrip()
    return name or 'story'


def resolve_input_path(input_path):
    path = Path(input_path)
    if path.is_dir():
        story_path = path / 'story.md'
        if not story_path.exists():
            raise FileNotFoundError(f'No story.md found in {path}')
        return story_path
    return path


def resolve_output_path(input_path, title, output_path=None):
    input_path = Path(input_path)
    if output_path:
        return Path(output_path)
    filename = safe_filename(title)
    if input_path.is_dir():
        return input_path / f'{filename}.html'
    return input_path.with_name(f'{filename}.html')


def parse_header_fields(header_fields):
    if not header_fields:
        return None
    return [x.strip() for x in header_fields.split(',') if x.strip()]


def looks_meaningful_header_value(value):
    if value is None:
        return False
    value = str(value).strip()
    if not value:
        return False
    if value in {'[]', '{}', '[0, 0]', '[1.0, 1.0]', '0', '0.0'}:
        return False
    return True


def prettify_field_name(name):
    pretty_map = {
        'created_utc': 'Created',
        'datetime': 'Date',
        'edit_date': 'Edit Date',
        'location_text': 'Location',
        'entry_id': 'Entry ID',
        'source': 'Source',
        'source_url': 'Source URL',
        'year': 'Year',
        'author': 'Author',
        'status': 'Status',
        'tags': 'Tags',
    }
    if name in pretty_map:
        return pretty_map[name]
    return ' '.join(part.capitalize() for part in name.split('_'))


def select_header_items(metadata, header_fields=None):
    candidate_keys = header_fields if header_fields else list(metadata.keys())
    items = []
    for key in candidate_keys:
        if key not in metadata:
            continue
        value = metadata.get(key, '')
        if not looks_meaningful_header_value(value):
            continue
        items.append((prettify_field_name(key), str(value).strip()))
    return items


def find_illustration_image(story_path):
    entry_dir = Path(story_path).parent

    for name in ('illustration.jpg', 'illustration.jpeg', 'illustration.png'):
        candidate = entry_dir / name
        if candidate.exists():
            return candidate

    images = []
    for pattern in ('*.jpg', '*.jpeg', '*.png'):
        images.extend(entry_dir.glob(pattern))

    images = sorted(p for p in images if p.is_file())
    if len(images) == 1:
        return images[0]
    return None


def resolve_inline_image_path(story_path, filename):
    entry_dir = Path(story_path).parent
    img_path = entry_dir / 'images' / filename
    if img_path.exists():
        return img_path
    return None


def parse_inline_image(line):
    m = INLINE_IMAGE_RE.match(line.strip())
    if not m:
        return None

    caption, filename, opts = m.groups()
    options = {'height_px': None, 'align': 'center'}

    if opts:
        for part in [p.strip() for p in opts.split() if p.strip()]:
            if part.startswith('height='):
                try:
                    options['height_px'] = int(float(part.split('=', 1)[1]))
                except Exception:
                    pass
            elif part.startswith('align='):
                val = part.split('=', 1)[1].lower()
                if val in ('left', 'center', 'right'):
                    options['align'] = val

    return caption, filename, options


def markup_inline(text):
    text = html.escape(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*(.+?)\*(?!\*)', r'<em>\1</em>', text)
    return text


def image_style_attr(height_px=None, align='center'):
    style_parts = []
    if height_px:
        style_parts.append(f'max-height:{int(height_px)}px')
        style_parts.append('width:auto')
    else:
        style_parts.append('max-width:100%')
        style_parts.append('height:auto')

    if align == 'left':
        style_parts.append('display:block')
        style_parts.append('margin:0 0 1em 0')
    elif align == 'right':
        style_parts.append('display:block')
        style_parts.append('margin:0 0 1em auto')
    else:
        style_parts.append('display:block')
        style_parts.append('margin:0 auto 1em auto')

    return '; '.join(style_parts)


def render_rich_text(content, story_path):
    parts = []
    lines = content.splitlines()
    paragraph_buffer = []
    bullet_buffer = []

    def flush_paragraph():
        if not paragraph_buffer:
            return
        paragraph_text = ' '.join(x.strip() for x in paragraph_buffer if x.strip()).strip()
        paragraph_buffer.clear()
        if not paragraph_text:
            return

        cls = 'story-aside' if paragraph_text.startswith('(') and paragraph_text.endswith(')') else 'story-paragraph'
        parts.append(f'<p class="{cls}">{markup_inline(paragraph_text)}</p>')

    def flush_bullets():
        if not bullet_buffer:
            return
        items = []
        for item in bullet_buffer:
            item_text = item.strip()
            if item_text:
                items.append(f'<li>{markup_inline(item_text)}</li>')
        bullet_buffer.clear()
        if items:
            parts.append('<ul>\n' + '\n'.join(items) + '\n</ul>')

    for raw_line in lines:
        line = raw_line.strip()

        if not line:
            flush_paragraph()
            flush_bullets()
            continue

        if line.startswith('* '):
            flush_paragraph()
            bullet_buffer.append(line[2:].strip())
            continue

        parsed = parse_inline_image(line)
        if parsed:
            flush_paragraph()
            flush_bullets()

            caption, filename, opts = parsed
            img_path = resolve_inline_image_path(story_path, filename)

            if img_path:
                rel_src = f'images/{filename}'
                style_attr = image_style_attr(opts['height_px'], opts['align'])
                parts.append(f'<img src="{html.escape(rel_src)}" alt="{html.escape(caption)}" style="{style_attr}">')
                if caption:
                    parts.append(f'<p class="image-caption">{markup_inline(caption)}</p>')
            continue

        if line.endswith(':'):
            flush_paragraph()
            flush_bullets()
            paragraph_buffer.append(line)
            flush_paragraph()
            continue

        flush_bullets()
        paragraph_buffer.append(line)

    flush_paragraph()
    flush_bullets()
    return '\n'.join(parts)


def render_html_document(
    metadata,
    title,
    blocks,
    story_path,
    header_fields=None,
    illustration_path=None,
    image_height_px=420,
    image_align='center',
    fragment=False,
):
    header_items = select_header_items(metadata or {}, header_fields=header_fields)

    body = []
    body.append('<article class="story-entry">')
    body.append(f'<h1>{markup_inline(title)}</h1>')

    if header_items:
        body.append('<div class="story-header-fields">')
        for label, value in header_items:
            body.append(f'<p class="story-header-field"><strong>{html.escape(label)}:</strong> {markup_inline(value)}</p>')
        body.append('</div>')

    if illustration_path is not None:
        rel_src = html.escape(illustration_path.name)
        style_attr = image_style_attr(image_height_px, image_align)
        body.append(f'<img src="{rel_src}" alt="Illustration" class="story-illustration" style="{style_attr}">')

    if len(blocks) == 1 and not blocks[0][0].strip():
        body.append(render_rich_text(blocks[0][1], story_path))
    else:
        for speaker, content in blocks:
            body.append('<section class="story-block">')
            if speaker.strip():
                body.append(f'<h2>{html.escape(speaker)}</h2>')
            body.append(render_rich_text(content, story_path))
            body.append('</section>')

    body.append('</article>')
    article_html = '\n'.join(body)

    if fragment:
        return article_html

    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
</head>
<body>
{article_html}
</body>
</html>
'''


def generate_html(
    input_path='.',
    output_path=None,
    fragment=False,
    header_fields=None,
    image_height_px=420,
    image_align='center',
):
    story_path = resolve_input_path(input_path)
    text = story_path.read_text(encoding='utf-8')
    metadata, title, blocks = parse_story(text)

    output_path = resolve_output_path(input_path, title, output_path)
    illustration_path = find_illustration_image(story_path)
    parsed_header_fields = parse_header_fields(header_fields)

    html_text = render_html_document(
        metadata=metadata,
        title=title,
        blocks=blocks,
        story_path=story_path,
        header_fields=parsed_header_fields,
        illustration_path=illustration_path,
        image_height_px=image_height_px,
        image_align=image_align,
        fragment=fragment,
    )

    Path(output_path).write_text(html_text, encoding='utf-8')
    return output_path


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    fragment = False
    header_fields = None
    image_height_px = 420
    image_align = 'center'

    positional = []
    i = 0
    while i < len(args):
        if args[i] == '--fragment':
            fragment = True
            i += 1
        elif args[i] == '--header-fields' and i + 1 < len(args):
            header_fields = args[i + 1]
            i += 2
        elif args[i] == '--image-height-px' and i + 1 < len(args):
            image_height_px = int(float(args[i + 1]))
            i += 2
        elif args[i] == '--image-align' and i + 1 < len(args):
            image_align = args[i + 1].lower()
            i += 2
        else:
            positional.append(args[i])
            i += 1

    input_path = positional[0] if len(positional) >= 1 else '.'
    output_path = positional[1] if len(positional) >= 2 else None

    out = generate_html(
        input_path=input_path,
        output_path=output_path,
        fragment=fragment,
        header_fields=header_fields,
        image_height_px=image_height_px,
        image_align=image_align,
    )
    print(f'Wrote: {out}')


if __name__ == '__main__':
    main()
