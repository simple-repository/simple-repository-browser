import asyncio
from pathlib import Path
import typing
import sqlite3

import fastapi
from diskcache import Cache
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi_utils.tasks import repeat_every
# from pypil.core.index import PackageIndex
# from pypil.core.package_name import PackageName

from . import _pypil
from . import __version__

from . import fetch_projects


app = FastAPI(docs_url=None, redoc_url=None)


here = Path(__file__).absolute().parent
pwd = Path.cwd()


app.mount("/static", StaticFiles(directory=here / "static"), name="static")

# app.mount("/static-img", StaticFiles(directory=here / "static" / "images"), name="static:images")

templates = Jinja2Templates(directory=str(here / "templates"))


@app.get("/", response_class=HTMLResponse, name='index')
async def read_items(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
        },
    )


@app.get("/search", response_class=HTMLResponse, name='search')
async def read_items(request: Request, name: str, page: typing.Optional[int] = 0):
    name = _pypil.PackageName(name).normalized

    page_size = 50
    offset = page * page_size

    with app.state.projects_db_connection as cursor:
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


from starlette.exceptions import HTTPException as StarletteHTTPException
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
async def project_w_specific_release(request: Request, project_name: str, release: str, recache: bool = False):
    return await release_result(request, project_name, release, recache=recache)


async def release_result(request: Request, project_name: str, version: typing.Optional[str] = None, recache: bool = False):
    index: _pypil.SimplePackageIndex = request.app.state.full_index
    try:
        prj = index.project(project_name)
    except _pypil.PackageNotFound:
        # TODO: This should remove an item from the database, if it previously existed.
        raise HTTPException(status_code=404, detail=f"Project {project_name} not found.")

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

    from .fetch_description import package_info
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
                update_summary(request.app.state.projects_db_connection, project_name, release_info.summary)

    return templates.TemplateResponse(
        "project.html",
        {
            "request": request,
            "project": prj,
            "latest_version": None,
            "release": release,
            "release_info": release_info,
        },
    )


def update_summary(conn, name, summary):
    with conn as cursor:
        cursor.execute('''
        UPDATE projects
        SET summary = ?
        WHERE canonical_name == ?;
        ''', (summary, name))


# def make_app() -> fastapi.FastAPI:
# app = fastapi.FastAPI()

# app.mount('/', )

app.state.full_index = _pypil.SimplePackageIndex(source_url='http://acc-py-repo.cern.ch:8000/simple/')
# app.state.full_index = _pypil.SimplePackageIndex()
app.state.index = app.state.full_index

app.state.cache = Cache(str(pwd/'.cache'))

con = sqlite3.connect(pwd/'.cache/projects.sqlite')
app.state.projects_db_connection = con


app.state.version = __version__

fetch_projects.create_table(con)


@app.on_event("startup")
@repeat_every(
    seconds=60 * 60 * 24 * 7,  # Each week.
    raise_exceptions=False,
    wait_first=False,  # TODO: Make sure that this runs when we first start, but not if we already have data.
)
async def refetch_full_index() -> None:
    # We periodically want to refresh the projects database to make sure we are up-to-date.
    await fetch_projects.fully_populate_db(app.state.projects_db_connection, app.state.full_index)
