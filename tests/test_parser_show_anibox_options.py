from __future__ import annotations

from pathlib import Path

from tools.rendervideo import compile_production


def write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def compile_from_video_md(tmp_path: Path, video_md: str) -> dict:
    production_dir = tmp_path / "prod"
    production_dir.mkdir()

    write_file(production_dir / "video.md", video_md)
    write_file(production_dir / "video.render.json", """{"events": []}""")

    return compile_production(production_dir)


def test_show_with_explicit_filename_and_seconds_duration(tmp_path: Path) -> None:
    compiled = compile_from_video_md(
        tmp_path,
        """---
renderer: remotion
duration: 30
fps: 30
---

[SHOW route-map.png FOR 5s]
""",
    )

    event = compiled["events"][0]
    assert event["type"] == "show"
    assert event["file"] == "route-map.png"
    assert event["durationFrames"] == 150


def test_show_with_explicit_filename_and_frame_duration(tmp_path: Path) -> None:
    compiled = compile_from_video_md(
        tmp_path,
        """---
renderer: remotion
duration: 30
fps: 30
---

[SHOW route-map.png FOR 150f]
""",
    )

    event = compiled["events"][0]
    assert event["type"] == "show"
    assert event["file"] == "route-map.png"
    assert event["durationFrames"] == 150


def test_show_enter_fade_from_black(tmp_path: Path) -> None:
    compiled = compile_from_video_md(
        tmp_path,
        """---
renderer: remotion
duration: 30
fps: 30
---

[SHOW route-map.png FOR 5s ENTER FADE FROM BLACK]
""",
    )

    event = compiled["events"][0]
    assert event["type"] == "show"
    assert event["file"] == "route-map.png"
    assert event["durationFrames"] == 150
    assert event["enter"] == {"type": "fade", "from": "black"}


def test_show_leave_fade_to_black(tmp_path: Path) -> None:
    compiled = compile_from_video_md(
        tmp_path,
        """---
renderer: remotion
duration: 30
fps: 30
---

[SHOW route-map.png FOR 5s LEAVE FADE TO BLACK]
""",
    )

    event = compiled["events"][0]
    assert event["type"] == "show"
    assert event["file"] == "route-map.png"
    assert event["durationFrames"] == 150
    assert event["leave"] == {"type": "fade", "to": "black"}


def test_show_motion_zoom_in(tmp_path: Path) -> None:
    compiled = compile_from_video_md(
        tmp_path,
        """---
renderer: remotion
duration: 30
fps: 30
---

[SHOW route-map.png FOR 5s MOTION ZOOM IN]
""",
    )

    event = compiled["events"][0]
    assert event["type"] == "show"
    assert event["file"] == "route-map.png"
    assert event["durationFrames"] == 150
    assert event["motion"] == {"type": "zoom_in"}


def test_show_motion_scroll_down(tmp_path: Path) -> None:
    compiled = compile_from_video_md(
        tmp_path,
        """---
renderer: remotion
duration: 30
fps: 30
---

[SHOW route-map.png FOR 5s MOTION SCROLL DOWN]
""",
    )

    event = compiled["events"][0]
    assert event["type"] == "show"
    assert event["file"] == "route-map.png"
    assert event["durationFrames"] == 150
    assert event["motion"] == {"type": "scroll_down"}


def test_anibox_starting_and_duration_seconds(tmp_path: Path) -> None:
    compiled = compile_from_video_md(
        tmp_path,
        """---
renderer: remotion
duration: 30
fps: 30
---

[ANIBOX harbour.png STARTING 1s FOR 3s]
""",
    )

    event = compiled["events"][0]
    assert event["type"] == "anibox"
    assert event["file"] == "harbour.png"
    assert event["atFrames"] == 30
    assert event["durationFrames"] == 90


def test_anibox_starting_and_duration_frames(tmp_path: Path) -> None:
    compiled = compile_from_video_md(
        tmp_path,
        """---
renderer: remotion
duration: 30
fps: 30
---

[ANIBOX harbour.png STARTING 45f FOR 120f]
""",
    )

    event = compiled["events"][0]
    assert event["type"] == "anibox"
    assert event["file"] == "harbour.png"
    assert event["atFrames"] == 45
    assert event["durationFrames"] == 120


