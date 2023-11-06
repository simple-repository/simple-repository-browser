# Copyright (C) 2023, CERN
# This software is distributed under the terms of the MIT
# licence, copied verbatim in the file "LICENSE".
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as Intergovernmental Organization
# or submit itself to any jurisdiction.

import logging
import sqlite3
import typing
from pathlib import Path

import aiosqlite
import diskcache
import fastapi
import httpx
from simple_repository import SimpleRepository
from simple_repository.components.http import HttpRepository

from . import controller, crawler, errors, fetch_projects, model, view
from .metadata_injector import MetadataInjector


class AppBuilder:
    def __init__(
        self,
        url_prefix: str,
        index_url: str,
        cache_dir: Path,
        template_paths: typing.Sequence[Path],
        static_files_path: Path,
        crawl_popular_projects: bool,
        browser_version: str,
    ) -> None:
        self.url_prefix = url_prefix
        self.index_url = index_url
        self.cache_dir = cache_dir
        self.template_paths = template_paths
        self.static_files_path = static_files_path
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
                httpx.AsyncClient() as http_client,
                aiosqlite.connect(self.db_path, timeout=5) as db,
            ):
                _controller = self.create_controller(
                    model=self.create_model(
                        http_client=http_client,
                        database=db,
                    ),
                    view=_view,
                )
                router = _controller.create_router(self.static_files_path)
                app.mount(self.url_prefix or "/", router)
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
                logging.error(err)
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
        return view.View(self.template_paths, self.browser_version)

    def create_crawler(self, http_client: httpx.AsyncClient, source: SimpleRepository) -> crawler.Crawler:
        return crawler.Crawler(
            http_client=http_client,
            crawl_popular_projects=self.crawl_popular_projects,
            source=source,
            projects_db=self.con,
            cache=self.cache,
        )

    def create_model(self, http_client: httpx.AsyncClient, database: aiosqlite.Connection) -> model.Model:
        source = MetadataInjector(
            HttpRepository(
                url=self.index_url,
                http_client=http_client,
            ),
            database=database,
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
