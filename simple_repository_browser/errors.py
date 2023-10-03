import typing


class RequestError(Exception):
    def __init__(
        self,
        status_code: int,
        detail: str,
        *args: typing.Any,
        **kwags: typing.Any,
    ) -> None:
        super().__init__(*args, **kwags)
        self.status_code = status_code
        self.detail = detail


class InvalidSearchQuery(ValueError):
    def __init__(self, msg) -> None:
        super().__init__(msg)
