# Copyright (C) 2023, CERN
# This software is distributed under the terms of the MIT
# licence, copied verbatim in the file "LICENSE".
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as Intergovernmental Organization
# or submit itself to any jurisdiction.

import typing
from pathlib import Path

import fastapi
import jinja2

from . import model


class View:
    def __init__(self, templates_paths: typing.Sequence[Path], browser_version: str):
        self.templates_paths = templates_paths
        self.version = browser_version
        self.templates_env = self.create_templates_environment()

    def create_templates_environment(self) -> jinja2.Environment:
        loader = jinja2.FileSystemLoader(self.templates_paths)
        templates = jinja2.Environment(loader=loader, autoescape=True)

        @jinja2.pass_context
        def url_for(context: typing.Mapping[str, typing.Any], name: str, **path_params: typing.Any) -> str:
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

    def render_template(
        self,
        context: typing.Mapping[str, typing.Any],
        request: fastapi.Request,
        template: str,
    ) -> str:
        return self.templates_env.get_template(template).render(request=request, **context)

    # TODO: use typed arguments in the views
    def about_page(self, context: model.RepositoryStatsModel, request: fastapi.Request) -> str:
        return self.render_template(context, request, "about.html")

    def search_page(self, context: model.QueryResultModel, request: fastapi.Request) -> str:
        return self.render_template(context, request, "search.html")

    def index_page(self, request: fastapi.Request) -> str:
        return self.render_template({}, request, "index.html")

    def project_page(self, context: model.ProjectPageModel, request: fastapi.Request) -> str:
        return self.render_template(context, request, "project.html")

    def error_page(self, context: model.ErrorModel, request: fastapi.Request) -> str:
        return self.render_template(context, request, "error.html")
