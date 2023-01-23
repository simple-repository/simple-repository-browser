from enum import Enum
import logging
import traceback
from pathlib import Path
import typing
import sqlite3

import fastapi
from diskcache import Cache
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi_utils.tasks import repeat_every
import jinja2
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import _pypil
from . import __version__

from .fetch_description import package_info, EMPTY_PKG_INFO, PackageInfo
from . import fetch_projects


here = Path(__file__).absolute().parent


class ProjectPageSection(str, Enum):
    description = "description"
    releases = "releases"
    files = "files"
    dependencies = "dependencies"


class Customiser:
    # A class which can be overridden in order to customise the behaviour of
    # the underlying webapp.

    @classmethod
    def template_loader(cls) -> jinja2.BaseLoader:
        return jinja2.FileSystemLoader(here / "templates")

    @classmethod
    def templates(cls) -> jinja2.Environment:
        loader = cls.template_loader()
        templates = jinja2.Environment(loader=loader)

        @jinja2.pass_context
        def url_for(context: dict, name: str, **path_params: typing.Any) -> str:
            request = context["request"]
            return request.url_for(name, **path_params)

        templates.globals['url_for'] = url_for
        return templates

    @classmethod
    async def release_info_retrieved(cls, project: _pypil.Project, package_info: PackageInfo):
        pass

    @classmethod
    def prepare_static(cls, app) -> None:
        app.mount("/static", StaticFiles(directory=here / "static"), name="static")

    @classmethod
    def add_exception_middleware(cls, app):
        async def catch_exceptions_middleware(request: Request, call_next):
            # For example: invalid type in a parameter.
            try:
                return await call_next(request)
            except Exception as err:
                logging.error(traceback.format_exc())
                return HTMLResponse(
                    cls.templates().get_template('error.html').render(
                    **{
                        "request": request,
                        "detail": "Internal server error",
                    },
                    ),
                    status_code=500,
                )

        app.middleware('http')(catch_exceptions_middleware)

    @classmethod
    def decorate(cls, fn):
        # A hook to allow tweaking of endpoints (e.g. based on function name).
        return fn


