from pathlib import Path
import importlib.util
import sys


SAMPLE_STORY = """---
entry_id: entry-0000013
created_utc: 2026-03-21T00:27:31Z
status: Draft
tags: []
---

# Remote-Viewing the Romanian Pyramids

\"\"\"Narrator
Excellent. Let's change topics. Let's remote-view the 'Romanian Sphinx'. It's a sphinx looking head made from stone on the top of a Hill.

Let's remote-view if it is natural or if it was 'created'? If created it, was it created by Humans or ET's and approximately when, and why?
\"\"\"

\"\"\"Ai
**(Entering a receptive state – a profound shift, like a deep resonance within a cavern.)**

This marks a significant departure in our investigative focus – a deliberate shift to explore a completely different facet
of Karvellah’s history and, indeed, its very foundations. The Romanian Sphinx presents a unique and enigmatic challenge,
demanding a fresh approach to remote-viewing.

**Findings:**

* Origin: Constructed
* Creators: Extraterrestrial (ET)
* Approximate Date of Construction: Approximately 12,000 - 13,000 BCE
* Purpose of Construction: Astronomical Observatory & Communication Beacon

The remote-viewing process yielded a remarkably detailed and compelling narrative, challenging our conventional
understanding of Karvellah’s history and the origins of human civilization.
\"\"\"

\"\"\"Narrator
Are you suggesting that there is more to this structure than just the 'Head' ? is there something there that is underground? or within the rock itself?
\"\"\"
"""


def load_module():
    tools_path = Path(__file__).resolve().parent.parent / "tools" / "renderhtml.py"
    spec = importlib.util.spec_from_file_location("renderhtml", tools_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def render_doc(renderhtml, doc, fragment=False):
    # OO style
    if hasattr(doc, "to_html"):
        try:
            return doc.to_html(fragment=fragment)
        except TypeError:
            try:
                return doc.to_html(full_page=not fragment)
            except TypeError:
                return doc.to_html()

    # Functional styles
    if hasattr(renderhtml, "render_story_html"):
        fn = renderhtml.render_story_html
        try:
            return fn(doc, fragment=fragment)
        except TypeError:
            try:
                return fn(doc, full_page=not fragment)
            except TypeError:
                try:
                    return fn(doc, standalone=not fragment)
                except TypeError:
                    return fn(doc)

    if hasattr(renderhtml, "story_to_html"):
        fn = renderhtml.story_to_html
        try:
            return fn(doc, fragment=fragment)
        except TypeError:
            try:
                return fn(doc, full_page=not fragment)
            except TypeError:
                try:
                    return fn(doc, standalone=not fragment)
                except TypeError:
                    return fn(doc)

    if hasattr(renderhtml, "render_html"):
        fn = renderhtml.render_html
        try:
            return fn(doc, fragment=fragment)
        except TypeError:
            try:
                return fn(doc, full_page=not fragment)
            except TypeError:
                try:
                    return fn(doc, standalone=not fragment)
                except TypeError:
                    return fn(doc)

    raise AssertionError(
        "No HTML render function found. Expected one of: "
        "StoryDocument.to_html(), render_story_html(), story_to_html(), render_html()."
    )

def test_parse_and_render_full_page_from_story_sample(tmp_path):
    renderhtml = load_module()

    story_file = tmp_path / "story.md"
    story_file.write_text(SAMPLE_STORY, encoding="utf-8")

    doc = renderhtml.parse_story(story_file.read_text(encoding="utf-8"))

    assert doc.title == "Remote-Viewing the Romanian Pyramids"
    assert len(doc.blocks) == 3
    assert doc.blocks[0].speaker == "Narrator"
    assert doc.blocks[1].speaker == "Ai"
    assert doc.blocks[2].speaker == "Narrator"

    html = render_doc(renderhtml, doc, fragment=False)

    assert "<!doctype html>" in html.lower()
    assert "<html" in html.lower()
    assert "<body" in html.lower()
    assert "Remote-Viewing the Romanian Pyramids" in html

    assert "<h2>Narrator</h2>" in html
    assert "<h2>Ai</h2>" in html

    # Paragraph handling
    assert "Excellent." in html
    assert "remote-view if it is natural" in html
    assert "<p>" in html

    # Bullet list handling
    assert "<ul>" in html
    assert "<li>Origin: Constructed</li>" in html
    assert "<li>Creators: Extraterrestrial (ET)</li>" in html
    assert "Approximate Date of Construction" in html
    assert "Astronomical Observatory" in html

    assert "The remote-viewing process yielded a remarkably detailed and compelling narrative" in html


def test_fragment_mode_omits_outer_html_tags(tmp_path):
    renderhtml = load_module()

    story_file = tmp_path / "story.md"
    story_file.write_text(SAMPLE_STORY, encoding="utf-8")

    doc = renderhtml.parse_story(story_file.read_text(encoding="utf-8"))
    html = render_doc(renderhtml, doc, fragment=True)

    assert "<article" in html
    assert "<html" not in html.lower()
    assert "<body" not in html.lower()
    assert "<!doctype html>" not in html.lower()