import logging

from . import _app


logging.basicConfig(level=logging.DEBUG)
app = _app.make_app(index_url='http://acc-py-repo.cern.ch/repository/vr-py-releases/simple')


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "pypi_frontend._develop:app", host="127.0.0.1", port=8000, reload=True,
        log_level = "info",
    )