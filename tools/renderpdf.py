from pathlib import Path
import re
import html
import hashlib
import sys

# ReportLab compatibility shim for some Python/OpenSSL builds
_real_md5 = hashlib.md5
def _compat_md5(*args, **kwargs):
    kwargs.pop("usedforsecurity", None)
    return _real_md5(*args, **kwargs)
hashlib.md5 = _compat_md5

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    ListFlowable,
    ListItem,
    HRFlowable,
    Image,
)

DEFAULT_SPEAKER_COLORS = [
    colors.orange,
    colors.HexColor("#2563eb"),
    colors.red,
    colors.HexColor("#059669"),
    colors.HexColor("#7c3aed"),
    colors.HexColor("#c2410c"),
]

IMAGE_ALIGN_MAP = {
    "left": "LEFT",
    "center": "CENTER",
    "right": "RIGHT",
}

INLINE_IMAGE_RE = re.compile(
    r'^!\[(.*?)\]\(([^/\\]+)\)(?:\{([^}]*)\})?$'
)



def strip_front_matter(text):
    if text.startswith("---"):
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if m:
            return m.group(1), text[m.end():]
    return "", text


def parse_front_matter(front_matter_text):
    """
    Very lightweight YAML-ish parser for simple key: value lines.
    Ignores nested blocks and comments.
    """
    metadata = {}
    for raw_line in front_matter_text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        metadata[key] = value
    return metadata


