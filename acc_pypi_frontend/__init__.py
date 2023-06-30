import typing
from pathlib import Path

import aiohttp
import fastapi
import jinja2
from acc_py_index import errors
from acc_py_index.simple import model
from acc_py_index.simple.repositories.http import HttpRepository

import pypi_frontend._app as base

here = Path(__file__).absolute().parent


class AccPyCustomiser(base.Customiser):
    @classmethod
    def template_loader(cls) -> jinja2.BaseLoader:
        templates_dir = here / 'templates'
        return jinja2.FileSystemLoader([templates_dir, base.here / 'templates' / 'base', base.here / 'templates'])

    @classmethod
    async def release_info_retrieved(cls, project: model.ProjectDetail, pkg_info: base.PackageInfo) -> None:
        async with aiohttp.ClientSession() as session:
            sc = SourceContext(session)

            extra_classifiers = []
            for source in await sc.determine_source(project):
                extra_classifiers.append(f'Package index :: {source}')
            pkg_info.classifiers = tuple(pkg_info.classifiers) + tuple(extra_classifiers)

    @classmethod
    async def crawl_recursively(cls, app: fastapi.FastAPI, normalized_project_names_to_crawl: typing.Set[str]) -> None:
        # Add all of the release-local packages to the set of names that need to be crawled.
        async with aiohttp.ClientSession() as session:
            internal_index = HttpRepository(
                url='http://acc-py-repo.cern.ch/repository/py-release-local/simple',
                session=session,
            )
            project_list = (await internal_index.get_project_list()).projects
            packages_for_reindexing = set(
                project.normalized_name for project in project_list
            )

            await super().crawl_recursively(app, normalized_project_names_to_crawl | packages_for_reindexing)


class SourceContext:
    # A class to identify the source of a package. This should be a configuration item, and not included in the core repository.

    def __init__(self, session: aiohttp.ClientSession):
        self._internal = HttpRepository(
            url='http://acc-py-repo.cern.ch/repository/py-release-local/simple',
            session=session,
        )
        self._external = HttpRepository(
            url='http://acc-py-repo.cern.ch/repository/py-thirdparty-remote/simple',
            session=session,
        )

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
            url='http://acc-py-repo.cern.ch/repository/vr-py-releases/simple',
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
