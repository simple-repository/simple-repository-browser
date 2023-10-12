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
(srb / '_develop.py').unlink()


for file in build.glob('**/*.py'):
    content = file.read_text().replace('acc_py_index', 'simple_repository')

    if '_devel_to_be_turned_into_test' in content:
        content = content.split('async def _devel_to_be_turned_into_test')[0]
        while content.strip().endswith('#'):
            content = content.rstrip()[:-1].rstrip()

    content = content.replace('https://gitlab.cern.ch/acc-co/devops/python/prototypes/simple-pypi-frontend', 'https://github.com/simple-repository/simple-repository-browser')

    file.write_text(content)


for file in [here / 'setup.py', here / 'pyproject.toml']:
    shutil.copy(file, build)

content = (build/'setup.py').read_text()
content = content.replace('acc-py-index~=3.0', 'simple-repository')
lines = []
for line in content.split('\n'):
    indent = len(line) - len(line.lstrip())
    if 'author=' in line:
        lines.append(' ' * indent + 'author="CERN, BE-CSS-SET",')
        continue
    if 'url=' in line:
        lines.append(' ' * indent + 'url="https://github.com/simple-repository/simple-repository-browser",')
        continue
    if 'author' in line:
        continue
    if 'maintainer' in line:
        continue
    lines.append(line)
(build/'setup.py').write_text('\n'.join(lines))


for file in build.glob('**/templates/base/*'):
    if not file.is_file():
        continue
    content = file.read_text()
    content = content.replace(
        'https://gitlab.cern.ch/acc-co/devops/python/prototypes/simple-pypi-frontend',
        'https://github.com/simple-repository/simple-repository-browser',
    )
    file.write_text(content)
