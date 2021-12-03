import fastapi
import gunicorn.app.base as _gunicorn_base


class Application(_gunicorn_base.Application):
    """ASGI gunicorn application for FastAPI app.

    Parameters
    ----------
    app:
        The ASGI application that will be run by gunicorn.
    options:
        The gunicorn configuration options to be used.
    """
    def __init__(self, app: fastapi.FastAPI, options: dict) -> None:
        self.application = app
        self.options = options
        super().__init__()

    def load_config(self) -> None:
        self.cfg.set("worker_class", "uvicorn.workers.UvicornWorker")
        for key, value in self.options.items():
            self.cfg.set(key, value)

    def load(self) -> fastapi.FastAPI:
        return self.application
