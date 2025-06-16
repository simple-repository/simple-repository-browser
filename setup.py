import pathlib
import sys

from setuptools import setup

sys.path.insert(0, 'simple_repository_browser')
from _compile_static import compile_static_files  # type: ignore[import-not-found]

root = pathlib.Path(__file__).parent

static_dir = root / 'simple_repository_browser' / 'static_source'
dest = root / 'simple_repository_browser' / 'static'

compile_static_files(destination=dest, sources=[static_dir])

setup()
