import asyncio
import itertools
import logging
import os
import sqlite3
import typing
from datetime import timedelta
from enum import Enum
from functools import partial
from pathlib import Path

import aiohttp
import diskcache
import fastapi
import jinja2
import packaging.requirements
from acc_py_index import errors, utils
from acc_py_index.simple import model
from acc_py_index.simple.repositories.core import SimpleRepository
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from . import _search, fetch_projects
from .fetch_description import EMPTY_PKG_INFO, PackageInfo, package_info

here = Path(__file__).absolute().parent


class ProjectPageSection(str, Enum):
    description = "description"
    releases = "releases"
    files = "files"
    dependencies = "dependencies"


class RequestError(Exception):
    def __init__(
        self,
        status_code: int,
        detail: dict[str, str] | str,
        *args: typing.Any,
        **kwags: typing.Any,
    ) -> None:
        super().__init__(*args, **kwags)
        self.status_code = status_code
        if isinstance(detail, str):
            self.detail = {"detail": detail}
        else:
            self.detail = detail


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


async def fetch_pkg_info(
    cache: diskcache.Cache,
    database: sqlite3.Connection,
    prj: model.ProjectDetail,
    version: Version,
    releases: dict[Version, tuple[model.File, ...]],
    force_recache: bool,
) -> typing.Optional[PackageInfo]:
    if version not in releases:
        return None

    key = ('pkg-info', prj.name, str(version))
    if key in cache and not force_recache:
        release_info = cache[key]
        # Validate that the cached result covers all of the files, and that no new
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
        database,
        canonicalize_name(prj.name),
        prj.name,
    )

    release_info = await package_info(releases[version])
    cache[key] = release_info
    is_latest = version == get_latest_version(releases.keys())
    if is_latest and release_info is not None:
        fetch_projects.update_summary(
            database,
            name=canonicalize_name(prj.name),
            summary=release_info.summary,
            release_date=release_info.release_date,
            release_version=str(version),
        )

    return release_info


async def compute_metadata(
    database: sqlite3.Connection,
    cache: diskcache.Cache,
    prj: model.ProjectDetail,
    releases: dict[Version, tuple[model.File, ...]],
    version: Version,
    recache: bool = False,
):
    release_files = releases[version]
    release_info = await fetch_pkg_info(cache, database, prj, version, releases, force_recache=recache)

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
            "classifier_groups": itertools.groupby(release_info.classifiers, key=lambda s: s.split('::')[0]),
            "creation_date": release_info.release_date,
            "description": release_info.description,
            "description_content_type": None,
            "description_html": release_info.description,
            "home_page": release_info.url,
            "license": "",
            "maintainer": release_info.maintainer,
            "maintainer_email": "",
            "name": prj.name,
            "platform": "",
            # Note on project-urls: https://stackoverflow.com/a/56243786/741316
            "project_urls": release_info.project_urls,
            "requires_dist": [Requirement(s) for s in release_info.requires_dist],
            "requires_python": release_info.requires_python,
            "summary": release_info.summary,
            "version": str(version),
        },
        "releases": {
            str(version): [
                {
                    "comment_text": "",
                    # "digests": {
                    #     "md5": "bab8eb22e6710eddae3c6c7ac3453bd9",
                    #     "sha256": "7a7a8b91086deccc54cac8d631e33f6a0e232ce5775c6be3dc44f86c2154019d"
                    # },
                    "filename": file.filename,
                    "has_sig": False,
                    # "md5_digest": "bab8eb22e6710eddae3c6c7ac3453bd9",
                    # "packagetype": "bdist_wheel",
                    # "python_version": "2.7",
                    "size": release_info.files_info[file.filename].size,
                    # "upload_time_iso_8601": release_info.files_info[file.filename].created.isoformat(),
                    "url": file.url,
                    "yanked": False,
                    "yanked_reason": None,
                }
                for file in release_files
            ],
        },
        "urls": [],
        "vulnerabilities": [],
    }
    return meta


Context = dict[str, typing.Any]


