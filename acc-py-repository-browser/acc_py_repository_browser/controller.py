import datetime
import typing
from copy import deepcopy
from dataclasses import replace
from functools import wraps
from typing import TypedDict

import fastapi
from authlib.integrations.starlette_client import OAuth
from fastapi.responses import RedirectResponse

import simple_repository_browser.controller as base
from simple_repository_browser.errors import RequestError
from simple_repository_browser.model import Model as BaseModel
from simple_repository_browser.view import View as BaseView

from .view import UserInfo, View


class Token(TypedDict):
    username: str
    expires: float


def add_login(fn: typing.Callable) -> typing.Callable:
    @wraps(fn)
    async def new_fn(*args, **kwargs):
        request: fastapi.Request = kwargs["request"]
        token = request.session.get("token")

        if isinstance(token, dict):
            expires = datetime.datetime.fromtimestamp(token["expires"])
            if expires > datetime.datetime.now():
                request.state.username = token["username"]
            else:
                request.session.pop("token", None)
        res = await fn(*args, **kwargs)
        return res
    return new_fn


def authenticated(fn: typing.Callable) -> typing.Callable:
    @wraps(fn)
    async def new_fn(*args, **kwargs):
        request: fastapi.Request = kwargs["request"]
        token = request.session.get("token")

        if isinstance(token, dict):
            expires = datetime.datetime.fromtimestamp(token["expires"])
            if expires > datetime.datetime.now():
                request.state.username = token["username"]
                res = await fn(*args, **kwargs)
                return res

        request.session.pop("token", None)
        raise RequestError(
            status_code=403,
            detail="You must be logged in to access this page.",
        )

    return new_fn


class Controller(base.Controller):
    view: View

    # Decorate all routes with add_login.
    router = deepcopy(base.Controller.router)
    for path, route in router:
        decorated_route = replace(route, fn=add_login(route.fn))
        router.update({path: decorated_route})

    def __init__(self, oidc_client_id: str, oidc_secret: str, model: BaseModel, view: BaseView) -> None:
        super().__init__(model=model, view=view)

        self.oauth = OAuth()
        self.oauth.register(
            name='cern',
            server_metadata_url='https://auth.cern.ch/auth/realms/cern/.well-known/openid-configuration',
            client_id=oidc_client_id,
            client_secret=oidc_secret,
            client_kwargs={
                'scope': 'openid',
            },
        )
        self.cern_sso_client = self.oauth.create_client("cern")

    @router.get("/login", name="login", response_model=None)
    async def login(self, request: fastapi.Request, redirect: str = "/"):
        url = request.url_for("auth")
        return await self.cern_sso_client.authorize_redirect(request, url)

    @router.get("/auth", name="auth", response_model=None)
    async def auth(self, request: fastapi.Request) -> RedirectResponse:
        token = await self.cern_sso_client.authorize_access_token(request)
        expires = (datetime.datetime.now() + datetime.timedelta(hours=1)).timestamp()
        request.session["token"] = Token(
            username=token["userinfo"]["cern_upn"],
            expires=expires,
        )
        return RedirectResponse("/")

    @router.get("/logout", name="logout", response_model=None)
    async def logout(self, request: fastapi.Request) -> RedirectResponse:
        request.session.pop("token", None)
        return RedirectResponse("/")

    @router.get("/user", name="user", response_model=None)
    @authenticated
    async def user(self, request: fastapi.Request) -> str | fastapi.responses.HTMLResponse:
        return self.view.user_page(UserInfo(username=request.state.username), request)
