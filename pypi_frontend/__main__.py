from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


app = FastAPI(docs_url=None, redoc_url=None)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.mount(
    "/warehouse/static",
    StaticFiles(directory="warehouse/warehouse/static"),
    name="warehouse:static",
)


templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse, name='index')
async def read_items(request: Request):

    def static_path(name):
        if not name.startswith('warehouse:'):
            raise ValueError("Only to be used by the original warehouse template code (to minimise change)")
        # TODO
        path = name.split('warehouse:static/dist', 1)[1]

        print(path)
        result = request.url_for('warehouse:static', path=path)
        print(result)
        return result
        return name

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "KNOWN_LOCALES": {'en': 'en'},
            'request_context': {
                'locale': {},
            },
            'static_path': static_path,
            'settings': {

            },
        },
    )


import pypil.simple as s
from pypil.core.index import PackageIndex


@app.get("/search", response_class=HTMLResponse, name='search')
async def read_items(request: Request, name: str):
    index: PackageIndex = request.app.state.index
    names = index.package_names()
    results = []
    for package in names:
        if name in package:
            results.append(package)

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "query": name,
            "results": results,
        },
    )


@app.get("/project/{project_name}", response_class=HTMLResponse, name='project')
async def read_items(request: Request, project_name: str):
    index: PackageIndex = request.app.state.index
    try:
        prj = index.package(project_name)
    except:
        return '404 - project not found'

    return templates.TemplateResponse(
        "project.html",
        {
            "request": request,
            "project": prj,
        },
    )


@app.get("/project/{project_name}/{release}", response_class=HTMLResponse, name='project_release')
async def read_items(request: Request, project_name: str, release: str):
    index: PackageIndex = request.app.state.index
    try:
        prj = index.package(project_name)
    except:
        return '404 - project not found'

    version = release
    # TODO: Could raise.
    release = prj.release(version)

    return templates.TemplateResponse(
        "release.html",
        {
            "request": request,
            "project": prj,
            "release": release,
        },
    )
    return f"testing {project_name} {request.app.state.index} {prj.name}"


from pypil.in_memory.package import InMemoryPackage, InMemoryPackageRelease
from pypil.in_memory.index import InMemoryPackageIndex
from pypil.core.package_name import PackageName


pkgs = [
    InMemoryPackage(
        name=PackageName('pkg-a'),
        releases=[
            InMemoryPackageRelease(version='1.2.3b0'),
            InMemoryPackageRelease(version='1.2.1'),
            # InMemoryPackageRelease(version='1.2.1', dist_metadata='wheel...'),
            InMemoryPackageRelease(version='0.9'),
        ],
    )
]
index = InMemoryPackageIndex(pkgs)


app.state.index = index

# if __name__ == '__main__':
#