# Copyright (C) 2023, CERN
# This software is distributed under the terms of the MIT
# licence, copied verbatim in the file "LICENSE".
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as Intergovernmental Organization
# or submit itself to any jurisdiction.

import argparse
import importlib
import logging
import typing
from pathlib import Path

import uvicorn

from . import _app


def configure_parser(parser: argparse.ArgumentParser) -> None:
    pwd = Path.cwd()
    parser.description = "Run the PyPI-frontend"

    # Define the function to be called to eventually handle the
    # parsed arguments.
    parser.set_defaults(handler=handler)

    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--cache-dir", type=str, default=str(pwd / 'cache'))
    parser.add_argument("--index-url", type=str, default="https://pypi.org/simple/")
    parser.add_argument("--url-prefix", type=str, default=None)
    parser.add_argument(
        '--customiser', type=str, default="simple_repository_browser._app:Customiser",
    )


def load_customiser(name: str) -> typing.Type[_app.Customiser]:
    mod_name, class_name = name.split(':', 1)
    module = importlib.import_module(mod_name)
    cls = getattr(module, class_name)
    return cls


def handler(args: typing.Any) -> None:
    customiser = load_customiser(args.customiser)
    app = _app.make_app(
        cache_dir=Path(args.cache_dir),
        index_url=args.index_url,
        prefix=args.url_prefix,
        customiser=customiser,
    )
    uvicorn.run(
        app=app,
        host=args.host,
        port=args.port,
    )


def main():
    parser = argparse.ArgumentParser()
    configure_parser(parser)
    args = parser.parse_args()
    args.handler(args)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
