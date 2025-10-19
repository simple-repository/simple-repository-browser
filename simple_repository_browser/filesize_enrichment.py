"""
File enrichment repository components.

This module provides base classes for enriching file metadata in project pages,
with a concrete implementation for HTTP HEAD-based enrichment.
"""

from __future__ import annotations

import abc
import asyncio
from dataclasses import replace
import logging

import httpx
from simple_repository import SimpleRepository, model
from simple_repository.components.core import RepositoryContainer

from ._typing_compat import override

logger = logging.getLogger(__name__)


class FileEnrichingRepository(RepositoryContainer):
    """
    Base class to enrich Files in parallel.

    This component handles the mechanics of enriching file metadata in parallel,
    without any assumptions about how the enrichment is performed. Subclasses
    implement the _enrich_file method to define enrichment logic.
    """

    @override
    async def get_project_page(
        self,
        project_name: str,
        *,
        request_context: model.RequestContext | None = None,
    ) -> model.ProjectDetail:
        """
        Get project page with enriched files.

        Files will be enriched in parallel according to the _enrich_file implementation.
        """
        project_page = await super().get_project_page(
            project_name, request_context=request_context
        )

        enriched_files = await self._enrich_files(project_page.files)

        if enriched_files is not project_page.files:
            project_page = replace(project_page, files=enriched_files)

        return project_page

    @abc.abstractmethod
    async def _enrich_file(self, file: model.File) -> model.File | None:
        """
        Enrich a single file with metadata.

        Subclasses must implement this method to define enrichment logic.

        Parameters
        ----------
        file: The file to enrich

        Returns
        -------
        The enriched file, or None if no enrichment is needed/possible
        """
        ...

    async def _enrich_files(
        self, files: tuple[model.File, ...]
    ) -> tuple[model.File, ...]:
        """
        Enrich multiple files in parallel.

        Parameters
        ----------
        files: Tuple of files to enrich

        Returns
        -------
        Tuple of enriched files. If no enrichment took place to original files
        tuple instance is returned.
        """
        # Create tasks for all files
        tasks = [self._enrich_file(file) for file in files]

        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results, converting exceptions to None
        enriched_files = []
        files_were_enriched = False

        # Create new files with updated information
        for orig_file, result in zip(files, results):
            if isinstance(result, BaseException):
                logger.warning(f"Exception occurred during file enrichment: {result}")
                enriched_files.append(orig_file)
            elif result is None:
                enriched_files.append(orig_file)
            else:
                files_were_enriched = True
                enriched_files.append(result)

        if not files_were_enriched:
            # Return the original files tuple if no changes. This is an optimisation,
            # but it also means that we can do `enriched_files is files`.
            return files

        return tuple(enriched_files)


class FileSizeEnrichmentRepository(FileEnrichingRepository):
    """
    Repository component that enriches file metadata using HTTP HEAD requests.

    This component makes HTTP HEAD requests to fetch metadata from response headers.
    It uses a semaphore to limit concurrent requests and provides a template method
    for processing response headers that can be easily overridden in subclasses.
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
    async def _enrich_file(self, file: model.File) -> model.File | None:
        """
        Enrich a single file by making an HTTP HEAD request.

        This checks if enrichment is needed, makes the HEAD request with semaphore
        control, and delegates header processing to _enrich_with_resource_head_response.

        Parameters
        ----------
        file: The file to enrich

        Returns
        -------
        The enriched file, or None if no enrichment is needed/possible
        """
        # Skip files that already have size information
        if file.size is not None:
            return None

        # Skip files without URLs (can't fetch metadata)
        if not file.url:
            return None

        async with self.semaphore:
            try:
                logger.debug(
                    f"Fetching HEAD metadata for {file.filename} from {file.url}"
                )

                response = await self.http_client.head(
                    file.url, follow_redirects=True, headers={}
                )
                response.raise_for_status()

                return self._enrich_with_resource_head_response(file, response)

            except BaseException as e:
                logger.warning(f"Failed to fetch metadata for {file.filename}: {e}")
                return None

    def _enrich_with_resource_head_response(
        self, file: model.File, response: httpx.Response
    ) -> model.File | None:
        """
        Process HTTP HEAD response headers to enrich file metadata.

        Override this method in subclasses to extract additional metadata from headers.
        By default, this extracts only the file size from Content-Length.

        Parameters
        ----------
        file: The original file
        response: The HTTP HEAD response

        Returns
        -------
        The enriched file, or None if no enrichment was possible
        """
        content_length = response.headers.get("Content-Length")
        if content_length:
            return replace(file, size=int(content_length))
        else:
            logger.warning(f"No Content-Length header for {file.filename}")
            return None
