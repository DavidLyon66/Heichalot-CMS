# renderpdf_slideparser_body_v2.py
from pathlib import Path
import re, html, hashlib, argparse, shutil, subprocess
from datetime import datetime
_real_md5 = hashlib.md5
def _compat_md5(*args, **kwargs):
    kwargs.pop("usedforsecurity", None)
    return _real_md5(*args, **kwargs)
hashlib.md5 = _compat_md5

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem, HRFlowable, Image, PageBreak, Flowable, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

try:
    from bidi.algorithm import get_display as bidi_get_display
except ImportError:
    bidi_get_display = None

INLINE_IMAGE_RE = re.compile(r'^!\[(.*?)\]\(([^/\\]+)\)(?:\{([^}]*)\})?$')
IMAGE_ALIGN_MAP = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}
DEFAULT_SPEAKER_COLORS = [colors.orange, colors.HexColor("#2563eb"), colors.red, colors.HexColor("#059669"), colors.HexColor("#7c3aed"), colors.HexColor("#c2410c")]

HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
HEBREW_RUN_RE = re.compile(r'([\u0590-\u05FF\uFB1D-\uFB4F]+(?:[ \u05BE׳״]+[\u0590-\u05FF\uFB1D-\uFB4F]+)*)')
HEBREW_FONT_NAME = "HeichalotHebrew"
HEBREW_BOLD_FONT_NAME = "HeichalotHebrewBold"
ENABLED_LANGUAGES = set()

LARGE_IMAGE_BYTES = 800 * 1024
PUBLISH_IMAGE_MAX_DIMENSION = 1200
PUBLISH_IMAGE_JPEG_QUALITY = 78

def parse_bool(value):
    value = str(value).strip().lower()
    if value in ("1", "true", "yes", "y", "on"):
        return True
    if value in ("0", "false", "no", "n", "off"):
        return False
    raise argparse.ArgumentTypeError("expected true or false")

def check_image_sizes(base_dir):
    """Reduce oversized images in <base_dir>/images before rendering.

    Originals are preserved in <base_dir>/private.  This deliberately mirrors
    publishentry.py's ImageMagick settings, but processes every image without
    prompting so it can act as a lightweight render preflight.
    """
    base_dir = Path(base_dir)
    images_dir = base_dir / "images"
    if not images_dir.is_dir():
        return

    images = sorted(
        p for p in images_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    large_images = []
    for image in images:
        try:
            if image.stat().st_size > LARGE_IMAGE_BYTES:
                large_images.append(image)
        except OSError:
            pass
    if not large_images:
        return

    which_result = subprocess.run(["which", "convert"], capture_output=True, text=True)
    if which_result.returncode != 0:
        print("⚠ Large images found, but ImageMagick 'convert' is not installed; leaving them unchanged.")
        return
    convert_cmd = which_result.stdout.strip() or "convert"
    private_dir = base_dir / "private"
    private_dir.mkdir(parents=True, exist_ok=True)
    geometry = f"{PUBLISH_IMAGE_MAX_DIMENSION}x{PUBLISH_IMAGE_MAX_DIMENSION}>"

    for image in large_images:
        size_kb = image.stat().st_size / 1024
        temp_output = images_dir / f".{image.stem}-renderpdf-reduced.jpg"
        try:
            subprocess.run([convert_cmd, str(image), "-resize", geometry, "-strip", "-quality", str(PUBLISH_IMAGE_JPEG_QUALITY), str(temp_output)], check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            if temp_output.exists():
                temp_output.unlink()
            print(f"⚠ Image reduction failed for {image.name}; original left unchanged: {exc}")
            continue
        if not temp_output.exists() or temp_output.stat().st_size == 0:
            if temp_output.exists():
                temp_output.unlink()
            print(f"⚠ Image reduction produced no output for {image.name}; original left unchanged.")
            continue

        private_original = private_dir / image.name
        if private_original.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            private_original = private_dir / f"{image.stem}-{stamp}{image.suffix}"
        output_image = image.with_suffix(".jpg")
        shutil.move(str(image), str(private_original))
        if output_image.exists() and output_image != image:
            output_image.unlink()
        temp_output.replace(output_image)
        new_size_kb = output_image.stat().st_size / 1024
        print(f"✔ Reduced image: {image.name} ({size_kb:.0f} KB → {new_size_kb:.0f} KB)")
        print(f"  Original moved to: {private_original}")

def parse_languages(value):
    if not value:
        return set()
    aliases = {"he": "hebrew", "heb": "hebrew", "yi": "yiddish", "yid": "yiddish"}
    result = set()
    for item in value.split(","):
        lang = item.strip().lower()
        if lang:
            result.add(aliases.get(lang, lang))
    return result

def _find_font_file(candidates):
    for candidate in candidates:
        p = Path(candidate).expanduser()
        if p.exists():
            return p
    return None

def configure_languages(languages):
    global ENABLED_LANGUAGES
    ENABLED_LANGUAGES = set(languages or ())
    if not (ENABLED_LANGUAGES & {"hebrew", "yiddish"}):
        return
    regular = _find_font_file([
        "/usr/share/fonts/truetype/noto/NotoSansHebrew-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerifHebrew-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansHebrew-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSerifHebrew-Regular.ttf",
        "~/.local/share/fonts/NotoSansHebrew-Regular.ttf",
        "~/.fonts/NotoSansHebrew-Regular.ttf",
    ])
    bold = _find_font_file([
        "/usr/share/fonts/truetype/noto/NotoSansHebrew-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSerifHebrew-Bold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansHebrew-Bold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSerifHebrew-Bold.ttf",
        "~/.local/share/fonts/NotoSansHebrew-Bold.ttf",
        "~/.fonts/NotoSansHebrew-Bold.ttf",
    ]) or regular
    if regular is None:
        raise RuntimeError(
            "Hebrew/Yiddish rendering requested, but no Noto Hebrew font was found. "
            "Install Noto Sans Hebrew (for Debian/Ubuntu: fonts-noto-core) and try again."
        )
    if HEBREW_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(HEBREW_FONT_NAME, str(regular)))
    if HEBREW_BOLD_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(HEBREW_BOLD_FONT_NAME, str(bold)))

