from __future__ import annotations

from pathlib import Path

from tools.rendervideo import compile_production


def write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_compile_events_into_single_scene(tmp_path: Path) -> None:
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
This is the HeichalotCMS VideoRenderer explanation.
\"\"\" FOR 3s

[ANIBOX celica-side-view.jpg AT 1s FOR 3s]
""",
    )

    write_file(
        production_dir / "video.render.json",
        """{"events": []}""",
    )

    compiled = compile_production(production_dir)

    assert "scenes" in compiled
    assert len(compiled["scenes"]) == 1

    scene = compiled["scenes"][0]
    assert scene["type"] == "scene"
    assert scene["background"]["type"] == "show"
    assert scene["background"]["file"] == "tokyo-harbour.png"
    assert scene["durationFrames"] == 150

    assert len(scene["events"]) == 2
    assert scene["events"][0]["type"] == "dialogue"
    assert scene["events"][0]["durationFrames"] == 90

    assert scene["events"][1]["type"] == "anibox"
    assert scene["events"][1]["file"] == "celica-side-view.jpg"
    assert scene["events"][1]["atFrames"] == 30
    assert scene["events"][1]["durationFrames"] == 90


def test_compile_two_shows_into_two_scenes(tmp_path: Path) -> None:
    production_dir = tmp_path / "prod"
    production_dir.mkdir()

    write_file(
        production_dir / "video.md",
        """---
renderer: remotion
duration: 10
fps: 30
---

[SHOW scene1.png FOR 5s]
\"\"\"NARRATOR
Scene one.
\"\"\" FOR 2s

[SHOW scene2.png FOR 4s]
\"\"\"NARRATOR
Scene two.
\"\"\" FOR 2s
""",
    )

    write_file(
        production_dir / "video.render.json",
        """{"events": []}""",
    )

    compiled = compile_production(production_dir)

    assert len(compiled["scenes"]) == 2
    assert compiled["scenes"][0]["background"]["file"] == "scene1.png"
    assert compiled["scenes"][0]["durationFrames"] == 150
    assert compiled["scenes"][1]["background"]["file"] == "scene2.png"
    assert compiled["scenes"][1]["durationFrames"] == 120