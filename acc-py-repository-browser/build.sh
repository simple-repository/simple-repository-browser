set -ex

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
acc_py_root=${SCRIPT_DIR}
repo_browser_root=$(dirname ${acc_py_root})
rm -rf ${acc_py_root}/simple_repository_browser

# Ship the code for the simple_repository_browser, which we extend in Acc-Py Repository browser
mkdir -p ${acc_py_root}/simple_repository_browser
cp -rf ${repo_browser_root}/simple_repository_browser/* ${acc_py_root}/simple_repository_browser

python -m pip install build setuptools-scm
# Make sure that simple-repo-browser gets its version file (so that it can be imported)
python -m build --no-isolation --sdist ${repo_browser_root}
python <(cat <<EoF
from pathlib import Path
import sys

sys.path.append('${repo_browser_root}')
from simple_repository_browser._compile_static import compile_static_files;

compile_static_files(
    destination=Path('./acc_py_repository_browser/static'),
    sources=[
      Path('${repo_browser_root}') / 'simple_repository_browser' / 'static_source',
      Path('${acc_py_root}') / 'acc_py_repository_browser' / 'static_source',
  ],
)

EoF
)
