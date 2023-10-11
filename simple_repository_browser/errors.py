# Copyright (C) 2023, CERN
# This software is distributed under the terms of the MIT
# licence, copied verbatim in the file "LICENSE".
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as Intergovernmental Organization
# or submit itself to any jurisdiction.

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
