from pathlib import Path
import importlib.util
import sys

SAMPLE_DIALOGUE_STORY = '''---
entry_id: entry-0000013
created_utc: 2026-03-21T00:27:31Z
location_text: Romania/Romanian Pyramids
datetime: 2026-01-01
status: Draft
source: Example Archive
---

# Remote-Viewing the Romanian Pyramids

"""Narrator
Excellent. Let's change topics. Let's remote-view the Romanian Sphinx.
"""

"""Ai
**Findings:**

* Origin: Constructed
* Creators: Extraterrestrial (ET)

The remote-viewing process yielded a remarkably detailed and compelling narrative.
"""
'''

SAMPLE_PROSE_STORY = '''---
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
'''

SAMPLE_INLINE_IMAGE_STORY = '''---
entry_id: entry-0000030
location_text: Test Location
datetime: 1900-01-01
---

# Inline Image Example

This is the opening paragraph.

![Inline caption](photo.jpg){height=240 align=right}

This is the closing paragraph.
'''


def load_module():
    tools_dir = Path(__file__).resolve().parent.parent / "tools"
    module_path = tools_dir / "renderhtml.py"
    assert module_path.exists(), f"Could not find {module_path}"

    spec = importlib.util.spec_from_file_location("renderhtml", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_renderhtml_generates_html_from_dialogue_story_file(tmp_path):
    renderhtml = load_module()
    story_file = tmp_path / "story.md"
    story_file.write_text(SAMPLE_DIALOGUE_STORY, encoding="utf-8")

    output_html = Path(renderhtml.generate_html(story_file))
    assert output_html.exists()
    assert output_html.name == "Remote-Viewing the Romanian Pyramids.html"
    html_text = output_html.read_text(encoding="utf-8")
    assert "<h1>Remote-Viewing the Romanian Pyramids</h1>" in html_text
    assert "<h2>Narrator</h2>" in html_text
    assert "<h2>Ai</h2>" in html_text
    assert "<ul>" in html_text
    assert "Creators: Extraterrestrial" in html_text


def test_renderhtml_generates_html_from_prose_story_file(tmp_path):
    renderhtml = load_module()
    story_file = tmp_path / "story.md"
    story_file.write_text(SAMPLE_PROSE_STORY, encoding="utf-8")

    output_html = Path(renderhtml.generate_html(story_file))
    assert output_html.exists()
    assert output_html.name == "Herencia Filipinas.html"
    html_text = output_html.read_text(encoding="utf-8")
    assert "<h1>Herencia Filipinas</h1>" in html_text
    assert '<p class="story-paragraph">' in html_text
    assert "<ul>" in html_text
    assert "Historical photograph" in html_text


def test_renderhtml_defaults_to_current_directory_and_uses_title_filename(tmp_path, monkeypatch):
    renderhtml = load_module()
    story_file = tmp_path / "story.md"
    story_file.write_text(SAMPLE_DIALOGUE_STORY, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    output_html = Path(renderhtml.generate_html())
    assert output_html.exists()
    assert output_html.name == "Remote-Viewing the Romanian Pyramids.html"
    assert output_html.resolve().parent == tmp_path.resolve()


def test_renderhtml_respects_header_field_filter():
    renderhtml = load_module()
    metadata, title, blocks = renderhtml.parse_story(SAMPLE_PROSE_STORY)
    selected = renderhtml.select_header_items(metadata, header_fields=["location_text", "source"])

    assert ("Location", "Philippines") in selected
    assert ("Source", "History and Description of Our Philippine Wonderland") in selected
    assert all(label in {"Location", "Source"} for label, _ in selected)


def test_renderhtml_finds_single_fallback_image_and_explicit_illustration(tmp_path):
    renderhtml = load_module()
    story_file = tmp_path / "story.md"
    story_file.write_text(SAMPLE_PROSE_STORY, encoding="utf-8")

    lone_image = tmp_path / "downloaded_image.jpg"
    lone_image.write_bytes(b"fakejpg")
    assert renderhtml.find_illustration_image(story_file) == lone_image

    explicit = tmp_path / "illustration.png"
    explicit.write_bytes(b"fakepng")
    assert renderhtml.find_illustration_image(story_file) == explicit


def test_renderhtml_parses_safe_filename():
    renderhtml = load_module()
    filename = renderhtml.safe_filename('Title: With / Illegal * Chars?')
    assert ":" not in filename
    assert "/" not in filename
    assert "*" not in filename


def test_renderhtml_inline_image_syntax_and_resolution(tmp_path):
    renderhtml = load_module()
    story_file = tmp_path / "story.md"
    story_file.write_text(SAMPLE_INLINE_IMAGE_STORY, encoding="utf-8")

    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "photo.jpg").write_bytes(b"fakejpg")

    parsed = renderhtml.parse_inline_image("![Inline caption](photo.jpg){height=240 align=right}")
    assert parsed is not None
    caption, filename, options = parsed
    assert caption == "Inline caption"
    assert filename == "photo.jpg"
    assert options["height_px"] == 240
    assert options["align"] == "right"

    img_path = renderhtml.resolve_inline_image_path(story_file, "photo.jpg")
    assert img_path == images_dir / "photo.jpg"

    output_html = Path(renderhtml.generate_html(story_file))
    assert output_html.exists()
    assert output_html.name == "Inline Image Example.html"
    html_text = output_html.read_text(encoding="utf-8")
    assert 'src="images/photo.jpg"' in html_text
    assert 'Inline caption' in html_text
    assert 'max-height:240px' in html_text
    assert 'margin:0 0 1em auto' in html_text


def test_renderhtml_fragment_mode_omits_outer_html(tmp_path):
    renderhtml = load_module()
    story_file = tmp_path / "story.md"
    story_file.write_text(SAMPLE_PROSE_STORY, encoding="utf-8")

    output_html = Path(renderhtml.generate_html(story_file, fragment=True))
    html_text = output_html.read_text(encoding="utf-8")
    assert "<article" in html_text
    assert "<html" not in html_text.lower()
    assert "<body" not in html_text.lower()
    assert "<!doctype html>" not in html_text.lower()
