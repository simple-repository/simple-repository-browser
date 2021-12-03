import argparse
from . import _app


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.description = "Run the PyPI-frontend (with gunicorn)"

    # Define the function to be called to eventually handle the
    # parsed arguments.
    parser.set_defaults(handler=handler)

    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)


def handler(args: dict) -> None:
    from ._gunicorn import Application
    Application(
        app=_app.app,
        options={
            'bind': f'{args.host}:{args.port}',
        }
    ).run()


def main():
    parser = argparse.ArgumentParser()
    configure_parser(parser)
    args = parser.parse_args()
    args.handler(args)


if __name__ == '__main__':
    main()
