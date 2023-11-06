import argparse
import logging
import pathlib
import typing

import uvicorn

import simple_repository_browser.__main__ as base
from simple_repository_browser import __version__

from ._app import AccAppBuilder

here = pathlib.Path(__file__).absolute().parent


def configure_parser(parser: argparse.ArgumentParser):
    base.configure_parser(parser)
    parser.set_defaults(
        handler=handler,
        repository_url='https://acc-py-repo.cern.ch/repository/vr-py-releases/simple/',
    )

    parser.add_argument("--internal-repository-url", type=str, default='https://acc-py-repo.cern.ch/repository/py-release-local/simple/')
    parser.add_argument("--external-repository-url", type=str, default='https://acc-py-repo.cern.ch/repository/py-thirdparty-remote/simple/')


def handler(args: typing.Any) -> None:
    base_app_directory = base.here
    app = AccAppBuilder(
        repository_url=args.repository_url,
        internal_repository_url=args.internal_repository_url,
        external_repository_url=args.external_repository_url,
        cache_dir=pathlib.Path(args.cache_dir),
        template_paths=[
            here / "templates",
            base_app_directory / "templates",
            base_app_directory / "templates" / "base",
        ],
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
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    main()
