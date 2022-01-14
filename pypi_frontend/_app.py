import asyncio
from pathlib import Path
import typing
import sqlite3

import fastapi
from diskcache import Cache
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi_utils.tasks import repeat_every
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import _pypil
from . import __version__

from .fetch_description import package_info, EMPTY_PKG_INFO
from . import fetch_projects


here = Path(__file__).absolute().parent


def build_app(app: fastapi.FastAPI) -> None:
    # TODO: Make this more configurable, so that we can implement our own
    #  overrides of endpoints (and templates). For example, there should be no
    #  Acc-Py mentioned in the base template.
    app.mount("/static", StaticFiles(directory=here / "static"), name="static")

    templates = Jinja2Templates(directory=str(here / "templates"))

    @app.get("/", response_class=HTMLResponse, name='index')
    async def read_items(request: Request):
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
            },
        )

    @app.get("/about", response_class=HTMLResponse, name='about')
    async def read_items(request: Request):
        return templates.TemplateResponse(
            "about.html",
            {
                "request": request,
            },
        )

    @app.get("/search", response_class=HTMLResponse, name='search')
    async def read_items(request: Request, name: str, page: typing.Optional[int] = 0):
        name = _pypil.PackageName(name).normalized

        page_size = 50
        offset = page * page_size

        with request.app.state.projects_db_connection as cursor:
            exact = cursor.execute('SELECT * FROM projects WHERE canonical_name == ?', (f'{name}',)).fetchone()
            results = cursor.execute(
                "SELECT * FROM projects WHERE canonical_name LIKE ? OR summary LIKE ? LIMIT ? OFFSET ?",
                (f'%{name}%', f'%{name}%', page_size, offset)
            ).fetchall()

        # TODO: This shouldn't include the pagination.
        n_results = len(results)

        # Drop the duplicate.
        if exact in results:
            results.remove(exact)

        return templates.TemplateResponse(
            "search.html",
            {
                "request": request,
                "search_query": name,
                "exact": exact,
                "results": results,
                "results_count": n_results
            },
        )


    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request, exc):
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "detail": exc.detail,
            },
            status_code=exc.status_code,
        )

    async def catch_exceptions_middleware(request: Request, call_next):
        # For example: invalid type in a parameter.
        try:
            return await call_next(request)
        except Exception:
            return templates.TemplateResponse(
                "error.html",
                {
                    "request": request,
                    "detail": "Internal server error",
                },
                status_code=500,
            )

    app.middleware('http')(catch_exceptions_middleware)

    @app.get("/project/{project_name}", response_class=HTMLResponse, name='project')
    async def project_latest_release(request: Request, project_name: str):
        return await release_result(request, project_name)

    @app.get("/project/{project_name}/{release}", response_class=HTMLResponse, name='project_release')
    async def project_w_specific_release(request: Request, project_name: str, release: str):
        return await release_result(request, project_name, release)

    async def release_result(request: Request, project_name: str, version: typing.Optional[str] = None):
        index: _pypil.SimplePackageIndex = request.app.state.full_index
        canonical_name = _pypil.PackageName(project_name).normalized
        try:
            prj = index.project(project_name)
            fetch_projects.insert_if_missing(request.app.state.projects_db_connection, prj.name, prj.name)
        except _pypil.PackageNotFound:
            fetch_projects.remove_if_found(request.app.state.projects_db_connection, canonical_name)
            raise HTTPException(status_code=404, detail=f"Project {project_name} not found.")

        if version is None:
            releases = prj.releases()
            if not releases:
                raise HTTPException(status_code=404, detail=f'Release "{version}" not found for {project_name}.')

            # Choose the latest stable release.
            # TODO: Needs to handle latest *stable* release - currently could get RCs.
            release = prj.releases()[-1]
        else:
            try:
                release = prj.release(version)
            except ValueError:  # TODO: make this exception specific
                raise HTTPException(status_code=404, detail=f'Release "{version}" not found for {project_name}.')

        return templates.TemplateResponse(
            "project.html",
            {
                "request": request,
                "project": prj,
                "latest_version": None,
                "release": release,
            },
        )

    @app.get("/api/project/{project_name}/{release}", response_class=JSONResponse, name='api_project_release')
    async def release_json(request: Request, project_name: str, release: str, recache: bool = False):
        index: _pypil.SimplePackageIndex = request.app.state.full_index
        try:
            prj = index.project(project_name)
            fetch_projects.insert_if_missing(request.app.state.projects_db_connection, prj.name, prj.name)
        except _pypil.PackageNotFound:
            fetch_projects.remove_if_found(request.app.state.projects_db_connection, canonical_name)
            raise HTTPException(status_code=404, detail=f"Project {project_name} not found.")

        version = release
        if version is None:
            releases = prj.releases()
            if not releases:
                raise HTTPException(status_code=404, detail=f'Release "{version}" not found for {project_name}.')

            # Choose the latest stable release.
            # TODO: Needs to handle latest *stable* release.
            release = prj.releases()[-1]
        else:
            try:
                release = prj.release(version)
            except ValueError:  # TODO: make this exception specific
                raise HTTPException(status_code=404, detail=f'Release "{version}" not found for {project_name}.')

        # TODO:
        is_latest = False

        with request.app.state.cache as cache:
            key = ('pkg-info', prj.name, release.version)
            if key in cache and not recache:
                release_info = cache[key]
            else:
                if recache:
                    print('Recaching')
                release_info = await package_info(release)
                cache[key] = release_info

                if is_latest:
                    fetch_projects.update_summary(request.app.state.projects_db_connection, project_name, release_info.summary)
        if release_info is None:
            release_info = EMPTY_PKG_INFO
        return {
            "info": {
                "author": release_info.author,
                "author_email": "",
                "classifiers": [],
                "creation_date": release_info.release_date.isoformat() if release_info.release_date else None,
                "description": release_info.description,
                "description_content_type": None,
                "description_html": release_info.description,
                "downloads": {
                    "last_day": -1,
                    "last_month": -1,
                    "last_week": -1
                },
                "home_page": release_info.url,
                "license": "",
                "maintainer": release_info.maintainer,
                "maintainer_email": "",
                "name": project_name,
                "platform": "",
                # Note on project-urls: https://stackoverflow.com/a/56243786/741316
                "project_urls": release_info.project_urls,
                "requires_dist": None,
                "requires_python": None,
                "summary": release_info.summary,
                "version": release.version,
                "yanked": False,
                "yanked_reason": None
            },
            "last_serial": -1,
            "releases": {
                release.version: [
                    {
                        "comment_text": "",
                        # "digests": {
                        #     "md5": "bab8eb22e6710eddae3c6c7ac3453bd9",
                        #     "sha256": "7a7a8b91086deccc54cac8d631e33f6a0e232ce5775c6be3dc44f86c2154019d"
                        # },
                        "downloads": -1,
                        "filename": file.filename,
                        "has_sig": False,
                        # "md5_digest": "bab8eb22e6710eddae3c6c7ac3453bd9",
                        # "packagetype": "bdist_wheel",
                        # "python_version": "2.7",
                        # "size": 3795,
                        "upload_time_iso_8601": "2015-06-14T14:38:05.869374Z",
                        "url": file.url,
                        "yanked": False,
                        "yanked_reason": None,
                    }
                    for file in release.files()
                ]
            },
            "urls": [],
            "vulnerabilities": []
        }

    @app.on_event("startup")
    @repeat_every(
        seconds=60 * 60 * 24 * 7,  # Each week.
        raise_exceptions=False,
        wait_first=False,  # TODO: Make sure that this runs when we first start, but not if we already have data.
    )
    async def refetch_full_index() -> None:
        await asyncio.sleep(60 * 30)  # Let the app properly start (30mn) before we do any work
        # We periodically want to refresh the project database to make sure we are up-to-date.
        await fetch_projects.fully_populate_db(app.state.projects_db_connection, app.state.full_index)


def make_app(cache_dir: Path = Path.cwd() / 'cache', index_url=None, prefix=None) -> fastapi.FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None)
    build_app(app)

    kwargs = {}
    if index_url is not None:
        kwargs.update({'source_url': index_url})

    # TODO: There is no longer a reason that this state should be separate from build_app.
    app.state.full_index = _pypil.SimplePackageIndex(**kwargs)
    app.state.index = app.state.full_index

    app.state.cache = Cache(str(cache_dir/'diskcache'))

    con = sqlite3.connect(cache_dir/'projects.sqlite')
    app.state.projects_db_connection = con

    app.state.version = __version__

    fetch_projects.create_table(con)

    if prefix is not None:
        base_app = FastAPI(docs_url=None, redoc_url=None)
        base_app.mount(prefix, app)
        app = base_app
    return app