def contains_hebrew(text):
    return bool(HEBREW_RE.search(str(text or "")))

# Explicit directional embedding characters.  python-bidi 0.6.x implements
# these reliably; unlike the newer isolate controls, they are accepted by both
# its Python and Rust-backed implementations.
_LRE = "\u202A"   # begin left-to-right embedding
_PDF = "\u202C"   # end directional embedding

# An ASCII/Latin "island" inside Hebrew prose.  Spaces are included only when
# they join Latin words, so "Eretz Or", "Ost | ra | liye" and similar phrases
# stay in their natural LTR order without swallowing surrounding Hebrew.
_LATIN_ISLAND_RE = re.compile(
    r"""(?x)
    (?<![A-Za-z0-9])
    (
      [A-Za-z0-9]+(?:[-./+][A-Za-z0-9]+)*
      (?:
        \s+
        (?:[|+→=/:-]\s*)?
        [A-Za-z0-9]+(?:[-./+][A-Za-z0-9]+)*
      )*
    )
    (?![A-Za-z0-9])
    """
)

def _protect_latin_islands(text):
    """Mark embedded Latin phrases as LTR before applying the bidi algorithm."""
    return _LATIN_ISLAND_RE.sub(lambda m: _LRE + m.group(1) + _PDF, text)

def _bidi_visual_text(text):
    """Convert mixed Hebrew/Latin Unicode text to visual order for ReportLab."""
    if not (ENABLED_LANGUAGES & {"hebrew", "yiddish"}) or not contains_hebrew(text):
        return text
    if bidi_get_display is None:
        raise RuntimeError(
            "Hebrew/Yiddish rendering requires python-bidi. "
            "Install it for this Python with: python3.9 -m pip install python-bidi"
        )
    protected = _protect_latin_islands(text)
    return bidi_get_display(protected, base_dir="R")

def _font_hebrew_runs(escaped_text):
    if not (ENABLED_LANGUAGES & {"hebrew", "yiddish"}):
        return escaped_text
    return HEBREW_RUN_RE.sub(
        lambda m: f'<font name="{HEBREW_FONT_NAME}">{m.group(0)}</font>',
        escaped_text,
    )

def strip_front_matter(text):
    if text.startswith("---"):
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if m:
            return m.group(1), text[m.end():]
    return "", text

