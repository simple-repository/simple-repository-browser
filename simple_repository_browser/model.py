import sqlite3
from typing import Any, TypedDict

import diskcache
from acc_py_index.errors import PackageNotFoundError
from acc_py_index.simple.model import ProjectDetail
from acc_py_index.simple.repositories.core import SimpleRepository
from packaging.utils import canonicalize_name
from packaging.version import Version

from . import _search, crawler, errors, fetch_projects, projects


class InvalidSearchQuery(ValueError):
    def __init__(self, msg) -> None:
        super().__init__(msg)


class RepositoryStatsModel(TypedDict):
    n_packages: int
    n_dist_info: int
    n_packages_w_dist_info: int


class QueryResultModel(TypedDict):
    exact: tuple[str, str, str, str] | None
    search_query: str
    results: list[tuple[str, str, str, str]]
    results_count: int
    single_name_proposal: str | None


class ProjectPageModel(TypedDict):
    project: ProjectDetail
    releases: list[Version]
    version: str
    latest_version: str
    metadata: dict[str, Any]


class ErrorModel(TypedDict):
    detail: str


class InvalidSearchQuery(ValueError):
    def __init__(self, msg) -> None:
        super().__init__(msg)


class Model:
    def __init__(
        self,
        source: SimpleRepository,
        projects_db: sqlite3.Connection,
        cache: diskcache.Cache,
        crawler: crawler.Crawler,
    ) -> None:
        self.projects_db = projects_db
        self.source = source
        self.cache = cache
        self.crawler = crawler

    def repository_stats(self) -> RepositoryStatsModel:
        with self.projects_db as cursor:
            [n_packages] = cursor.execute('SELECT COUNT(canonical_name) FROM projects').fetchone()

        with self.cache as cache:
            n_dist_info = len(cache)
            packages_w_dist_info = set()
            for cache_type, name, version in cache:
                if cache_type == 'pkg-info':
                    packages_w_dist_info.add(name)
            n_packages_w_dist_info = len(packages_w_dist_info)

        return RepositoryStatsModel(
            n_packages=n_packages,
            n_dist_info=n_dist_info,
            n_packages_w_dist_info=n_packages_w_dist_info,
        )

    def project_query(self, query: str, size: int, offset: int) -> QueryResultModel:
        try:
            search_terms = _search.parse(query)
        except _search.ParseError:
            raise InvalidSearchQuery("Invalid search pattern")

        try:
            if len(search_terms) == 0:
                raise ValueError("Please specify a search query")
            condition_query, condition_terms = _search.build_sql(search_terms)
        except ValueError as err:
            raise InvalidSearchQuery(f"Search query invalid ({str(err)})")

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

        return QueryResultModel(
            exact=exact,
            search_query=query,
            results=results,
            results_count=n_results,
            single_name_proposal=single_name_proposal,
        )

    async def project_page(
        self,
        project_name: str,
        version: Version,
        recache: bool,
    ) -> ProjectPageModel:
        canonical_name = canonicalize_name(project_name)
        try:
            prj = await self.source.get_project_page(canonical_name)
            fetch_projects.insert_if_missing(self.projects_db, canonical_name, project_name)
        except PackageNotFoundError:
            # Tidy up the cache if the project is no longer found.
            for key in list(self.cache):
                if key[:2] == ('pkg-info', canonical_name):
                    self.cache.pop(key)
            fetch_projects.remove_if_found(self.projects_db, canonical_name)
            raise errors.RequestError(status_code=404, detail=f"Project {project_name} not found.")

        releases = projects.get_releases(prj)
        if not releases:
            raise errors.RequestError(status_code=404, detail=f"No releases for {project_name}.")

        latest_version = projects.get_latest_version(releases)
        if version is None:
            version = latest_version
        if version not in releases:
            raise errors.RequestError(status_code=404, detail=f'Release "{version}" not found for {project_name}.')

        json_metadata = await self.crawler.compute_metadata(prj, releases, version, recache=recache)
        return ProjectPageModel(
            project=prj,
            releases=sorted(releases),
            version=str(version),
            latest_version=str(latest_version),  # Note: May be the same release.
            metadata=json_metadata,
        )
