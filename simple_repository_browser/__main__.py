import argparse
import logging
import os
from pathlib import Path
import typing

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from . import __version__
from ._app import AppBuilder

here = Path(__file__).absolute().parent


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.description = "Run the simple-repository-browser"

    # Define the function to be called to eventually handle the
    # parsed arguments.
    parser.set_defaults(handler=handler)

    parser.add_argument(
        "repository_url", type=str, nargs="?", default="https://pypi.org/simple/"
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=Path(os.environ.get("XDG_CACHE_DIR", Path.home() / ".cache"))
        / "simple-repository-browser",
    )
    parser.add_argument("--url-prefix", type=str, default="")
    parser.add_argument(
        "--no-popular-project-crawl",
        dest="crawl_popular_projects",
        action="store_false",
        default=True,
    )
    parser.add_argument("--templates-dir", default=here / "templates", type=Path)


def handler(args: typing.Any) -> None:
    app = AppBuilder(
        repository_url=args.repository_url,
        cache_dir=Path(args.cache_dir),
        template_paths=[
            args.templates_dir,
            # Include the base templates so that the given templates directory doesn't have to
            # implement *all* of the templates. This must be at a lower precedence than the given
            # templates path, so that they can be overriden.
            here / "templates" / "base",
            # Include the "base" folder, such that upstream templates can inherit from "base/...".
            here / "templates",
        ],
        static_files_paths=[here / "static"],
        crawl_popular_projects=args.crawl_popular_projects,
        url_prefix=args.url_prefix,
        browser_version=__version__,
    ).create_app()

    log_conf = LOGGING_CONFIG.copy()
    log_conf["formatters"]["default"]["fmt"] = (
        "%(asctime)s [%(name)s] %(levelprefix)s %(message)s"
    )
    log_conf["formatters"]["access"]["fmt"] = (
        '%(asctime)s [%(name)s] %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
    )

    uvicorn.run(
        app=app,
        host=args.host,
        port=args.port,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_config=log_conf,
    )


def main():
    parser = argparse.ArgumentParser()
    configure_parser(parser)
    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    main()