def build_app(app: fastapi.FastAPI, customiser: Customiser) -> None:
    customiser.prepare_static(app)
    templates = customiser.templates()
    customiser.add_exception_middleware(app)

    @app.get("/", response_class=HTMLResponse, name='index')
    async def index_page(request: Request):
        return templates.get_template('index.html').render(
            **{
                "request": request,
            },
        )

    @app.get("/about", response_class=HTMLResponse, name='about')
    @customiser.decorate
    async def about_page(request: Request):

        with request.app.state.projects_db_connection as cursor:
            [n_packages] = cursor.execute('SELECT COUNT(canonical_name) FROM projects').fetchone()

        with request.app.state.cache as cache:
            n_dist_info = len(cache)
            packages_w_dist_info = set()
            for cache_type, name, version in cache:
                if cache_type == 'pkg-info':
                    packages_w_dist_info.add(name)
            n_packages_w_dist_info = len(packages_w_dist_info)

        return templates.get_template('about.html').render(
            **{
                "request": request,
                "n_packages": n_packages,
                "n_dist_info": n_dist_info,
                "n_packages_w_dist_info": n_packages_w_dist_info,
            },
        )

    @app.get("/search", response_class=HTMLResponse, name='search')
    @customiser.decorate
    async def search_page(request: Request, name: str, page: typing.Optional[int] = 0):
        name = _pypil.PackageName(name).normalized

        page_size = 50
        offset = page * page_size

        with request.app.state.projects_db_connection as cursor:
            exact = cursor.execute('SELECT * FROM projects WHERE canonical_name == ?', (f'{name}',)).fetchone()
            results = cursor.execute(
                "SELECT * FROM projects WHERE canonical_name LIKE ? OR summary LIKE ? LIMIT ? OFFSET ?",
                (f'%{name}%', f'%{name}%', page_size, offset)
            ).fetchall()

        # TODO: This shouldn't include the pagination.
        n_results = len(results)

        # Drop the duplicate.
        if exact in results:
            results.remove(exact)

        return templates.get_template("search.html").render(
            **{
                "request": request,
                "search_query": name,
                "exact": exact,
                "results": results,
                "results_count": n_results
            },
        )

    @app.exception_handler(StarletteHTTPException)
    @customiser.decorate
    async def http_exception_handler(request, exc):
        return HTMLResponse(
            templates.get_template("error.html").render(
                **{
                    "request": request,
                    "detail": exc.detail,
                },
            ),
            status_code=exc.status_code,
        )

    @app.get("/project/{project_name}", response_class=HTMLResponse, name='project')
    @customiser.decorate
    async def project_page__latest_release(
            request: Request,
            project_name: str,
    ):
        return await project_page__common_impl(request, project_name)

    @app.get("/project/{project_name}/{release}", response_class=HTMLResponse, name='project_release')
    @app.get("/project/{project_name}/{release}/{page_section}", response_class=HTMLResponse, name='project_release')
    @customiser.decorate
    async def project_page__specific_release(
            request: Request,
            project_name: str,
            release: str,
            page_section: typing.Optional[ProjectPageSection] = ProjectPageSection.description,
    ):
        _ = page_section  # Handled in javascript.
        return await project_page__common_impl(request, project_name, release)

    @customiser.decorate
    async def project_page__common_impl(request: Request, project_name: str, version: typing.Optional[str] = None) -> str:
        index: _pypil.SimplePackageIndex = request.app.state.full_index
        canonical_name = _pypil.PackageName(project_name).normalized
        try:
            prj = index.project(project_name)
            fetch_projects.insert_if_missing(request.app.state.projects_db_connection, prj.name, prj.name)
        except _pypil.PackageNotFound:
            fetch_projects.remove_if_found(request.app.state.projects_db_connection, canonical_name)
            raise HTTPException(status_code=404, detail=f"Project {project_name} not found.")

        latest_release = prj.latest_release()

        if version is None:
            release = latest_release
        else:
            try:
                release = prj.release(version)
            except ValueError:  # TODO: make this exception specific
                raise HTTPException(status_code=404, detail=f'Release "{version}" not found for {project_name}.')
        return templates.get_template("project.html").render(
            **{
                "request": request,
                "project": prj,
                "latest_version": None,
                "release": release,
                "latest_release": latest_release,  # Note: May be the same release.
            },
        )

    @app.get("/api/project/{project_name}/{release}", response_class=JSONResponse, name='api_project_release')
    @customiser.decorate
    async def release_api__json(request: Request, project_name: str, release: str, recache: bool = False):
        index: _pypil.SimplePackageIndex = request.app.state.full_index
        try:
            prj = index.project(project_name)
            fetch_projects.insert_if_missing(request.app.state.projects_db_connection, prj.name, prj.name)
        except _pypil.PackageNotFound:
            fetch_projects.remove_if_found(request.app.state.projects_db_connection, canonical_name)
            raise HTTPException(status_code=404, detail=f"Project {project_name} not found.")

        version = release
        try:
            release = prj.release(version)
        except ValueError:  # TODO: make this exception specific
            raise HTTPException(status_code=404, detail=f'Release "{version}" not found for {project_name}.')

        is_latest = release == prj.latest_release()

        with request.app.state.cache as cache:
            key = ('pkg-info', prj.name, release.version)
            if key in cache and not recache:
                release_info = cache[key]
            else:
                if recache:
                    print('Recaching')
                release_info = await package_info(release)
                await customiser.release_info_retrieved(prj, release_info)
                cache[key] = release_info

                if is_latest:
                    fetch_projects.update_summary(request.app.state.projects_db_connection, project_name, release_info.summary)
        if release_info is None:
            release_info = EMPTY_PKG_INFO
        # https://packaging.python.org/en/latest/specifications/core-metadata/
        # https://peps.python.org/pep-0566/
        # https://peps.python.org/pep-0621/
        # But also, the JSON API in practice https://warehouse.pypa.io/api-reference/json.html.
        meta = {
            "info": {
                "author": release_info.author,
                "author_email": "",
                "classifiers": release_info.classifiers,
                "creation_date": release_info.release_date.isoformat() if release_info.release_date else None,
                "description": release_info.description,
                "description_content_type": None,
                "description_html": release_info.description,
                "downloads": {
                    "last_day": -1,
                    "last_month": -1,
                    "last_week": -1
                },
                "home_page": release_info.url,
                "license": "",
                "maintainer": release_info.maintainer,
                "maintainer_email": "",
                "name": project_name,
                "platform": "",
                # Note on project-urls: https://stackoverflow.com/a/56243786/741316
                "project_urls": release_info.project_urls,
                "requires_dist": release_info.requires_dist,
                "requires_python": release_info.requires_python,
                "summary": release_info.summary,
                "version": release.version,
                "yanked": False,
                "yanked_reason": None
            },
            "last_serial": -1,
            "releases": {
                release.version: [
                    {
                        "comment_text": "",
                        # "digests": {
                        #     "md5": "bab8eb22e6710eddae3c6c7ac3453bd9",
                        #     "sha256": "7a7a8b91086deccc54cac8d631e33f6a0e232ce5775c6be3dc44f86c2154019d"
                        # },
                        "downloads": -1,
                        "filename": file.filename,
                        "has_sig": False,
                        # "md5_digest": "bab8eb22e6710eddae3c6c7ac3453bd9",
                        # "packagetype": "bdist_wheel",
                        # "python_version": "2.7",
                        "size": release_info.files_info[file.filename].size,
                        "upload_time_iso_8601": release_info.files_info[file.filename].created.isoformat(),
                        "url": file.url,
                        "yanked": False,
                        "yanked_reason": None,
                    }
                    for file in release.files()
                ]
            },
            "urls": [],
            "vulnerabilities": []
        }
        return meta

    @app.on_event("startup")
    @repeat_every(
        seconds=60 * 60 * 24,  # Each day.
        raise_exceptions=False,
        wait_first=False,
    )
    @customiser.decorate
    async def refetch_full_index() -> None:
        # We periodically want to refresh the project database to make sure we are up-to-date.
        await fetch_projects.fully_populate_db(app.state.projects_db_connection, app.state.full_index)


def make_app(
        cache_dir: Path = Path.cwd() / 'cache',
        index_url=None, prefix=None,
        customiser: Customiser = Customiser,
) -> fastapi.FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None)
    build_app(app, customiser=customiser)

    kwargs = {}
    if index_url is not None:
        kwargs.update({'source_url': index_url})

    # TODO: There is no longer a reason that this state should be separate from build_app.
    app.state.full_index = _pypil.SimplePackageIndex(**kwargs)
    app.state.index = app.state.full_index

    app.state.cache = Cache(str(cache_dir/'diskcache'))

    con = sqlite3.connect(cache_dir/'projects.sqlite')
    app.state.projects_db_connection = con

    app.state.version = __version__

    fetch_projects.create_table(con)

    if prefix is not None:
        base_app = FastAPI(docs_url=None, redoc_url=None)
        base_app.mount(prefix, app)
        app = base_app
    return app
