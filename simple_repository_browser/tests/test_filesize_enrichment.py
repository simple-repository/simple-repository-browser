import typing
from unittest.mock import AsyncMock, MagicMock

import pytest
from simple_repository import SimpleRepository, model
import simple_repository.errors

from .._typing_compat import override
from ..filesize_enrichment import FileSizeEnrichmentRepository


class FakeRepository(SimpleRepository):
    def __init__(self) -> None:
        self.project_pages: dict[str, model.ProjectDetail] = {}

    @override
    async def get_project_page(
        self,
        project_name: str,
        *,
        request_context: typing.Optional[model.RequestContext] = None,
    ) -> model.ProjectDetail:
        try:
            return self.project_pages[project_name]
        except KeyError:
            raise simple_repository.errors.PackageNotFoundError(project_name)


@pytest.mark.asyncio
async def test_successful_size_enrichment() -> None:
    """Test successful enrichment of file sizes."""
    project_page = model.ProjectDetail(
        meta=model.Meta("1.0"),
        name="test-project",
        files=(
            model.File("test-1.0.whl", "http://example.com/test-1.0.whl", {}),
            model.File("test-1.0.tar.gz", "http://example.com/test-1.0.tar.gz", {}),
            model.File("test-1.1.tar.gz", "http://example.com/test-1.1.tar.gz", {}),
            model.File("test-1.2.tar.gz", "http://example.com/test-1.2.tar.gz", {}),
            model.File("test-1.3.tar.gz", "http://example.com/test-1.3.tar.gz", {}),
            model.File("test-1.4.tar.gz", "http://example.com/test-1.4.tar.gz", {}),
            model.File("test-1.5.tar.gz", "http://example.com/test-1.5.tar.gz", {}),
        ),
    )
    fake_repository = FakeRepository()
    fake_repository.project_pages["test-project"] = project_page

    # Create mock HTTP client that returns Content-Length headers
    mock_http_client = MagicMock()

    async def mock_head(url: str, **kwargs):
        """Mock HEAD request that returns Content-Length based on filename."""
        response = MagicMock()
        response.raise_for_status.return_value = None

        # Return different sizes based on URL
        if "test-1.0.whl" in url:
            response.headers = {"Content-Length": "1024"}
        elif "test-1.0.tar.gz" in url:
            response.headers = {"Content-Length": "2048"}
        elif "test-1.1.tar.gz" in url:
            response.headers = {"Content-Length": "3072"}
        elif "test-1.2.tar.gz" in url:
            response.headers = {"Content-Length": "4096"}
        elif "test-1.3.tar.gz" in url:
            response.headers = {"Content-Length": "5120"}
        elif "test-1.4.tar.gz" in url:
            response.headers = {"Content-Length": "6144"}
        elif "test-1.5.tar.gz" in url:
            response.headers = {"Content-Length": "7168"}
        else:
            response.headers = {"Content-Length": "1000"}

        return response

    mock_http_client.head = AsyncMock(side_effect=mock_head)

    # Create enrichment repository
    enrichment_repo = FileSizeEnrichmentRepository(
        source=fake_repository,
        http_client=mock_http_client,
        max_concurrent_requests=3,
    )

    # Test that sizes are enriched
    result = await enrichment_repo.get_project_page("test-project")

    # Check that all files have the expected sizes
    expected_sizes = [1024, 2048, 3072, 4096, 5120, 6144, 7168]
    for i, file in enumerate(result.files):
        assert file.size == expected_sizes[i]

    # Verify that HEAD requests were made for all files
    assert mock_http_client.head.call_count == 7
