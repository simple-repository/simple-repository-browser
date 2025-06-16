
from hashlib import sha256
import json
import pathlib
from pprint import pprint
import shutil
import typing


def compile_static_files(*, destination: pathlib.Path, sources: typing.Sequence[pathlib.Path]):
    """Compile a static directory from one or more source directories."""
    files_to_compile = {}
    for source in sources:
        assert source.exists()
        for path in sorted(source.glob('**/*')):
            if not path.is_file():
                continue
            if path.name.startswith('.'):
                continue
            rel = path.relative_to(source)
            files_to_compile[rel] = path

    print('Compiled static sources:')
    pprint(files_to_compile)

    manifest = {}
    for rel, source_path in files_to_compile.items():
        target_dir = (destination / rel).parent
        target_dir.mkdir(parents=True, exist_ok=True)

        file_hash = sha256(source_path.read_bytes()).hexdigest()[:12]
        name = f'{source_path.stem}.{file_hash}{source_path.suffix}'
        manifest[str(rel)] = str(rel.parent / name)
        shutil.copy(source_path, target_dir / name)

    json.dump({'file-map': manifest}, (destination / '.manifest.json').open('w'), indent=2)
    (destination / '.gitignore').write_text('*')


if __name__ == '__main__':
    pass
