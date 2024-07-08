import logging
import pathlib
from logging.handlers import RotatingFileHandler

import uvicorn
import uvicorn.config
from uvicorn.logging import DefaultFormatter

default_formatter = DefaultFormatter(
    fmt="[%(asctime)s] [%(process)s] | %(levelprefix)s %(message)s",
    use_colors=False,
)
default_logger = logging.getLogger("default_logger")


def config_access_log(access_log_path: pathlib.Path) -> None:
    # Because uvicorn doesn't allow to configure logs partially,
    # to not redefine the full configuration, we simply patch
    # the built-in uvicorn one that it will use by default
    uvicorn_logging_config = uvicorn.config.LOGGING_CONFIG

    # Define a new formatter that will be used for file
    # (same one as console output, just with colors disabled)
    uvicorn_logging_config["formatters"]["access_file"] = {
        **uvicorn_logging_config["formatters"]["access"],
        "use_colors": False,
    }

    # Define a handler that will use our formatter and will
    # output the logs to the file
    uvicorn_logging_config["handlers"]["access_file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "formatter": "access_file",
        "filename": str(access_log_path),
        "maxBytes": 16777215,
        "backupCount": 3,
    }

    uvicorn_logging_config["loggers"]["uvicorn.access"]["handlers"].append("access_file")


def config_error_log(error_log_path: pathlib.Path) -> None:
    error_handler = RotatingFileHandler(
        filename=error_log_path,
        maxBytes=16777215,
        backupCount=3,
    )
    error_handler.setFormatter(default_formatter)
    # We use custom formatter here, because uvicorn.error is logged into
    # by the entire uvicorn application, so it would produce lots of
    # non-error logs
    error_logger = logging.getLogger("simple_repository_browser.error")
    error_logger.setLevel(logging.ERROR)
    error_logger.addHandler(error_handler)


def config_default_log(default_log_path: pathlib.Path) -> None:
    default_handler = RotatingFileHandler(
        filename=default_log_path,
        maxBytes=16777215,
        backupCount=3,
    )
    default_handler.setFormatter(default_formatter)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[default_handler],
        force=True,
    )


def config_logging(
    log_path: pathlib.Path,
) -> None:
    config_default_log(log_path / "default.log")
    config_access_log(log_path / "access.log")
    config_error_log(log_path / "error.log")
