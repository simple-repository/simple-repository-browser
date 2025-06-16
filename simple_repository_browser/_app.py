import logging
from pathlib import Path
import sqlite3
import typing
from urllib.parse import urlparse

import aiosqlite
import diskcache
import fastapi
import fastapi.responses
import httpx
from simple_repository import SimpleRepository
from simple_repository.components.http import HttpRepository
from simple_repository.components.local import LocalRepository

from . import controller, crawler, errors, fetch_projects, model, view
from .metadata_injector import MetadataInjector
from .static_files import generate_manifest


class AppBuilder:
    def __init__(
        self,
        url_prefix: str,
        repository_url: str,
        cache_dir: Path,
        template_paths: typing.Sequence[Path],
        static_files_paths: typing.Sequence[Path],
        crawl_popular_projects: bool,
        browser_version: str,
    ) -> None:
        self.url_prefix = url_prefix
        self.repository_url = repository_url
        self.cache_dir = cache_dir
        self.template_paths = template_paths
        self.static_files_manifest = generate_manifest(static_files_paths)
        self.crawl_popular_projects = crawl_popular_projects
        self.browser_version = browser_version

        self.cache = diskcache.Cache(str(cache_dir/'diskcache'))
        self.db_path = cache_dir / 'projects.sqlite'
        self.con = sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=5,
        )
        self.con.row_factory = sqlite3.Row
        fetch_projects.create_table(self.con)

    def create_app(self) -> fastapi.FastAPI:
        _view = self.create_view()

        async def lifespan(app: fastapi.FastAPI):

            async with (
                httpx.AsyncClient(timeout=30) as http_client,
                aiosqlite.connect(self.db_path, timeout=5) as db,
            ):
                _controller = self.create_controller(
                    model=self.create_model(
                        http_client=http_client,
                        database=db,
                    ),
                    view=_view,
                )
                router = _controller.create_router(self.static_files_manifest)
                app.mount(self.url_prefix or "/", router)

                if self.url_prefix:
                    # If somebody visits the root URL, and that isn't index (because we are
                    # using a prefix) just redirect them to the index page. This is super
                    # convenient for development purposes.
                    @app.get("/")
                    async def redirect_to_index():
                        return fastapi.responses.RedirectResponse(url=app.url_path_for('index'))

                yield

        app = fastapi.FastAPI(
            lifespan=lifespan,
        )

        # TODO: refactor into a controller
        async def catch_exceptions_middleware(request: fastapi.Request, call_next):
            try:
                return await call_next(request)
            except errors.RequestError as err:
                status_code = err.status_code
                detail = err.detail
            except Exception as err:
                status_code = 500
                detail = f"Internal server error ({err})"
                # raise
                logging.getLogger("simple_repository_browser.error").error(
                    'Unhandled exception',
                    exc_info=err,
                )
            content = _view.error_page(
                request=request,
                context=model.ErrorModel(detail=detail),
            )
            return fastapi.responses.HTMLResponse(
                content=content,
                status_code=status_code,
            )

        app.middleware('http')(catch_exceptions_middleware)

        return app

    def create_view(self) -> view.View:
        return view.View(self.template_paths, self.browser_version, static_files_manifest=self.static_files_manifest)

    def create_crawler(self, http_client: httpx.AsyncClient, source: SimpleRepository) -> crawler.Crawler:
        return crawler.Crawler(
            http_client=http_client,
            crawl_popular_projects=self.crawl_popular_projects,
            source=source,
            projects_db=self.con,
            cache=self.cache,
        )

    def _repo_from_url(self, url: str, http_client: httpx.AsyncClient) -> SimpleRepository:
        if urlparse(url).scheme in ("http", "https"):
            return HttpRepository(
                url=url,
                http_client=http_client,
            )
        else:
            return LocalRepository(Path(url))

    def create_model(self, http_client: httpx.AsyncClient, database: aiosqlite.Connection) -> model.Model:
        source = MetadataInjector(
            self._repo_from_url(self.repository_url, http_client=http_client),
            http_client=http_client,
        )
        return model.Model(
            source=source,
            projects_db=self.con,
            cache=self.cache,
            crawler=self.create_crawler(http_client, source),
        )

    def create_controller(self, view: view.View, model: model.Model) -> controller.Controller:
        return controller.Controller(
            model=model,
            view=view,
        )
