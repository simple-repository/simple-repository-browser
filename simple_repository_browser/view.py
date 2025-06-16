from pathlib import Path
import typing

import fastapi
import jinja2
from packaging.requirements import Requirement
from starlette.datastructures import URL

from . import model
from .static_files import StaticFilesManifest


class View:
    def __init__(self, templates_paths: typing.Sequence[Path], browser_version: str, static_files_manifest: StaticFilesManifest):
        self.templates_paths = templates_paths
        self.version = browser_version
        self.static_files_manifest = static_files_manifest
        self.templates_env = self.create_templates_environment()

    def create_templates_environment(self) -> jinja2.Environment:
        loader = jinja2.FileSystemLoader(self.templates_paths)
        templates = jinja2.Environment(loader=loader, autoescape=True, undefined=jinja2.StrictUndefined)

        @jinja2.pass_context
        def url_for(context: typing.Mapping[str, typing.Any], name: str, **path_params: typing.Any) -> URL:
            request: fastapi.Request = context["request"]
            # We don't use request.url_for, as it always returns an absolute URL.
            # This prohibits running behind a proxy which doesn't correctly set
            # X-Forwarded-Proto / X-Forwarded-Prefix, such as the OpenShift ingress.
            # See https://github.com/encode/starlette/issues/538#issuecomment-1135096753 for the
            # proposed solution.
            return URL(str(request.app.url_path_for(name, **path_params)))

        @jinja2.pass_context
        def static_file_url(context: typing.Mapping[str, typing.Any], target_file: str) -> URL:
            if target_file.startswith("/"):
                target_file = target_file[1:]
            filename, _ = self.static_files_manifest.get(target_file) or [None, None]
            if not filename:
                raise ValueError(f"Asset not found in manifest: {target_file}")
            return url_for(context, 'static', path=filename)

        def sizeof_fmt(num: float, suffix: str = "B"):
            for unit in ("", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"):
                if abs(num) < 1024.0:
                    return f"{num:3.1f}{unit}{suffix}"
                num /= 1024.0
            return f"{num:.1f}Yi{suffix}"

        templates.globals['url_for'] = url_for
        templates.globals['static_file_url'] = static_file_url
        templates.globals['fmt_size'] = sizeof_fmt
        templates.globals['browser_version'] = self.version
        templates.globals['render_markers'] = render_markers

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


def render_markers(requirement: Requirement, *, format_strings: dict[str, str]) -> str:
    req_marker = requirement.marker
    result = ''
    if req_marker:
        # Access the AST. Not yet a public API, see https://github.com/pypa/packaging/issues/448.
        markers_ast = req_marker._markers
        result, _ = render_marker_ast(markers_ast, format_strings=format_strings)
    return result


def render_marker_ast(ast: list | tuple, *, format_strings: dict[str, str]) -> tuple[str, int]:
    # Render the given ast, and return the maximum depth of the ast that was found when rendering.

    # Comment in https://github.com/pypa/packaging/blob/09f131b326453f18a217fe34f4f7a77603b545db/src/packaging/markers.py#L203C13-L215C16.
    # For example, the following expression:
    # python_version > "3.6" or (python_version == "3.6" and os_name == "unix")
    #
    # is parsed into:
    # [
    #     (<Variable('python_version')>, <Op('>')>, <Value('3.6')>),
    #     'and',
    #     [
    #         (<Variable('python_version')>, <Op('==')>, <Value('3.6')>),
    #         'or',
    #         (<Variable('os_name')>, <Op('==')>, <Value('unix')>)
    #     ]
    # ]

    if isinstance(ast, list) and len(ast) == 1:
        # https://github.com/pypa/packaging/blob/09f131b326453f18a217fe34f4f7a77603b545db/src/packaging/markers.py#L75
        return render_marker_ast(ast[0], format_strings=format_strings)

    if isinstance(ast, list):
        lhs_str, lhs_maxdepth = render_marker_ast(ast[0], format_strings=format_strings)
        rhs_str, rhs_maxdepth = render_marker_ast(ast[2], format_strings=format_strings)
        group_formatter = format_strings.get('group_expr', '({expr})')
        if lhs_maxdepth >= 1:
            lhs_str = group_formatter.format(expr=lhs_str)
        if rhs_maxdepth >= 1:
            rhs_str = group_formatter.format(expr=rhs_str)
        format_str = format_strings['combine_nested_expr']
        result = format_str.format(lhs=lhs_str, op=ast[1], rhs=rhs_str)
        return result, max([lhs_maxdepth, rhs_maxdepth]) + 1
    elif isinstance(ast, tuple):
        format_str = format_strings['expr']
        result = format_str.format(lhs=ast[0].serialize(), op=ast[1].serialize(), rhs=ast[2].serialize())
        return result, 0
    else:
        raise TypeError(f'Unhandled marker {ast!r}')
