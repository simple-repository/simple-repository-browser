import typing

import fastapi

import simple_repository_browser.view as base


class UserInfo(typing.TypedDict):
    username: str


class View(base.View):
    def user_page(self, context: UserInfo, request: fastapi.Request) -> str:
        return self.render_template(context, request, "user.html")
