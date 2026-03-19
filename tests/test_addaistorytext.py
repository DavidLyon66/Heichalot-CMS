from pathlib import Path
import sys

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


def test_render_blocks_formats_story_sections():
    blocks = [("Question", "Answer")]
    rendered = mod.render_blocks(blocks)
    assert rendered == '"""Narrator\nQuestion\n\n"""Ai\nAnswer\n'


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
    mod.append_story(path, '"""Narrator\nQ\n\n"""Ai\nA\n')
    assert path.read_text(encoding="utf-8") == (
        'header\n\n"""Narrator\nQ\n\n"""Ai\nA\n\n'
    )


def test_append_story_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "story.md"
    mod.append_story(path, '"""Narrator\nQ\n\n"""Ai\nA\n')
    assert path.read_text(encoding="utf-8") == (
        '\n"""Narrator\nQ\n\n"""Ai\nA\n\n'
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

    mod.write_debate('"""Narrator\nQ\n\n"""Ai\nA\n')

    debate_file = tmp_path / "debate" / "2026-03-19_02-17-44.md"
    assert debate_file.exists()
    assert debate_file.read_text(encoding="utf-8") == (
        "---\n"
        "origin: addaistorytext\n"
        "timestamp: 2026-03-19T02:17:44\n"
        "---\n\n"
        '"""Narrator\nQ\n\n"""Ai\nA\n'
    )


def test_read_config_defaults_when_no_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    story_filename, tags = mod.read_config()
    assert story_filename == "story.md"
    assert tags == []


def test_read_config_loads_story_filename_and_tags_from_heichalotcms(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / "heichalotcms"
    cfg_dir.mkdir()
    (cfg_dir / "config.ini").write_text(
        "[cms]\n"
        "story_filename = historia.md\n\n"
        "[tags]\n"
        "default_story_tags = remote-viewing, ai-session\n",
        encoding="utf-8",
    )

    story_filename, tags = mod.read_config()
    assert story_filename == "historia.md"
    assert tags == ["remote-viewing", "ai-session"]


def test_read_config_falls_back_to_local_config_ini(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.ini").write_text(
        "[cms]\n"
        "story_filename = localstory.md\n\n"
        "[tags]\n"
        "default_story_tags = remote-viewing\n",
        encoding="utf-8",
    )

    story_filename, tags = mod.read_config()
    assert story_filename == "localstory.md"
    assert tags == ["remote-viewing"]


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
    assert f"Appended 2 block(s) to {story_path}" in out

    assert story_path.read_text(encoding="utf-8") == (
        '"""Tags\n'
        'remote-viewing\n\n'
        '\n"""Narrator\n'
        'First question\n\n'
        '"""Ai\n'
        'First answer\n\n'
        '"""Narrator\n'
        'Second question\n\n'
        '"""Ai\n'
        'Second answer\n\n'

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
    assert f"Appended 1 block(s) to {story_path}" in out
    assert story_path.read_text(encoding="utf-8") == (
        '\n"""Narrator\n'
        'Clipboard question\n\n'
        '"""Ai\n'
        'Clipboard answer\n\n'
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

    assert called["text"] == '"""Narrator\nQ\n\n"""Ai\nA\n'
    assert not story_path.exists()
    _ = capsys.readouterr()
