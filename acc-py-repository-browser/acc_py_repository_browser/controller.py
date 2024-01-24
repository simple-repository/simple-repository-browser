import datetime
import typing
from copy import deepcopy
from dataclasses import replace
from functools import wraps
from typing import TypedDict

import fastapi
from authlib.integrations.starlette_client import OAuth
from fastapi.responses import RedirectResponse, Response

import simple_repository_browser.controller as base
from simple_repository_browser.errors import RequestError
from simple_repository_browser.model import Model as BaseModel
from simple_repository_browser.view import View as BaseView

from .model import AccPyModel
from .view import View
from .yank_manager import YankManager


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


unauthorized_error = RequestError(
    status_code=401,
    detail="Unauthorized.",
)


class Controller(base.Controller):
    view: View
    model: AccPyModel

    # Decorate all routes with add_login.
    router = deepcopy(base.Controller.router)
    for path, route in router:
        decorated_route = replace(route, fn=add_login(route.fn))
        router.update({path: decorated_route})

    def __init__(
        self,
        oidc_client_id: str,
        oidc_secret: str,
        model: BaseModel,
        view: BaseView,
        yank_manager: YankManager,
    ) -> None:
        super().__init__(model=model, view=view)

        self.yank_manager = yank_manager
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
    async def login(self, request: fastapi.Request):
        url = request.url_for("auth")
        redirect_url = request.headers.get("referer", str(request.url_for("index")))
        request.session["redirect_url"] = redirect_url
        return await self.cern_sso_client.authorize_redirect(request, url)

    @router.get("/auth", name="auth", response_model=None)
    async def auth(self, request: fastapi.Request) -> RedirectResponse:
        redirect_url = request.session.pop("redirect_url", "/")
        token = await self.cern_sso_client.authorize_access_token(request)
        expires = (datetime.datetime.now() + datetime.timedelta(hours=1)).timestamp()
        request.session["token"] = Token(
            username=token["userinfo"]["cern_upn"],
            expires=expires,
        )
        return RedirectResponse(redirect_url)

    @router.get("/logout", name="logout", response_model=None)
    async def logout(self, request: fastapi.Request) -> RedirectResponse:
        request.session.pop("token", None)
        redirect_url = request.headers.get("referer", str(request.url_for("index")))
        return RedirectResponse(redirect_url)

    @router.get("/manage/{project_name}", name="manage", response_model=None)
    @authenticated
    async def manage(self, request: fastapi.Request, project_name: str) -> str:
        project_info = await self.model.project_page(project_name, None, False)
        return self.view.manage_page(project_info, request)

    @router.get("/user", name="user", response_model=None)
    @authenticated
    async def user(self, request: fastapi.Request) -> str | fastapi.responses.HTMLResponse:
        user_info = await self.model.get_user_info(request.state.username)
        return self.view.user_page(user_info, request)

    @router.get("/api/_PRIVATE/{project_name}/{version}/yank", name="yank")
    @authenticated
    async def yank(self, request: fastapi.Request, project_name: str, version: str, reason: str | None = None) -> Response:
        user_info = await self.model.get_user_info(request.state.username)

        allowed = project_name in user_info["owned_resources"]
        if not allowed:
            raise unauthorized_error
        self.yank_manager.yank(project_name, version, reason or f"Yanked by {request.state.username}")

        redirect_url = request.headers.get("referer", str(request.url_for("index")))
        return RedirectResponse(redirect_url, status_code=302)

    @router.get("/api/_PRIVATE/{project_name}/{version}/un-yank", name="un-yank")
    @authenticated
    async def un_yank(self, request: fastapi.Request, project_name: str, version: str) -> Response:
        user_info = await self.model.get_user_info(request.state.username)

        allowed = project_name in user_info["owned_resources"]
        if not allowed:
            raise unauthorized_error
        self.yank_manager.unyank(project_name, version)

        redirect_url = request.headers.get("referer", str(request.url_for("index")))
        return RedirectResponse(redirect_url, status_code=302)

    @router.post("/add_owner/{project_name}", name="add-owner")
    @authenticated
    async def add_owner(self, request: fastapi.Request, project_name: str, owner_id: typing.Annotated[str, fastapi.Form()]) -> Response:
        user_info = await self.model.get_user_info(request.state.username)

        allowed = project_name in user_info["owned_resources"]
        if not allowed:
            raise unauthorized_error

        try:
            await self.model.ownership_service.add_package_owner(project_name, owner_id)
        except ValueError as exc:
            raise RequestError(
                status_code=400,
                detail=str(exc),
            )

        redirect_url = request.headers.get("referer", str(request.url_for("index"))) + "#collaborators"
        return RedirectResponse(redirect_url, status_code=302)
