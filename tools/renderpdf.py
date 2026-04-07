# renderpdf_slideparser_body_v2.py
from pathlib import Path
import re, html, hashlib, argparse
_real_md5 = hashlib.md5
def _compat_md5(*args, **kwargs):
    kwargs.pop("usedforsecurity", None)
    return _real_md5(*args, **kwargs)
hashlib.md5 = _compat_md5

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem, HRFlowable, Image, PageBreak, Flowable, Table, TableStyle

INLINE_IMAGE_RE = re.compile(r'^!\[(.*?)\]\(([^/\\]+)\)(?:\{([^}]*)\})?$')
IMAGE_ALIGN_MAP = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}
DEFAULT_SPEAKER_COLORS = [colors.orange, colors.HexColor("#2563eb"), colors.red, colors.HexColor("#059669"), colors.HexColor("#7c3aed"), colors.HexColor("#c2410c")]

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
        title = None
        content_lines = []
        for line in lines:
            if title is None and line.startswith("# "):
                title = line[2:].strip()
            else:
                content_lines.append(line)
        if title is None:
            title = content_lines[0].strip() if content_lines else "Slide"
            content_lines = content_lines[1:] if content_lines else []
        slide = {"title": title, "image": None, "background": None, "bullets": [], "body": []}
        for line in content_lines:
            parsed = parse_inline_image(line)
            if parsed:
                caption, filename, opts = parsed
                img_def = {"caption": caption, "filename": filename, "opts": opts}
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
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(.+?)\*(?!\*)", r"<i>\1</i>", text)
    return text

def emit_rich_text(flow, content, body_style, bullet_style, aside_style, story_path):
    lines = content.splitlines()
    paragraph_buffer, bullet_buffer = [], []
    def flush_paragraph():
        if not paragraph_buffer: return
        paragraph_text = " ".join(x.strip() for x in paragraph_buffer if x.strip()).strip()
        paragraph_buffer.clear()
        if not paragraph_text: return
        style = aside_style if paragraph_text.startswith("(") and paragraph_text.endswith(")") else body_style
        flow.append(Paragraph(markup_inline(paragraph_text), style))
    def flush_bullets():
        if not bullet_buffer: return
        items = [ListItem(Paragraph(markup_inline(item.strip()), bullet_style), leftIndent=0) for item in bullet_buffer if item.strip()]
        bullet_buffer.clear()
        if items:
            flow.append(ListFlowable(items, bulletType="bullet", start="circle", leftIndent=14, bulletFontName="Helvetica", bulletFontSize=9, bulletOffsetY=2, spaceBefore=2, spaceAfter=8))
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_paragraph(); flush_bullets(); continue
        if line.startswith("* "):
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
    flush_paragraph(); flush_bullets()

def build_story_flowables(title, blocks, metadata=None, header_fields=None, illustration_path=None, image_height_mm=65, image_align="center", heading_colors=None, story_path=None):
    story_path = Path(story_path) if story_path is not None else Path("story.md")
    styles = getSampleStyleSheet()
    speaker_palette = heading_colors or DEFAULT_SPEAKER_COLORS
    title_style = ParagraphStyle("StoryTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=21, leading=25, alignment=TA_LEFT, textColor=colors.HexColor("#1f2937"), spaceAfter=10)
    header_style = ParagraphStyle("HeaderField", parent=styles["Normal"], fontName="Helvetica", fontSize=9.4, leading=12, textColor=colors.HexColor("#4b5563"), spaceAfter=2, alignment=TA_LEFT)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontName="Helvetica", fontSize=11.2, leading=16, textColor=colors.HexColor("#111827"), spaceAfter=8, alignment=TA_LEFT)
    bullet_style = ParagraphStyle("BulletBody", parent=body_style, leftIndent=0, firstLineIndent=0, spaceAfter=2)
    aside_style = ParagraphStyle("Aside", parent=body_style, fontName="Helvetica-Oblique", textColor=colors.HexColor("#374151"), leftIndent=8, spaceAfter=8)
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
        flow.append(Paragraph(markup_inline(slide["title"]), slide_title))
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

def generate_pdf(input_path=".", output_path=None, image_height_mm=65, image_align="center", heading_colors=None, header_fields=None, mode="story"):
    base = Path(input_path)
    if base.is_dir():
        file_map = {"story": "story.md", "summary": "summary.md", "slides": "slides.md"}
        story_path = base / file_map[mode]
        if not story_path.exists():
            raise FileNotFoundError(f"{story_path} not found")
    else:
        story_path = base
    text = story_path.read_text(encoding="utf-8")
    if mode == "slides":
        metadata, title, slides = parse_slides(text)
        output_path = Path(output_path) if output_path else story_path.with_name(f"{safe_filename(title)}.pdf")
        doc = SimpleDocTemplate(str(output_path), pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm, title=title, author="Heichalot-CMS")
        flow = build_slide_flowables(title, slides, story_path, extract_slide_config(metadata))
        doc.build(flow)
        return output_path
    metadata, title, blocks = parse_story(text)
    output_path = Path(output_path) if output_path else story_path.with_name(f"{safe_filename(title)}.pdf")
    illustration_path = find_illustration_image(story_path)
    parsed_heading_colors = parse_color_list(heading_colors)
    parsed_header_fields = parse_header_fields(header_fields)
    doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm, title=title, author="Heichalot-CMS")
    flow = build_story_flowables(title, blocks, metadata=metadata, header_fields=parsed_header_fields, illustration_path=illustration_path, image_height_mm=image_height_mm, image_align=image_align, heading_colors=parsed_heading_colors, story_path=story_path)
    doc.build(flow)
    return output_path

def build_arg_parser():
    parser = argparse.ArgumentParser(description="Render story.md, summary.md, or slides.md to PDF.")
    parser.add_argument("input_path", nargs="?", default=".", help="Path to entry directory or explicit markdown file (default: current directory).")
    parser.add_argument("output_path", nargs="?", default=None, help="Optional output PDF path.")
    parser.add_argument("--summary", action="store_true", help="Render summary.md instead of story.md.")
    parser.add_argument("--slides", action="store_true", help="Render slides.md as a landscape slide deck.")
    parser.add_argument("--image-height-mm", type=float, default=65, help="Maximum illustration image height in mm for story/summary mode.")
    parser.add_argument("--image-align", choices=("left","center","right"), default="center", help="Illustration image alignment for story/summary mode.")
    parser.add_argument("--heading-colors", default=None, help="Comma-separated hex colors for dialogue speaker headings.")
    parser.add_argument("--header-fields", default=None, help="Comma-separated metadata fields to display under the title in story/summary mode.")
    return parser

def main(args=None):
    parser = build_arg_parser()
    ns = parser.parse_args(args)
    mode = "story"
    if ns.summary: mode = "summary"
    if ns.slides: mode = "slides"
    out = generate_pdf(input_path=ns.input_path, output_path=ns.output_path, image_height_mm=ns.image_height_mm, image_align=ns.image_align, heading_colors=ns.heading_colors, header_fields=ns.header_fields, mode=mode)
    print(f"Wrote: {out}")

if __name__ == "__main__":
    main()