def parse_front_matter(front_matter_text):
    metadata = {}
    current_key = None
    for raw_line in front_matter_text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.startswith("  ") and current_key and isinstance(metadata.get(current_key), dict):
            if ":" in line:
                k, v = line.strip().split(":", 1)
                metadata[current_key][k.strip()] = v.strip()
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            key, value = key.strip(), value.strip()
            if value == "":
                metadata[key] = {}
                current_key = key
            else:
                metadata[key] = value
                current_key = None
    return metadata

def parse_story(text):
    front_matter_text, body_plus = strip_front_matter(text)
    metadata = parse_front_matter(front_matter_text)
    title_match = re.search(r"^# (.+)", body_plus, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "story"
    raw_blocks = re.findall(r'"""(.*?)\n(.*?)"""', body_plus, re.DOTALL)
    if raw_blocks:
        blocks = [(speaker.strip(), content.strip()) for speaker, content in raw_blocks]
        return metadata, title, blocks
    body = re.sub(r"^# .+\n?", "", body_plus, count=1, flags=re.MULTILINE).strip()
    return metadata, title, [("", body)] if body else []


def parse_slides(text):
    front_matter_text, body = strip_front_matter(text)
    metadata = parse_front_matter(front_matter_text)

    chunks = re.split(r'^\s*---\s*$', body, flags=re.MULTILINE)
    slides = []

    for chunk in chunks:
        lines = [l.rstrip() for l in chunk.splitlines() if l.strip()]
        if not lines:
            continue

        title_lines = []
        content_lines = []

        for line in lines:
            if line.startswith("# "):
                title_lines.append(line[2:].strip())
            else:
                content_lines.append(line)

        if not title_lines:
            if content_lines:
                title_lines = [content_lines[0].strip()]
                content_lines = content_lines[1:]
            else:
                title_lines = ["Slide"]

        slide = {
            "title": title_lines[0],
            "title_lines": title_lines,
            "image": None,
            "background": None,
            "bullets": [],
            "body": [],
        }

        for line in content_lines:
            parsed = parse_inline_image(line)
            if parsed:
                caption, filename, opts = parsed
                img_def = {
                    "caption": caption,
                    "filename": filename,
                    "opts": opts,
                }

                if opts.get("background") and slide["background"] is None:
                    slide["background"] = img_def
                    continue

                if slide["image"] is None:
                    slide["image"] = img_def
                    continue

            if line.startswith("* ") or line.startswith("- "):
                slide["bullets"].append(line[2:].strip())
            else:
                slide["body"].append(line.strip())

        slides.append(slide)

    title = metadata.get("title") if isinstance(metadata.get("title"), str) and metadata.get("title").strip() else "slides"
    return metadata, title, slides

def parse_inline_image(line):
    m = INLINE_IMAGE_RE.match(line.strip())
    if not m:
        return None
    caption, filename, opts = m.groups()
    options = {"height_mm": None, "align": "center", "background": False}
    if opts:
        for p in [p.strip() for p in opts.split() if p.strip()]:
            if p.startswith("height="):
                try:
                    options["height_mm"] = float(p.split("=", 1)[1])
                except Exception:
                    pass
            elif p.startswith("align="):
                val = p.split("=", 1)[1].lower()
                if val in ("left", "center", "right"):
                    options["align"] = val
            elif p == "background":
                options["background"] = True
    return caption, filename, options

def resolve_inline_image_path(story_path, filename):
    p = Path(story_path).parent / "images" / filename
    return p if p.exists() else None

def safe_filename(title, max_length=120):
    name = re.sub(r'[\\/*?:"<>|]', "", title or "")
    name = re.sub(r"\s+", " ", name).strip()
    if len(name) > max_length:
        name = name[:max_length].rstrip()
    return name or "story"

def parse_header_fields(header_fields):
    return [x.strip() for x in header_fields.split(",") if x.strip()] if header_fields else None

def looks_meaningful_header_value(value):
    if value is None:
        return False
    value = str(value).strip()
    return bool(value) and value not in {"[]", "{}", "[0, 0]", "[1.0, 1.0]", "0", "0.0"}

def prettify_field_name(name):
    pretty_map = {"created_utc": "Created", "datetime": "Date", "edit_date": "Edit Date", "location_text": "Location", "entry_id": "Entry ID", "source": "Source", "source_url": "Source URL", "year": "Year", "author": "Author", "status": "Status", "tags": "Tags"}
    return pretty_map.get(name, " ".join(part.capitalize() for part in name.split("_")))

def select_header_items(metadata, header_fields=None):
    candidate_keys = header_fields if header_fields else list(metadata.keys())
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
    return images[0] if len(images) == 1 else None

def parse_color_list(color_string):
    if not color_string:
        return None
    result = []
    for p in [c.strip() for c in color_string.split(",") if c.strip()]:
        if re.fullmatch(r"#[0-9A-Fa-f]{6}", p):
            result.append(colors.HexColor(p))
    return result or None

def parse_font(font_string, default_name, default_size, default_color=colors.black):
    if not font_string:
        return default_name, default_size, default_color
    parts = [p.strip() for p in font_string.split(",")]
    name, size, color = default_name, default_size, default_color
    if len(parts) >= 1 and parts[0]:
        name = parts[0]
    if len(parts) >= 2:
        try: size = float(parts[1])
        except Exception: pass
    if len(parts) >= 3:
        try: color = colors.HexColor(parts[2])
        except Exception: pass
    return name, size, color

def extract_slide_config(metadata):
    slide = metadata.get("slide", {})
    if not isinstance(slide, dict):
        return {}
    def _f(v, d):
        try: return float(v)
        except Exception: return d
    return {"title_font": slide.get("title_font"), "heading_font": slide.get("heading_font"), "bullet_font": slide.get("bullet_font"), "body_font": slide.get("body_font"), "background_dim": _f(slide.get("background_dim", 0.35), 0.35), "title_align": str(slide.get("title_align", "left")).strip().lower(), "body_align": str(slide.get("body_align", "left")).strip().lower()}

def markup_inline(text):
    text = _bidi_visual_text(text)
    text = html.escape(text)
    text = _font_hebrew_runs(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(.+?)\*(?!\*)", r"<i>\1</i>", text)
    return text

def _markdown_table_cells(line):
    """Return pipe-separated cells, respecting escaped literal pipes."""
    line = line.strip()
    if not line.startswith("|"):
        return None
    line = line.strip("|")
    return [cell.strip().replace(r"\|", "|") for cell in re.split(r"(?<!\\)\|", line)]


def _markdown_table_separator(cells):
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c.strip()) for c in cells)


