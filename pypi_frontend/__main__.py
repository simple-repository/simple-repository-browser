import argparse
import logging
from pathlib import Path

from ._gunicorn import Application
from . import _app


def configure_parser(parser: argparse.ArgumentParser) -> None:
    pwd = Path.cwd()
    parser.description = "Run the PyPI-frontend (with gunicorn)"

    # Define the function to be called to eventually handle the
    # parsed arguments.
    parser.set_defaults(handler=handler)

    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--logs-dir", type=str, default=str(pwd / 'logs'))
    parser.add_argument("--cache-dir", type=str, default=str(pwd / 'cache'))
    parser.add_argument("--index-url", type=str, default=None)
    parser.add_argument("--url-prefix", type=str, default=None)


def handler(args: dict) -> None:
    app = _app.make_app(cache_dir=Path(args.cache_dir), index_url=args.index_url, prefix=args.url_prefix)
    Path(args.logs_dir).mkdir(exist_ok=True, parents=True)
    bind = f'{args.host}:{args.port}'
    print(f'Starting application on http://{bind}')
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
        }
    ).run()


def main():
    parser = argparse.ArgumentParser()
    configure_parser(parser)
    args = parser.parse_args()
    args.handler(args)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
