from datetime import timedelta
import logging
import sqlite3
import typing

import diskcache
import httpx
from simple_repository import SimpleRepository
import simple_repository_browser.crawler as base


class Crawler(base.Crawler):
    def __init__(
        self,
        full_repository: SimpleRepository,
        internal_repository: SimpleRepository,
        http_client: httpx.AsyncClient,
        crawl_popular_projects: bool,
        projects_db: sqlite3.Connection,
        cache: diskcache.Cache,
        reindex_frequency: timedelta = timedelta(days=1),
    ) -> None:
        super().__init__(http_client, crawl_popular_projects, full_repository, projects_db, cache, reindex_frequency)
        self.internal_repository = internal_repository

    async def crawl_recursively(
        self,
        normalized_project_names_to_crawl: typing.Set[str],
    ) -> None:
        # Add all the release-local packages to the set of names that need to be crawled.
        project_list = (await self.internal_repository.get_project_list()).projects
        packages_for_reindexing = set(
            project.normalized_name for project in project_list
        )
        logging.info(f'Acc-Py index crawler grew the crawl list to {len(normalized_project_names_to_crawl | packages_for_reindexing)}')
        await super().crawl_recursively(normalized_project_names_to_crawl | packages_for_reindexing)
