import sys
import importlib.util
from configparser import ConfigParser
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


def load_createentry_module():
    repo_root = Path(__file__).resolve().parent.parent
    module_path = repo_root / "tools" / "createentry.py"

    spec = importlib.util.spec_from_file_location("createentry", module_path)
    module = importlib.util.module_from_spec(spec)

    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return module


createentry = load_createentry_module()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_frontmatter(path: Path) -> dict:
    """
    Parse only the YAML frontmatter from story.md.

    This deliberately uses yaml.safe_load() so malformed YAML fails the test
    rather than being hidden by string comparisons.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    assert lines
    assert lines[0].strip() == "---"

    try:
        end = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration:
        pytest.fail("story.md has no closing YAML frontmatter marker")

    header = "\n".join(lines[1:end])
    parsed = yaml.safe_load(header)

    assert isinstance(parsed, dict)
    return parsed


def test_find_yaml_header_bounds() -> None:
    lines = [
        "---",
        "title: Test",
        "tags: []",
        "---",
        "",
        "# Test",
    ]

    assert createentry._find_yaml_header_bounds(lines) == (0, 3)


def test_find_yaml_header_bounds_rejects_missing_header() -> None:
    with pytest.raises(ValueError, match="does not begin"):
        createentry._find_yaml_header_bounds([
            "# No YAML here",
        ])


def test_strip_blank_lines_from_yaml_header_preserves_body(tmp_path: Path) -> None:
    story = tmp_path / "story.md"

    write_text(
        story,
        """---
entry_id: entry-0000001

kind: youtube

tags: []

---

# Heading

Body paragraph.

Second paragraph.
""",
    )

    createentry.strip_blank_lines_from_yaml_header(story)

    result = story.read_text(encoding="utf-8")

    assert result.startswith(
        "---\n"
        "entry_id: entry-0000001\n"
        "kind: youtube\n"
        "tags: []\n"
        "---\n"
    )

    assert "# Heading\n\nBody paragraph.\n\nSecond paragraph." in result


def test_set_yaml_field_adds_valid_scalar_yaml(tmp_path: Path) -> None:
    story = tmp_path / "story.md"

    write_text(
        story,
        """---
entry_id: entry-0000001
kind: youtube
---

# Test
""",
    )

    createentry.set_yaml_field(
        story,
        "source",
        "youtube",
    )

    header = read_frontmatter(story)

    assert header["source"] == "youtube"

    # Regression check: a top-level field must not be emitted as a standalone
    # flow mapping such as "{source: youtube}".
    assert "\n{source:" not in story.read_text(encoding="utf-8")


def test_set_yaml_fields_adds_import_metadata_as_valid_yaml(tmp_path: Path) -> None:
    """
    Regression test for the ytv2cms.py frontmatter problem.
    """
    story = tmp_path / "story.md"

    write_text(
        story,
        """---
entry_id: entry-0000181
kind: youtube
status: Draft
tags: []
---

# Example
""",
    )

    createentry.set_yaml_fields(
        story,
        {
            "tags": ["Islam", "Baal"],
            "source": "youtube",
            "source_video_id": "ywvOgLNGw6s",
            "source_url": "https://www.youtube.com/watch?v=ywvOgLNGw6s",
            "timeframe": ["past"],
        },
    )

    header = read_frontmatter(story)

    assert header["tags"] == ["Islam", "Baal"]
    assert header["source"] == "youtube"
    assert header["source_video_id"] == "ywvOgLNGw6s"
    assert header["source_url"] == "https://www.youtube.com/watch?v=ywvOgLNGw6s"
    assert header["timeframe"] == ["past"]


def test_set_yaml_fields_replaces_existing_field_without_duplicate(tmp_path: Path) -> None:
    story = tmp_path / "story.md"

    write_text(
        story,
        """---
entry_id: entry-0000001
status: Draft
timeframe: [present]
---

# Test
""",
    )

    createentry.set_yaml_fields(
        story,
        {
            "status": "Published",
            "timeframe": ["past"],
        },
    )

    header = read_frontmatter(story)
    text = story.read_text(encoding="utf-8")

    assert header["status"] == "Published"
    assert header["timeframe"] == ["past"]
    assert text.count("status:") == 1
    assert text.count("timeframe:") == 1


def test_add_yaml_field_is_repeatable(tmp_path: Path) -> None:
    story = tmp_path / "story.md"

    write_text(
        story,
        """---
