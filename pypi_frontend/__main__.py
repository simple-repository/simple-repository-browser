import typing

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


app = FastAPI(docs_url=None, redoc_url=None)

from pathlib import Path
here = Path(__file__).absolute().parent
print(here)
print(here / "static" / "dist")
app.mount("/static", StaticFiles(directory=here / "static" / "dist"), name="static")

app.mount("/static-img", StaticFiles(directory=here / "static" / "images"), name="static:images")

# app.mount(
#     "/warehouse/static",
#     StaticFiles(directory="warehouse/warehouse/static"),
#     name="warehouse:static",
# )


templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse, name='index')
async def read_items(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
        },
    )


from pypil.core.index import PackageIndex, PackageIndexContainer



@app.get("/search", response_class=HTMLResponse, name='search')
async def read_items(request: Request, name: str, page: typing.Optional[int] = 0):
    index: PackageIndex = request.app.state.index
    name = PackageName(name).normalized

    page_size = 50
    offset = page * page_size

    with app.state.projects_db_connection as cursor:
        exact = cursor.execute("SELECT * FROM projects WHERE canonical_name == ?", (f'{name}',)).fetchone()
        results = cursor.execute(
            "SELECT * FROM projects WHERE canonical_name LIKE ? OR summary LIKE ? LIMIT ? OFFSET ?",
            (f'%{name}%', f'%{name}%', page_size, offset)
        ).fetchall()

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
            # "results_count": n_results
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
async def project_w_specific_release(request: Request, project_name: str, release: str):
    return await release_result(request, project_name, release)


async def release_result(request: Request, project_name: str, version: typing.Optional[str] = None):
    index: PackageIndex = request.app.state.full_index
    from pypil.core.index import PackageNotFound
    try:
        prj = index.project(project_name)
    except PackageNotFound:
        # TODO: This should remove an item from the database, if it previously existed.
        raise HTTPException(status_code=404, detail=f"Project {project_name} not found.")

    if version is None:
        # Choose the latest stable release.
        releases = prj.releases()
        if not releases:
            raise HTTPException(status_code=404, detail=f'Release "{version}" not found for {project_name}.')
        # TODO: Needs to handle latest *stable* release.
        release = prj.releases()[-1]
    else:
        try:
            release = prj.release(version)
        except ValueError:  # TODO: make this exception specific
            raise HTTPException(status_code=404, detail=f'Release "{version}" not found for {project_name}.')

    from .fetch_description import package_info
    with request.app.state.cache as cache:
        key = ('pkg-info', prj.name, release.version)
        if key in cache:
            release_info = cache[key]
        else:
            release_info = await package_info(release)
            cache[key] = release_info

    return templates.TemplateResponse(
        "project.html",
        {
            "request": request,
            "project": prj,
            "release": release,
            "release_info": release_info,
        },
    )



from pypil.in_memory.project import InMemoryProject, InMemoryProjectRelease, InMemoryProjectFile
from pypil.in_memory.index import InMemoryPackageIndex
from pypil.core.package_name import PackageName


pkgs = [
    InMemoryProject(
        name=PackageName('pkg-a'),
        releases=InMemoryProjectRelease.build_from_files([
            InMemoryProjectFile('', version='1.2.3b0'),
            InMemoryProjectFile('', version='1.2.1'),
            # InMemoryPackageRelease(version='1.2.1', dist_metadata='wheel...'),
            InMemoryProjectFile('', version='0.9'),
        ]),
    )
]
index = InMemoryPackageIndex(pkgs)

app.state.index = index

from pypil.simple.index import SimplePackageIndex
app.state.full_index = SimplePackageIndex()
app.state.index = app.state.full_index

from diskcache import Cache

app.state.cache = Cache('.cache')


import sqlite3
con = sqlite3.connect('.cache/projects.sqlite')
app.state.projects_db_connection = con

# Create table
cursor = app.state.projects_db_connection.cursor()

cursor.execute(
    '''CREATE TABLE IF NOT EXISTS projects
    (canonical_name text unique, preferred_name text, summary text, description_html text)
    '''
)
