import asyncio
from datetime import datetime, timedelta, timezone
import logging
import os
import sqlite3
import typing

import diskcache
import httpx
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version
from simple_repository import SimpleRepository, model
from simple_repository.errors import PackageNotFoundError

from . import fetch_projects
from .fetch_description import PackageInfo, package_info
from .short_release_info import ReleaseInfoModel, ShortReleaseInfo


class Crawler:
    """
    A crawler designed to populate and periodically reindex
    the content of the project's metadata database.
    """
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        crawl_popular_projects: bool,
        source: SimpleRepository,
        projects_db: sqlite3.Connection,
        cache: diskcache.Cache,
        reindex_frequency: timedelta = timedelta(days=1),
        release_info_model: typing.Type[ReleaseInfoModel] = ReleaseInfoModel,
    ) -> None:
        self.frequency_seconds = reindex_frequency.total_seconds()
        self._http_client = http_client
        self._source = source
        self._projects_db = projects_db
        self._cache = cache
        self._crawl_popular_projects = crawl_popular_projects
        if os.environ.get("DISABLE_REPOSITORY_INDEXING") != "1":
            self._task = asyncio.create_task(self.run_reindex_periodically())
        self._release_info_model = release_info_model

    async def crawl_recursively(
        self,
        normalized_project_names_to_crawl: typing.Set[str],
    ) -> None:
        """
        Crawl the metadata of the packages in normalized_project_names_to_crawl and
        of their dependencies.
        """
        seen: set = set()
        packages_for_reindexing = set(normalized_project_names_to_crawl)
        while packages_for_reindexing - seen:
            remaining_packages = packages_for_reindexing - seen
            pkg_name = remaining_packages.pop()
            logging.debug(
                f"Index iteration loop. Looking at {pkg_name}, with {len(remaining_packages)} remaining ({len(seen)} having been completed)",
            )
            seen.add(pkg_name)
            if len(seen) % 100 == 0:
                logging.info(
                    f"Index iteration batch of 100 complete. {len(seen)} completed, {len(remaining_packages)} remaining",
                )
            try:
                prj = await self._source.get_project_page(pkg_name)
            except PackageNotFoundError:
                # faulthandler
                continue

            if not prj.files:
                # The project doesn't have any files.
                continue

            releases, latest_version = self._release_info_model.release_infos(prj)

            if latest_version.is_devrelease or latest_version.is_prerelease:
                # Don't bother fetching pre-release only projects.
                continue

            try:
                file, pkg_info = await self.fetch_pkg_info(
                    prj=prj,
                    version=latest_version,
                    releases=releases,
                    force_recache=False,
                )
            except InvalidRequirement as err:
                # See https://discuss.python.org/t/pip-supporting-non-pep508-dependency-specifiers/23107.
                logging.warning(f"Problem handling package {pkg_name}: {err}")
                continue

            for dist in pkg_info.requires_dist:
                if isinstance(dist, Requirement):
                    dep_name = dist.name
                    packages_for_reindexing.add(canonicalize_name(dep_name))

            # Don't DOS the service, we aren't in a rush here.
            await asyncio.sleep(0.01)

    async def refetch_hook(self) -> None:
        # A hook, that can take as long as it likes to execute (asynchronously), which
        # gets called when the periodic reindexing occurs.
        # We periodically want to refresh the project database to make sure we are up-to-date.
        await fetch_projects.fully_populate_db(
            connection=self._projects_db,
            repository=self._source,
        )
        packages_w_dist_info = set()
        for cache_type, name, version in self._cache:
            if cache_type == 'pkg-info':
                packages_w_dist_info.add(name)

        popular_projects = []
        if self._crawl_popular_projects:
            # Add the top 100 packages (and their dependencies) to the repository
            URL = 'https://hugovk.github.io/top-pypi-packages/top-pypi-packages-30-days.min.json'
            try:
                resp = await self._http_client.get(URL)
                s = resp.json()
                for _, row in zip(range(100), s['rows']):
                    popular_projects.append(row['project'])
            except Exception as err:
                logging.warning(f'Problem fetching popular projects ({err})')
                pass

        projects_to_crawl = packages_w_dist_info | set(popular_projects)
        logging.info(f'About to start crawling {len(projects_to_crawl)} projects (and their transient dependencies)')
        await self.crawl_recursively(projects_to_crawl)

    async def run_reindex_periodically(self) -> None:
        logging.debug("Starting the reindexing loop")
        while True:
            try:
                await self.refetch_hook()
            except Exception as err:
                logging.exception(err, exc_info=True)
            await asyncio.sleep(self.frequency_seconds)

    # TODO: Refactor this function.
    async def fetch_pkg_info(
        self,
        prj: model.ProjectDetail,
        version: Version,
        releases: dict[Version, ShortReleaseInfo],
        force_recache: bool,
    ) -> tuple[model.File, PackageInfo]:

        key = ('pkg-info', prj.name, str(version))
        if key in self._cache and not force_recache:
            info_file, files_used_for_cache, pkg_info = self._cache[key]

            # Validate that the cached result covers all of the files, and that no new
            # files have been added since the cache was made. In that case, we re-cache.
            if all(
                [
                    file.filename in files_used_for_cache
                    for file in releases[version].files
                ],
            ):
                return info_file, pkg_info

        if force_recache:
            logging.info('Recaching')

        fetch_projects.insert_if_missing(
            self._projects_db,
            canonicalize_name(prj.name),
            prj.name,
        )

        info_file, pkg_info = await package_info(releases[version].files, self._source, prj.name)

        self._cache[key] = info_file, releases[version].files, pkg_info
        release_info = releases[version]
        if 'latest-release' in release_info.labels:
            fetch_projects.update_summary(
                self._projects_db,
                name=canonicalize_name(prj.name),
                summary=pkg_info.summary,
                release_date=info_file.upload_time or datetime.fromtimestamp(0, tz=timezone.utc),
                release_version=str(version),
            )

        return info_file, pkg_info
