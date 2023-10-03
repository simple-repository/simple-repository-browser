import sqlite3
import typing
from pathlib import Path

import aiohttp
import diskcache
import fastapi
from acc_py_index.simple.repositories.http import HttpRepository

from simple_repository_browser import errors
from simple_repository_browser.controller import Controller as BaseController
from simple_repository_browser.model import ErrorModel
from simple_repository_browser.model import Model as BaseModel
from simple_repository_browser.view import View as BaseView

from .crawler import Crawler


def create_app(
    url_prefix: str,
    index_url: str,
    internal_index_url: str,
    external_index_url: str,
    cache_dir: Path,
    template_paths: typing.Sequence[Path],
    static_files_path: Path,
    crawl_popular_projects: bool,
    browser_version: str,
) -> fastapi.FastAPI:
    _view = BaseView(template_paths, browser_version)

    async def lifespan(app: fastapi.FastAPI):
        async with aiohttp.ClientSession() as session:
            full_index = HttpRepository(
                url=index_url,
                session=session,
            )
            intenal_index = HttpRepository(
                url=internal_index_url,
                session=session,
            )
            external_index = HttpRepository(
                url=external_index_url,
                session=session,
            )
            cache = diskcache.Cache(str(cache_dir/'diskcache'))
            con = sqlite3.connect(
                cache_dir/'projects.sqlite',
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            con.row_factory = sqlite3.Row

            _crawler = Crawler(
                internal_index=intenal_index,
                external_index=external_index,
                full_index=full_index,
                session=session,
                crawl_popular_projects=crawl_popular_projects,
                projects_db=con,
                cache=cache,
            )
            _model = BaseModel(
                source=full_index,
                projects_db=con,
                cache=cache,
                crawler=_crawler,
            )
            _controller = BaseController(
                model=_model,
                view=_view,
            )

            router = _controller.create_router(static_files_path)
            app.mount(url_prefix or "/", router)

            yield

    app = fastapi.FastAPI(
        lifespan=lifespan,
    )

    async def catch_exceptions_middleware(request: fastapi.Request, call_next):
        try:
            return await call_next(request)
        except errors.RequestError as e:
            status_code = e.status_code
            detail = e.detail
        except Exception:
            status_code = 500
            detail = "Internal server error"
        content = _view.error_page(
            request=request,
            context=ErrorModel(detail=detail),
        )
        return fastapi.responses.HTMLResponse(
            content=content,
            status_code=status_code,
        )

    app.middleware('http')(catch_exceptions_middleware)
