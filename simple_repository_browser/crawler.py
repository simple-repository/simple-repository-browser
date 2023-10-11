# Copyright (C) 2023, CERN
# This software is distributed under the terms of the MIT
# licence, copied verbatim in the file "LICENSE".
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as Intergovernmental Organization
# or submit itself to any jurisdiction.

import asyncio
import logging
import os
import sqlite3
import typing
from datetime import timedelta

import aiohttp
import diskcache
from packaging.requirements import InvalidRequirement
from packaging.utils import canonicalize_name
from packaging.version import Version
from simple_repository import SimpleRepository, model
from simple_repository.errors import PackageNotFoundError

from . import fetch_projects, projects
from .fetch_description import PackageInfo, package_info


class Crawler:
    """
    A crawler designed to populate and periodically reindex
    the content of the project's metadata database.
    """
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
        """
        Crawl the matadata of the packages in
        normalized_project_names_to_crawl and
        of their dependencies.
        """
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
            except PackageNotFoundError:
                # faulthandler
                continue

            releases = projects.get_releases(prj)
            latest_version = projects.get_latest_version(releases.keys())
            if not latest_version or latest_version.is_devrelease or latest_version.is_prerelease:
                # Don't bother fetching pre-release only projects.
                continue

            try:
                file, release_info = await self.fetch_pkg_info(
                    prj=prj,
                    version=latest_version,
                    releases=releases,
                    force_recache=False,
                )
            except InvalidRequirement as err:
                # See https://discuss.python.org/t/pip-supporting-non-pep508-dependency-specifiers/23107.
                print(f"Problem handling package {pkg_name}: {err}")
                continue

            for dist in release_info.requires_dist:
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

    # TODO: Refactor this function.
    async def fetch_pkg_info(
        self,
        prj: model.ProjectDetail,
        version: Version,
        releases: dict[Version, tuple[model.File, ...]],
        force_recache: bool,
    ) -> tuple[model.File, PackageInfo]:

        key = ('pkg-info', prj.name, str(version))
        if key in self._cache and not force_recache:
            info_file, files_used_for_cache, release_info = self._cache[key]
            # Validate that the cached result covers all of the files, and that no new
            # files have been added since the cache was made. In that case, we re-cache.
            if all(
                [
                    file.filename in files_used_for_cache
                    for file in releases[version]
                ],
            ):
                return info_file, release_info

        if force_recache:
            print('Recaching')

        fetch_projects.insert_if_missing(
            self._projects_db,
            canonicalize_name(prj.name),
            prj.name,
        )

        info_file, release_info = await package_info(releases[version], self._source, prj.name)
        if release_info is not None:
            await self.release_info_retrieved(prj, release_info)

        self._cache[key] = info_file, releases[version], release_info
        is_latest = version == projects.get_latest_version(releases.keys())
        if is_latest and release_info is not None:
            fetch_projects.update_summary(
                self._projects_db,
                name=canonicalize_name(prj.name),
                summary=release_info.summary,
                release_date=info_file.upload_time,
                release_version=str(version),
            )

        return info_file, release_info

    # TODO: Document this function, or remove it.
    async def release_info_retrieved(self, project: model.ProjectDetail, package_info: PackageInfo) -> None:
        pass