def _append_markdown_table(flow, rows, body_style):
    """Render a standard Markdown table as a splitting ReportLab table."""
    if not rows:
        return
    count = len(rows[0])
    if not count:
        return
    # A4 story mode has 170 mm usable width (20 mm margins each side).
    available_width = 170 * mm
    widths = [available_width / count] * count
    cell_style = ParagraphStyle("MarkdownTableCell", parent=body_style,
        fontSize=9, leading=12, spaceAfter=0)
    header_style = ParagraphStyle("MarkdownTableHeader", parent=cell_style,
        fontName="Helvetica-Bold", textColor=colors.white)
    data = []
    for row_index, row in enumerate(rows):
        padded = (row + [""] * count)[:count]
        style = header_style if row_index == 0 else cell_style
        data.append([Paragraph(markup_inline(cell), style) for cell in padded])
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#374151")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#d1d5db")),
    ]))
    flow.append(table)
    flow.append(Spacer(1, 4 * mm))


def emit_rich_text(flow, content, body_style, bullet_style, aside_style, story_path):
    # Do not use splitlines(): Python treats ASCII FF (0x0C) as a line boundary
    # and would discard the page-break marker before we can process it.
    lines = content.split("\n")
    paragraph_buffer, bullet_buffer, quote_buffer = [], [], []
    table_buffer = []

    def flush_paragraph():
        if not paragraph_buffer: return
        paragraph_text = " ".join(x.strip() for x in paragraph_buffer if x.strip()).strip()
        paragraph_buffer.clear()
        if not paragraph_text: return
        style = aside_style if paragraph_text.startswith("(") and paragraph_text.endswith(")") else body_style
        if contains_hebrew(paragraph_text) and (ENABLED_LANGUAGES & {"hebrew", "yiddish"}):
            style = ParagraphStyle(style.name + "_RTL", parent=style, alignment=TA_RIGHT)
        flow.append(Paragraph(markup_inline(paragraph_text), style))

    def flush_bullets():
        if not bullet_buffer: return
        items = [ListItem(Paragraph(markup_inline(item.strip()), bullet_style), leftIndent=0) for item in bullet_buffer if item.strip()]
        bullet_buffer.clear()
        if items:
            flow.append(ListFlowable(items, bulletType="bullet", start="circle", leftIndent=14, bulletFontName="Helvetica", bulletFontSize=9, bulletOffsetY=2, spaceBefore=2, spaceAfter=8))

    def flush_quote():
        if not quote_buffer:
            return

        # A line beginning with the Unicode box character "│" is a
        # Heichalot-CMS ChatGPT response line.  Do not print the character;
        # render the whole consecutive group as one block with a real rule.
        quote_parts = []
        paragraph_lines = []

        def flush_quote_paragraph():
            if not paragraph_lines:
                return
            text = " ".join(x.strip() for x in paragraph_lines if x.strip()).strip()
            paragraph_lines.clear()
            if text:
                quote_parts.append(Paragraph(markup_inline(text), body_style))

        for quoted_line in quote_buffer:
            if quoted_line.strip():
                paragraph_lines.append(quoted_line)
            else:
                flush_quote_paragraph()
        flush_quote_paragraph()
        quote_buffer.clear()

        if not quote_parts:
            return

        table = Table([[quote_parts]], colWidths=[None], hAlign="LEFT")
        table.setStyle(TableStyle([
            ("LINEBEFORE", (0, 0), (0, -1), 2, colors.HexColor("#4b5563")),
            ("LEFTPADDING", (0, 0), (0, -1), 10),
            ("RIGHTPADDING", (0, 0), (0, -1), 0),
            ("TOPPADDING", (0, 0), (0, -1), 0),
            ("BOTTOMPADDING", (0, 0), (0, -1), 2),
            ("VALIGN", (0, 0), (0, -1), "TOP"),
        ]))
        flow.append(table)
        flow.append(Spacer(1, 2 * mm))

    def flush_table():
        if table_buffer:
            _append_markdown_table(flow, table_buffer, body_style)
            table_buffer.clear()

    for line_index, raw_line in enumerate(lines):
        # Recognise a table only when a header is followed by a separator.
        cells = _markdown_table_cells(raw_line)
        if cells is not None:
            if table_buffer and _markdown_table_separator(cells) and len(cells) == len(table_buffer[0]):
                continue
            if table_buffer:
                if len(cells) == len(table_buffer[0]) and not _markdown_table_separator(cells):
                    table_buffer.append(cells)
                    continue
                flush_table()
            if line_index + 1 < len(lines):
                separator = _markdown_table_cells(lines[line_index + 1])
                if separator is not None and len(separator) == len(cells) and _markdown_table_separator(separator):
                    flush_quote(); flush_paragraph(); flush_bullets()
                    table_buffer.append(cells)
                    continue
        if table_buffer:
            flush_table()
        # The separator is consumed logically, not added to the PDF.
        if cells is not None and _markdown_table_separator(cells) and line_index > 0:
            previous = _markdown_table_cells(lines[line_index - 1])
            if previous is not None and len(previous) == len(cells):
                continue
        # ASCII Form Feed (FF, 0x0C) at the front of a line means new page.
        # Keeping this test before strip() is important because strip() removes FF.
        if raw_line.startswith("\f") or raw_line.startswith("\\ff") or raw_line.startswith("\\formfeed"):
            flush_quote(); flush_paragraph(); flush_bullets()
            flow.append(PageBreak())
            raw_line = raw_line[1:] if raw_line.startswith("\f") else ""
            if not raw_line.strip():
                continue

        line = raw_line.strip()

        # ChatGPT-style response block: every line is prefixed with "│".
        # A bare "│" preserves a paragraph break inside the block.
        if line.startswith("│"):
            flush_paragraph(); flush_bullets()
            quote_buffer.append(line[1:].lstrip())
            continue

        # Any non-quote line closes the current response block.
        flush_quote()

        if not line:
            flush_paragraph(); flush_bullets(); continue

        # Markdown headings inside the story body.  parse_story() consumes the
        # first H1 as the document title; combined files leave later headings
        # here, so render them rather than printing the # characters literally.
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading_match:
            flush_paragraph(); flush_bullets()
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            heading_sizes = {1: 18, 2: 14, 3: 12.5, 4: 11.5, 5: 11, 6: 10.5}
            heading_style = ParagraphStyle(
                f"MarkdownHeading{level}", parent=body_style,
                fontName="Helvetica-Bold", fontSize=heading_sizes[level],
                leading=heading_sizes[level] + 4,
                spaceBefore=10 if level > 1 else 14,
                spaceAfter=6, textColor=colors.HexColor("#1f2937"),
            )
            flow.append(Paragraph(markup_inline(heading_text), heading_style))
            continue

        if line.startswith("* ") or line.startswith("- "):
            flush_paragraph(); bullet_buffer.append(line[2:].strip()); continue
        parsed = parse_inline_image(line)
        if parsed:
            flush_paragraph(); flush_bullets()
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
            flush_paragraph(); flush_bullets(); paragraph_buffer.append(line); flush_paragraph(); continue
        flush_bullets(); paragraph_buffer.append(line)

    flush_table(); flush_quote(); flush_paragraph(); flush_bullets()

