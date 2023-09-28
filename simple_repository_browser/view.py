import typing
from pathlib import Path

import fastapi
import jinja2

from . import Context


class View:
    def __init__(self, templates_paths: typing.Sequence[Path], browser_version: str):
        self.templates_paths = templates_paths
        self.version = browser_version
        self.templates_env = self.create_templates_environment()

    def create_templates_environment(self) -> jinja2.Environment:
        loader = jinja2.FileSystemLoader(self.templates_paths)
        templates = jinja2.Environment(loader=loader)

        @jinja2.pass_context
        def url_for(context: dict, name: str, **path_params: typing.Any) -> str:
            request: fastapi.Request = context["request"]
            return request.url_for(name, **path_params)

        def sizeof_fmt(num: float, suffix: str = "B"):
            for unit in ("", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"):
                if abs(num) < 1024.0:
                    return f"{num:3.1f}{unit}{suffix}"
                num /= 1024.0
            return f"{num:.1f}Yi{suffix}"

        templates.globals['url_for'] = url_for
        templates.globals['fmt_size'] = sizeof_fmt
        templates.globals['browser_version'] = self.version

        return templates

    def render_template(self, context: Context, template: str) -> str:
        return self.templates_env.get_template(template).render(**context)

    def about_page(self, context) -> str:
        return self.render_template(context, "about.html")

    def search_page(self, context) -> str:
        return self.render_template(context, "search.html")

    def index_page(self, context) -> str:
        return self.render_template(context, "index.html")

    def project_page(self, context) -> str:
        return self.render_template(context, "project.html")

    def error_page(self, context) -> str:
        return self.render_template(context, "error.html")
