import shutil
import textwrap
from pathlib import Path

import tomlkit

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
if (srb/'static'/'js').exists():
    shutil.rmtree(srb / 'static' / 'js')
if (build / 'javascript' / 'node_modules').exists():
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


for file in [here / 'pyproject.toml']:
    shutil.copy(file, build)

pyproject_path = build / 'pyproject.toml'
pyproject_contents = tomlkit.parse(pyproject_path.read_text())
pyproject_contents['project']['urls']['Homepage'] = "https://github.com/simple-repository/simple-repository-browser"
pyproject_txt = tomlkit.dumps(pyproject_contents)

lines = []
for line in pyproject_txt.splitlines():
    if 'acc-py-repo' in line:
        continue
    if 'authlib' in line:
        continue
    if 'starlette' in line:
        continue
    lines.append(line)
pyproject_path.write_text('\n'.join(lines) + '\n')


for file in build.glob('**/templates/base/*'):
    if not file.is_file():
        continue
    content = file.read_text()
    content = content.replace(
        'https://gitlab.cern.ch/acc-co/devops/python/prototypes/simple-pypi-frontend',
        'https://github.com/simple-repository/simple-repository-browser',
    )

    content = textwrap.dedent('''\
    {#
     Copyright (C) 2023, CERN
     This software is distributed under the terms of the MIT
     licence, copied verbatim in the file "LICENSE".
     In applying this license, CERN does not waive the privileges and immunities
     granted to it by virtue of its status as Intergovernmental Organization
     or submit itself to any jurisdiction.
    #}\n
    ''') + content

    file.write_text(content)

hash_comment_files = (
    list(build.glob('**/*.py')) + list(build.glob('**/*.toml'))
)
for path in hash_comment_files:
    if not path.is_file():
        continue
    content = path.read_text()
    content = '\n'.join([
        '# Copyright (C) 2023, CERN',
        '# This software is distributed under the terms of the MIT',
        '# licence, copied verbatim in the file "LICENSE".',
        '# In applying this license, CERN does not waive the privileges and immunities',
        '# granted to it by virtue of its status as Intergovernmental Organization',
        '# or submit itself to any jurisdiction.',
        '',
    ]) + '\n' + content.lstrip()
    content = content.rstrip() + '\n'
    path.write_text(content, 'utf-8')
