import asyncio
import itertools
import logging
import os
import sqlite3
import typing
from datetime import timedelta

import aiohttp
import diskcache
import packaging.requirements
from acc_py_index.errors import PackageNotFoundError
from acc_py_index.simple import model
from acc_py_index.simple.repositories.core import SimpleRepository
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from . import fetch_projects, projects
from .fetch_description import EMPTY_PKG_INFO, PackageInfo, package_info


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
        """
        Crawl the matadata of the packages in
        normalized_project_names_to_crawl and
        of their dependecies.
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

            release_info = await self.fetch_pkg_info(
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

    # TODO: Refactor this function.
    async def fetch_pkg_info(
        self,
        prj: model.ProjectDetail,
        version: Version,
        releases: dict[Version, tuple[model.File, ...]],
        force_recache: bool,
    ) -> typing.Optional[PackageInfo]:
        if version not in releases:
            return None

        key = ('pkg-info', prj.name, str(version))
        if key in self._cache and not force_recache:
            release_info = self._cache[key]
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
            self._projects_db,
            canonicalize_name(prj.name),
            prj.name,
        )

        release_info = await package_info(releases[version])
        if release_info is not None:
            await self.release_info_retrieved(prj, release_info)

        self._cache[key] = release_info
        is_latest = version == projects.get_latest_version(releases.keys())
        if is_latest and release_info is not None:
            fetch_projects.update_summary(
                self._projects_db,
                name=canonicalize_name(prj.name),
                summary=release_info.summary,
                release_date=release_info.release_date,
                release_version=str(version),
            )

        return release_info

    # TODO: Remove json representation.
    async def compute_metadata(
        self,
        prj: model.ProjectDetail,
        releases: dict[Version, tuple[model.File, ...]],
        version: Version,
        recache: bool = False,
    ):
        release_files = releases[version]
        release_info = await self.fetch_pkg_info(prj, version, releases, force_recache=recache)

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

    # TODO: Remove this function
    async def release_info_retrieved(self, project: model.ProjectDetail, package_info: PackageInfo) -> None:
        pass
