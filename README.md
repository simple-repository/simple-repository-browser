# simple-repository-browser

A web interface to browse and search packages in **any** simple package repository (PEP-503), inspired by PyPI / warehouse.

Built using FastAPI and the [simple-repository](https://github.com/simple-repository/simple-repository) core library.

## Demo

A tech-preview demo is available at https://simple-repository.app.cern.ch/.

## Usage

Install from PyPI:

```bash
python -m pip install simple-repository-browser
```

And run:

```bash
simple-repository-browser
```

(or alternatively ``python -m simple_repository_browser``)

By default, this will use the repository at PyPI (https://pypi.org/simple/). You can point it to a custom
repository by passing the URL to the project list endpoint (the base URL according to PEP-503):

```bash
simple-repository-browser https://my-custom-repository.example.com/foo/simple/
```

## Screenshots:

Homepage:

![homepage screenshot](https://raw.githubusercontent.com/simple-repository/simple-repository-browser/main/screenshots/home.png)


Search:

![search result](https://raw.githubusercontent.com/simple-repository/simple-repository-browser/main/screenshots/search.png)


Project page:

![example project page](https://raw.githubusercontent.com/simple-repository/simple-repository-browser/main/screenshots/project.png)



## Runtime details

```simple-repository-browser``` exposes a FastAPI application, and it runs the application in a single ``uvicorn`` worker.
Metadata that is computed will be cached in the ``$XDG_CACHE_DIR/simple-repository-browser`` directory. This cache is not
intended to be shared among different repository URLs, and is unlikely to work for multiple ``simple-repository-browser``
versions. There is currently no intelligent cache invalidation for those cases.


## Development

In order to build the ``simple-repository-browser``, first:

```bash
cd javascript
npm install --include=dev
npm run build
cd ..
```

And then the normal installation procedure applies:

```bash
python -m pip install -e .
```

The browser can be run with:

```bash
python -m simple_repository_browser
```
