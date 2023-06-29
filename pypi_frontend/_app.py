import asyncio
import logging
import sqlite3
import typing
from enum import Enum
from pathlib import Path

import aiohttp
import fastapi
import jinja2
import packaging.requirements
from diskcache import Cache
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, _pypil, _search, fetch_projects
from .fetch_description import EMPTY_PKG_INFO, PackageInfo, package_info
from acc_py_index.simple.repositories import http
from acc_py_index import errors, utils
from packaging.utils import canonicalize_name
from packaging.version import Version, InvalidVersion


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
        # Load the base directory directly (referencable as "index.html") as well as keeping the
        # base namespace "base/index.html". In this way, others can override specific pages
        # (e.g. index.html) but still extend from "base/index.html".
        return jinja2.FileSystemLoader([here / "templates", here / "templates" / "base"])

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
                logging.exception(err, exc_info=True)
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

    @classmethod
    async def fetch_pkg_info(cls, app: fastapi.FastAPI, prj: _pypil.Project, release: _pypil.ProjectRelease, force_recache: bool) -> typing.Optional[PackageInfo]:
        is_latest = release == prj.latest_release()
        with app.state.cache as cache:
            key = ('pkg-info', prj.name, release.version)
            if key in cache and not force_recache:
                release_info = cache[key]
                # Validate that the cached result covers all of the files, and that no new
                # files have been added since the cache was made. In that case, we re-cache.
                if all(
                    [
                        file.filename in release_info.files_info
                        for file in release.files()
                    ],
                ):
                    return release_info

            if force_recache:
                print('Recaching')

            fetch_projects.insert_if_missing(
                app.state.projects_db_connection,
                prj.name.normalized,
                prj.name,
            )

            release_info = await package_info(release)
            if release_info is not None:
                await cls.release_info_retrieved(prj, release_info)
            cache[key] = release_info

            if is_latest and release_info is not None:
                fetch_projects.update_summary(
                    app.state.projects_db_connection,
                    name=prj.name.normalized,
                    summary=release_info.summary,
                    release_date=release_info.release_date,
                    release_version=release.version,
                )

        return release_info

    @classmethod
    async def refetch_hook(cls, app: fastapi.FastAPI) -> None:
        # A hook, that can take as long as it likes to execute (asynchronously), which
        # gets called when the periodic reindexing occurs.
        # We periodically want to refresh the project database to make sure we are up-to-date.
        await fetch_projects.fully_populate_db(
            app.state.projects_db_connection,
            app.state.full_index,
        )
        with app.state.cache as cache:
            packages_w_dist_info = set()
            for cache_type, name, version in cache:
                if cache_type == 'pkg-info':
                    packages_w_dist_info.add(name)
        await cls.crawl_recursively(app, packages_w_dist_info)

    @classmethod
    async def crawl_recursively(cls, app: fastapi.FastAPI, normalized_project_names_to_crawl: typing.Set[str]) -> None:
        seen: set = set()
        packages_for_reindexing = set(normalized_project_names_to_crawl)
        full_index = app.state.full_index

        while packages_for_reindexing - seen:
            remaining_packages = packages_for_reindexing - seen
            pkg_name = remaining_packages.pop()
            print(
                f"Index iteration loop. Looking at {pkg_name}, with {len(remaining_packages)} remaining ({len(seen)} having been completed)",
            )
            seen.add(pkg_name)
            try:
                prj = full_index.project(pkg_name)
            except _pypil.PackageNotFound:
                # faulthandler
                continue

            latest = prj.latest_release()
            # Don't bother fetching devrelease only projects.
            vn = _pypil.safe_version(latest.version)
            if vn.is_devrelease or vn.is_prerelease:
                continue

            release_info = await cls.fetch_pkg_info(app, prj, latest, force_recache=False)
            if release_info is None:
                continue

            for dist in release_info.requires_dist:
                try:
                    dep_name = packaging.requirements.Requirement(dist).name
                except packaging.requirements.InvalidRequirement:
                    # See https://discuss.python.org/t/pip-supporting-non-pep508-dependency-specifiers/23107.
                    continue
                packages_for_reindexing.add(dep_name)

            # Don't DOS the service, we aren't in a rush here.
            await asyncio.sleep(0.01)


