import os
import typing
import uuid
from pathlib import Path

import fastapi
import httpx
from simple_repository import SimpleRepository
from simple_repository.components.http import HttpRepository
from starlette.middleware.sessions import SessionMiddleware

from simple_repository_browser import model, view
from simple_repository_browser._app import AppBuilder

from .controller import Controller
from .crawler import Crawler
from .view import View


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

    def create_app(self) -> fastapi.FastAPI:
        app = super().create_app()
        secret_key = os.getenv("SERVER_SECRET") or uuid.uuid4().hex
        app.add_middleware(SessionMiddleware, secret_key=secret_key)
        return app

    def create_view(self) -> View:
        return View(self.template_paths, self.browser_version)

    def create_controller(self, view: view.View, model: model.Model) -> Controller:
        client_id = os.getenv("CLIENT_ID")
        client_secret = os.getenv("CLIENT_SECRET")

        if not client_id or not client_secret:
            raise RuntimeError(
                "SSO authentication requires both OIDC client_id and client_secret "
                "to be set as environment variables. Please ensure CLIENT_ID and "
                "CLIENT_SECRET are correctly configured.",
            )

        return Controller(
            oidc_client_id=client_id,
            oidc_secret=client_secret,
            model=model,
            view=view,
        )

    def create_crawler(self, http_client: httpx.AsyncClient, source: SimpleRepository) -> Crawler:
        intenal_index = HttpRepository(
            url=self.internal_index_url,
            http_client=http_client,
        )
        external_index = HttpRepository(
            url=self.external_index_url,
            http_client=http_client,
        )

        return Crawler(
            internal_index=intenal_index,
            external_index=external_index,
            full_index=source,
            http_client=http_client,
            crawl_popular_projects=self.crawl_popular_projects,
            projects_db=self.con,
            cache=self.cache,
        )
