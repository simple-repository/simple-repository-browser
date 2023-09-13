set -e

# Copy the simple-repository-browser's javascript directory, and then
# inject any substitution files found in acc-py-repository-browser's repo.
# For more advanced functionality (like adding additional JS dependencies, then
# acc-py-repository-browser needs to become a node package which depends on
# simple-repository-browser. For now, we want to keep things as simple as
# possible though.


SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
JS_BUILD_DIR="${SCRIPT_DIR}/../js_build"
repo_browser_root=$(dirname $(dirname ${SCRIPT_DIR}))
rm -rf ${JS_BUILD_DIR}
mkdir -p ${JS_BUILD_DIR}
cp -rf ${repo_browser_root}/javascript/* ${JS_BUILD_DIR}

pushd ${SCRIPT_DIR} > /dev/null  # chdir so that find gives us relative paths
find . -type f -exec cp {} ${JS_BUILD_DIR}/{} \;
popd  > /dev/null

pushd ${JS_BUILD_DIR} > /dev/null
npm install
npm run build

rm -rf ${SCRIPT_DIR}/../acc_py_repository_browser/static/js
mv ${SCRIPT_DIR}/../simple_repository_browser/static/js ${SCRIPT_DIR}/../acc_py_repository_browser/static/
rm -rf ${SCRIPT_DIR}/../simple_repository_browser
