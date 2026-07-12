from pathlib import Path
import sys
import os

# Allow importing tools/addaistorytext.py
ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import addaistorytext as mod


def test_parse_transcript_single_turn():
    text = ">>> What do you see?\n\nA quiet concourse.\n"
    blocks = mod.parse_transcript(text)
    assert blocks == [("What do you see?", "A quiet concourse.")]


def test_parse_transcript_multiple_turns():
    text = (
        ">>> First question\n"
        "First answer line 1\n"
        "First answer line 2\n"
        ">>> Second question\n"
        "Second answer\n"
    )
    blocks = mod.parse_transcript(text)
    assert blocks == [
        ("First question", "First answer line 1\nFirst answer line 2"),
        ("Second question", "Second answer"),
    ]


def test_parse_transcript_ignores_preamble_before_first_prompt():
    text = "Welcome banner\nmodel info\n>>> Actual question\nActual answer\n"
    blocks = mod.parse_transcript(text)
    assert blocks == [("Actual question", "Actual answer")]


def test_parse_transcript_merges_multiline_prompt_continuations():
    text = (
        ">>> let's remote-view the conference at Niecaea where they decided which books w\n"
        "... ould be included and which books not. Let's first get an overall picture of\n"
        "... the setting.\n"
        "Okay, fantastic!\n"
    )
    blocks = mod.parse_transcript(text)
    assert blocks == [
        (
            "let's remote-view the conference at Niecaea where they decided which books would be included and which books not. Let's first get an overall picture of the setting.",
            "Okay, fantastic!",
        )
    ]


def test_render_blocks_formats_story_sections():
    blocks = [("Question", "Answer")]
    rendered = mod.render_blocks(blocks)
    assert rendered == '"""Narrator\nQuestion\n"""\n\n"""Ai\nAnswer\n"""\n'


def test_ensure_tags_creates_file_with_tags_when_missing(tmp_path):
    path = tmp_path / "story.md"
    mod.ensure_tags(path, ["remote-viewing", "ai-session"])
    assert path.read_text(encoding="utf-8") == (
        '"""Tags\n'
        'remote-viewing\n'
        'ai-session\n\n'
    )


def test_ensure_tags_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "path" / "story.md"
    mod.ensure_tags(path, ["remote-viewing"])
    assert path.read_text(encoding="utf-8") == (
        '"""Tags\n'
        'remote-viewing\n\n'
    )


def test_ensure_tags_appends_tags_only_once(tmp_path):
    path = tmp_path / "story.md"
    path.write_text("existing content\n", encoding="utf-8")

    mod.ensure_tags(path, ["remote-viewing"])
    once = path.read_text(encoding="utf-8")

    mod.ensure_tags(path, ["remote-viewing"])
    twice = path.read_text(encoding="utf-8")

    assert once == twice
    assert once == 'existing content\n\n"""Tags\nremote-viewing\n\n'


def test_append_story_appends_text_with_spacing(tmp_path):
    path = tmp_path / "story.md"
    path.write_text("header\n", encoding="utf-8")
    mod.append_story(path, '"""Narrator\nQ\n"""\n\n"""Ai\nA\n"""\n')
    assert path.read_text(encoding="utf-8") == (
        'header\n\n"""Narrator\nQ\n"""\n\n"""Ai\nA\n"""\n\n'
    )


def test_append_story_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "story.md"
    mod.append_story(path, '"""Narrator\nQ\n"""\n\n"""Ai\nA\n"""\n')
    assert path.read_text(encoding="utf-8") == (
        '\n"""Narrator\nQ\n"""\n\n"""Ai\nA\n"""\n\n'
    )


def test_write_debate_creates_timestamped_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class FakeNow:
        def strftime(self, fmt):
            if fmt == "%Y-%m-%d_%H-%M-%S":
                return "2026-03-19_02-17-44"
            raise AssertionError(f"unexpected strftime format: {fmt}")

        def isoformat(self):
            return "2026-03-19T02:17:44"

    class FakeDateTime:
        @staticmethod
        def now():
            return FakeNow()

    monkeypatch.setattr(mod, "datetime", FakeDateTime)

    mod.write_debate('"""Narrator\nQ\n"""\n\n"""Ai\nA\n"""\n')

    debate_file = tmp_path / "debate" / "2026-03-19_02-17-44.md"
    assert debate_file.exists()
    assert debate_file.read_text(encoding="utf-8") == (
        "---\n"
        "origin: addaistorytext\n"
        "timestamp: 2026-03-19T02:17:44\n"
        "---\n\n"
        '"""Narrator\nQ\n"""\n\n"""Ai\nA\n"""\n'
    )


def test_read_config_defaults_when_no_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    story_filename, tags = mod.read_config()
    assert story_filename == "story.md"
    assert tags == []


