# pypi-frontend

A frontend to a simple package index ([PEP503](https://www.python.org/dev/peps/pep-0503/))


## Development

See the Dockerfile for canonical instructions. They approximately look like:

```
pushd javascript
  npm install --include=dev
  npm run build
popd
pip install -e .[dev]
```

## Deployment

On development machine:

```
npm run build

python -m build
```

Then, copy the built wheel to acc-py-repo.cern.ch. On that machine:

```
source /opt/acc-py/base/2020.11/setup.sh
acc-py app deploy /path/to/wheel --deploy-base /opt/acc-py/apps/
```

Restart the acc-pypi-frontend service:

```
systemctrl restart acc-pypi-frontend
```