def build_story_flowables(title, blocks, metadata=None, header_fields=None, illustration_path=None, image_height_mm=65, image_align="center", heading_colors=None, story_path=None):
    story_path = Path(story_path) if story_path is not None else Path("story.md")
    styles = getSampleStyleSheet()
    speaker_palette = heading_colors or DEFAULT_SPEAKER_COLORS
    title_style = ParagraphStyle("StoryTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=21, leading=25, alignment=TA_LEFT, textColor=colors.HexColor("#1f2937"), spaceAfter=10)
    header_style = ParagraphStyle("HeaderField", parent=styles["Normal"], fontName="Helvetica", fontSize=9.4, leading=12, textColor=colors.HexColor("#4b5563"), spaceAfter=2, alignment=TA_LEFT)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontName="Helvetica", fontSize=11.2, leading=16, textColor=colors.HexColor("#111827"), spaceAfter=8, alignment=TA_LEFT)
    bullet_style = ParagraphStyle("BulletBody", parent=body_style, leftIndent=0, firstLineIndent=0, spaceAfter=2)
    aside_style = ParagraphStyle("Aside", parent=body_style, fontName="Helvetica-Oblique", textColor=colors.HexColor("#374151"), leftIndent=8, spaceAfter=8)
    if contains_hebrew(title) and (ENABLED_LANGUAGES & {"hebrew", "yiddish"}):
        title_style.alignment = TA_RIGHT
    flow = [Paragraph(markup_inline(title), title_style), Spacer(1, 2 * mm)]
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
        flow += [img, Spacer(1, 6 * mm)]
    if len(blocks) == 1 and not blocks[0][0].strip():
        emit_rich_text(flow, blocks[0][1], body_style, bullet_style, aside_style, story_path)
        return flow
    speaker_color_map, next_color_index = {}, 0
    def get_speaker_color(speaker):
        nonlocal next_color_index
        key = speaker.strip().lower()
        if key not in speaker_color_map:
            speaker_color_map[key] = speaker_palette[next_color_index % len(speaker_palette)]
            next_color_index += 1
        return speaker_color_map[key]
    def make_speaker_style(speaker):
        return ParagraphStyle(f"Speaker_{speaker}", parent=styles["Heading3"], fontName="Helvetica-Bold", fontSize=12.5, leading=15, textColor=get_speaker_color(speaker), spaceBefore=10, spaceAfter=6)
    for i, (speaker, content) in enumerate(blocks):
        if i > 0: flow.append(Spacer(1, 4 * mm))
        if speaker.strip(): flow.append(Paragraph(html.escape(speaker), make_speaker_style(speaker)))
        emit_rich_text(flow, content, body_style, bullet_style, aside_style, story_path)
    return flow

