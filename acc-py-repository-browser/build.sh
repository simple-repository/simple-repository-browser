set -ex

# Copy the simple-repository-browser's setup.py directory, and then
# inject any substitutions.

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
acc_py_root=${SCRIPT_DIR}
repo_browser_root=$(dirname ${acc_py_root})
rm -rf ${acc_py_root}/setup.py ${acc_py_root}/deployment ${acc_py_root}/simple_repository_browser
cp -rf ${repo_browser_root}/pyproject.toml ${acc_py_root}
cp -rf ${repo_browser_root}/deployment ${acc_py_root}
# Ship the code for the simple_repository_browser, which we extend in Acc-Py Repository browser
mkdir -p ${acc_py_root}/simple_repository_browser
cp -rf ${repo_browser_root}/simple_repository_browser/* ${acc_py_root}/simple_repository_browser
cp -rf ${repo_browser_root}/simple_repository_browser/static/images/python-logo-only.svg ${acc_py_root}/acc_py_repository_browser/static/images
cp -rf ${repo_browser_root}/simple_repository_browser/static/images/favicon.6a76275d.ico ${acc_py_root}/acc_py_repository_browser/static/images

python <(cat <<EoF
from pathlib import Path
lines = []
pyproject_file = Path('${acc_py_root}/pyproject.toml')
for line in pyproject_file.read_text().splitlines():
    if line.startswith('include ='):
        line = 'include = ["simple_repository_browser", "simple_repository_browser.*", "acc_py_repository_browser", "acc_py_repository_browser.*  "]'
    else:
        line = line.replace('simple-repository-browser', 'acc-py-repository-browser')

    if line == 'version_file = "simple_repository_browser/_version.py"':
        lines.append('root = ".."')
        line = 'version_file = "simple_repository_browser/_version.py"'

    lines.append(line)
pyproject_file.write_text('\n'.join(lines) + '\n')

EoF
)

${acc_py_root}/javascript/build.sh
