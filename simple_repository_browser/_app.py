# Copyright (C) 2023, CERN
# This software is distributed under the terms of the MIT
# licence, copied verbatim in the file "LICENSE".
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as Intergovernmental Organization
# or submit itself to any jurisdiction.

import asyncio
import logging
import sqlite3
import typing
from enum import Enum
from pathlib import Path

import aiohttp
import diskcache
import fastapi
import jinja2
import packaging.requirements
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from simple_repository import errors, utils
from simple_repository.simple import model
from simple_repository.simple.repositories import http
from simple_repository.simple.repositories.core import SimpleRepository
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, _search, fetch_projects
from .fetch_description import EMPTY_PKG_INFO, PackageInfo, package_info

here = Path(__file__).absolute().parent


class ProjectPageSection(str, Enum):
    description = "description"
    releases = "releases"
    files = "files"
    dependencies = "dependencies"


def get_releases(
    project_page: model.ProjectDetail,
) -> dict[Version, tuple[model.File, ...]]:
    result: dict[Version, list[model.File]] = {}
    canonical_name = canonicalize_name(project_page.name)
    for file in project_page.files:
        try:
            release = Version(
                version=utils.extract_package_version(
                    filename=file.filename,
                    project_name=canonical_name,
                ),
            )
        except (ValueError, InvalidVersion):
            release = Version('0.0rc0')
        result.setdefault(release, []).append(file)
    return {
        version: tuple(files) for version, files in result.items()
    }


def get_latest_version(
    versions: typing.Iterable[Version],
) -> typing.Optional[Version]:
    # Use the pip logic to determine the latest release. First, pick the greatest non-dev version,
    # and if nothing, fall back to the greatest dev version. If no release is available return None.
    sorted_versions = sorted(versions)
    if not sorted_versions:
        return None
    for version in sorted_versions[::-1]:
        if not (version.is_devrelease or version.is_prerelease):
            return version
    return sorted_versions[-1]


