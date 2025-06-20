# from __future__ import annotations

import asyncio
import dataclasses
from enum import Enum
from functools import partial
import typing

import fastapi
from fastapi.responses import StreamingResponse
from markupsafe import Markup
from packaging.version import InvalidVersion, Version

from . import errors, model, view
from .static_files import HashedStaticFileHandler, StaticFilesManifest


@dataclasses.dataclass(frozen=True)
class Route:
    fn: typing.Callable
    methods: set[str]
    response_class: typing.Type
    kwargs: dict[str, typing.Any]


class Router:
    # A class-level router definition, capable of generating an instance specific router with its "build_fastapi_router".
    def __init__(self) -> None:
        self._routes_register: dict[str, Route] = {}

    def route(
        self,
        path: str,
        methods: typing.Sequence[str],
        response_class: typing.Type = fastapi.responses.HTMLResponse,
        **kwargs: typing.Any,
    ):
        def dec(fn):
            self._routes_register[path] = Route(fn, methods, response_class, kwargs)
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
            bound_endpoint = partial(route.fn, controller)
            router.add_api_route(
                path=path,
                endpoint=bound_endpoint,
                response_class=route.response_class,
                methods=list(route.methods),
                **route.kwargs,
            )
        return router

    def __iter__(self) -> typing.Iterator[tuple[str, Route]]:
        return self._routes_register.items().__iter__()

    def update(self, new_values: dict[str, Route]) -> None:
        self._routes_register.update(new_values)


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

    def create_router(
        self, static_files_manifest: StaticFilesManifest
    ) -> fastapi.APIRouter:
        router = self.router.build_fastapi_router(self)
        router.mount(
            "/static",
            HashedStaticFileHandler(manifest=static_files_manifest),
            name="static",
        )
        return router

    @router.get("/", name="index")
    async def index(self, request: fastapi.Request) -> str:
        return self.view.index_page(request)

    @router.get("/about", name="about")
    async def about(self, request: fastapi.Request) -> str:
        response = self.model.repository_stats()
        return self.view.about_page(response, request)

    @router.get("/search", name="search")
    async def search(self, request: fastapi.Request, query: str, page: int = 1) -> str:
        # Note: page is 1 based. We don't have a page 0.
        page_size = 50
        try:
            response = self.model.project_query(
                query=query, page_size=page_size, page=page
            )
        except errors.InvalidSearchQuery as e:
            raise errors.RequestError(
                detail=str(e),
                status_code=400,
            )
        return self.view.search_page(response, request)

    @router.get("/project/{project_name}", name="project", response_model=None)
    @router.get(
        "/project/{project_name}/{version}", name="project_version", response_model=None
    )
    @router.get(
        "/project/{project_name}/{version}/{page_section}",
        name="project_version_section",
        response_model=None,
    )
    async def project(
        self,
        request: fastapi.Request,
        project_name: str,
        version: str | None = None,
        page_section: ProjectPageSection | None = ProjectPageSection.description,
        recache: bool = False,
    ) -> str | StreamingResponse:
        _ = page_section  # Handled in javascript.
        _version = None
        if version:
            try:
                _version = Version(version)
            except InvalidVersion:
                raise errors.RequestError(
                    status_code=404, detail=f"Invalid version {version}."
                )

        t = asyncio.create_task(
            self.model.project_page(project_name, _version, recache)
        )
        # Try for 5 seconds to get the response. Otherwise, fall back to a waiting page which can
        # re-direct us back here once the data is available.
        # TODO: Prevent infinite looping.
        await asyncio.wait([t], timeout=5)
        if not t.done():

            async def iter_file():
                # TODO: use a different view for this.
                yield self.view.error_page(
                    context=model.ErrorModel(
                        detail=Markup(
                            "<div>Project metadata is being fetched. This page will reload when ready.</div>"
                        ),
                    ),
                    request=request,
                )
                for attempt in range(100):
                    await asyncio.wait([t], timeout=1)
                    if not t.done():
                        yield f"<div style='visibility: hidden; max-height: 0px;' class='update-message'>Still working {attempt}</div>"
                    else:
                        break
                # We are done (or were in an infinite loop). Signal that we are finished, then exit.
                yield "Done!<script>location.reload();</script><br>\n"

            return StreamingResponse(iter_file(), media_type="text/html")

        response = t.result()
        return self.view.project_page(response, request)
