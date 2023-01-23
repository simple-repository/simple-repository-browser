from pathlib import Path

import jinja2

import pypi_frontend._app as base


here = Path(__file__).absolute().parent


class AccPyCustomiser(base.Customiser):
    @classmethod
    def template_loader(cls) -> jinja2.BaseLoader:
        templates_dir = here / 'templates'
        # if not (templates_dir / 'base').exists():
        #     (templates_dir / 'base').symlink_to(base.here / 'templates')

        loader = jinja2.FileSystemLoader([templates_dir, base.here / 'templates'])
        return loader
