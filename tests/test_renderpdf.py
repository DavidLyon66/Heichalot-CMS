from pathlib import Path
import importlib.util
import sys


SAMPLE_DIALOGUE_STORY = """---
entry_id: entry-0000013
created_utc: 2026-03-21T00:27:31Z
location_text: Romania/Romanian Pyramids
datetime: 2026-01-01
status: Draft
source: Example Archive
---

# Remote-Viewing the Romanian Pyramids

\"\"\"Narrator
Excellent. Let's change topics. Let's remote-view the Romanian Sphinx.
\"\"\"

\"\"\"Ai
**Findings:**

* Origin: Constructed
* Creators: Extraterrestrial (ET)

The remote-viewing process yielded a remarkably detailed and compelling narrative.
\"\"\"
"""

SAMPLE_PROSE_STORY = """---
entry_id: entry-0000022
created_utc: 2026-04-01T11:03:55Z
location_text: Philippines
datetime: 1870-01-01
status: Draft
source: History and Description of Our Philippine Wonderland
---

# Herencia Filipinas

This photograph documents a Moro Chieftain and his family in Northern Mindanao at the end of the
19th century.

The term "Moro" was used by Spanish and American colonizers to describe the diverse
Muslim ethnolinguistic groups of the southern Philippines.

* Historical photograph
* Educational use
* Archival source
"""


def load_module():
    tools_dir = Path(__file__).resolve().parent.parent / "tools"
    module_path = tools_dir / "renderpdf.py"

    assert module_path.exists(), f"Could not find {module_path}"

    spec = importlib.util.spec_from_file_location("renderpdf", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_renderpdf_generates_pdf_from_dialogue_story_file(tmp_path):
    renderpdf = load_module()

    story_file = tmp_path / "story.md"
    story_file.write_text(SAMPLE_DIALOGUE_STORY, encoding="utf-8")

    output_pdf = renderpdf.generate_pdf(story_file)

    output_pdf = Path(output_pdf)
    assert output_pdf.exists()
    assert output_pdf.name == "Remote-Viewing the Romanian Pyramids.pdf"
    assert output_pdf.stat().st_size > 0


def test_renderpdf_generates_pdf_from_prose_story_file(tmp_path):
    renderpdf = load_module()

    story_file = tmp_path / "story.md"
    story_file.write_text(SAMPLE_PROSE_STORY, encoding="utf-8")

    output_pdf = renderpdf.generate_pdf(story_file)

    output_pdf = Path(output_pdf)
    assert output_pdf.exists()
    assert output_pdf.name == "Herencia Filipinas.pdf"
    assert output_pdf.stat().st_size > 0


def test_renderpdf_defaults_to_current_directory_and_uses_title_filename(tmp_path, monkeypatch):
    renderpdf = load_module()

    story_file = tmp_path / "story.md"
    story_file.write_text(SAMPLE_DIALOGUE_STORY, encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    output_pdf = renderpdf.generate_pdf()

    output_pdf = Path(output_pdf)
    assert output_pdf.exists()
    assert output_pdf.name == "Remote-Viewing the Romanian Pyramids.pdf"
    assert output_pdf.parent == tmp_path


def test_renderpdf_respects_header_field_filter(tmp_path):
    renderpdf = load_module()

    story_file = tmp_path / "story.md"
    story_file.write_text(SAMPLE_PROSE_STORY, encoding="utf-8")

    metadata, title, blocks = renderpdf.parse_story(SAMPLE_PROSE_STORY)
    selected = renderpdf.select_header_items(metadata, header_fields=["location_text", "source"])

    assert ("Location", "Philippines") in selected
    assert ("Source", "History and Description of Our Philippine Wonderland") in selected
    assert all(label in {"Location", "Source"} for label, _ in selected)


def test_renderpdf_finds_single_fallback_image_and_explicit_illustration(tmp_path):
    renderpdf = load_module()

    story_file = tmp_path / "story.md"
    story_file.write_text(SAMPLE_PROSE_STORY, encoding="utf-8")

    lone_image = tmp_path / "downloaded_image.jpg"
    lone_image.write_bytes(b"fakejpg")
    assert renderpdf.find_illustration_image(story_file) == lone_image

    explicit = tmp_path / "illustration.png"
    explicit.write_bytes(b"fakepng")
    assert renderpdf.find_illustration_image(story_file) == explicit


def test_renderpdf_parses_heading_colors_and_safe_filename(tmp_path):
    renderpdf = load_module()

    palette = renderpdf.parse_color_list("#223344,#553377")
    assert palette is not None
    assert len(palette) == 2

    filename = renderpdf.safe_filename('Title: With / Illegal * Chars?')
    assert ":" not in filename
    assert "/" not in filename
    assert "*" not in filename
