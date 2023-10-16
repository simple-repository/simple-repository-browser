# simple-repository-browser

A web interface to browse and search packages in **any** simple package repository ([PEP503](https://www.python.org/dev/peps/pep-0503/)), inspired by PyPI / warehouse.


## Development

See the Dockerfile for canonical instructions. They approximately look like:

```
pushd javascript
  npm install --include=dev
  npm run build
popd
pip install -e .[dev]
```


If you want to build the acc-py-browser:

```
cd acc-py-repository-browser/javascript
./build.sh
```

Note that any static resources in simple-repository-browser must also be mirrored in the acc-py-repository-browser.
