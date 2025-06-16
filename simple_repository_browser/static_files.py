import argparse
from hashlib import sha256
import json
import os
import pathlib
import shutil
import sys
import typing

from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles
from typing_extensions import override


def compile_static_files(*, destination: pathlib.Path, sources: typing.Sequence[pathlib.Path]):
    """Compile a static directory from one or more source directories."""
    # This function is designed to write the static files, could be useful for serving static
    # files via apache/nginx/etc.
    manifest = generate_manifest(sources)
    file_map = {'file-map': {}}

    for input_filename, (hashed_relpath, source_path) in manifest.items():
        target = destination / hashed_relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source_path, target)
        file_map['file-map'][str(input_filename)] = str(target)

    json.dump(file_map, (destination / '.manifest.json').open('w'), indent=2)
    (destination / '.gitignore').write_text('*')


def generate_manifest(sources: typing.Sequence[pathlib.Path]) -> dict[str, tuple[str, pathlib.Path]]:
    """
    Generate a manifest which maps template_rel_path to a (hashed_relpath, full_path) tuple.
    """
    manifest: dict[str, tuple[str, str]] = {}
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

    for rel, source_path in files_to_compile.items():
        file_hash = sha256(source_path.read_bytes()).hexdigest()[:12]
        name = f'{source_path.stem}.{file_hash}{source_path.suffix}'
        manifest[str(rel)] = (str(rel.parent / name), source_path)

    return manifest


class HashedStaticFileHandler(StaticFiles):
    def __init__(self, *, manifest, **kwargs):
        super().__init__(**kwargs)
        self.manifest = manifest
        self._inverted_manifest = {src: path for src, path in manifest.values()}

    @override
    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        actual_path = self._inverted_manifest.get(path)
        if actual_path is None:
            super.lookup_path(path)
        return actual_path, os.stat(actual_path)

    @override
    async def get_response(self, path: str, scope):
        response: FileResponse = await super().get_response(path, scope)
        if response.status_code in [200, 304]:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def main(argv: typing.Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog='simple_repository_browser.static')

    subparsers = parser.add_subparsers()

    parser_compile_static = subparsers.add_parser('compile', help='Compile the static files into a directory')
    parser_compile_static.add_argument('destination', type=pathlib.Path, help='Where to write the static files')
    parser_compile_static.add_argument(
        'source',
        type=pathlib.Path,
        help='The source of static files to combine (may be provided multiple times)',
        nargs='+',
    )
    parser_compile_static.set_defaults(handler=handle_compile)

    args = parser.parse_args(argv)
    args.handler(args)


def handle_compile(args: argparse.Namespace):
    print(f'Writing static files to {args.destination}')
    compile_static_files(destination=args.destination, sources=args.source)


if __name__ == '__main__':
    # Enable simple_repository_browser.static_files CLI.
    main(sys.argv[1:])
