import pathlib
import typing

import httpx
import pytest
from simple_repository import SimpleRepository, model
import simple_repository.errors

from .._typing_compat import override
from ..metadata_injector import MetadataInjector


class FakeRepository(SimpleRepository):
    """A repository which"""

    def __init__(self) -> None:
        self.project_pages: dict[str, model.ProjectDetail] = {}
        self.resources: dict[str, model.Resource] = {}

    @override
    async def get_project_page(
        self,
        project_name: str,
        *,
        request_context: typing.Optional[model.RequestContext] = None,
    ) -> model.ProjectDetail:
        try:
            return self.project_pages[project_name]
        except:
            raise simple_repository.errors.PackageNotFoundError(project_name)

    @override
    async def get_resource(
        self,
        project_name: str,
        resource_name: str,
        *,
        request_context: typing.Optional[model.RequestContext] = None,
    ) -> model.Resource:
        try:
            return self.resources[resource_name]
        except:
            raise simple_repository.errors.ResourceUnavailable(resource_name)


@pytest.fixture
def repository() -> MetadataInjector:
    return MetadataInjector(
        source=FakeRepository(),
        http_client=httpx.AsyncClient(),
    )


@pytest.fixture(scope="session")
def cache_dir() -> pathlib.Path:
    cache_path = pathlib.Path(__file__).parent / "cache"
    cache_path.mkdir(exist_ok=True)
    return cache_path


async def download_package(url: str, cache_dir: pathlib.Path) -> pathlib.Path:
    """Download package to cache if not already present."""
    filename = url.split("/")[-1]
    cache_path = cache_dir / filename

    if cache_path.exists():
        return cache_path

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        cache_path.write_bytes(response.content)

    return cache_path


@pytest.mark.parametrize(
    ["url", "project", "version"],
    [
        (
            "https://files.pythonhosted.org/packages/a7/56/5f481ac5fcde5eb0fcfd5f3a421c0b345842cd9e0019048b8adeb17a3ecc/simple_repository-0.9.0-py3-none-any.whl",
            "simple-repository",
            "0.9.0",
        ),
        (
            "https://files.pythonhosted.org/packages/2e/19/d7c972dfe90a353dbd3efbbe1d14a5951de80c99c9dc1b93cd998d51dc0f/numpy-2.3.1.tar.gz",
            "numpy",
            "2.3.1",
        ),
        (
            "https://files.pythonhosted.org/packages/5e/20/91f4ed6fdc3c399fc58e9af1f812a1f5cb002f479494ecacc39b6be96032/numpy-1.10.0.post2.tar.gz",
            "numpy",
            "1.10.0.post2",
        ),
        (
            "https://files.pythonhosted.org/packages/bc/7c/d724ef1ec3ab2125f38a1d53285745445ec4a8f19b9bb0761b4064316679/pyreadline-2.1.zip",
            "pyreadline",
            "2.1",
        ),
    ],
)
@pytest.mark.asyncio
async def test_get_metadata_from_packages(
    cache_dir: pathlib.Path,
    repository: MetadataInjector,
    url: str,
    project: str,
    version: str,
) -> None:
    """Test metadata extraction from different package formats."""
    package_path = await download_package(url, cache_dir)

    # Create a fake resource to test get_resource
    filename = url.split("/")[-1]
    fake_resource = model.LocalResource(package_path)

    fake_root = typing.cast(FakeRepository, repository.source)
    fake_root.resources[filename] = fake_resource

    # Test get_resource returns metadata
    resource = await repository.get_resource(project, filename + ".metadata")
    assert isinstance(resource, model.TextResource)

    metadata = resource.text

    assert "Metadata-Version" in metadata
    assert f"Name: {project}" in metadata
    assert f"Version: {version}" in metadata


@pytest.mark.asyncio
async def test_add_metadata_attribute_adds_to_all_files(
    repository: MetadataInjector,
) -> None:
    """Test metadata attributes added to all files with URLs."""
    project_page = model.ProjectDetail(
        meta=model.Meta("1.0"),
        name="test-project",
        files=(
            model.File("test-1.0.whl", "", {}),
            model.File("test-1.0.tar.gz", "", {}),
            model.File("test-1.0.zip", "", {}),
            model.File("test-1.0.egg", "", {}),
        ),
    )
    source = typing.cast(FakeRepository, repository.source)
    source.project_pages["test-project"] = project_page

    detail = await repository.get_project_page("test-project")

    assert detail.files[0].dist_info_metadata is True  # .whl
    assert detail.files[1].dist_info_metadata is True  # .tar.gz
    assert detail.files[2].dist_info_metadata is True  # .zip
    assert detail.files[3].dist_info_metadata is None  # .egg (no URL)
