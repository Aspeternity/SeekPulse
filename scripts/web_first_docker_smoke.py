"""Offline Docker smoke: the real B container over a localhost-published port.

No provider APIs or user NAS/PVE. Run 'first' then restart the container and
run 'restarted'. This script only uses the Python standard library.
"""
from __future__ import annotations

import http.cookiejar
import ipaddress
import re
import sys
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

_TEST_USER = "webfirst_ci_admin"
_TEST_PASSWORD = "Only a Docker CI dummy password 2026!"


def checked(condition: bool, description: str) -> None:
    if not condition:
        raise AssertionError(description)


def csrf(html: str) -> str:
    token = re.search(r'name="_csrf"\s+value="([^"]+)"', html)
    checked(token is not None, "auth form must include CSRF")
    return token.group(1)


def run(phase: str, base_url: str) -> None:
    parsed = urlparse(base_url)
    checked(parsed.scheme == "http", "smoke only supports local HTTP")
    checked(parsed.hostname is not None and ipaddress.ip_address(parsed.hostname).is_loopback,
            "smoke may only target loopback")
    checked(phase in ("first", "restarted"), "unknown smoke phase")
    cookies = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookies))

    def request(path: str, fields: dict[str, str] | None = None) -> tuple[str, str, int]:
        data = None if fields is None else urlencode(fields).encode()
        headers = {} if data is None else {"Content-Type": "application/x-www-form-urlencoded"}
        with opener.open(Request(base_url + path, data=data, headers=headers), timeout=6) as response:
            html = response.read().decode()
            return html, urlparse(response.url).path, response.status

    initial, landing, status = request("/")
    checked(status == 200, "admin page must resolve through redirects")
    if phase == "first":
        checked(landing == "/register", "first visit must open registration")
        checked('name="username"' in initial and 'name="confirm"' in initial,
                "signup must request username, password and confirmation")
        checked("setup_code" not in initial and "初始化码" not in initial,
                "signup must not require any generated setup code")
        account, location, status = request("/register", {
            "_csrf": csrf(initial),
            "username": _TEST_USER,
            "password": _TEST_PASSWORD,
            "confirm": _TEST_PASSWORD,
        })
        checked(status == 200 and location == "/login",
                "signup must finish at a distinct login page")
        checked("管理员登录" in account, "login form must appear after signup")
        login, target, code = request("/login", {
            "_csrf": csrf(account), "username": _TEST_USER,
            "password": _TEST_PASSWORD,
        })
        checked(code == 200 and target == "/", "new account must log in to overview")
        checked("运行概览" in login, "dashboard must render")
        prefs, _, _ = request("/settings")
        changed, _, _ = request("/settings/preferences", {
            "_csrf": csrf(prefs),
            "theme": "dark",
            "home": "rules",
        })
        checked("设置已保存" in changed, "preferences should save")
        checked('class="dark"' in changed, "dark mode should apply")
    else:
        checked(landing == "/login", "after restart first visit must open login")
        page, target, code = request("/login", {
            "_csrf": csrf(initial),
            "username": _TEST_USER,
            "password": _TEST_PASSWORD,
        })
        checked(code == 200 and target == "/rules", "saved home page must persist")
        checked("关键词规则" in page, "rules placeholder must render")
        prefs, _, _ = request("/settings")
        checked('class="dark"' in prefs, "theme preference must persist")
        checked("常规" in prefs and "账户安全" in prefs
                and "数据备份" in prefs and "系统维护" in prefs,
                "V4 four-tab navigation must persist")
        registration, target, _ = request("/register")
        # The redirect chain is /register -> /login -> / for an already
        # authenticated administrator. Test that registration does not render.
        checked(target != "/register" and "创建管理员账号" not in registration,
                "after signup the public registration form must be closed")
    print("WEB_FIRST_DOCKER_" + phase.upper() + "=PASS")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: web_first_docker_smoke.py first|restarted <localhost URL>")
    run(sys.argv[1], sys.argv[2])
