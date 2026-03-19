from __future__ import annotations

from pathlib import Path

from tools.rendervideo import compile_production, parse_show_tokens

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
    assert events[1]["type"] == "sfx"
    assert events[1]["file"] == "soft_whoosh.wav"
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

[SHOW hero_image.png FOR 5s]
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

def test_parse_show_basic():
    event = parse_show_tokens(["background.png", "FOR", "60s"], 30)
    assert event["type"] == "show"
    assert event["file"] == "background.png"
    assert event["durationFrames"] == 1800
    assert "zoomStart" not in event
    assert "zoomEnd" not in event
    assert "zoomCurve" not in event


def test_parse_show_zoom_defaults_to_linear():
    event = parse_show_tokens(
        ["background.png", "FOR", "60s", "ZOOM", "1.0->1.2"],
        30,
    )
    assert event["zoomStart"] == 1.0
    assert event["zoomEnd"] == 1.2
    assert event["zoomCurve"] == "linear"


def test_parse_show_zoom_with_curve():
    event = parse_show_tokens(
        ["background.png", "FOR", "60s", "ZOOM", "1.0->1.2", "CURVE", "ease_in_out"],
        30,
    )
    assert event["zoomStart"] == 1.0
    assert event["zoomEnd"] == 1.2
    assert event["zoomCurve"] == "ease_in_out"

import pytest

@pytest.mark.parametrize("curve_name", [
    "linear",
    "ease_in",
    "ease_out",
    "ease_in_out",
    "strong_ease_in",
    "strong_ease_out",
    "strong_ease_in_out",
])
def test_parse_show_zoom_supported_curves(curve_name):
    event = parse_show_tokens(
        ["background.png", "FOR", "60s", "ZOOM", "1.0->1.2", "CURVE", curve_name],
        30,
    )
    assert event["zoomCurve"] == curve_name


def test_parse_show_curve_without_zoom_rejected():
    with pytest.raises(ValueError, match="CURVE"):
        parse_show_tokens(
            ["background.png", "FOR", "60s", "CURVE", "ease_in_out"],
            30,
        )


def test_parse_show_bad_zoom_range_rejected():
    with pytest.raises(ValueError, match="Invalid SHOW ZOOM range"):
        parse_show_tokens(
            ["background.png", "FOR", "60s", "ZOOM", "hello"],
            30,
        )


def test_parse_show_unknown_curve_rejected():
    with pytest.raises(ValueError, match="Unsupported SHOW CURVE"):
        parse_show_tokens(
            ["background.png", "FOR", "60s", "ZOOM", "1.0->1.2", "CURVE", "banana"],
            30,
        )
