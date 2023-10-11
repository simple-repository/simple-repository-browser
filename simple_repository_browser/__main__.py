# Copyright (C) 2023, CERN
# This software is distributed under the terms of the MIT
# licence, copied verbatim in the file "LICENSE".
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as Intergovernmental Organization
# or submit itself to any jurisdiction.

import argparse
import logging
import os
import typing
from pathlib import Path

import uvicorn

from . import __version__
from ._app import AppBuilder

here = Path(__file__).absolute().parent


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.description = "Run the simple-repository-browser"

    # Define the function to be called to eventually handle the
    # parsed arguments.
    parser.set_defaults(handler=handler)

    parser.add_argument("index_url", type=str, nargs='?', default='https://pypi.org/simple/')
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--cache-dir", type=str, default=Path(os.environ.get('XDG_CACHE_DIR', Path.home() / '.cache')) / 'simple-repository-browser')
    parser.add_argument("--url-prefix", type=str, default="")
    parser.add_argument('--no-popular-project-crawl', dest='crawl_popular_projects', action='store_false', default=True)


def handler(args: typing.Any) -> None:
    app = AppBuilder(
        index_url=args.index_url,
        cache_dir=Path(args.cache_dir),
        template_paths=[here / "templates", here / "templates" / "base"],
        static_files_path=here / "static",
        crawl_popular_projects=args.crawl_popular_projects,
        url_prefix=args.url_prefix,
        browser_version=__version__,
    ).create_app()

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
