set -e

# Copy the simple-repository-browser's setup.py directory, and then
# inject any substitutions.

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
repo_browser_root=$(dirname ${SCRIPT_DIR})
rm -rf ${SCRIPT_DIR}/setup.py ${SCRIPT_DIR}/deployment
cp -rf ${repo_browser_root}/setup.py ${SCRIPT_DIR}
cp -rf ${repo_browser_root}/deployment ${SCRIPT_DIR}
rm -f ${SCRIPT_DIR}/simple_repository_browser
ln -s ${repo_browser_root}/simple_repository_browser ${SCRIPT_DIR}/simple_repository_browser
cp -rf ${repo_browser_root}/simple_repository_browser/static/images/python-logo-only.svg ${SCRIPT_DIR}/acc_py_repository_browser/static/images
cp -rf ${repo_browser_root}/simple_repository_browser/static/images/favicon.6a76275d.ico ${SCRIPT_DIR}/acc_py_repository_browser/static/images

sed -i 's/packages\=\['"'"'simple_repository_browser'"'"'\],/packages=['"'"'acc_py_repository_browser'"'"', '"'"'simple_repository_browser'"'"'],/g' ${SCRIPT_DIR}/setup.py
sed -i 's/simple-repository-browser/acc-py-repository-browser/g' ${SCRIPT_DIR}/setup.py
find ${SCRIPT_DIR}/deployment -type f -exec sed -i 's/simple-repository-browser/acc-py-repository-browser/g' {} \;

${SCRIPT_DIR}/javascript/build.sh
