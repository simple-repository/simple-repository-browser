# Copyright (C) 2023, CERN
# This software is distributed under the terms of the MIT
# licence, copied verbatim in the file "LICENSE".
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as Intergovernmental Organization
# or submit itself to any jurisdiction.

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

from . import _search, crawler, errors, fetch_projects, projects
from .fetch_description import PackageInfo


class RepositoryStatsModel(typing.TypedDict):
    n_packages: int
    n_dist_info: int
    n_packages_w_dist_info: int


class QueryResultModel(typing.TypedDict):
    exact: tuple[str, str, str, str] | None
    search_query: str
    results: list[tuple[str, str, str, str]]
    results_count: int  # May be more than in the results list (since paginated).
    single_name_proposal: str | None
    page: int  # Note: starts at 1.
    n_pages: int


class ProjectPageModel(typing.TypedDict):
    # The project detail contents for this project.
    project: ProjectDetail

    # The list of versions for this project.
    releases: list[Version]

    # This version.
    version: str

    # The files for this version.
    files_for_version: tuple[File, ...]

    # Classifiers, grouped by the first part of the classifier
    classifiers_by_top_level: dict[str, tuple[str, ...]]

    # The latest stable version of this project.
    latest_version: str

    # The file, found in the project detail page, for which the metadata applies.
    file_info: File

    # The pkg-info metadata, in dictionary form.
    file_metadata: PackageInfo


class ErrorModel(typing.TypedDict):
    detail: str


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

    def project_query(self, query: str, page_size: int, page: int) -> QueryResultModel:
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

        offset = (page-1) * page_size  # page is 1 based.

        with self.projects_db as cursor:
            result_count = cursor.execute(
                "SELECT COUNT(*) as count FROM projects WHERE "
                f"{condition_query}", condition_terms,
            ).fetchone()
            n_results = result_count['count']

            n_pages = math.ceil(n_results / page_size)
            if n_pages > 0 and (page < 1 or page > n_pages):
                raise errors.InvalidSearchQuery(
                    f"Requested page (page: {page}) is beyond the number of pages ({n_pages})",
                )

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

        # Drop the duplicate.
        if exact in results:
            results.remove(exact)

        return QueryResultModel(
            exact=exact,
            search_query=query,
            results=results,
            results_count=n_results,
            single_name_proposal=single_name_proposal,
            page=page,
            n_pages=n_pages,
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

        info_file, pkg_info = await self.crawler.fetch_pkg_info(prj, version, releases, force_recache=recache)
        classifiers_by_top_level = {
            top_level: tuple(classifier) for top_level, classifier in itertools.groupby(
                pkg_info.classifiers, key=lambda s: s.split('::')[0],
            )
        }
        return ProjectPageModel(
            project=prj,
            releases=sorted(releases),
            version=str(version),
            classifiers_by_top_level=classifiers_by_top_level,
            files_for_version=releases[version],
            latest_version=str(latest_version),  # Note: May be the same release.
            file_info=info_file,
            file_metadata=pkg_info,
        )
