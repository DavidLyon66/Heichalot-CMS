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
Excellent. Let's change topics. Let's remote-view the Romanian Sphinx.
\"\"\"

\"\"\"Ai
**Findings:**

* Origin: Constructed
* Creators: Extraterrestrial (ET)

The remote-viewing process yielded a remarkably detailed and compelling narrative.
\"\"\"
"""


def load_module():
    tools_dir = Path(__file__).resolve().parent.parent / "tools"
    candidates = [
        tools_dir / "renderpdf.py",
        tools_dir / "renderpdf_simple.py",
    ]

    module_path = None
    for candidate in candidates:
        if candidate.exists():
            module_path = candidate
            break

    assert module_path is not None, (
        "Could not find tools/renderpdf.py or tools/renderpdf_simple.py"
    )

    spec = importlib.util.spec_from_file_location("renderpdf", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def render_pdf(renderpdf, input_path, output_path):
    # Most likely function name
    if hasattr(renderpdf, "generate_pdf"):
        return renderpdf.generate_pdf(str(input_path), str(output_path))

    # Alternate possible names
    if hasattr(renderpdf, "render_pdf"):
        return renderpdf.render_pdf(str(input_path), str(output_path))

    if hasattr(renderpdf, "main"):
        # As a last resort, emulate CLI-ish entrypoint
        return renderpdf.main([str(input_path), str(output_path)])

    raise AssertionError(
        "No supported PDF render entrypoint found. "
        "Expected generate_pdf(), render_pdf(), or main()."
    )


def test_renderpdf_generates_pdf_from_story_file(tmp_path):
    renderpdf = load_module()

    story_file = tmp_path / "story.md"
    story_file.write_text(SAMPLE_STORY, encoding="utf-8")

    output_pdf = tmp_path / "story.pdf"
    render_pdf(renderpdf, story_file, output_pdf)

    assert output_pdf.exists()
    assert output_pdf.stat().st_size > 0


def test_renderpdf_can_target_entry_directory_output(tmp_path):
    renderpdf = load_module()

    entry_dir = tmp_path / "entry-0000013"
    entry_dir.mkdir()

    story_file = entry_dir / "story.md"
    story_file.write_text(SAMPLE_STORY, encoding="utf-8")

    output_dir = entry_dir / "output"
    output_dir.mkdir()
    output_pdf = output_dir / "story.pdf"

    render_pdf(renderpdf, story_file, output_pdf)

    assert output_pdf.exists()
    assert output_pdf.stat().st_size > 0