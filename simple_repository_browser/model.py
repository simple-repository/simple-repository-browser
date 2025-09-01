import dataclasses
import datetime
import itertools
import math
import sqlite3
import typing

import diskcache
from packaging.utils import canonicalize_name
from packaging.version import Version
from simple_repository import SimpleRepository
from simple_repository.errors import PackageNotFoundError
from simple_repository.model import File, ProjectDetail

from . import _search, compatibility_matrix, crawler, errors, fetch_projects
from .fetch_description import PackageInfo
from .short_release_info import ReleaseInfoModel, ShortReleaseInfo


@dataclasses.dataclass(frozen=True)
class SearchResultItem:
    canonical_name: str
    summary: str | None = None
    release_version: str | None = None
    release_date: datetime.datetime | None = None


class RepositoryStatsModel(typing.TypedDict):
    n_packages: int
    n_dist_info: int
    n_packages_w_dist_info: int


class QueryResultModel(typing.TypedDict):
    search_query: str
    results: list[SearchResultItem]
    results_count: int  # May be more than in the results list (since paginated).
    page: int  # Note: starts at 1.
    n_pages: int


class ProjectPageModel(typing.TypedDict):
    # The project detail contents for this project.
    project: ProjectDetail

    # The list of versions for this project. Sorted by version.
    releases: tuple[ShortReleaseInfo, ...]

    # This version.
    this_release: ShortReleaseInfo

    # Classifiers, grouped by the first part of the classifier
    classifiers_by_top_level: dict[str, tuple[str, ...]]

    # The latest stable version of this project.
    latest_release: ShortReleaseInfo

    # The file, found in the project detail page, for which the metadata applies.
    file_info: File

    # The pkg-info metadata, in dictionary form.
    file_metadata: PackageInfo

    # Information about the wheel compatibility
    compatibility_matrix: compatibility_matrix.CompatibilityMatrixModel


class ErrorModel(typing.TypedDict):
    detail: str


class Model:
    def __init__(
        self,
        source: SimpleRepository,
        projects_db: sqlite3.Connection,
        cache: diskcache.Cache,
        crawler: crawler.Crawler,
        release_info_model: typing.Type[ReleaseInfoModel] = ReleaseInfoModel,
    ) -> None:
        self.projects_db = projects_db
        self.source = source
        self.cache = cache
        self.crawler = crawler
        self._release_info_model = release_info_model

    def repository_stats(self) -> RepositoryStatsModel:
        with self.projects_db as cursor:
            [n_packages] = cursor.execute(
                "SELECT COUNT(canonical_name) FROM projects"
            ).fetchone()

        with self.cache as cache:
            n_dist_info = len(cache)
            packages_w_dist_info = set()
            for cache_type, name, version in cache:
                if cache_type == "pkg-info":
                    packages_w_dist_info.add(name)
            n_packages_w_dist_info = len(packages_w_dist_info)

        return RepositoryStatsModel(
            n_packages=n_packages,
            n_dist_info=n_dist_info,
            n_packages_w_dist_info=n_packages_w_dist_info,
        )

    def _compatibility_matrix(
        self, files: tuple[File, ...]
    ) -> compatibility_matrix.CompatibilityMatrixModel:
        # Compute the compatibility matrix for the given files.
        return compatibility_matrix.compatibility_matrix(files)

    async def project_query(
        self, query: str, page_size: int, page: int
    ) -> QueryResultModel:
        try:
            search_terms = _search.parse(query)
        except _search.ParseError:
            raise errors.InvalidSearchQuery("Invalid search pattern")

        if not search_terms:
            raise errors.InvalidSearchQuery("Please specify a search query")
        try:
            condition_query, condition_terms = _search.build_sql(search_terms)
        except ValueError as err:
            raise errors.InvalidSearchQuery(f"Search query invalid ({str(err)})")

        single_name_proposal = _search.simple_name_from_query(search_terms)
        exact = None

        offset = (page - 1) * page_size  # page is 1 based.

        with self.projects_db as cursor:
            result_count = cursor.execute(
                f"SELECT COUNT(*) as count FROM projects WHERE {condition_query}",
                condition_terms,
            ).fetchone()
            n_results = result_count["count"]

            n_pages = math.ceil(n_results / page_size)
            if n_pages > 0 and (page < 1 or page > n_pages):
                raise errors.InvalidSearchQuery(
                    f"Requested page (page: {page}) is beyond the number of pages ({n_pages})",
                )

            results = cursor.execute(
                "SELECT canonical_name, summary, release_version, release_date FROM projects WHERE "
                f"{condition_query} LIMIT ? OFFSET ?",
                condition_terms + (page_size, offset),
            ).fetchall()

        # Convert results to SearchResultItem objects
        results = [SearchResultItem(*result) for result in results]

        # Check if single_name_proposal is already in the results
        if single_name_proposal and page == 1:
            exact_found = any(r.canonical_name == single_name_proposal for r in results)
            if not exact_found:
                # Not in results, check if it exists in repository
                try:
                    await self.source.get_project_page(single_name_proposal)
                    # Package exists in repository! Add it to the beginning
                    results.insert(
                        0, SearchResultItem(canonical_name=single_name_proposal)
                    )
                    n_results += 1
                except PackageNotFoundError:
                    pass

        return QueryResultModel(
            search_query=query,
            results=results,
            results_count=n_results,
            page=page,
            n_pages=n_pages,
        )

    async def project_page(
        self,
        project_name: str,
        version: Version | None,
        recache: bool,
    ) -> ProjectPageModel:
        canonical_name = canonicalize_name(project_name)
        try:
            prj = await self.source.get_project_page(canonical_name)
            fetch_projects.insert_if_missing(
                self.projects_db, canonical_name, project_name
            )
        except PackageNotFoundError:
            # Tidy up the cache if the project is no longer found.
            for key in list(self.cache):
                if key[:2] == ("pkg-info", canonical_name):
                    self.cache.pop(key)
            fetch_projects.remove_if_found(self.projects_db, canonical_name)
            raise errors.RequestError(
                status_code=404, detail=f"Project {project_name} not found."
            )

        if not prj.files:
            raise errors.RequestError(
                status_code=404, detail=f"No releases for {project_name}."
            )

        releases, latest_version = self._release_info_model.release_infos(prj)

        if version is None:
            version = latest_version

        if version not in releases:
            raise errors.RequestError(
                status_code=404,
                detail=f'Release "{version}" not found for {project_name}.',
            )

        release = releases[version]
        if not release.files:
            quarantine_context = ""
            if "quarantined" in release.labels:
                quarantine_context = (
                    " Files have been identified as quarantined for this project."
                )
            raise errors.RequestError(
                status_code=404,
                detail=f'Release "{version}" has no files.' + quarantine_context,
                project_page=prj,
            )

        info_file, pkg_info = await self.crawler.fetch_pkg_info(
            prj, version, releases, force_recache=recache
        )
        classifiers_by_top_level = {
            top_level: tuple(classifier)
            for top_level, classifier in itertools.groupby(
                pkg_info.classifiers,
                key=lambda s: s.split("::")[0],
            )
        }

        compat_mtx = self._compatibility_matrix(releases[version].files)

        return ProjectPageModel(
            project=prj,
            releases=tuple(releases.values()),
            this_release=release,
            classifiers_by_top_level=classifiers_by_top_level,
            latest_release=releases[latest_version],  # Note: May be the same release.
            file_info=info_file,
            file_metadata=pkg_info,
            compatibility_matrix=compat_mtx,
        )
