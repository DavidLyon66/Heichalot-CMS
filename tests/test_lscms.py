import sys
import importlib.util
import json
from pathlib import Path

import importlib.util
from pathlib import Path


def load_lscms_module():
    repo_root = Path(__file__).resolve().parent.parent
    module_path = repo_root / "tools" / "lscms.py"
    spec = importlib.util.spec_from_file_location("lscms", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


lscms = load_lscms_module()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def touch_with_mtime(path: Path, text: str, epoch: int) -> None:
    write_text(path, text)
    path.chmod(0o644)
    import os

    os.utime(path, (epoch, epoch))


def test_extract_title_prefers_yaml_title(tmp_path: Path) -> None:
    entry = tmp_path / 'entry-0000001'
    entry.mkdir()
    write_text(
        entry / 'story.md',
        '---\ntitle: Tokyo Station Remote-viewing\nkind: story\n---\n\n# Ignored Heading\n',
    )

    assert lscms.extract_title(entry) == 'Tokyo Station Remote-viewing'


def test_extract_title_falls_back_to_heading_then_text(tmp_path: Path) -> None:
    entry_heading = tmp_path / 'entry-0000002'
    entry_heading.mkdir()
    write_text(entry_heading / 'story.md', '\n# Karvellah population scan\n\nBody\n')
    assert lscms.extract_title(entry_heading) == 'Karvellah population scan'

    entry_text = tmp_path / 'entry-0000003'
    entry_text.mkdir()
    write_text(entry_text / 'story.md', '\n[SHOW A.png FOR 5s]\n\nOpening line here\n')
    assert lscms.extract_title(entry_text) == 'Opening line here'


def test_choose_activity_timestamp_includes_assets_and_markers(tmp_path: Path) -> None:
    entry = tmp_path / 'entry-0000004'
    entry.mkdir()

    touch_with_mtime(entry / 'story.md', '# Early title\n', 1_700_000_000)
    touch_with_mtime(entry / 'assets' / 'image.png', 'fake image payload', 1_700_100_000)
    touch_with_mtime(entry / 'debate' / 'comment.md', 'comment', 1_700_050_000)

    info = lscms.build_entry_info(entry, current_entry='entry-0000004')

    assert info.current is True
    assert info.last_activity_epoch == 1_700_100_000
    assert info.markers == ['story', 'assets', 'debate']


def test_iter_entry_dirs_ignores_non_entry_directories(tmp_path: Path) -> None:
    cms_dir = tmp_path / 'cms'
    cms_dir.mkdir()
    (cms_dir / 'entry-0000001').mkdir()
    (cms_dir / 'entry-0000002').mkdir()
    (cms_dir / 'notes').mkdir()
    write_text(cms_dir / 'entry-xyz' / 'story.md', '# not valid')

    found = [p.name for p in lscms.iter_entry_dirs(cms_dir)]
    assert found == ['entry-0000001', 'entry-0000002']


def test_main_json_output_uses_config_and_sorts_newest_first(tmp_path: Path, monkeypatch, capsys) -> None:
    cms_dir = tmp_path / 'cms'
    cms_dir.mkdir()

    older = cms_dir / 'entry-0000001'
    newer = cms_dir / 'entry-0000002'
    older.mkdir()
    newer.mkdir()

    touch_with_mtime(older / 'story.md', '---\ntitle: Older Entry\n---\n', 1_700_000_000)
    touch_with_mtime(newer / 'story.md', '---\ntitle: Newer Entry\n---\n', 1_700_200_000)

    config_dir = tmp_path / '.heichalotcms'
    config_dir.mkdir()
    write_text(
        config_dir / 'config.ini',
        f'[cms]\ncms_dir = {cms_dir}\ncurrent_entry = entry-0000002\n',
    )

    monkeypatch.setattr(lscms, 'CONFIG_PATH', config_dir / 'config.ini')

    rc = lscms.main(['--json'])
    assert rc == 0

    data = json.loads(capsys.readouterr().out)
    assert [item['entry_id'] for item in data] == ['entry-0000002', 'entry-0000001']
    assert data[0]['title'] == 'Newer Entry'
    assert data[0]['current'] is True
    assert data[1]['current'] is False


def test_main_rejects_invalid_limit(capsys) -> None:
    rc = lscms.main(['--limit', '0', '--cms-dir', '.'])
    assert rc == 2
    assert '--limit must be >= 1' in capsys.readouterr().err