class BackgroundImage(Flowable):
    def __init__(self, image_path, dim=0.35):
        super().__init__()
        self.image_path = image_path
        self.dim = dim
    def wrap(self, availWidth, availHeight):
        return (0, 0)
    def drawOn(self, canvas, x, y, _sW=0):
        page_width, page_height = canvas._pagesize
        canvas.saveState()
        canvas.drawImage(str(self.image_path), 0, 0, width=page_width, height=page_height, preserveAspectRatio=False, mask='auto')
        if self.dim > 0:
            canvas.setFillColor(colors.black, alpha=self.dim)
            canvas.rect(0, 0, page_width, page_height, fill=1, stroke=0)
        canvas.restoreState()

def build_slide_flowables(deck_title, slides, story_path, slide_config=None):
    slide_config = slide_config or {}
    styles = getSampleStyleSheet()
    title_name, title_size, title_color = parse_font(slide_config.get("title_font"), "Helvetica-Bold", 30)
    bullet_name, bullet_size, bullet_color = parse_font(slide_config.get("bullet_font"), "Helvetica", 18)
    body_name, body_size, body_color = parse_font(slide_config.get("body_font"), "Helvetica", 18)
    title_align = TA_CENTER if slide_config.get("title_align") == "center" else TA_LEFT
    body_align = TA_CENTER if slide_config.get("body_align") == "center" else TA_LEFT
    background_dim = slide_config.get("background_dim", 0.35)
    flow = []
    total = len(slides)
    for idx, slide in enumerate(slides):
        slide_title = ParagraphStyle(f"SlideTitle_{idx}", parent=styles["Heading1"], fontName=title_name, fontSize=title_size, leading=title_size + 4, spaceAfter=10, textColor=title_color, alignment=title_align)
        bullet_style = ParagraphStyle(f"SlideBullet_{idx}", parent=styles["Normal"], fontName=bullet_name, fontSize=bullet_size, leading=bullet_size + 4, spaceAfter=4, textColor=bullet_color, alignment=body_align)
        body_style = ParagraphStyle(f"SlideBody_{idx}", parent=styles["Normal"], fontName=body_name, fontSize=body_size, leading=body_size + 4, spaceAfter=8, textColor=body_color, alignment=body_align)
        bg_image = None
        bg_def = slide.get("background")
        if bg_def:
            bg_path = resolve_inline_image_path(story_path, bg_def["filename"])
            if bg_path: bg_image = bg_path
        if bg_image:
            flow.append(BackgroundImage(bg_image, dim=background_dim))
        title_lines = slide.get("title_lines") or [slide["title"]]

        for i, tline in enumerate(title_lines):
            if i == 0:
                style = slide_title
            else:
                style = ParagraphStyle(
                    f"SlideSubtitle_{idx}_{i}",
                    parent=slide_title,
                    fontSize=slide_title.fontSize * 0.7,
                    leading=slide_title.leading * 0.8,
                    spaceAfter=4,
                )
            flow.append(Paragraph(markup_inline(tline), style))

        flow.append(Spacer(1, 8))        

        image = None
        image_align = "center"
        img_def = slide.get("image")
        if img_def:
            img_path = resolve_inline_image_path(story_path, img_def["filename"])
            if img_path:
                img = Image(str(img_path))
                height_mm = img_def["opts"].get("height_mm") or 70
                img._restrictSize(140 * mm, height_mm * mm)
                img.hAlign = IMAGE_ALIGN_MAP.get(img_def["opts"].get("align", "center"), "CENTER")
                image = img
                image_align = img_def["opts"].get("align", "center")
        body_parts = [Paragraph(markup_inline(para), body_style) for para in slide.get("body", []) if para.strip()]
        bullets = slide.get("bullets", [])
        bullet_flow = ListFlowable([ListItem(Paragraph(markup_inline(b), bullet_style)) for b in bullets], bulletType="bullet") if bullets else None
        text_parts = []
        if body_parts: text_parts.extend(body_parts)
        if bullet_flow is not None:
            if text_parts: text_parts.append(Spacer(1, 8))
            text_parts.append(bullet_flow)
        if image and image_align == "left":
            right_col = text_parts if text_parts else [Spacer(1,1)]
            table = Table([[image, right_col]], colWidths=[95 * mm, None])
            table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),

                # image cell padding
                ("LEFTPADDING", (0, 0), (0, 0), 8),
                ("RIGHTPADDING", (0, 0), (0, 0), 14),

                # text cell padding
                ("LEFTPADDING", (1, 0), (1, 0), 18),
                ("RIGHTPADDING", (1, 0), (1, 0), 8),
            ]))

