import asyncio
from pathlib import Path
import typing

import fastapi
import jinja2
import packaging.specifiers
import packaging.requirements
import pypi_simple

import pypi_frontend._app as base
from pypi_frontend import _pypil


here = Path(__file__).absolute().parent


class AccPyCustomiser(base.Customiser):
    @classmethod
    def template_loader(cls) -> jinja2.BaseLoader:
        templates_dir = here / 'templates'
        return jinja2.FileSystemLoader([templates_dir, base.here / 'templates' / 'base', base.here / 'templates'])

    @classmethod
    async def release_info_retrieved(cls, project: _pypil.Project, pkg_info: base.PackageInfo) -> None:
        sc = SourceContext()

        extra_classifiers = []
        for source in await sc.determine_source(project):
            extra_classifiers.append(f'Package index :: {source}')
        pkg_info.classifiers = tuple(pkg_info.classifiers) + tuple(extra_classifiers)

    @classmethod
    async def crawl_recursively(cls, app: fastapi.FastAPI, normalized_project_names_to_crawl: typing.Set[str]) -> None:
        # Add all of the release-local packages to the set of names that need to be crawled.
        internal_index = _pypil.SimplePackageIndex(
            source_url='http://acc-py-repo.cern.ch/repository/py-release-local/simple'
        )

        packages_for_reindexing = set(
            str(pkg_name.normalized) for pkg_name in internal_index.project_names()
        )

        await super().crawl_recursively(app, normalized_project_names_to_crawl | packages_for_reindexing)


class SourceContext:
    # A class to identify the source of a package. This should be a configuration item, and not included in the core repository.

    def __init__(self):
        self._internal = _pypil.SimplePackageIndex(
            source_url='http://acc-py-repo.cern.ch/repository/py-release-local/simple'
        )
        self._external = _pypil.SimplePackageIndex(
            source_url='http://acc-py-repo.cern.ch/repository/py-thirdparty-remote/simple'
        )

    def pkg_same(self, pkg_a: _pypil.Project, pkg_b: _pypil.Project):
        # We don't use equality, as a difference in source results in a difference in URL prefix
        # in the underlying ProjectFiles.url.

        if pkg_a.name != pkg_b.name:
            return False

        releases_a = pkg_a.releases()
        releases_b = pkg_b.releases()

        if len(releases_a) != len(releases_b):
            return False

        for release_a, release_b in zip(releases_a, releases_b):
            if release_a.version != release_b.version:
                return False

            files_a, files_b = release_a.files(), release_b.files()
            if len(files_a) != len(files_b):
                return False

            for file_a, file_b in zip(files_a, files_b):
                if file_a.filename != file_b.filename:
                    return False

        return True

    async def determine_source(self, prj: _pypil.Project) -> typing.Sequence[str]:
        try:
            internal_pkg = self._internal.project(prj.name)
        except _pypil.PackageNotFound:
            return ['PyPI.org']

        if self.pkg_same(prj, internal_pkg):
            return ['Acc-PyPI']

        try:
            external_pkg = self._external.project(prj.name)
        except _pypil.PackageNotFound:
            # We don't know... (this shouldn't happen!)
            return []
        if prj == external_pkg:
            return ['PyPI.org']

        return ['PyPI.org', 'Acc-PyPI']


async def _to_be_turned_into_a_test():
    index = _pypil.SimplePackageIndex(
        source_url='http://acc-py-repo.cern.ch/repository/vr-py-releases/simple',
    )
    prj = index.project('pylogbook')
    sc = SourceContext()
    sources = await sc.determine_source(prj)
    print('SOURCES:', sources)

    numpy = index.project('numpy')
    print("numpy:", await sc.determine_source(numpy))

    jpype = index.project('jpype1')
    print("jpype:", await sc.determine_source(jpype))


if __name__ == '__main__':
    import asyncio

    asyncio.run(_to_be_turned_into_a_test())
