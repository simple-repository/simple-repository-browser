import fastapi

import simple_repository_browser.view as base

from .model import UserInfoModel


class View(base.View):
    def user_page(self, context: UserInfoModel, request: fastapi.Request) -> str:
        return self.render_template(context, request, "user.html")

    def manage_page(self, context, request) -> str:
        return self.render_template(context, request, "manage.html")
