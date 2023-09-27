import asyncio
import typing
from enum import Enum
from functools import partial
from pathlib import Path

import fastapi
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from packaging.version import InvalidVersion, Version

from . import errors, model, view


class Router:
    # A class-level router definition, capable of generating an instance specific router with its "build_fastapi_router".
    def __init__(self):
        self._routes_register = {}

    def route(
        self,
        path: str,
        methods: typing.Sequence[str],
        response_class: typing.Type = fastapi.responses.HTMLResponse,
        **kwargs: typing.Any,
    ):
        def dec(fn):
            self._routes_register[path] = (fn, methods, response_class, kwargs)
            return fn
        return dec

    def get(self, path: str, **kwargs: typing.Any):
        return self.route(path=path, methods=["GET"], **kwargs)

    def post(self, path: str, **kwargs: typing.Any):
        return self.route(path=path, methods=["POST"], **kwargs)

    def head(self, path: str, **kwargs: typing.Any):
        return self.route(path=path, methods=["HEAD"], **kwargs)

    def build_fastapi_router(self, controller: "Controller") -> fastapi.APIRouter:
        router = fastapi.APIRouter()
        for path, route in self._routes_register.items():
            endpoint, methods, response_class, kwargs = route
            _endpoint = partial(endpoint, controller)
            router.add_api_route(path=path, endpoint=_endpoint, response_class=response_class, methods=methods, **kwargs)
        return router


class ProjectPageSection(str, Enum):
    description = "description"
    releases = "releases"
    files = "files"
    dependencies = "dependencies"


class Controller:
    router = Router()

    def __init__(self, model: model.Model, view: view.View) -> None:
        self.model = model
        self.view = view
        self.version = "__version__"

    def create_router(self, static_file_path: Path) -> fastapi.APIRouter:
        router = self.router.build_fastapi_router(self)
        router.mount("/static", StaticFiles(directory=static_file_path), name="static")
        return router

    @router.get("/", name="index")
    async def index(self, request: fastapi.Request = None) -> str:
        return self.view.index_page({"request": request})

    @router.get("/about", name="about")
    async def about(self, request: fastapi.Request) -> str:
        resp = self.model.indexing_info()
        return self.view.about_page(resp | {"request": request})

    @router.get("/search", name="search")
    async def search(self, request: fastapi.Request, query: str, page: int = 0) -> str:
        page_size = 50
        offset = page * page_size
        resp = self.model.project_query(query=query, size=page_size, offset=offset)
        return self.view.search_page(resp | {"request": request})

    @router.get("/project/{project_name}", name="project")
    @router.get("/project/{project_name}/{version}", name='project_version')
    @router.get("/project/{project_name}/{version}/{page_section}", name='project_version_section')
    async def project(
        self,
        request: fastapi.Request,
        project_name: str,
        version: str | None = None,
        page_section: ProjectPageSection | None = ProjectPageSection.description,
        recache: bool = False,
    ) -> str:
        _ = page_section  # Handled in javascript.
        _version = None
        if version:
            try:
                _version = Version(version)
            except InvalidVersion:
                raise errors.RequestError(status_code=404, detail=f"Invalid version {version}.")

        t = asyncio.create_task(self.model.project_page(project_name, _version, recache))
        # Try for 5 seconds to get the response. Otherwise, fall back to a waiting page which can
        # re-direct us back here once the data is available.
        # TODO: Prevent infinite looping.
        await asyncio.wait([t], timeout=5)
        if not t.done():
            async def iter_file():
                yield self.view.error_page({
                    "detail": "<div>Project metadata is being fetched. This page will reload when ready.</div>",
                    "browser_version": self.version,
                })
                for attempt in range(100):
                    await asyncio.wait([t], timeout=1)
                    if not t.done():
                        yield f"<div style='visibility: hidden; max-height: 0px;' class='update-message'>Still working {attempt}</div>"
                    else:
                        break
                # We are done (or were in an infinite loop). Signal that we are finished, then exit.
                yield 'Done!<script>location.reload();</script><br>\n'
            return StreamingResponse(iter_file(), media_type="text/html")

        res = t.result()
        return self.view.project_page(res | {"request": request})
