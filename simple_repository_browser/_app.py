import sqlite3
import typing
from pathlib import Path

import aiohttp
import diskcache
import fastapi
from acc_py_index.simple.repositories.http import HttpRepository

from . import controller, crawler, model, view


def create_app(
    url_prefix: str,
    index_url: str,
    cache_dir: Path,
    template_paths: typing.Sequence[Path],
    static_files_path: Path,
    crawl_popular_projects: bool,
    *,
    crawler_class: type[crawler.Crawler] = crawler.Crawler,
    view_class: type[view.View] = view.View,
    model_class: type[model.Model] = model.Model,
    controller_class: type[controller.Controller] = controller.Controller,
) -> fastapi.FastAPI:
    async def lifespan(app: fastapi.FastAPI):
        async with aiohttp.ClientSession() as session:
            source = HttpRepository(
                url=index_url,
                session=session,
            )
            cache = diskcache.Cache(str(cache_dir/'diskcache'))
            con = sqlite3.connect(
                cache_dir/'projects.sqlite',
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            con.row_factory = sqlite3.Row

            _view = view_class(template_paths)
            _crawler = crawler_class(
                session=session,
                crawl_popular_projects=crawl_popular_projects,
                source=source,
                projects_db=con,
                cache=cache,
            )
            _model = model_class(
                source=source,
                projects_db=con,
                cache=cache,
                crawler=_crawler,
            )
            _controller = controller_class(
                model=_model,
                view=_view,
            )

            router = _controller.create_router(static_files_path)
            app.mount(url_prefix or "/", router)

            yield

    return fastapi.FastAPI(
        lifespan=lifespan,
    )
