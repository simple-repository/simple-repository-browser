import argparse
import logging

from simple_repository_browser.__main__ import \
    configure_parser as simple_configure_parser


def configure_parser(parser: argparse.ArgumentParser):
    simple_configure_parser(parser)
    parser.set_defaults(**{'customiser': 'acc_py_repository_browser:AccPyCustomiser'})


def main():
    parser = argparse.ArgumentParser()
    configure_parser(parser)
    args = parser.parse_args()
    args.handler(args)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