def test_main_writes_to_story_override_path(tmp_path, monkeypatch, capsys):
    story_path = tmp_path / "output" / "story.md"
    input_file = tmp_path / "input.txt"
    input_file.write_text(
        ">>> First question\n"
        "First answer\n"
        ">>> Second question\n"
        "Second answer\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "addaistorytext.py",
            str(input_file),
            "--story",
            str(story_path),
        ],
    )
    monkeypatch.setattr(mod, "read_config", lambda: ("story.md", ["remote-viewing"]))

    mod.main()

    out = capsys.readouterr().out

    assert "Appended 2 block(s)" in out
    assert story_path.name in out

    assert story_path.read_text(encoding="utf-8") == (
        '"""Tags\n'
        'remote-viewing\n\n'
        '\n"""Narrator\n'
        'First question\n'
        '"""\n\n'
        '"""Ai\n'
        'First answer\n'
        '"""\n\n'
        '"""Narrator\n'
        'Second question\n'
        '"""\n\n'
        '"""Ai\n'
        'Second answer\n'
        '"""\n\n'
    )


def test_main_reads_from_stdin_when_no_file(tmp_path, monkeypatch, capsys):
    story_path = tmp_path / "story.md"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "addaistorytext.py",
            "--story",
            str(story_path),
        ],
    )
    monkeypatch.setattr(
        mod,
        "read_input",
        lambda path: ">>> Clipboard question\nClipboard answer\n",
    )
    monkeypatch.setattr(mod, "read_config", lambda: ("story.md", []))

    mod.main()

    out = capsys.readouterr().out
    assert "Appended 1 block(s)" in out
    assert story_path.name in out
    assert story_path.read_text(encoding="utf-8") == (
        '\n"""Narrator\n'
        'Clipboard question\n'
        '"""\n\n'
        '"""Ai\n'
        'Clipboard answer\n'
        '"""\n\n'
    )


def test_main_exits_when_no_prompts_found(tmp_path, monkeypatch):
    story_path = tmp_path / "story.md"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "addaistorytext.py",
            "--story",
            str(story_path),
        ],
    )
    monkeypatch.setattr(mod, "read_input", lambda path: "no prompt markers here")
    monkeypatch.setattr(mod, "read_config", lambda: ("story.md", []))

    try:
        mod.main()
        assert False, "Expected SystemExit"
    except SystemExit as exc:
        assert exc.code == 1


def test_main_debate_mode_ignores_story_override(tmp_path, monkeypatch, capsys):
    story_path = tmp_path / "should_not_be_written.md"
    input_file = tmp_path / "input.txt"
    input_file.write_text(">>> Q\nA\n", encoding="utf-8")

    called = {}

    def fake_write_debate(text):
        called["text"] = text

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "addaistorytext.py",
            "--debate",
            str(input_file),
            "--story",
            str(story_path),
        ],
    )
    monkeypatch.setattr(mod, "read_config", lambda: ("story.md", ["remote-viewing"]))
    monkeypatch.setattr(mod, "write_debate", fake_write_debate)

    mod.main()

    assert called["text"] == '"""Narrator\nQ\n"""\n\n"""Ai\nA\n"""\n'
    assert not story_path.exists()
    _ = capsys.readouterr()

def test_discover_story_files_returns_existing_levels_in_order(tmp_path):
    (tmp_path / "story-free.md").write_text("free", encoding="utf-8")
    (tmp_path / "story.md").write_text("premium", encoding="utf-8")

    found = mod.discover_story_files(tmp_path)

    assert found == [
        tmp_path / "story-free.md",
        tmp_path / "story.md",
    ]


def test_select_story_files_prompts_each_existing_file(tmp_path):
    for name in ("story-free.md", "story-members.md", "story.md"):
        (tmp_path / name).write_text(name, encoding="utf-8")

    asked = []

    def confirm(path):
        asked.append(path.name)
        return path.name != "story-members.md"

    selected = mod.select_story_files(tmp_path, confirm_fn=confirm)

    assert asked == ["story-free.md", "story-members.md", "story.md"]
    assert selected == [
        tmp_path / "story-free.md",
        tmp_path / "story.md",
    ]


def test_main_updates_only_selected_story_levels(tmp_path, monkeypatch):
    free = tmp_path / "story-free.md"
    members = tmp_path / "story-members.md"
    premium = tmp_path / "story.md"

    for path in (free, members, premium):
        path.write_text(f"header {path.name}\n", encoding="utf-8")

    monkeypatch.setattr(
        mod,
        "read_settings",
        lambda: mod.AddAIStorySettings(
            story_filenames=mod.DEFAULT_STORY_FILENAMES,
            default_tags=(),
            image_mode="move",
        ),
    )
    monkeypatch.setattr(
        mod,
        "select_story_files",
        lambda target, names: [free, premium],
    )
    monkeypatch.setattr(
        mod,
        "read_input",
        lambda path: ">>> Question\nAnswer\n",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["addaistorytext.py", str(tmp_path)],
    )

    mod.main()

    assert '"""Narrator' in free.read_text(encoding="utf-8")
    assert '"""Narrator' not in members.read_text(encoding="utf-8")
    assert '"""Narrator' in premium.read_text(encoding="utf-8")
