"""Web-first B control-plane HTTP app, independent from all Bot/source workers.

Only administrator registration/login and small Web preferences are operational.
Source/notification/rules/history pages deliberately show unconnected states.
"""

from __future__ import annotations

import hmac
import ipaddress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.web_auth import WebAuth
from app.web_first_store import WebFirstStore

_UI = Path(__file__).parent / "web_first_ui"
_PAGES = {
    "/": ("overview", "运行概览"),
    "/sources": ("sources", "监控来源"),
    "/rules": ("rules", "关键词规则"),
    "/channels": ("channels", "通知管理"),
    "/history": ("history", "推送历史"),
    "/settings": ("settings", "系统设置"),
}
_TABS = ("general", "account", "data", "maintenance")


@dataclass(frozen=True, slots=True)
class _SessionConfig:
    session_seconds: int = 3600
    secure_cookie: bool = False  # Local LAN HTTP only; HTTPS belongs to a later gated change.


def _valid_host(value: str | None) -> bool:
    if not value or len(value) > 255:
        return False
    try:
        parsed = urlsplit("http://" + value)
        if (parsed.scheme != "http" or not parsed.hostname
                or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment):
            return False
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return False
        if parsed.hostname == "localhost":
            return True
        ip = ipaddress.ip_address(parsed.hostname)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except (ValueError, TypeError):
        return False


