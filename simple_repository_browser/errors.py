import typing


class RequestError(Exception):
    def __init__(
        self,
        status_code: int,
        detail: str,
        **kwargs: typing.Any,
    ) -> None:
        self._kwargs = kwargs
        super().__init__()
        self.status_code = status_code
        self.detail = detail


class InvalidSearchQuery(ValueError):
    def __init__(self, msg) -> None:
        super().__init__(msg)