class Crawler:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        crawl_popular_projects: bool,
        source: SimpleRepository,
        projects_db: sqlite3.Connection,
        cache: diskcache.Cache,
        reindex_frequency: timedelta = timedelta(days=1),
    ) -> None:
        self.frequency_seconds = reindex_frequency.total_seconds()
        self._session = session
        self._source = source
        self._projects_db = projects_db
        self._cache = cache
        self._crawl_popular_projects = crawl_popular_projects
        if os.environ.get("DISABLE_REPOSITORY_INDEXING") != "1":
            self._task = asyncio.create_task(self.run_reindex_periodically())

    async def crawl_recursively(
        self,
        normalized_project_names_to_crawl: typing.Set[str],
    ) -> None:
        seen: set = set()
        packages_for_reindexing = set(normalized_project_names_to_crawl)
        while packages_for_reindexing - seen:
            remaining_packages = packages_for_reindexing - seen
            pkg_name = remaining_packages.pop()
            print(
                f"Index iteration loop. Looking at {pkg_name}, with {len(remaining_packages)} remaining ({len(seen)} having been completed)",
            )
            seen.add(pkg_name)
            try:
                prj = await self._source.get_project_page(pkg_name)
            except errors.PackageNotFoundError:
                # faulthandler
                continue

            releases = get_releases(prj)
            latest_version = get_latest_version(releases.keys())
            if not latest_version or latest_version.is_devrelease or latest_version.is_prerelease:
                # Don't bother fetching pre-release only projects.
                continue

            release_info = await fetch_pkg_info(
                cache=self._cache,
                database=self._projects_db,
                prj=prj,
                version=latest_version,
                releases=releases,
                force_recache=False,
            )
            if release_info is None:
                continue

            for dist in release_info.requires_dist:
                try:
                    dep_name = Requirement(dist).name
                except packaging.requirements.InvalidRequirement:
                    # See https://discuss.python.org/t/pip-supporting-non-pep508-dependency-specifiers/23107.
                    continue
                packages_for_reindexing.add(canonicalize_name(dep_name))

            # Don't DOS the service, we aren't in a rush here.
            await asyncio.sleep(0.01)

    async def refetch_hook(self) -> None:
        # A hook, that can take as long as it likes to execute (asynchronously), which
        # gets called when the periodic reindexing occurs.
        # We periodically want to refresh the project database to make sure we are up-to-date.
        await fetch_projects.fully_populate_db(
            connection=self._projects_db,
            index=self._source,
        )
        packages_w_dist_info = set()
        for cache_type, name, version in self._cache:
            if cache_type == 'pkg-info':
                packages_w_dist_info.add(name)

        popular_projects = []
        if self._crawl_popular_projects:
            # Add the top 100 packages (and their dependencies) to the index
            URL = 'https://hugovk.github.io/top-pypi-packages/top-pypi-packages-30-days.min.json'
            try:
                async with self._session.get(URL, raise_for_status=False) as resp:
                    s = await resp.json()
                    for _, row in zip(range(100), s['rows']):
                        popular_projects.append(row['project'])
            except Exception as err:
                print(f'Problem fetching popular projects ({err})')
                pass

        await self.crawl_recursively(packages_w_dist_info | set(popular_projects))

    async def run_reindex_periodically(self) -> None:
        print("Starting the reindexing loop")
        while True:
            try:
                await self.refetch_hook()
            except Exception as err:
                logging.exception(err, exc_info=True)
            await asyncio.sleep(self.frequency_seconds)


class Model:
    def __init__(
        self,
        source: SimpleRepository,
        projects_db: sqlite3.Connection,
        cache: diskcache.Cache,
        crawler: Crawler,
    ) -> None:
        self.projects_db = projects_db
        self.source = source
        self.cache = cache
        self.crawler = crawler

    def indexing_info(self) -> Context:
        with self.projects_db as cursor:
            [n_packages] = cursor.execute('SELECT COUNT(canonical_name) FROM projects').fetchone()

        with self.cache as cache:
            n_dist_info = len(cache)
            packages_w_dist_info = set()
            for cache_type, name, version in cache:
                if cache_type == 'pkg-info':
                    packages_w_dist_info.add(name)
            n_packages_w_dist_info = len(packages_w_dist_info)

        return {
            "n_packages": n_packages,
            "n_dist_info": n_dist_info,
            "n_packages_w_dist_info": n_packages_w_dist_info,
        }

    def project_query(self, query: str, size: int, offset: int) -> Context:
        try:
            search_terms = _search.parse(query)
        except _search.ParseError:
            raise RequestError(
                detail={
                    "search_query": query,
                    "detail": "Invalid search pattern",
                },
                status_code=400,
            )

        try:
            if len(search_terms) == 0:
                raise ValueError("Please specify a search query")
            condition_query, condition_terms = _search.build_sql(search_terms)
        except ValueError as err:
            raise RequestError(
                detail={
                    "search_query": query,
                    "detail": f"Search query invalid ({str(err)})",
                },
                status_code=400,
            )

        single_name_proposal = _search.simple_name_from_query(search_terms)
        exact = None

        with self.projects_db as cursor:
            if single_name_proposal:
                exact = cursor.execute(
                    'SELECT canonical_name, summary, release_version, release_date FROM projects WHERE canonical_name == ?',
                    (single_name_proposal,),
                ).fetchone()
            results = cursor.execute(
                "SELECT canonical_name, summary, release_version, release_date FROM projects WHERE "
                f"{condition_query} LIMIT ? OFFSET ?",
                condition_terms + (size, offset),
            ).fetchall()

        # TODO: This shouldn't include the pagination.
        n_results = len(results)

        # Drop the duplicate.
        if exact in results:
            results.remove(exact)

        return {
            "exact": exact,
            "results": results,
            "results_count": n_results,
            "single_name_proposal": single_name_proposal,
        }

    async def project_page(self, project_name: str, version: Version, recache: bool) -> Context:
        canonical_name = canonicalize_name(project_name)
        try:
            prj = await self.source.get_project_page(canonical_name)
            fetch_projects.insert_if_missing(self.projects_db, canonical_name, project_name)
        except errors.PackageNotFoundError:
            # Tidy up the cache if the project is no longer found.
            for key in list(self.cache):
                if key[:2] == ('pkg-info', canonical_name):
                    self.cache.pop(key)
            fetch_projects.remove_if_found(self.projects_db, canonical_name)
            raise RequestError(status_code=404, detail=f"Project {project_name} not found.")

        releases = get_releases(prj)
        if not releases:
            raise RequestError(status_code=404, detail=f"No releases for {project_name}.")

        latest_version = get_latest_version(releases)
        if version is None:
            version = latest_version
        if version not in releases:
            print(version)
            raise RequestError(status_code=404, detail=f'Release "{version}" not found for {project_name}.')

        json_metadata = await compute_metadata(self.projects_db, self.cache, prj, releases, version, recache=recache)

        return {
            "project": prj,
            "releases": sorted(releases),
            "version": str(version),
            "latest_version": str(latest_version),  # Note: May be the same release.
            "metadata": json_metadata,
        }