def build_app(app: fastapi.FastAPI, customiser: typing.Type[Customiser]) -> None:
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

        if app.state.periodic_reindexing_task is None:
            # Note that on_event('startup') does not reliably get called in our production
            # environment (unclear why not, as it does in local development).
            app.state.periodic_reindexing_task = asyncio.create_task(run_reindex_periodically(60*60*24))

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
    async def search_page(request: Request, query: str, page: typing.Optional[int] = 0):
        try:
            search_terms = _search.parse(query)
        except _search.ParseError:
            return HTMLResponse(
                templates.get_template("error.html").render(
                    **{
                        "request": request,
                        "search_query": query,
                        "detail": "Invalid search pattern",
                    },
                ),
                status_code=400,
            )

        try:
            if len(search_terms) == 0:
                raise ValueError("Please specify a search query")
            condition_query, condition_terms = _search.build_sql(search_terms)
        except ValueError as err:
            return HTMLResponse(
                templates.get_template("error.html").render(
                    **{
                        "request": request,
                        "search_query": query,
                        "detail": f"Search query invalid ({str(err)})",
                    },
                ),
                status_code=400,
            )

        page_size = 50
        page = page or 0
        offset = page * page_size

        single_name_proposal = _search.simple_name_from_query(search_terms)
        exact = None

        with request.app.state.projects_db_connection as cursor:
            if single_name_proposal:
                exact = cursor.execute(
                    'SELECT canonical_name, summary, release_version, release_date FROM projects WHERE canonical_name == ?',
                    (single_name_proposal,),
                ).fetchone()
            results = cursor.execute(
                "SELECT canonical_name, summary, release_version, release_date FROM projects WHERE "
                f"{condition_query} LIMIT ? OFFSET ?",
                condition_terms + (page_size, offset),
            ).fetchall()

        # TODO: This shouldn't include the pagination.
        n_results = len(results)

        # Drop the duplicate.
        if exact in results:
            results.remove(exact)

        return templates.get_template("search.html").render(
            **{
                "request": request,
                "search_query": query,
                "exact": exact,
                "results": results,
                "results_count": n_results,
                "single_name_proposal": single_name_proposal,
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

    @app.get("/project/{project_name}/{version}", response_class=HTMLResponse, name='project_version')
    @app.get("/project/{project_name}/{version}/{page_section}", response_class=HTMLResponse, name='project_version_section')
    @customiser.decorate
    async def project_page__specific_release(
            request: Request,
            project_name: str,
            version: str,
            page_section: typing.Optional[ProjectPageSection] = ProjectPageSection.description,
    ):
        _ = page_section  # Handled in javascript.
        return await project_page__common_impl(request, project_name, version)

    @customiser.decorate
    async def project_page__common_impl(request: Request, project_name: str, version: typing.Optional[str] = None) -> str:
        index: http.HttpRepository = request.app.state.source
        canonical_name = canonicalize_name(project_name)
        try:
            project_page = await index.get_project_page(canonical_name)
            fetch_projects.insert_if_missing(request.app.state.projects_db_connection, canonical_name, project_name)
        except errors.PackageNotFoundError:
            # Tidy up the cache if the project is no longer found.
            with request.app.state.cache as cache:
                for key in list(cache):
                    if key[:2] == ('pkg-info', canonical_name):
                        cache.pop(key)
            fetch_projects.remove_if_found(request.app.state.projects_db_connection, canonical_name)
            raise HTTPException(status_code=404, detail=f"Project {project_name} not found.")

        releases = []
        for file in project_page.files:
            try:
                release = Version(utils.extract_package_version(file.filename, canonical_name))
            except (ValueError, InvalidVersion):
                release = Version('0.0rc0')
            releases.append(release)

        if len(releases) == 0:
            raise HTTPException(status_code=404, detail=f'No release not found for {project_name}.')
        releases = set(releases)
        releases = [str(release) for release in sorted(releases)]
        latest_release = releases[-1]

        if version is None:
            release = latest_release
        else:
            if not version in releases:
                raise HTTPException(status_code=404, detail=f'Release "{version}" not found for {project_name}.')
            release = version
        return templates.get_template("project.html").render(
            **{
                "request": request,
                "project_name": canonical_name,
                "releases": releases,
                "latest_version": None,
                "release": release,
                "latest_release": latest_release,  # Note: May be the same release.
            },
        )

    @app.get("/api/project/{project_name}/{version}", response_class=JSONResponse, name='api_project_version')
    @customiser.decorate
    async def release_api__json(request: Request, project_name: str, version: str, recache: bool = False):
        index: _pypil.SimplePackageIndex = request.app.state.full_index
        try:
            prj = index.project(project_name)
            fetch_projects.insert_if_missing(request.app.state.projects_db_connection, prj.name.normalized, prj.name)
        except _pypil.PackageNotFound:
            fetch_projects.remove_if_found(request.app.state.projects_db_connection, _pypil.PackageName(project_name).normalized)
            raise HTTPException(status_code=404, detail=f"Project {project_name} not found.")

        try:
            release = prj.release(version)
        except ValueError:  # TODO: make this exception specific
            raise HTTPException(status_code=404, detail=f'Release "{version}" not found for {project_name}.')

        release_info = await customiser.fetch_pkg_info(app, prj, release, force_recache=recache)

        if release_info is None:
            release_info = EMPTY_PKG_INFO
            release._files = ()  # crcmod as an example.

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
                    "last_week": -1,
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
                "yanked_reason": None,
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
                ],
            },
            "urls": [],
            "vulnerabilities": [],
        }
        return meta

    async def run_reindex_periodically(frequency_seconds: int) -> None:
        # Tried using startup hooks, worked on dev, didn't work in prod (seemingly the same setup)
        print("Starting the reindexing loop")
        while True:
            try:
                await customiser.refetch_hook(app)
            except Exception as err:
                logging.exception(err, exc_info=True)
            await asyncio.sleep(frequency_seconds)

    @app.on_event('startup')
    async def create_task():
        app.state.periodic_reindexing_task = asyncio.create_task(run_reindex_periodically(60*60*24))
        app.state.session = aiohttp.ClientSession()
        app.state.source = http.HttpRepository(
            url = "https://pypi.org/simple/",
            session=app.state.session,
        )

    @app.on_event("shutdown")
    async def close_sessions():
        await app.state.session.close()



def make_app(
        cache_dir: Path = Path.cwd() / 'cache',
        index_url=None, prefix=None,
        customiser: typing.Type[Customiser] = Customiser,
) -> fastapi.FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None)
    build_app(app, customiser=customiser)

    kwargs = {}
    if index_url is not None:
        kwargs.update({'source_url': index_url})

    # TODO: There is no longer a reason that this state should be separate from build_app.
    app.state.full_index = _pypil.SimplePackageIndex(**kwargs)
    app.state.index = app.state.full_index

    app.state.periodic_reindexing_task = None

    app.state.cache = Cache(str(cache_dir/'diskcache'))

    con = sqlite3.connect(
        cache_dir/'projects.sqlite',
        # For datetimes https://stackoverflow.com/a/1830499/741316
        detect_types=sqlite3.PARSE_DECLTYPES,
    )
    # For name based row access https://stackoverflow.com/a/2526294/741316.
    con.row_factory = sqlite3.Row
    app.state.projects_db_connection = con

    app.state.version = __version__

    fetch_projects.create_table(con)

    if prefix is not None:
        base_app = FastAPI(docs_url=None, redoc_url=None)
        base_app.mount(prefix, app)
        app = base_app
    return app