def parse_story(text):
    """
    Supports both:
    1) dialogue stories with triple-quoted speaker blocks
    2) prose-only stories with plain paragraphs after the title
    """
    front_matter_text, body_plus = strip_front_matter(text)
    metadata = parse_front_matter(front_matter_text)

    title_match = re.search(r"^# (.+)", body_plus, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "story"

    raw_blocks = re.findall(r'"""(.*?)\n(.*?)"""', body_plus, re.DOTALL)
    if raw_blocks:
        blocks = [(speaker.strip(), content.strip()) for speaker, content in raw_blocks]
        return metadata, title, blocks

    body = re.sub(r"^# .+\n?", "", body_plus, count=1, flags=re.MULTILINE).strip()

    if body:
        return metadata, title, [("", body)]
    return metadata, title, []


def parse_inline_image(line):
    m = INLINE_IMAGE_RE.match(line.strip())
    if not m:
        return None

    caption, filename, opts = m.groups()

    options = {
        "height_mm": None,
        "align": "center"
    }

    if opts:
        parts = [p.strip() for p in opts.split() if p.strip()]
        for p in parts:
            if p.startswith("height="):
                try:
                    options["height_mm"] = float(p.split("=")[1])
                except:
                    pass
            elif p.startswith("align="):
                val = p.split("=")[1].lower()
                if val in ("left", "center", "right"):
                    options["align"] = val

    return caption, filename, options

def safe_filename(title, max_length=120):
    name = re.sub(r'[\\/*?:"<>|]', "", title or "")
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > max_length:
        name = name[:max_length].rstrip()
    return name or "story"


def resolve_input_path(input_path):
    path = Path(input_path)
    if path.is_dir():
        story_path = path / "story.md"
        if not story_path.exists():
            raise FileNotFoundError(f"No story.md found in {path}")
        return story_path
    return path


def resolve_output_path(input_path, title, output_path=None):
    input_path = Path(input_path)

    if output_path:
        return Path(output_path)

    filename = safe_filename(title)

    if input_path.is_dir():
        return input_path / f"{filename}.pdf"

    return input_path.with_name(f"{filename}.pdf")


def resolve_inline_image_path(story_path, filename):
    entry_dir = Path(story_path).parent
    img_path = entry_dir / "images" / filename
    if img_path.exists():
        return img_path
    return None


def parse_color_list(color_string):
    if not color_string:
        return None

    result = []
    parts = [c.strip() for c in color_string.split(",") if c.strip()]

    for p in parts:
        try:
            if re.fullmatch(r"#[0-9A-Fa-f]{6}", p):
                result.append(colors.HexColor(p))
        except Exception:
            pass

    return result if result else None


def parse_header_fields(header_fields):
    if not header_fields:
        return None
    return [x.strip() for x in header_fields.split(",") if x.strip()]


def looks_meaningful_header_value(value):
    if value is None:
        return False
    value = str(value).strip()
    if not value:
        return False
    if value in {"[]", "{}", "[0, 0]", "[1.0, 1.0]", "0", "0.0"}:
        return False
    return True


def prettify_field_name(name):
    pretty_map = {
        "created_utc": "Created",
        "datetime": "Date",
        "edit_date": "Edit Date",
        "location_text": "Location",
        "entry_id": "Entry ID",
        "source": "Source",
        "source_url": "Source URL",
        "year": "Year",
        "author": "Author",
        "status": "Status",
        "tags": "Tags",
    }
    if name in pretty_map:
        return pretty_map[name]
    return " ".join(part.capitalize() for part in name.split("_"))


def select_header_items(metadata, header_fields=None):
    """
    Default behavior:
    - use fields discovered in the YAML/front matter
    - include only fields with meaningful values

    Optional behavior:
    - if header_fields is provided, only those fields are considered
    """
    if header_fields:
        candidate_keys = header_fields
    else:
        candidate_keys = list(metadata.keys())

    items = []
    for key in candidate_keys:
        if key not in metadata:
            continue
        value = metadata.get(key, "")
        if not looks_meaningful_header_value(value):
            continue
        items.append((prettify_field_name(key), str(value).strip()))

    return items


def find_illustration_image(story_path):
    entry_dir = Path(story_path).parent

    for name in ("illustration.jpg", "illustration.jpeg", "illustration.png"):
        candidate = entry_dir / name
        if candidate.exists():
            return candidate

    images = []
    for pattern in ("*.jpg", "*.jpeg", "*.png"):
        images.extend(entry_dir.glob(pattern))

    images = sorted(p for p in images if p.is_file())

    if len(images) == 1:
        return images[0]

    return None


def markup_inline(text):
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(.+?)\*(?!\*)", r"<i>\1</i>", text)
    return text

def emit_rich_text(flow, content, body_style, bullet_style, aside_style, story_path):
    """
    Render a block of prose with paragraphs and bullet lists.
    Blank lines split paragraphs. Lines starting with '* ' become bullets.
    """
    lines = content.splitlines()
    paragraph_buffer = []
    bullet_buffer = []

    def flush_paragraph():
        if not paragraph_buffer:
            return
        paragraph_text = " ".join(x.strip() for x in paragraph_buffer if x.strip()).strip()
        paragraph_buffer.clear()
        if not paragraph_text:
            return

        style = aside_style if paragraph_text.startswith("(") and paragraph_text.endswith(")") else body_style
        flow.append(Paragraph(markup_inline(paragraph_text), style))

    def flush_bullets():
        if not bullet_buffer:
            return

        items = []
        for item in bullet_buffer:
            item_text = item.strip()
            if not item_text:
                continue
            items.append(ListItem(Paragraph(markup_inline(item_text), bullet_style), leftIndent=0))

        bullet_buffer.clear()

        if items:
            flow.append(
                ListFlowable(
                    items,
                    bulletType="bullet",
                    start="circle",
                    leftIndent=14,
                    bulletFontName="Helvetica",
                    bulletFontSize=9,
                    bulletOffsetY=2,
                    spaceBefore=2,
                    spaceAfter=8,
                )
            )


    for raw_line in lines:
        line = raw_line.strip()

        if not line:
            flush_paragraph()
            flush_bullets()
            continue

        if line.startswith("* "):
            flush_paragraph()
            bullet_buffer.append(line[2:].strip())
            continue

        if line.startswith("!"):
            parsed = parse_inline_image(line)
            if parsed:
                flush_paragraph()
                flush_bullets()

                caption, filename, opts = parsed
                img_path = resolve_inline_image_path(story_path, filename)

                if img_path:
                    img = Image(str(img_path))
                    height_mm = opts["height_mm"] or 60
                    img._restrictSize(170 * mm, height_mm * mm)
                    img.hAlign = IMAGE_ALIGN_MAP.get(opts["align"], "CENTER")

                    flow.append(img)

                    if caption:
                        flow.append(Paragraph(markup_inline(caption), aside_style))

                    flow.append(Spacer(1, 6 * mm))

                continue

        if line.endswith(":"):
            flush_paragraph()
            flush_bullets()
            paragraph_buffer.append(line)
            flush_paragraph()
            continue

        flush_bullets()
        paragraph_buffer.append(line)

    flush_paragraph()
    flush_bullets()


def build_story_flowables(
    title,
    blocks,
    metadata=None,
    header_fields=None,
    illustration_path=None,
    image_height_mm=65,
    image_align="center",
    heading_colors=None,
    story_dir = '.',
):
    styles = getSampleStyleSheet()
    speaker_palette = heading_colors or DEFAULT_SPEAKER_COLORS

    title_style = ParagraphStyle(
        "StoryTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=21,
        leading=25,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#1f2937"),
        spaceAfter=10,
    )

    header_style = ParagraphStyle(
        "HeaderField",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.4,
        leading=12,
        textColor=colors.HexColor("#4b5563"),
        spaceAfter=2,
        alignment=TA_LEFT,
    )

    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11.2,
        leading=16,
        textColor=colors.HexColor("#111827"),
        spaceAfter=8,
        alignment=TA_LEFT,
    )

    bullet_style = ParagraphStyle(
        "BulletBody",
        parent=body_style,
        leftIndent=0,
        firstLineIndent=0,
        spaceAfter=2,
    )

    aside_style = ParagraphStyle(
        "Aside",
        parent=body_style,
        fontName="Helvetica-Oblique",
        textColor=colors.HexColor("#374151"),
        leftIndent=8,
        spaceAfter=8,
    )

    flow = []
    flow.append(Paragraph(markup_inline(title), title_style))
    flow.append(Spacer(1, 2 * mm))

    header_items = select_header_items(metadata or {}, header_fields=header_fields)
    if header_items:
        for label, value in header_items:
            flow.append(Paragraph(f"<b>{html.escape(label)}:</b> {markup_inline(value)}", header_style))
        flow.append(Spacer(1, 4 * mm))

    flow.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#d1d5db")))
    flow.append(Spacer(1, 5 * mm))

    if illustration_path is not None:
        img = Image(str(illustration_path))
        img._restrictSize(170 * mm, float(image_height_mm) * mm)
        img.hAlign = IMAGE_ALIGN_MAP.get(image_align, "CENTER")
        flow.append(img)
        flow.append(Spacer(1, 6 * mm))

    # prose-only mode: one unnamed block
    if len(blocks) == 1 and not blocks[0][0].strip():
        emit_rich_text(flow, blocks[0][1], body_style, bullet_style, aside_style, story_dir)
        return flow

    speaker_color_map = {}
    next_color_index = 0

    def get_speaker_color(speaker):
        nonlocal next_color_index
        key = speaker.strip().lower()
        if key not in speaker_color_map:
            speaker_color_map[key] = speaker_palette[next_color_index % len(speaker_palette)]
            next_color_index += 1
        return speaker_color_map[key]

    def make_speaker_style(speaker):
        return ParagraphStyle(
            f"Speaker_{speaker}",
            parent=styles["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=15,
            textColor=get_speaker_color(speaker),
            spaceBefore=10,
            spaceAfter=6,
        )

    for i, (speaker, content) in enumerate(blocks):
        if i > 0:
            flow.append(Spacer(1, 4 * mm))

        if speaker.strip():
            flow.append(Paragraph(html.escape(speaker), make_speaker_style(speaker)))

        emit_rich_text(flow, content, body_style, bullet_style, aside_style)

    return flow


def generate_pdf(
    input_path=".",
    output_path=None,
    image_height_mm=65,
    image_align="center",
    heading_colors=None,
    header_fields=None,
):
    story_path = resolve_input_path(input_path)
    text = story_path.read_text(encoding="utf-8")
    metadata, title, blocks = parse_story(text)

    output_path = resolve_output_path(input_path, title, output_path)
    illustration_path = find_illustration_image(story_path)
    parsed_heading_colors = parse_color_list(heading_colors)
    parsed_header_fields = parse_header_fields(header_fields)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="Heichalot-CMS",
    )

    flow = build_story_flowables(
        title,
        blocks,
        metadata=metadata,
        header_fields=parsed_header_fields,
        illustration_path=illustration_path,
        image_height_mm=image_height_mm,
        image_align=image_align,
        heading_colors=parsed_heading_colors,
    )
    doc.build(flow)
    return output_path


def main(args=None):
    if args is None:
        args = sys.argv[1:]

    image_height_mm = 65
    image_align = "center"
    heading_colors = None
    header_fields = None

    positional = []
    i = 0
    while i < len(args):
        if args[i] == "--image-height-mm" and i + 1 < len(args):
            image_height_mm = float(args[i + 1])
            i += 2
        elif args[i] == "--image-align" and i + 1 < len(args):
            image_align = args[i + 1].lower()
            i += 2
        elif args[i] == "--heading-colors" and i + 1 < len(args):
            heading_colors = args[i + 1]
            i += 2
        elif args[i] == "--header-fields" and i + 1 < len(args):
            header_fields = args[i + 1]
            i += 2
        else:
            positional.append(args[i])
            i += 1

    input_path = positional[0] if len(positional) >= 1 else "."
    output_path = positional[1] if len(positional) >= 2 else None

    out = generate_pdf(
        input_path=input_path,
        output_path=output_path,
        image_height_mm=image_height_mm,
        image_align=image_align,
        heading_colors=heading_colors,
        header_fields=header_fields,
    )
    print(f"Wrote: {out}")


if __name__ == "__main__":
    main()
