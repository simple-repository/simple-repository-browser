"""
FileSizeEnrichmentRepository component for adding file size information to project pages.

This component wraps another repository and automatically enriches file metadata
with size information by making HTTP HEAD requests to files that don't already
have size information.
"""

import asyncio
from dataclasses import replace
import logging
import typing

import httpx
from simple_repository import SimpleRepository, model
from simple_repository.components.core import RepositoryContainer

from ._typing_compat import override

logger = logging.getLogger(__name__)


class FileSizeEnrichmentRepository(RepositoryContainer):
    """
    Repository component that enriches file metadata with size information.

    This component automatically adds size information to files that don't already
    have it by making HTTP HEAD requests. It maintains parallelism for efficiency
    while respecting concurrency limits.
    """

    def __init__(
        self,
        source: SimpleRepository,
        http_client: httpx.AsyncClient,
        *,
        max_concurrent_requests: int = 10,
    ) -> None:
        """
        Initialize the FileSizeEnrichmentRepository.

        Parameters
        ----------
        source: The underlying repository to wrap

        http_client: HTTP client for making HEAD requests

        max_concurrent_requests: Maximum number of concurrent HEAD requests
        """
        super().__init__(source)
        self.http_client = http_client
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)

    @override
    async def get_project_page(
        self,
        project_name: str,
        *,
        request_context: model.RequestContext = model.RequestContext.DEFAULT,
    ) -> model.ProjectDetail:
        """
        Get project page with file sizes enriched.

        Files that don't have size information will have their sizes fetched
        via HTTP HEAD requests in parallel.
        """
        project_page = await super().get_project_page(
            project_name, request_context=request_context
        )

        # Identify files that need size information
        files_needing_size = [
            file for file in project_page.files if not file.size and file.url
        ]

        if not files_needing_size:
            # No files need size information, return as-is
            return project_page

        # Fetch sizes for files that need them
        size_info = await self._fetch_file_sizes(files_needing_size)

        # Create new files with updated size information
        enriched_files = []
        for file in project_page.files:
            if file.filename in size_info:
                file = replace(file, size=size_info[file.filename])
            enriched_files.append(file)

        return replace(project_page, files=tuple(enriched_files))

    async def _fetch_file_sizes(
        self, files: typing.List[model.File]
    ) -> typing.Dict[str, int]:
        """
        Fetch file sizes for multiple files in parallel.

        Args:
            files: List of files to fetch sizes for

        Returns:
            Dictionary mapping filename to size in bytes
        """

        async def fetch_single_file_size(
            file: model.File,
        ) -> typing.Tuple[str, typing.Optional[int]]:
            """Fetch size for a single file with semaphore protection."""
            async with self.semaphore:
                try:
                    logger.debug(f"Fetching size for {file.filename} from {file.url}")

                    # Make HEAD request to get Content-Length
                    response = await self.http_client.head(
                        file.url, follow_redirects=True, headers={}
                    )
                    response.raise_for_status()

                    content_length = response.headers.get("Content-Length")
                    if content_length:
                        return file.filename, int(content_length)
                    else:
                        logger.warning(f"No Content-Length header for {file.filename}")
                        return file.filename, None

                except BaseException as e:
                    logger.warning(f"Failed to get size for {file.filename}: {e}")
                    return file.filename, None

        # Create tasks for all files
        tasks = [fetch_single_file_size(file) for file in files]

        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results, filtering out failures
        size_info = {}
        for result in results:
            if isinstance(result, BaseException):
                logger.warning(f"Exception occurred during size fetching: {result}")
                continue

            filename, size = result
            if size is not None:
                size_info[filename] = size

        return size_info