def test_anibox_enter_fade(tmp_path: Path) -> None:
    compiled = compile_from_video_md(
        tmp_path,
        """---
renderer: remotion
duration: 30
fps: 30
---

[ANIBOX harbour.png STARTING 1s FOR 3s ENTER FADE]
""",
    )

    event = compiled["events"][0]
    assert event["type"] == "anibox"
    assert event["file"] == "harbour.png"
    assert event["atFrames"] == 30
    assert event["durationFrames"] == 90
    assert event["enter"] == "fade"


def test_anibox_enter_and_leave(tmp_path: Path) -> None:
    compiled = compile_from_video_md(
        tmp_path,
        """---
renderer: remotion
duration: 30
fps: 30
---

[ANIBOX harbour.png STARTING 45f FOR 120f ENTER SLIDE LEAVE ZOOM]
""",
    )

    event = compiled["events"][0]
    assert event["type"] == "anibox"
    assert event["file"] == "harbour.png"
    assert event["atFrames"] == 45
    assert event["durationFrames"] == 120
    assert event["enter"] == "slide"
    assert event["leave"] == "zoom"

def test_anibox_at_seconds_is_relative_to_last_show(tmp_path: Path) -> None:
    compiled = compile_from_video_md(
        tmp_path,
        """---
renderer: remotion
duration: 30
fps: 30
---

[SHOW route-map.png FOR 5s]
[ANIBOX donkey.png AT 1s FOR 3s]
""",
    )

    events = compiled["events"]

    assert events[0]["type"] == "show"
    assert events[0]["durationFrames"] == 150

    assert events[1]["type"] == "anibox"
    assert events[1]["file"] == "donkey.png"
    assert events[1]["atFrames"] == 30
    assert events[1]["durationFrames"] == 90


def test_anibox_at_frames_after_second_show_is_scene_relative(tmp_path: Path) -> None:
    compiled = compile_from_video_md(
        tmp_path,
        """---
renderer: remotion
duration: 30
fps: 30
---

[SHOW scene1.png FOR 5s]
[SHOW scene2.png FOR 4s]
[ANIBOX carrot.png AT 30f FOR 60f]
""",
    )

    assert len(compiled["scenes"]) == 2

    scene1 = compiled["scenes"][0]
    scene2 = compiled["scenes"][1]

    assert scene1["background"]["file"] == "scene1.png"
    assert scene1["durationFrames"] == 150

    assert scene2["background"]["file"] == "scene2.png"
    assert scene2["durationFrames"] == 120

    event = scene2["events"][0]
    assert event["type"] == "anibox"
    assert event["file"] == "carrot.png"
    assert event["atFrames"] == 30
    assert event["durationFrames"] == 60

def test_chapter_parses_title(tmp_path: Path) -> None:
    compiled = compile_from_video_md(
        tmp_path,
        """---
renderer: remotion
duration: 30
fps: 30
---

[CHAPTER Tokyo Harbour]
""",
    )

    event = compiled["events"][0]
    assert event["type"] == "chapter"
    assert event["title"] == "Tokyo Harbour"


def test_chapter_parses_longer_title(tmp_path: Path) -> None:
    compiled = compile_from_video_md(
        tmp_path,
        """---
renderer: remotion
duration: 30
fps: 30
---

[CHAPTER History of the Toyota Celica]
""",
    )

    event = compiled["events"][0]
    assert event["type"] == "chapter"
    assert event["title"] == "History of the Toyota Celica"

def test_anibox_at_is_preserved_inside_scene(tmp_path: Path) -> None:
    production_dir = tmp_path / "prod"
    production_dir.mkdir()

    write_file(
        production_dir / "video.md",
        """---
renderer: remotion
duration: 10
fps: 30
---

[SHOW tokyo-harbour.png FOR 5s]

\"\"\"NARRATOR
Intro text.
\"\"\" FOR 3s

[ANIBOX donkey.png AT 1s FOR 2s]

\"\"\"NARRATOR
More text.
\"\"\" FOR 2s
""",
    )

    write_file(
        production_dir / "video.render.json",
        """{"events": []}""",
    )

    compiled = compile_production(production_dir)
    scene = compiled["scenes"][0]
    events = scene["events"]

    assert events[0]["type"] == "dialogue"
    assert events[0]["atFrames"] == 0
    assert events[0]["durationFrames"] == 90

    assert events[1]["type"] == "anibox"
    assert events[1]["atFrames"] == 30
    assert events[1]["durationFrames"] == 60

    assert events[2]["type"] == "dialogue"
    assert events[2]["atFrames"] == 90
    assert events[2]["durationFrames"] == 60
