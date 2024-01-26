import os
import typing
import uuid
from pathlib import Path

import aiosqlite
import fastapi
import httpx
from simple_repository import SimpleRepository
from simple_repository.components.http import HttpRepository
from starlette.middleware.sessions import SessionMiddleware

from simple_repository_browser import model, view
from simple_repository_browser._app import AppBuilder
from simple_repository_browser.metadata_injector import MetadataInjector

from .controller import Controller
from .crawler import Crawler
from .model import AccPyModel, OwnershipService, SourceContext
from .view import View
from .yank_manager import YankManager


class AccAppBuilder(AppBuilder):
    def __init__(
        self,
        url_prefix: str,
        repository_url: str,
        cache_dir: Path,
        template_paths: typing.Sequence[Path],
        static_files_path: Path,
        crawl_popular_projects: bool,
        browser_version: str,
        internal_repository_url: str,
        external_repository_url: str,
        ownership_service_url: str,
        yank_db_path: Path,
    ) -> None:
        super().__init__(
            url_prefix,
            repository_url,
            cache_dir,
            template_paths,
            static_files_path,
            crawl_popular_projects,
            browser_version,
        )
        self.internal_repository_url = internal_repository_url
        self.external_repository_url = external_repository_url
        self.ownership_service_url = ownership_service_url
        self.yank_db_path = yank_db_path

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
        yank_manager = YankManager(self.yank_db_path)

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
            yank_manager=yank_manager,
        )

    def create_model(self, http_client: httpx.AsyncClient, database: aiosqlite.Connection) -> AccPyModel:
        ownership_api_key = os.getenv("OWNERSHIP_API_KEY")
        ownership_namespace = os.getenv("OWNERSHIP_NAMESPACE", "acc-py-package")

        if not ownership_api_key:
            raise RuntimeError(
                "In order to interact with the ownership service "
                "OWNERSHIP_API_KEY must to be set as environment variable.",
            )

        full_repository = MetadataInjector(
            self._repo_from_url(self.repository_url, http_client=http_client),
            http_client=http_client,
        )
        internal_repository = HttpRepository(
            url=self.internal_repository_url,
            http_client=http_client,
        )
        external_repository = HttpRepository(
            url=self.external_repository_url,
            http_client=http_client,
        )

        return AccPyModel(
            source_context=SourceContext(
                internal_repository=internal_repository,
                external_repository=external_repository,
                internal_repository_name="Acc-PyPI",
                external_repository_name="PyPI.org",
            ),
            ownership_service=OwnershipService(
                base_url=self.ownership_service_url,
                http_client=http_client,
                namespace=ownership_namespace,
                api_key=ownership_api_key,
            ),
            source=full_repository,
            projects_db=self.con,
            cache=self.cache,
            crawler=self.create_custom_crawler(http_client, full_repository, internal_repository),
        )

    def create_custom_crawler(
        self,
        http_client: httpx.AsyncClient,
        full_repository: SimpleRepository,
        internal_repository: SimpleRepository,
    ) -> Crawler:
        return Crawler(
            internal_repository=internal_repository,
            full_repository=full_repository,
            http_client=http_client,
            crawl_popular_projects=self.crawl_popular_projects,
            projects_db=self.con,
            cache=self.cache,
        )
