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


def handler(args: dict) -> None:
    # app = _app.make_app(cache_dir=args.cache_dir)
    Path(args.logs_dir).mkdir(exist_ok=True, parents=True)
    Application(
        app=_app.app,
        options={
            'bind': f'{args.host}:{args.port}',
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