#            table = Table([[image, right_col]], colWidths=[90 * mm, None])
#            table.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8)]))

            flow.append(table)
        else:
            if image:
                flow.append(image); flow.append(Spacer(1,10))
            flow.extend(text_parts)
        if idx < total - 1:
            flow.append(PageBreak())
    return flow

def generate_pdf(input_path=".", output_path=None, image_height_mm=65, image_align="center", heading_colors=None, header_fields=None, mode="story", languages=None, combine_paths=None, check_image_sizes_enabled=True):
    configure_languages(languages or set())
    base = Path(input_path)
    if combine_paths:
        story_path = Path(combine_paths[0])
    elif base.is_dir():
        file_map = {"story": "story.md", "summary": "summary.md", "slides": "slides.md"}
        story_path = base / file_map[mode]
        if not story_path.exists():
            raise FileNotFoundError(f"{story_path} not found")
    else:
        story_path = base

    # Image preflight runs before Markdown parsing/PDF construction.
    if check_image_sizes_enabled:
        check_image_sizes(story_path.parent)

    if combine_paths:
        combine_files = [Path(p) for p in combine_paths]
        missing = [str(p) for p in combine_files if not p.is_file()]
        if missing:
            raise FileNotFoundError("Combine input not found: " + ", ".join(missing))
        story_path = combine_files[0]
        # FF is the traditional ASCII form-feed character.  The renderer below
        # interprets it as PageBreak() when it appears at the front of a line.
        text = "\n\f\n".join(p.read_text(encoding="utf-8") for p in combine_files)
    else:
        text = story_path.read_text(encoding="utf-8")
    if mode == "slides":
        metadata, title, slides = parse_slides(text)
        output_path = Path(output_path) if output_path else story_path.with_name(f"{safe_filename(title)}.pdf")
        doc = SimpleDocTemplate(str(output_path), pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm, title=title, author="Heichalot-CMS")
        flow = build_slide_flowables(title, slides, story_path, extract_slide_config(metadata))
        doc.build(flow)
        return output_path
    metadata, title, blocks = parse_story(text)
    output_path = (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else (story_path.parent / f"{safe_filename(title)}.pdf").resolve()
    )
    illustration_path = find_illustration_image(story_path)
    parsed_heading_colors = parse_color_list(heading_colors)
    parsed_header_fields = parse_header_fields(header_fields)
    doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm, title=title, author="Heichalot-CMS")
    flow = build_story_flowables(title, blocks, metadata=metadata, header_fields=parsed_header_fields, illustration_path=illustration_path, image_height_mm=image_height_mm, image_align=image_align, heading_colors=parsed_heading_colors, story_path=story_path)
    doc.build(flow)
    return str(output_path)

