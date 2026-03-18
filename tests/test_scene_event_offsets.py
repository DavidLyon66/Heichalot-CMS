from __future__ import annotations

from pathlib import Path

from tools.rendervideo import compile_production


def write_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")

def test_untimed_aniboxes_anchor_to_latest_dialogue_start(tmp_path: Path) -> None:
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
This is the History of the Toyota Celica set in Tokyo Bay.
\"\"\" FOR 3s

[ANIBOX celica-side-view.jpg FOR 3s]

\"\"\"NARRATOR
Here we have the finest model ever produced
\"\"\" FOR 90f

[ANIBOX toyotacelicacarlossainz-3-2660714950.jpg FOR 3s]

\"\"\"NARRATOR
Thank you for coming.
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
    assert events[1]["atFrames"] == 0
    assert events[1]["durationFrames"] == 90

    assert events[2]["type"] == "dialogue"
    assert events[2]["atFrames"] == 90
    assert events[2]["durationFrames"] == 90

    assert events[3]["type"] == "anibox"
    assert events[3]["atFrames"] == 0
    assert events[3]["durationFrames"] == 90

    assert events[4]["type"] == "dialogue"
    assert events[4]["atFrames"] == 180
    assert events[4]["durationFrames"] == 60