import argparse
import importlib
import logging
import os
import typing
from pathlib import Path

from . import _app
from ._gunicorn import Application


def configure_parser(parser: argparse.ArgumentParser) -> None:
    pwd = Path.cwd()
    parser.description = "Run the PyPI-frontend (with gunicorn)"

    # Define the function to be called to eventually handle the
    # parsed arguments.
    parser.set_defaults(handler=handler)

    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--logs-dir", type=str, default=str(pwd / 'logs'))
    parser.add_argument("--cache-dir", type=str, default=Path(os.environ.get('XDG_CACHE_DIR', Path.home() / '.cache')) / 'simple-repository-browser')
    parser.add_argument("--index-url", type=str, default=None)
    parser.add_argument("--url-prefix", type=str, default=None)
    parser.add_argument('--customiser', type=str, default="simple_repository_browser._app:Customiser")


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
    Path(args.logs_dir).mkdir(exist_ok=True, parents=True)
    bind = f'{args.host}:{args.port}'
    print(f'Starting application on http://{bind}{args.url_prefix or ""}/')
    print(f'Cache in {args.cache_dir}')
    print(f'Logs in {args.logs_dir}')
    Application(
        app=app,
        options={
            'bind': bind,
            "accesslog": f"{args.logs_dir}/access.log",
            "errorlog": f"{args.logs_dir}/error.log",
            "worker_class": "uvicorn.workers.UvicornWorker",
            "default_proc_name": __package__,
            "capture_output": True,
        },
    ).run()


def main():
    parser = argparse.ArgumentParser()
    configure_parser(parser)
    args = parser.parse_args()
    args.handler(args)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
