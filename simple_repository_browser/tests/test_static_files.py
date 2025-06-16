import json
import pathlib

import pytest

import simple_repository_browser
from simple_repository_browser.static_files import main


def test_cli__help(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as err_info:
        main(['--help'])
    assert err_info.value.code == 0
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) > 1


def test_cli__compile(tmp_path: pathlib.Path) -> None:
    simple_static_dir = pathlib.Path(simple_repository_browser.__file__).parent / 'static'
    target_static_dir = tmp_path / 'static'
    orig_files = [
        path for path in simple_static_dir.glob('**/*') if path.is_file() and not path.name.startswith('.')
    ]

    main(['compile', str(tmp_path / 'static'), str(simple_static_dir)])
    created_files = [
        path for path in target_static_dir.glob('**/*') if path.is_file() and not path.name.startswith('.')
    ]

    assert len(orig_files) > 1
    assert len(created_files) == len(orig_files)

    manifest_path = target_static_dir / '.manifest.json'
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text())
    file_map = manifest['file-map']

    assert len(file_map) == len(orig_files)
