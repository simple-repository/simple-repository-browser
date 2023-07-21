import shutil
from pathlib import Path

here = Path(__file__).parent

build = here / 'built-repo'
if build.is_dir():
    shutil.rmtree(build)
build.mkdir()

shutil.copytree(here / 'javascript', build / 'javascript')
srb = build / 'simple_repository_browser'
shutil.copytree(here / 'simple_repository_browser', srb)


for pcache in build.glob('**/__pycache__'):
    shutil.rmtree(pcache)

(srb / '_version.py').unlink()
shutil.rmtree(srb / 'static' / 'js')
shutil.rmtree(build / 'javascript' / 'node_modules')
(srb / 'tests' / 'test_pypi_frontend.py').unlink()
(srb / 'lazy_wheel.py').unlink()
(srb / '_develop.py').unlink()


for file in build.glob('**/*.py'):
    file.write_text(file.read_text().replace('acc_py_index', 'simple_repository'))

for file in [here / 'setup.py', here / 'pyproject.toml']:
    shutil.copy(file, build)