class Customiser:
    # A class which can be overridden in order to customise the behaviour of
    # the underlying webapp.

    @classmethod
    def template_loader(cls) -> jinja2.BaseLoader:
        # Load the base directory directly (referencable as "index.html.jinja2") as well as keeping the
        # base namespace "base/index.html.jinja2". In this way, others can override specific pages
        # (e.g. index.html.jinja2) but still extend from "base/index.html.jinja2".
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
    async def release_info_retrieved(cls, project: model.ProjectDetail, package_info: PackageInfo):
        pass

    @classmethod
    def prepare_static(cls, router: fastapi.APIRouter) -> None:
        router.mount("/static", StaticFiles(directory=here / "static"), name="static")

    @classmethod
    def add_exception_middleware(cls, app):
        async def catch_exceptions_middleware(request: Request, call_next):
            # For example: invalid type in a parameter.
            try:
                return await call_next(request)
            except Exception as err:
                logging.exception(err, exc_info=True)
                return HTMLResponse(
                    cls.templates().get_template('error.html.jinja2').render(
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
    async def fetch_pkg_info(
        cls,
        app: fastapi.FastAPI,
        prj: model.ProjectDetail,
        version: Version,
        releases: dict[Version, tuple[model.File, ...]],
        force_recache: bool,
    ) -> typing.Optional[PackageInfo]:
        if version not in releases:
            return None

        with app.state.cache as cache:
            key = ('pkg-info', prj.name, str(version))
            if key in cache and not force_recache:
                release_info = cache[key]
                # Validate that the cached result covers all the files, and that no new
                # files have been added since the cache was made. In that case, we re-cache.
                if all(
                    [
                        file.filename in release_info.files_info
                        for file in releases[version]
                    ],
                ):
                    return release_info

            if force_recache:
                print('Recaching')

            fetch_projects.insert_if_missing(
                app.state.projects_db_connection,
                canonicalize_name(prj.name),
                prj.name,
            )

            release_info = await package_info(releases[version])
            if release_info is not None:
                await cls.release_info_retrieved(prj, release_info)
            cache[key] = release_info
            is_latest = version == get_latest_version(releases.keys())
            if is_latest and release_info is not None:
                fetch_projects.update_summary(
                    app.state.projects_db_connection,
                    name=canonicalize_name(prj.name),
                    summary=release_info.summary,
                    release_date=release_info.release_date,
                    release_version=str(version),
                )

        return release_info

    @classmethod
    async def refetch_hook(cls, app: fastapi.FastAPI) -> None:
        # A hook, that can take as long as it likes to execute (asynchronously), which
        # gets called when the periodic reindexing occurs.
        # We periodically want to refresh the project database to make sure we are up-to-date.
        await fetch_projects.fully_populate_db(
            app.state.projects_db_connection,
            app.state.source,
        )
        with app.state.cache as cache:
            packages_w_dist_info = set()
            for cache_type, name, version in cache:
                if cache_type == 'pkg-info':
                    packages_w_dist_info.add(name)
        await cls.crawl_recursively(app, packages_w_dist_info)

    @classmethod
    async def crawl_recursively(
        cls,
        app: fastapi.FastAPI,
        normalized_project_names_to_crawl: typing.Set[str],
    ) -> None:
        seen: set = set()
        packages_for_reindexing = set(normalized_project_names_to_crawl)
        full_index: SimpleRepository = app.state.source
        while packages_for_reindexing - seen:
            remaining_packages = packages_for_reindexing - seen
            pkg_name = remaining_packages.pop()
            print(
                f"Index iteration loop. Looking at {pkg_name}, with "
                f"{len(remaining_packages)} remaining ({len(seen)} having been completed)",
            )
            seen.add(pkg_name)
            try:
                prj = await full_index.get_project_page(pkg_name)
            except errors.PackageNotFoundError:
                # faulthandler
                continue

            releases = get_releases(prj)
            latest_version = get_latest_version(releases.keys())
            if not latest_version or latest_version.is_devrelease or latest_version.is_prerelease:
                # Don't bother fetching pre-release only projects.
                continue

            release_info = await cls.fetch_pkg_info(
                app, prj, latest_version, releases, force_recache=False,
            )
            if release_info is None:
                continue

            for dist in release_info.requires_dist:
                try:
                    dep_name = packaging.requirements.Requirement(dist).name
                except packaging.requirements.InvalidRequirement:
                    continue
                packages_for_reindexing.add(canonicalize_name(dep_name))

            # Don't DOS the service, we aren't in a rush here.
            await asyncio.sleep(0.01)


def build_app(
    app: fastapi.FastAPI,
    customiser: typing.Type[Customiser],
    prefix: str,
    index_url: str,
    cache_dir: Path,
) -> None:
    templates = customiser.templates()
    customiser.add_exception_middleware(app)
    router = fastapi.APIRouter()
    customiser.prepare_static(router)
    app.mount(prefix, router)

    @router.get("/", response_class=HTMLResponse, name='index')
    async def index_page(request: Request):
        return templates.get_template('index.html.jinja2').render(
            **{
                "request": request,
            },
        )

    @router.get("/about", response_class=HTMLResponse, name='about')
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

        return templates.get_template('about.html.jinja2').render(
            **{
                "request": request,
                "n_packages": n_packages,
                "n_dist_info": n_dist_info,
                "n_packages_w_dist_info": n_packages_w_dist_info,
            },
        )

    @router.get("/search", response_class=HTMLResponse, name='search')
    @customiser.decorate
    async def search_page(request: Request, query: str, page: typing.Optional[int] = 0):
        try:
            search_terms = _search.parse(query)
        except _search.ParseError:
            return HTMLResponse(
                templates.get_template("error.html.jinja2").render(
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
                templates.get_template("error.html.jinja2").render(
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
                    'SELECT canonical_name, summary, release_version, '
                    'release_date FROM projects WHERE canonical_name == ?',
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

        return templates.get_template("search.html.jinja2").render(
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
            templates.get_template("error.html.jinja2").render(
                **{
                    "request": request,
                    "detail": exc.detail,
                },
            ),
            status_code=exc.status_code,
        )

    @router.get("/project/{project_name}", response_class=HTMLResponse, name='project')
    @customiser.decorate
    async def project_page__latest_release(
            request: Request,
            project_name: str,
    ):
        return await project_page__common_impl(request, project_name)

    @router.get(
        "/project/{project_name}/{version}",
        response_class=HTMLResponse,
        name='project_version',
    )
    @router.get(
        "/project/{project_name}/{version}/{page_section}",
        response_class=HTMLResponse,
        name='project_version_section',
    )
    @customiser.decorate
    async def project_page__specific_release(
            request: Request,
            project_name: str,
            version: str,
            page_section: typing.Optional[ProjectPageSection] = ProjectPageSection.description,
    ):
        _ = page_section  # Handled in javascript.
        try:
            _version = Version(version)
        except InvalidVersion:
            raise HTTPException(status_code=404, detail=f"Invalid version {version}.")
        return await project_page__common_impl(request, project_name, _version)

    @customiser.decorate
    async def project_page__common_impl(
        request: Request,
        project_name: str,
        version: typing.Optional[Version] = None,
    ) -> str:
        index: http.HttpRepository = request.app.state.source
        canonical_name = canonicalize_name(project_name)
        try:
            prj = await index.get_project_page(canonical_name)
            fetch_projects.insert_if_missing(
                request.app.state.projects_db_connection,
                canonical_name,
                project_name,
            )
        except errors.PackageNotFoundError:
            # Tidy up the cache if the project is no longer found.
            with request.app.state.cache as cache:
                for key in list(cache):
                    if key[:2] == ('pkg-info', canonical_name):
                        cache.pop(key)
            fetch_projects.remove_if_found(request.app.state.projects_db_connection, canonical_name)
            raise HTTPException(status_code=404, detail=f"Project {project_name} not found.")

        releases = get_releases(prj)
        if not releases:
            raise HTTPException(status_code=404, detail=f"No releases for {project_name}.")

        latest_version = get_latest_version(releases)
        if version is None:
            version = latest_version
        if version not in releases:
            raise HTTPException(
                status_code=404,
                detail=f'Release "{version}" not found for {project_name}.',
            )

        return templates.get_template("project.html.jinja2").render(
            **{
                "request": request,
                "project": prj,
                "releases": sorted(releases),
                "version": str(version),
                "latest_version": str(latest_version),  # Note: May be the same release.
            },
        )

    @router.get(
        "/api/project/{project_name}/{version}",
        response_class=JSONResponse,
        name='api_project_version',
    )
    @customiser.decorate
    async def release_api__json(
        request: Request,
        project_name: str,
        version: str,
        recache: bool = False,
    ):
        index: SimpleRepository = request.app.state.source
        try:
            prj = await index.get_project_page(canonicalize_name(project_name))
            fetch_projects.insert_if_missing(
                request.app.state.projects_db_connection,
                canonicalize_name(prj.name),
                project_name,
            )
        except errors.PackageNotFoundError:
            fetch_projects.remove_if_found(
                request.app.state.projects_db_connection,
                canonicalize_name(project_name),
            )
            raise HTTPException(status_code=404, detail=f"Project {project_name} not found.")

        try:
            _version = Version(version)
        except InvalidVersion:
            raise HTTPException(status_code=406, detail=f"Invalid version {version}.")

        releases = get_releases(prj)
        if not releases:
            raise HTTPException(status_code=404, detail=f'No release found for {project_name}.')
        if _version not in releases:
            raise HTTPException(
                status_code=404, detail=f'Release "{version}" not found for {project_name}.',
            )

        release_files = releases[_version]
        release_info = await customiser.fetch_pkg_info(
            app, prj, _version, releases, force_recache=recache,
        )

        if release_info is None:
            release_info = EMPTY_PKG_INFO
            release_files = ()  # crcmod as an example.

        # https://packaging.python.org/en/latest/specifications/core-metadata/
        # https://peps.python.org/pep-0566/
        # https://peps.python.org/pep-0621/
        # But also, the JSON API in practice https://warehouse.pypa.io/api-reference/json.html.
        meta = {
            "info": {
                "author": release_info.author,
                "author_email": "",
                "classifiers": release_info.classifiers,
                "creation_date": (
                    release_info.release_date.isoformat()
                    if release_info.release_date else None
                ),
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
                "project_urls": release_info.project_urls,
                "requires_dist": release_info.requires_dist,
                "requires_python": release_info.requires_python,
                "summary": release_info.summary,
                "version": version,
                "yanked": True,
                "yanked_reason": None,
            },
            "last_serial": -1,
            "releases": {
                version: [
                    {
                        "comment_text": "",
                        "downloads": -1,
                        "filename": file.filename,
                        "has_sig": False,
                        "size": release_info.files_info[file.filename].size,
                        "url": file.url,
                        "yanked": True,
                        "yanked_reason": "None",
                    }
                    for file in release_files
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

    @customiser.decorate
    def create_source_repository(app: fastapi.FastAPI):
        return http.HttpRepository(
            url=index_url,
            session=app.state.session,
        )

    @app.on_event('startup')
    @customiser.decorate
    async def create_task():
        app.state.periodic_reindexing_task = asyncio.create_task(run_reindex_periodically(60*60*24))
        app.state.session = aiohttp.ClientSession()
        app.state.source = create_source_repository(app)
        app.state.cache = diskcache.Cache(str(cache_dir/'diskcache'))
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

    @app.on_event("shutdown")
    @customiser.decorate
    async def close_sessions():
        await app.state.session.close()


def make_app(
        index_url: str,
        cache_dir: Path = Path.cwd() / 'cache',
        prefix: typing.Optional[str] = None,
        customiser: typing.Type[Customiser] = Customiser,
) -> fastapi.FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None)
    build_app(
        app=app,
        customiser=customiser,
        prefix=prefix or "",
        index_url=index_url,
        cache_dir=cache_dir,
    )
    return app
