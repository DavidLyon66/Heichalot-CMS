from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
TEMPLATES_DIR = TESTS_DIR / "templates"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def make_production(tmp_path: Path):
    """
    Create a temporary production directory by copying a fixture template
    directory from tests/templates/<template_name>.
    """

    def _make(template_name: str) -> Path:
        src = TEMPLATES_DIR / template_name
        if not src.exists():
            raise FileNotFoundError(f"Missing test template directory: {src}")

        production_dir = tmp_path / template_name
        shutil.copytree(src, production_dir)

        (production_dir / "assets").mkdir(exist_ok=True)
        (production_dir / "output").mkdir(exist_ok=True)

        return production_dir

    return _make


