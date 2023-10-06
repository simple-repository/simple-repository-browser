import logging
from pathlib import Path

from . import _app

here = Path(__file__).parent

logging.basicConfig(level=logging.DEBUG)
app = _app.AppBuilder(
    url_prefix='',
    index_url='http://acc-py-repo.cern.ch/repository/vr-py-releases/simple/',
    cache_dir=here.parent / 'dev-cache',
    template_paths=[here / 'templates', here / 'templates' / 'base'],
    static_files_path=here / 'static',
    crawl_popular_projects=False,
    browser_version='dev',
).create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "simple_repository_browser._develop:app", host="127.0.0.1", port=8000, reload=True,
        log_level="info",
    )