entry_id: entry-0000001
---

# Test
""",
    )

    createentry.add_yaml_field(
        story,
        "source",
        "youtube",
    )

    createentry.add_yaml_field(
        story,
        "source",
        "manual",
    )

    header = read_frontmatter(story)
    text = story.read_text(encoding="utf-8")

    assert header["source"] == "manual"
    assert text.count("source:") == 1


def test_conversation_to_story_text_normalises_roles() -> None:
    text = createentry.conversation_to_story_text(
        [
            {
                "role": "user",
                "content": "First message",
            },
            {
                "role": "assistant",
                "content": "Second message",
            },
        ],
        include_datetime=False,
    )

    assert '"""Narrator\n\nFirst message\n"""' in text
    assert '"""Ai\n\nSecond message\n"""' in text


def test_build_story_body_combines_body_and_conversation() -> None:
    text = createentry.build_story_body(
        body="Opening paragraph.",
        conversation=[
            {
                "role": "assistant",
                "content": "Transcript response.",
            },
        ],
    )

    assert text.startswith("Opening paragraph.")
    assert '"""Ai' in text
    assert "Transcript response." in text


def test_create_entry_persists_yaml_fields_and_tags(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """
    Small integration test for the public create_entry() API.

    External config/state functions are patched so the test never touches the
    user's real CMS or ~/.heichalotcms/config.ini.
    """
    cms_dir = tmp_path / "cms"
    template = tmp_path / "story.md.j2"
    config_path = tmp_path / "config.ini"

    write_text(
        template,
        """---
entry_id: {{ entry_id }}

created_utc: {{ created_utc }}

kind: {{ kind }}

year: {{ year }}

datetime: {{ datetime }}

status: {{ status }}

tags: []

---

# {{ title }}
""",
    )

    cfg = ConfigParser()
    cfg["new_entry"] = {
        "default_title": "Title",
    }

    paths = SimpleNamespace(
        cms_dir=cms_dir,
    )

    monkeypatch.setattr(
        createentry,
        "load_app_config",
        lambda _config_path=None: (
            cfg,
            config_path,
            paths,
        ),
    )

    monkeypatch.setattr(
        createentry,
        "get_entry_prefix",
        lambda _cfg: "entry-",
    )

    monkeypatch.setattr(
        createentry,
        "get_entry_pad_width",
        lambda _cfg: 7,
    )

    monkeypatch.setattr(
        createentry,
        "get_last_id",
        lambda _cfg: 179,
    )

    monkeypatch.setattr(
        createentry,
        "get_template_path",
        lambda _cfg: template,
    )

    monkeypatch.setattr(
        createentry,
        "resolve_entry_kind",
        lambda _cfg, entry_type: "youtube" if entry_type == "yt" else entry_type,
    )

    saved_last_id = {}

    def fake_set_last_id(_cfg, value, _config_path) -> None:
        saved_last_id["value"] = value

    monkeypatch.setattr(
        createentry,
        "set_last_id",
        fake_set_last_id,
    )

    entry_id, entry_dir, story_path = createentry.create_entry(
        "yt",
        title="Did Baal Become Allah?",
        tags=["Islam", "Baal"],
        body="Imported transcript.",
        yaml_fields={
            "source": "youtube",
            "source_video_id": "ywvOgLNGw6s",
            "source_url": "https://www.youtube.com/watch?v=ywvOgLNGw6s",
            "timeframe": ["past"],
        },
    )

    assert entry_id == "entry-0000180"
    assert entry_dir == cms_dir / "entry-0000180"
    assert story_path == entry_dir / "story.md"
    assert saved_last_id["value"] == 180

    header = read_frontmatter(story_path)

    assert header["kind"] == "youtube"
    assert header["tags"] == ["Islam", "Baal"]
    assert header["source"] == "youtube"
    assert header["source_video_id"] == "ywvOgLNGw6s"
    assert header["source_url"] == "https://www.youtube.com/watch?v=ywvOgLNGw6s"
    assert header["timeframe"] == ["past"]

    result = story_path.read_text(encoding="utf-8")

    # create_entry() should clean blank lines only inside YAML.
    frontmatter_text = result.split("---", 2)[1]
    assert "\n\n" not in frontmatter_text

    # Body content must remain intact.
    assert "# Did Baal Become Allah?" in result
    assert "Imported transcript." in result
