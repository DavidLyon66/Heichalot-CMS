from __future__ import annotations

from pathlib import Path

from tools.rendervideo import compile_production


def write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_compile_simple_dialogue(tmp_path: Path) -> None:
    production_dir = tmp_path / "prod"
    production_dir.mkdir()

    write_file(
        production_dir / "video.md",
        """---
kind: video
entry_id: 0000003
production_name: something
renderer: remotion
duration: 30
fps: 30
---

\"\"\"NARRATOR
This is the HeichalotCMS VideoRenderer explanation.
\"\"\"
""",
    )

    write_file(
        production_dir / "video.render.json",
        """{
  "renderer": "remotion",
  "duration": 30,
  "fps": 30,
  "events": []
}
""",
    )

    compiled = compile_production(production_dir)

    assert compiled["renderer"] == "remotion"
    assert compiled["duration"] == 30
    assert compiled["fps"] == 30
    assert len(compiled["events"]) == 1

    event = compiled["events"][0]
    assert event["type"] == "dialogue"
    assert event["speaker"] == "NARRATOR"
    assert event["text"] == "This is the HeichalotCMS VideoRenderer explanation."


def test_compile_show_fade_sfx_dialogue(tmp_path: Path) -> None:
    production_dir = tmp_path / "prod"
    production_dir.mkdir()

    write_file(
        production_dir / "video.md",
        """---
renderer: remotion
duration: 30
fps: 30
---

[SHOW hero_image.png]
[SFX soft_whoosh.wav]
[FADE TO EVIDENCE OVERLAY]

\"\"\"NARRATOR
This is the HeichalotCMS VideoRenderer explanation.
\"\"\"
""",
    )

    write_file(
        production_dir / "video.render.json",
        """{"events": []}""",
    )

    compiled = compile_production(production_dir)
    events = compiled["events"]

    assert len(events) == 4
    assert events[0]["type"] == "show"
    assert events[0]["file"] == "hero_image.png"
    assert events[1] == {"type": "sfx", "file": "soft_whoosh.wav", "line": 7}
    assert events[2]["type"] == "fade"
    assert events[2]["target"] == "evidence_overlay"
    assert events[3]["type"] == "dialogue"
    assert events[3]["text"] == "This is the HeichalotCMS VideoRenderer explanation."

def test_compile_show_with_duration_seconds(tmp_path: Path) -> None:
    production_dir = tmp_path / "prod"
    production_dir.mkdir()

    write_file(
        production_dir / "video.md",
        """---
renderer: remotion
duration: 30
fps: 30
---

[SHOW hero.png IMAGE FOR 5s]
""",
    )

    write_file(
        production_dir / "video.render.json",
        """{"events": []}""",
    )

    compiled = compile_production(production_dir)
    events = compiled["events"]

    assert len(events) == 1
    assert events[0]["type"] == "show"
    assert events[0]["file"] == "hero.png"
    assert events[0]["durationFrames"] == 150


def test_compile_show_with_duration_frames(tmp_path: Path) -> None:
    production_dir = tmp_path / "prod"
    production_dir.mkdir()

    write_file(
        production_dir / "video.md",
        """---
renderer: remotion
duration: 30
fps: 30
---

[SHOW hero_image.png FOR 150f]
""",
    )

    write_file(
        production_dir / "video.render.json",
        """{"events": []}""",
    )

    compiled = compile_production(production_dir)
    events = compiled["events"]

    assert len(events) == 1
    assert events[0]["type"] == "show"
    assert events[0]["file"] == "hero_image.png"
    assert events[0]["durationFrames"] == 150

def test_compile_dialogue_with_seconds_duration(tmp_path: Path) -> None:
    production_dir = tmp_path / "prod"
    production_dir.mkdir()

    write_file(
        production_dir / "video.md",
        """---
renderer: remotion
duration: 30
fps: 30
---

\"\"\"NARRATOR
This is the HeichalotCMS VideoRenderer explanation.
\"\"\" FOR 3s
""",
    )

    write_file(
        production_dir / "video.render.json",
        """{"events": []}""",
    )

    compiled = compile_production(production_dir)
    event = compiled["events"][0]

    assert event["type"] == "dialogue"
    assert event["speaker"] == "NARRATOR"
    assert event["text"] == "This is the HeichalotCMS VideoRenderer explanation."
    assert event["durationFrames"] == 90


def test_compile_dialogue_with_frame_duration(tmp_path: Path) -> None:
    production_dir = tmp_path / "prod"
    production_dir.mkdir()

    write_file(
        production_dir / "video.md",
        """---
renderer: remotion
duration: 30
fps: 30
---

\"\"\"NARRATOR
Thank you for coming.
\"\"\" FOR 45f
""",
    )

    write_file(
        production_dir / "video.render.json",
        """{"events": []}""",
    )

    compiled = compile_production(production_dir)
    event = compiled["events"][0]

    assert event["type"] == "dialogue"
    assert event["speaker"] == "NARRATOR"
    assert event["text"] == "Thank you for coming."
    assert event["durationFrames"] == 45

def test_compile_dialogue_with_seconds_duration(tmp_path: Path) -> None:
    production_dir = tmp_path / "prod"
    production_dir.mkdir()

    write_file(
        production_dir / "video.md",
        """---
renderer: remotion
duration: 30
fps: 30
---

\"\"\"NARRATOR
This is the HeichalotCMS VideoRenderer explanation.
\"\"\" FOR 3s
""",
    )

    write_file(
        production_dir / "video.render.json",
        """{"events": []}""",
    )

    compiled = compile_production(production_dir)
    event = compiled["events"][0]

    assert event["type"] == "dialogue"
    assert event["speaker"] == "NARRATOR"
    assert event["text"] == "This is the HeichalotCMS VideoRenderer explanation."
    assert event["durationFrames"] == 90


def test_compile_dialogue_with_frame_duration(tmp_path: Path) -> None:
    production_dir = tmp_path / "prod"
    production_dir.mkdir()

    write_file(
        production_dir / "video.md",
        """---
renderer: remotion
duration: 30
fps: 30
---

\"\"\"NARRATOR
Thank you for coming.
\"\"\" FOR 45f
""",
    )

    write_file(
        production_dir / "video.render.json",
        """{"events": []}""",
    )

    compiled = compile_production(production_dir)
    event = compiled["events"][0]

    assert event["type"] == "dialogue"
    assert event["speaker"] == "NARRATOR"
    assert event["text"] == "Thank you for coming."
    assert event["durationFrames"] == 45
