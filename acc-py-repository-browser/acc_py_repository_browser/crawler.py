import sqlite3
import typing
from datetime import timedelta

import aiohttp
import diskcache
from simple_repository import SimpleRepository, errors, model
from simple_repository.components.http import HttpRepository

import simple_repository_browser.crawler as base
from simple_repository_browser.fetch_description import PackageInfo


class Crawler(base.Crawler):
    def __init__(
        self,
        full_index: SimpleRepository,
        internal_index: SimpleRepository,
        external_index: SimpleRepository,
        session: aiohttp.ClientSession,
        crawl_popular_projects: bool,
        projects_db: sqlite3.Connection,
        cache: diskcache.Cache,
        reindex_frequency: timedelta = timedelta(days=1),
    ) -> None:
        super().__init__(session, crawl_popular_projects, full_index, projects_db, cache, reindex_frequency)
        self.internal_index = internal_index
        self.external_index = external_index
        self.source_context = SourceContext(internal_index, external_index)

    async def release_info_retrieved(self, project: model.ProjectDetail, package_info: PackageInfo) -> None:
        """Extend the metadata with the source repository classifier"""
        extra_classifiers = []
        for source in await self.source_context.determine_source(project):
            extra_classifiers.append(f'Package index :: {source}')
        package_info.classifiers = tuple(package_info.classifiers) + tuple(extra_classifiers)

    async def crawl_recursively(
        self,
        normalized_project_names_to_crawl: typing.Set[str],
    ) -> None:
        # Add all the release-local packages to the set of names that need to be crawled.
        project_list = (await self.internal_index.get_project_list()).projects
        packages_for_reindexing = set(
            project.normalized_name for project in project_list
        )
        await super().crawl_recursively(normalized_project_names_to_crawl | packages_for_reindexing)


class SourceContext:
    # A class to identify the source of a package. This should be a configuration item, and not included in the core repository.

    def __init__(self, internal_index: SimpleRepository, external_index: SimpleRepository):
        self._internal = internal_index
        self._external = external_index

    def pkg_same(self, pkg_a: model.ProjectDetail, pkg_b: model.ProjectDetail):
        # We don't use equality, as a difference in source results in a difference in URL prefix
        # in the underlying ProjectFiles.url.

        if pkg_a.name != pkg_b.name:
            return False

        if len(pkg_a.files) != len(pkg_a.files):
            return False

        files_a = {file.filename for file in pkg_a.files}
        files_b = {file.filename for file in pkg_b.files}
        if files_a != files_b:
            return False

        return True

    async def determine_source(self, prj: model.ProjectDetail) -> typing.Sequence[str]:
        try:
            internal_pkg = await self._internal.get_project_page(prj.name)
        except errors.PackageNotFoundError:
            return ['PyPI.org']

        if self.pkg_same(prj, internal_pkg):
            return ['Acc-PyPI']

        try:
            external_pkg = self._external.get_project_page(prj.name)
        except errors.PackageNotFoundError:
            # We don't know... (this shouldn't happen!)
            return []
        if prj == external_pkg:
            return ['PyPI.org']

        return ['PyPI.org', 'Acc-PyPI']


async def _to_be_turned_into_a_test():
    async with aiohttp.ClientSession() as session:
        index = HttpRepository(
            url='https://acc-py-repo.cern.ch/repository/vr-py-releases/simple/',
            session=session,
        )
        sc = SourceContext(session)
        prj = await index.get_project_page('pylogbook')
        sources = await sc.determine_source(prj)
        print('SOURCES:', sources)

        numpy = await index.get_project_page('numpy')
        print("numpy:", await sc.determine_source(numpy))

        jpype = await index.get_project_page('jpype1')
        print("jpype:", await sc.determine_source(jpype))


if __name__ == '__main__':
    import asyncio
    asyncio.run(_to_be_turned_into_a_test())
