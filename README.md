# simple-repository-browser

A web interface to explore and discover packages in a simple package repository ([PEP503](https://www.python.org/dev/peps/pep-0503/)), inspired by PyPI / warehouse.


## Development

See the Dockerfile for canonical instructions. They approximately look like:

```
pushd javascript
  npm install --include=dev
  npm run build
popd
pip install -e .[dev]
```
