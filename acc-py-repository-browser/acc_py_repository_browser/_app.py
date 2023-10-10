import typing
from pathlib import Path

from aiohttp import ClientSession
from simple_repository.components.http import HttpRepository

from simple_repository_browser._app import AppBuilder

from .crawler import Crawler


class AccAppBuilder(AppBuilder):
    def __init__(
        self,
        url_prefix: str,
        index_url: str,
        cache_dir: Path,
        template_paths: typing.Sequence[Path],
        static_files_path: Path,
        crawl_popular_projects: bool,
        browser_version: str,
        internal_index_url: str,
        external_index_url: str,
    ) -> None:
        super().__init__(
            url_prefix,
            index_url,
            cache_dir,
            template_paths,
            static_files_path,
            crawl_popular_projects,
            browser_version,
        )
        self.internal_index_url = internal_index_url
        self.external_index_url = external_index_url

    def create_crawler(self, session: ClientSession, source: HttpRepository) -> Crawler:
        intenal_index = HttpRepository(
            url=self.internal_index_url,
            session=session,
        )
        external_index = HttpRepository(
            url=self.external_index_url,
            session=session,
        )

        return Crawler(
            internal_index=intenal_index,
            external_index=external_index,
            full_index=source,
            session=session,
            crawl_popular_projects=self.crawl_popular_projects,
            projects_db=self.con,
            cache=self.cache,
        )