def _origin_ok(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return True
    try:
        given = urlsplit(origin)
        expected = urlsplit(str(request.base_url))
        return (given.scheme, given.hostname, given.port) == (
            expected.scheme, expected.hostname, expected.port
        )
    except (ValueError, TypeError):
        return False


def create_web_first_app(store: WebFirstStore) -> FastAPI:
    """Build after the caller has prepared the volume under its instance lock."""
    if not isinstance(store, WebFirstStore):
        raise TypeError("web-first store required")
    auth = WebAuth(_SessionConfig())
    templates = Jinja2Templates(directory=str(_UI / "templates"))
    app = FastAPI(
        title="SeekPulse Web-first",
        docs_url=None, redoc_url=None, openapi_url=None,
    )
    app.mount("/assets", StaticFiles(directory=str(_UI / "static")), name="assets")

    @app.middleware("http")
    async def protect_transport(request: Request, call_next):
        forwarded = any(k in request.headers for k in (
            "forwarded", "x-forwarded-host", "x-forwarded-proto",
            "x-forwarded-for", "x-real-ip",
        ))
        if forwarded or not _valid_host(request.headers.get("host")):
            response = PlainTextResponse("Forbidden host", status_code=403)
        elif request.method not in ("GET", "HEAD", "POST"):
            response = PlainTextResponse("Method not allowed", status_code=405)
        elif request.method == "POST" and not _origin_ok(request):
            response = PlainTextResponse("Forbidden origin", status_code=403)
        else:
            response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'self'; font-src 'self'; "
                "img-src 'self' data:; script-src 'none'; "
                "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
            ),
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        })
        return response

    def current_token(request: Request) -> str | None:
        return request.cookies.get(WebAuth.COOKIE)

    def current(request: Request):
        return auth.get(current_token(request), authenticated=True)

    def response_redirect(path: str) -> RedirectResponse:
        return RedirectResponse(path, status_code=303)

    def attach_cookie(response, token: str):
        response.set_cookie(
            WebAuth.COOKIE, token, httponly=True, secure=False,
            samesite="strict", max_age=3600, path="/",
        )

    def render(request: Request, name: str, csrf: str = "", **context):
        return templates.TemplateResponse(
            request, name, {"csrf": csrf, **context},
            headers={"Cache-Control": "no-store"},
        )

    def guest_page(request: Request, *, register: bool, error: str | None = None):
        token, session = auth.new_session(authenticated=False)
        response = render(request, "auth.html", session.csrf, register=register, error=error)
        attach_cookie(response, token)
        return response

    async def checked_form(request: Request, expected_auth: bool):
        session = auth.get(current_token(request), authenticated=expected_auth)
        if session is None:
            raise HTTPException(403, "session expired")
        if not request.headers.get("content-type", "").startswith(
            ("application/x-www-form-urlencoded", "multipart/form-data")
        ):
            raise HTTPException(415, "form required")
        raw = await request.body()
        if len(raw) > 8192:
            raise HTTPException(413, "form too large")
        form = await request.form()
        candidate = form.get("_csrf", "")
        if not isinstance(candidate, str) or not hmac.compare_digest(candidate, session.csrf):
            raise HTTPException(403, "CSRF verification failed")
        return form, session

    @app.get("/register")
    async def registration_page(request: Request):
        if store.admin_exists():
            return response_redirect("/login")
        return guest_page(request, register=True)

    @app.post("/register")
    async def register(request: Request):
        if store.admin_exists():
            return response_redirect("/login")
        form, _ = await checked_form(request, False)
        peer = str(request.client.host) if request.client else "unknown"
        if not auth.login_allowed(peer):
            raise HTTPException(429, "registration temporarily limited")
        username = form.get("username")
        password = form.get("password")
        confirm = form.get("confirm")
        code = form.get("setup_code")
        if (not isinstance(password, str) or not isinstance(confirm, str)
                or not hmac.compare_digest(password, confirm)
                or not store.create_admin(username, password, code)):
            auth.login_failure(peer)
            return guest_page(request, register=True, error="注册信息或初始化码无效")
        auth.login_success(peer)
        auth.revoke(current_token(request))
        response = response_redirect("/login")
        response.delete_cookie(WebAuth.COOKIE, path="/")
        return response

    @app.get("/login")
    async def login_page(request: Request):
        if not store.admin_exists():
            return response_redirect("/register")
        if current(request):
            return response_redirect("/")
        return guest_page(request, register=False)

    @app.post("/login")
    async def login(request: Request):
        if not store.admin_exists():
            return response_redirect("/register")
        form, _ = await checked_form(request, False)
        peer = str(request.client.host) if request.client else "unknown"
        if not auth.login_allowed(peer):
            raise HTTPException(429, "login temporarily limited")
        if not store.check_login(form.get("username"), form.get("password")):
            auth.login_failure(peer)
            return guest_page(request, register=False, error="用户名或密码错误")
        auth.login_success(peer)
        auth.revoke(current_token(request))
        token, _ = auth.new_session(authenticated=True)
        response = response_redirect("/")
        attach_cookie(response, token)
        return response

    @app.post("/logout")
    async def logout(request: Request):
        await checked_form(request, True)
        auth.revoke(current_token(request))
        response = response_redirect("/login")
        response.delete_cookie(WebAuth.COOKIE, path="/")
        return response

    async def show_page(request: Request):
        path = request.url.path
        if not store.admin_exists():
            return response_redirect("/register")
        session = current(request)
        if not session:
            return response_redirect("/login")
        page, title = _PAGES[path]
        tab = request.query_params.get("tab", "general")
        if tab not in _TABS:
            tab = "general"
        return render(
            request, "page.html", session.csrf,
            page=page, title=title, tab=tab, tabs=_TABS,
            admin_name=store.admin_name(), prefs=store.preferences(),
            info=request.query_params.get("info", ""),
        )

    for url in _PAGES:
        app.add_api_route(url, show_page, methods=["GET"], name="control_" + _PAGES[url][0])

    @app.post("/settings/preferences")
    async def save_preferences(request: Request):
        form, _ = await checked_form(request, True)
        try:
            store.save_preferences({
                "theme": form.get("theme"),
                "home": form.get("home"),
            })
        except ValueError:
            raise HTTPException(422, "invalid preferences") from None
        return response_redirect("/settings?tab=general&info=saved")

    @app.post("/settings/log-level")
    async def save_log_level(request: Request):
        form, _ = await checked_form(request, True)
        try:
            store.save_preferences({"log_level": form.get("log_level")})
        except ValueError:
            raise HTTPException(422, "invalid log level") from None
        return response_redirect("/settings?tab=maintenance&info=saved")

    @app.post("/settings/password")
    async def change_password(request: Request):
        form, _ = await checked_form(request, True)
        new = form.get("new_password")
        confirm = form.get("confirm")
        if (not isinstance(new, str) or not isinstance(confirm, str)
                or not hmac.compare_digest(new, confirm)
                or not store.change_password(form.get("old_password"), new)):
            return response_redirect("/settings?tab=account&info=password-error")
        # Invalidate all outstanding authenticated and guest sessions.
        auth._sessions.clear()
        response = response_redirect("/login")
        response.delete_cookie(WebAuth.COOKIE, path="/")
        return response

    return app