class View:
    def __init__(self, templates_paths: typing.Sequence[Path]):
        self.templates_paths = templates_paths
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


class Router:
    # A class-level router definition, capable of generating an instance specific router with its "build_fastapi_router".
    def __init__(self):
        self._routes_register = {}

    def route(
        self,
        path: str,
        methods: typing.Sequence[str],
        response_class: typing.Type = fastapi.responses.HTMLResponse,
        **kwargs: typing.Any,
    ):
        def dec(fn):
            self._routes_register[path] = (fn, methods, response_class, kwargs)
            return fn
        return dec

    def get(self, path: str, **kwargs: typing.Any):
        return self.route(path=path, methods=["GET"], **kwargs)

    def post(self, path: str, **kwargs: typing.Any):
        return self.route(path=path, methods=["POST"], **kwargs)

    def head(self, path: str, **kwargs: typing.Any):
        return self.route(path=path, methods=["HEAD"], **kwargs)

    def build_fastapi_router(self, controller: "Controller") -> fastapi.APIRouter:
        router = fastapi.APIRouter()
        for path, route in self._routes_register.items():
            endpoint, methods, response_class, kwargs = route
            _endpoint = partial(endpoint, controller)
            router.add_api_route(path=path, endpoint=_endpoint, response_class=response_class, methods=methods, **kwargs)
        print(router.routes)
        return router


class Controller:
    router = Router()

    def __init__(self, model: Model, view: View) -> None:
        self.model = model
        self.view = view
        self.version = "__version__"

    def create_router(self, static_file_path: Path) -> fastapi.APIRouter:
        router = self.router.build_fastapi_router(self)
        router.mount("/static", StaticFiles(directory=static_file_path), name="static")
        return router

    @router.get("/", name="index")
    async def index(self, request: fastapi.Request = None) -> str:
        print(request.url_for("index"))
        return self.view.index_page({"request": request})

    @router.get("/about", name="about")
    async def about(self, request: fastapi.Request) -> str:
        resp = self.model.indexing_info()
        return self.view.about_page(resp | {"request": request})

    @router.get("/search", name="search")
    async def search(self, request: fastapi.Request, query: str, page: int = 0) -> str:
        page_size = 50
        offset = page * page_size
        resp = self.model.project_query(query=query, size=page_size, offset=offset)
        return self.view.search_page(resp | {"request": request})

    @router.get("/project/{project_name}", name="project")
    @router.get("/project/{project_name}/{version}", name='project_version')
    @router.get("/project/{project_name}/{version}/{page_section}", name='project_version_section')
    async def project(
        self,
        request: fastapi.Request,
        project_name: str,
        version: str | None = None,
        page_section: ProjectPageSection | None = ProjectPageSection.description,
        recache: bool = False,
    ) -> str:
        _ = page_section  # Handled in javascript.
        _version = None
        if version:
            try:
                _version = Version(version)
            except InvalidVersion:
                raise RequestError(status_code=404, detail=f"Invalid version {version}.")

        t = asyncio.create_task(self.model.project_page(project_name, _version, recache))
        # Try for 5 seconds to get the response. Otherwise, fall back to a waiting page which can
        # re-direct us back here once the data is available.
        # TODO: Prevent infinite looping.
        await asyncio.wait([t], timeout=5)
        if not t.done():
            async def iter_file():
                yield self.view.error_page({
                    "detail": "<div>Project metadata is being fetched. This page will reload when ready.</div>",
                    "browser_version": self.version,
                })
                for attempt in range(100):
                    await asyncio.wait([t], timeout=1)
                    if not t.done():
                        yield f"<div style='visibility: hidden; max-height: 0px;' class='update-message'>Still working {attempt}</div>"
                    else:
                        break
                # We are done (or were in an infinite loop). Signal that we are finished, then exit.
                yield 'Done!<script>location.reload();</script><br>\n'
            return StreamingResponse(iter_file(), media_type="text/html")

        res = t.result()
        return self.view.project_page(res | {"request": request})
