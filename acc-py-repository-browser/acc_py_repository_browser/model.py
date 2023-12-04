import typing
from urllib.parse import urljoin

import httpx
from packaging.version import Version
from simple_repository import SimpleRepository, errors, model
from simple_repository.components.http import HttpRepository

import simple_repository_browser.model as base


class ProjectPageModel(base.ProjectPageModel):
    source_package_index: str
    user_owners: list[str]
    group_owners: list[str]


class SourceContext:
    # A class to identify the source of a package. This should be a configuration item, and not included in the core repository.

    def __init__(
        self,
        internal_repository: SimpleRepository,
        internal_repository_name: str,
        external_repository: SimpleRepository,
        external_repository_name: str,
    ):
        self._internal = internal_repository
        self._external = external_repository
        self._internal_name = internal_repository_name
        self._external_name = external_repository_name

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
            return [self._external_name]

        if self.pkg_same(prj, internal_pkg):
            return [self._internal_name]

        try:
            external_pkg = self._external.get_project_page(prj.name)
        except errors.PackageNotFoundError:
            # We don't know... (this shouldn't happen!)
            return []
        if prj == external_pkg:
            return [self._external_name]

        return [self._external_name, self._internal_name]


class OwnershipService:
    def __init__(self, base_url: str, http_client: httpx.AsyncClient) -> None:
        self._base_url = base_url
        self._http_client = http_client

    async def get_package_owners(self, package_name: str) -> tuple[list[str], list[str]]:
        url = urljoin(self._base_url, f"/owners/acc-py-package/{package_name}")
        res = await self._http_client.get(url)
        if res.status_code != 200:
            return [], []
        res_dict = res.json()["owners"]
        return res_dict["users"], res_dict["groups"]


class AccPyModel(base.Model):
    def __init__(self, source_context: SourceContext, ownership_service: OwnershipService, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.source_context = source_context
        self.ownership_service = ownership_service

    async def project_page(self, project_name: str, version: Version | None, recache: bool) -> ProjectPageModel:
        base_res = await super().project_page(project_name, version, recache)
        prj = await self.source.get_project_page(project_name)
        source_package_index = await self.source_context.determine_source(prj)
        source_package_index_str = ",".join(source_package_index)

        user_owners, group_owners = await self.ownership_service.get_package_owners(project_name)
        return ProjectPageModel(
            source_package_index=source_package_index_str,
            user_owners=user_owners,
            group_owners=group_owners,
            **base_res,
        )


async def _to_be_turned_into_a_test():
    async with httpx.AsyncClient() as http_client:
        index = HttpRepository(
            url='https://acc-py-repo.cern.ch/repository/vr-py-releases/simple/',
            http_client=http_client,
        )
        sc = SourceContext(http_client)
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
