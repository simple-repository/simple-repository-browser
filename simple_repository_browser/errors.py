import typing


class RequestError(Exception):
    def __init__(
        self,
        status_code: int,
        detail: dict[str, str] | str,
        *args: typing.Any,
        **kwags: typing.Any,
    ) -> None:
        super().__init__(*args, **kwags)
        self.status_code = status_code
        if isinstance(detail, str):
            self.detail = {"detail": detail}
        else:
            self.detail = detail
