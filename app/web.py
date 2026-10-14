"""S5 opt-in local FastAPI/Jinja2/HTMX administrator dashboard.

This application is NOT imported or launched by app.main. It binds loopback
only via app.web_cli after separate operator approval. The Bot and Web both
use the pre-existing SQLite domain APIs and stay in sync without replication.
"""

from __future__ import annotations

import hmac
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.web_auth import AdminWebConfig, Session, WebAuth, check_password, loopback_request
from app.web_service import MissingAdminProfile, WebService


_ROOT = Path(__file__).parent / "web_ui"


def _integer(value: str) -> int:
    if (not isinstance(value, str) or len(value) > 19
            or not value.isascii() or not value.isdecimal()):
        raise HTTPException(422, "invalid identifier")
    number = int(value)
    if number <= 0 or number >= 2**63:
        raise HTTPException(422, "invalid identifier")
    return number


def _targets(form) -> list[int]:
    entries = form.getlist("target_ids")
    if len(entries) > 50:
        raise HTTPException(422, "too many targets")
    ids = [_integer(x) for x in entries]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "duplicate target")
    return ids


def _enabled(form) -> bool:
    value = form.get("enabled")
    if value not in ("0", "1"):
        raise HTTPException(422, "invalid state")
    return value == "1"


def create_web_app(
    database_path: Path, config: AdminWebConfig, *, auth: WebAuth | None = None
) -> FastAPI:
    """Build a single-worker ASGI app; no network access at factory time."""
    if not isinstance(config, AdminWebConfig):
        raise ValueError("administrator Web configuration is required")
    service = WebService(database_path, config.admin_tg_user_id)
    sessions = auth or WebAuth(config)
    templates = Jinja2Templates(directory=str(_ROOT / "templates"))
    templates.env.filters["utc_time"] = (
        lambda epoch: datetime.fromtimestamp(int(epoch), timezone.utc)
        .strftime("%Y-%m-%d %H:%M UTC")
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await service.ensure_schema()
        yield

    app = FastAPI(
        title="SeekPulse", docs_url=None, redoc_url=None, openapi_url=None,
        lifespan=lifespan,
    )
    app.mount("/assets", StaticFiles(directory=str(_ROOT / "static")), name="assets")

    def cookie(request: Request) -> str | None:
        return request.cookies.get(WebAuth.COOKIE)

    def session(request: Request) -> Session:
        current = sessions.get(cookie(request), authenticated=True)
        if current is None:
            raise HTTPException(status_code=401, detail="authentication required")
        return current

    def render(request: Request, name: str, csrf: str, **context):
        return templates.TemplateResponse(
            request, name, {"csrf": csrf, "active_page": name, **context},
            headers={"Cache-Control": "no-store"},
        )

    def attach_cookie(response, token: str) -> None:
        response.set_cookie(
            WebAuth.COOKIE, token, httponly=True, secure=config.secure_cookie,
            samesite="strict", max_age=config.session_seconds, path="/",
        )

    @app.middleware("http")
    async def secure_local_request(request: Request, call_next):
        forwarded = any(x in request.headers for x in (
            "forwarded", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-for"
        ))
        if not loopback_request(request.scope, request.headers.get("host"), forwarded):
            response = PlainTextResponse("Forbidden", status_code=403)
        elif request.method not in ("GET", "HEAD", "POST"):
            response = PlainTextResponse("Method not allowed", status_code=405)
        elif request.method == "POST" and request.headers.get("origin"):
            origin = request.headers["origin"]
            try:
                u = urlsplit(origin)
                expected = urlsplit(str(request.base_url))
                if (u.scheme, u.hostname, u.port) != (
                    expected.scheme, expected.hostname, expected.port
                ):
                    response = PlainTextResponse("Forbidden origin", status_code=403)
                else:
                    response = await call_next(request)
            except (ValueError, TypeError):
                response = PlainTextResponse("Forbidden origin", status_code=403)
        else:
            response = await call_next(request)
        response.headers.update({
            "Content-Security-Policy": (
                "default-src 'none'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; form-action 'self'; "
                "base-uri 'none'; frame-ancestors 'none'"
            ),
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        })
        return response

    async def form_with_csrf(request: Request, current: Session):
        if not request.headers.get("content-type", "").startswith(
            ("application/x-www-form-urlencoded", "multipart/form-data")
        ):
            raise HTTPException(415, "form body required")
        raw = await request.body()
        if len(raw) > 8192:
            raise HTTPException(413, "form too large")
        form = await request.form()
        token = form.get("_csrf", "")
        if not isinstance(token, str) or not hmac.compare_digest(token, current.csrf):
            raise HTTPException(403, "CSRF verification failed")
        return form

    def protected(request: Request) -> Session:
        return session(request)

    def changed(path: str) -> RedirectResponse:
        return RedirectResponse(path, status_code=303)

    async def apply(action):
        try:
            return await action
        except MissingAdminProfile as exc:
            raise HTTPException(409, "administrator must first /start the Telegram Bot") from exc
        except ValueError as exc:
            # Do not reflect user data or a secret URL in any error response.
            raise HTTPException(422, "invalid or unauthorized configuration") from exc

    @app.get("/login")
    async def login_form(request: Request):
        if sessions.get(cookie(request), authenticated=True):
            return changed("/")
        token, guest = sessions.new_session(authenticated=False)
        response = render(request, "login.html", guest.csrf, error=None)
        attach_cookie(response, token)
        return response

    @app.post("/login")
    async def login(request: Request):
        guest = sessions.get(cookie(request), authenticated=False)
        if guest is None:
            raise HTTPException(403, "login session expired")
        form = await form_with_csrf(request, guest)
        peer = str(request.client.host)
        if not sessions.login_allowed(peer):
            raise HTTPException(429, "login temporarily limited")
        password = form.get("password", "")
        if not isinstance(password, str) or not check_password(password, config.password_digest):
            sessions.login_failure(peer)
            return render(request, "login.html", guest.csrf, error="密码错误",)
        sessions.login_success(peer)
        sessions.revoke(cookie(request))
        token, _ = sessions.new_session(authenticated=True)
        response = changed("/")
        attach_cookie(response, token)
        return response

    @app.post("/logout")
    async def logout(request: Request):
        await form_with_csrf(request, protected(request))
        sessions.revoke(cookie(request))
        response = changed("/login")
        response.delete_cookie(WebAuth.COOKIE, path="/")
        return response

    @app.get("/")
    async def dashboard(request: Request):
        current = protected(request)
        try:
            data = await service.dashboard()
            return render(request, "dashboard.html", current.csrf, **data)
        except MissingAdminProfile:
            return render(request, "onboarding.html", current.csrf)

    @app.get("/fragments/summary")
    async def summary(request: Request):
        protected(request)
        data = await apply(service.dashboard())
        return templates.TemplateResponse(
            request, "_summary.html", data, headers={"Cache-Control": "no-store"}
        )

    @app.get("/rules")
    async def rules(request: Request):
        current = protected(request)
        data = await apply(service.rules())
        return render(request, "rules.html", current.csrf, **data)

    @app.get("/sources")
    async def sources(request: Request):
        current = protected(request)
        data = await apply(service.sources_view())
        return render(request, "sources.html", current.csrf, **data)

    @app.get("/channels")
    async def channels(request: Request):
        current = protected(request)
        data = await apply(service.channels())
        return render(request, "channels.html", current.csrf, **data)

    @app.get("/history")
    async def history(request: Request):
        current = protected(request)
        data = await apply(service.history())
        return render(request, "history.html", current.csrf, **data)

    @app.get("/settings")
    async def settings(request: Request):
        current = protected(request)
        data = await apply(service.settings())
        return render(request, "settings.html", current.csrf, **data)

    @app.post("/rules/add")
    async def add_rule(request: Request):
        form = await form_with_csrf(request, protected(request))
        await apply(service.add_rule(str(form.get("keyword", ""))))
        return changed("/rules")

    @app.post("/rules/{rule_id}/state")
    async def rule_state(request: Request, rule_id: int):
        form = await form_with_csrf(request, protected(request))
        if not await apply(service.update_rule(rule_id, _enabled(form))):
            raise HTTPException(404, "rule not found")
        return changed("/rules")

    @app.post("/rules/{rule_id}/delete")
    async def rule_delete(request: Request, rule_id: int):
        await form_with_csrf(request, protected(request))
        if not await apply(service.delete_rule(rule_id)):
            raise HTTPException(404, "rule not found")
        return changed("/rules")

    @app.post("/rules/{rule_id}/route")
    async def rule_route(request: Request, rule_id: int):
        form = await form_with_csrf(request, protected(request))
        flag = form.get("override")
        if flag not in ("0", "1"):
            raise HTTPException(422, "invalid override flag")
        await apply(service.update_rule_route(
            rule_id, str(form.get("priority", "")), flag == "1", _targets(form)
        ))
        return changed("/rules")

    @app.post("/blocks/add")
    async def block_add(request: Request):
        form = await form_with_csrf(request, protected(request))
        await apply(service.add_block(str(form.get("keyword", ""))))
        return changed("/rules")

    @app.post("/blocks/{block_id}/delete")
    async def block_delete(request: Request, block_id: int):
        await form_with_csrf(request, protected(request))
        if not await apply(service.delete_block(block_id)):
            raise HTTPException(404, "block not found")
        return changed("/rules")

    @app.post("/sources/{source}/state")
    async def source_state(request: Request, source: str):
        form = await form_with_csrf(request, protected(request))
        await apply(service.set_source(source, _enabled(form)))
        return changed("/sources")

    @app.post("/channels/defaults")
    async def channel_defaults(request: Request):
        form = await form_with_csrf(request, protected(request))
        value = form.get("override")
        if value not in ("0", "1"):
            raise HTTPException(422, "invalid override")
        await apply(service.update_default_targets(_targets(form) if value == "1" else None))
        return changed("/channels")

    @app.post("/channels/{target_id}/bind")
    async def bind_channel(request: Request, target_id: int):
        form = await form_with_csrf(request, protected(request))
        await apply(service.update_channel(
            target_id, str(form.get("channel", "")), str(form.get("secret_ref", ""))
        ))
        return changed("/channels")

    @app.post("/channels/{target_id}/state")
    async def target_state(request: Request, target_id: int):
        form = await form_with_csrf(request, protected(request))
        if not await apply(service.update_target(target_id, _enabled(form))):
            raise HTTPException(404, "target not found")
        return changed("/channels")

    @app.post("/settings/categories")
    async def set_categories(request: Request):
        form = await form_with_csrf(request, protected(request))
        categories = form.getlist("categories")
        if len(categories) > 30 or not all(isinstance(x, str) for x in categories):
            raise HTTPException(422, "invalid categories")
        await apply(service.set_categories(categories))
        return changed("/settings")

    @app.post("/settings/state")
    async def set_state(request: Request):
        form = await form_with_csrf(request, protected(request))
        await apply(service.set_paused(_enabled(form)))
        return changed("/settings")

    return app
