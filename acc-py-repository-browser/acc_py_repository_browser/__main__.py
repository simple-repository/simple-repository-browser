import argparse
import logging
import pathlib
import typing

import uvicorn

import simple_repository_browser.__main__ as base
from simple_repository_browser import __version__

from ._app import create_app

here = pathlib.Path(__file__).absolute().parent


def configure_parser(parser: argparse.ArgumentParser):
    base.configure_parser(parser)
    parser.set_defaults(
        **{
            'handler': handler,
            'index_url': 'https://acc-py-repo.cern.ch/repository/vr-py-releases/simple/',
        },
    )

    parser.add_argument("--internal_index_url", type=str, default='https://acc-py-repo.cern.ch/repository/py-release-local/simple/')
    parser.add_argument("--external_index_url", type=str, default='https://acc-py-repo.cern.ch/repository/py-thirdparty-remote/simple/')


def handler(args: typing.Any) -> None:
    parent_dir = base.here
    app = create_app(
        index_url=args.index_url,
        internal_index_url=args.internal_index_url,
        external_index_url=args.external_index_url,
        cache_dir=pathlib.Path(args.cache_dir),
        template_paths=[
            here / "templates",
            parent_dir / "templates",
            parent_dir / "templates" / "base",
        ],
        static_files_path=here / "static",
        crawl_popular_projects=args.crawl_popular_projects,
        url_prefix=args.url_prefix,
        browser_version=__version__,
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