def build_arg_parser():
    parser = argparse.ArgumentParser(description="Render story.md, summary.md, or slides.md to PDF.")
    parser.add_argument("input_path", nargs="?", default=".", help="Path to entry directory or explicit markdown file (default: current directory).")
    parser.add_argument("output_path", nargs="?", default=None, help="Optional output PDF path.")
    parser.add_argument("--summary", action="store_true", help="Render summary.md instead of story.md.")
    parser.add_argument("--combine", nargs="+", metavar="FILE", help="Combine Markdown files in the supplied order, inserting an ASCII form feed/page break between files.")
    parser.add_argument("--slides", action="store_true", help="Render slides.md as a landscape slide deck.")
    parser.add_argument("--image-height-mm", type=float, default=65, help="Maximum illustration image height in mm for story/summary mode.")
    parser.add_argument("--image-align", choices=("left","center","right"), default="center", help="Illustration image alignment for story/summary mode.")
    parser.add_argument("--heading-colors", default=None, help="Comma-separated hex colors for dialogue speaker headings.")
    parser.add_argument("--header-fields", default=None, help="Comma-separated metadata fields to display under the title in story/summary mode.")
    parser.add_argument("--languages", default=None, help="Comma-separated extra languages/scripts to enable, e.g. hebrew,yiddish (aliases: he,yi).")
    parser.add_argument("--check-image-sizes", type=parse_bool, default=True, metavar="true/false", help="Check and reduce oversized images in the images subdirectory before rendering (default: true).")
    return parser

def main(args=None):
    parser = build_arg_parser()
    ns = parser.parse_args(args)
    mode = "story"
    if ns.summary: mode = "summary"
    if ns.slides: mode = "slides"
    out = generate_pdf(input_path=ns.input_path, output_path=ns.output_path, image_height_mm=ns.image_height_mm, image_align=ns.image_align, heading_colors=ns.heading_colors, header_fields=ns.header_fields, mode=mode, languages=parse_languages(ns.languages), combine_paths=ns.combine, check_image_sizes_enabled=ns.check_image_sizes)
    print(f"Wrote: {out}")

if __name__ == "__main__":
    main()
