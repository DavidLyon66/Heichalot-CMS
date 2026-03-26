from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4

from pathlib import Path
import re


def parse_story(text):
    # Extract title
    title_match = re.search(r'^# (.+)', text, re.MULTILINE)
    title = title_match.group(1) if title_match else "Untitled"

    # Extract dialogue blocks
    blocks = re.findall(r'"""(.*?)\n(.*?)"""', text, re.DOTALL)

    parsed_blocks = []
    for speaker, content in blocks:
        parsed_blocks.append((speaker.strip(), content.strip()))

    return title, parsed_blocks


def resolve_input_path(input_path):
    path = Path(input_path)

    if path.is_dir():
        story_path = path / "story.md"
        if not story_path.exists():
            raise FileNotFoundError(f"No story.md found in {path}")
        return story_path

    return path


def resolve_output_path(input_path, output_path=None):
    input_path = Path(input_path)

    if output_path:
        return Path(output_path)

    if input_path.is_dir():
        output_dir = input_path / "output"
        output_dir.mkdir(exist_ok=True)
        return output_dir / "story.pdf"

    return input_path.with_suffix(".pdf")


def generate_pdf(input_path, output_path=None):
    story_path = resolve_input_path(input_path)
    output_path = resolve_output_path(input_path, output_path)

    text = story_path.read_text(encoding="utf-8")
    title, blocks = parse_story(text)

    doc = SimpleDocTemplate(str(output_path), pagesize=A4)
    styles = getSampleStyleSheet()

    title_style = styles["Title"]

    speaker_style = ParagraphStyle(
        'Speaker',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        spaceAfter=6
    )

    ai_style = ParagraphStyle(
        'AI',
        parent=styles['Normal'],
        leftIndent=20,
        spaceAfter=12
    )

    normal_style = styles['Normal']

    story = []

    # Title
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 20))

    for speaker, content in blocks:
        # Speaker label
        story.append(Paragraph(f"{speaker}:", speaker_style))

        lines = content.split("\n")

        bullet_buffer = []
        paragraph_buffer = []

        def flush_paragraph():
            if paragraph_buffer:
                text = " ".join(paragraph_buffer).strip()
                if text:
                    story.append(Paragraph(text, normal_style))
                    story.append(Spacer(1, 10))
                paragraph_buffer.clear()

        def flush_bullets():
            if bullet_buffer:
                for item in bullet_buffer:
                    story.append(Paragraph(f"• {item}", normal_style))
                story.append(Spacer(1, 10))
                bullet_buffer.clear()

        for line in lines:
            line = line.strip()

            if not line:
                flush_paragraph()
                flush_bullets()
                continue

            if line.startswith("* "):
                flush_paragraph()
                bullet_buffer.append(line[2:].strip())
            else:
                flush_bullets()
                paragraph_buffer.append(line)

        flush_paragraph()
        flush_bullets()

        story.append(Spacer(1, 12))

    doc.build(story)

    return output_path


def main(args=None):
    import sys

    if args is None:
        args = sys.argv[1:]

    if not args:
        print("Usage: renderpdf.py <story.md | entry_dir> [output.pdf]")
        return

    input_path = args[0]
    output_path = args[1] if len(args) > 1 else None

    generate_pdf(input_path, output_path)


if __name__ == "__main__":
    main()