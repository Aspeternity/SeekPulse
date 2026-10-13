#!/usr/bin/env python3
"""S0-only Apprise Bark/ntfy loopback smoke; no real push, tokens or external endpoints."""

from __future__ import annotations

import argparse
import asyncio
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class MockPushHandler(BaseHTTPRequestHandler):
    requests_seen: list[dict[str, object]] = []
    response_code: int = 200

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        if length > 100_000:
            self.send_error(413)
            return
        self.rfile.read(length)
        self.requests_seen.append({"method": "POST", "length": length})
        self.send_response(self.response_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if self.response_code == 200:
            self.wfile.write(b'{"code":200,"message":"success","id":"s0"}')
        else:
            self.wfile.write(b'{"code":403,"message":"forbidden"}')

    def log_message(self, format: str, *args: object) -> None:
        return


def result_summary(result: object) -> dict[str, object]:
    """Handle a result object, not identity comparison with True."""
    status = getattr(result, "status", None)
    services = list(result) if hasattr(result, "__iter__") else []
    return {
        "ok": bool(result),
        "result_type": type(result).__name__,
        "status": getattr(status, "name", str(status) if status is not None else "UNKNOWN"),
        "services": len(services),
        "service_results": [bool(s) for s in services],
    }


async def run_probe() -> dict[str, object]:
    import apprise

    server = ThreadingHTTPServer(("127.0.0.1", 0), MockPushHandler)
    server.daemon_threads = True
    MockPushHandler.requests_seen = []
    MockPushHandler.response_code = 200
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    result: dict[str, object] = {
        "kind": "ISOLATED_LOOPBACK_ONLY_NOT_DEVICE_DELIVERY",
        "apprise_version": getattr(apprise, "__version__", "UNKNOWN"),
        "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "service_tests": [],
    }
    try:
        for kind, url in [
            ("bark", f"bark://{host}:{port}/s0-fake-device"),
            ("ntfy", f"ntfy://{host}:{port}/s0-fake-topic"),
        ]:
            instance = apprise.Apprise()
            added = instance.add(url)
            if not added:
                observation: dict[str, object] = {"channel": kind, "config_accepted": False}
            else:
                message_result = await instance.async_notify(
                    title="SeekPulse S0", body="loopback adapter test"
                )
                observation = {
                    "channel": kind,
                    "config_accepted": True,
                    "success_response": result_summary(message_result),
                }
            result["service_tests"].append(observation)
        # A single 403 denial is a representative failure, not a full retry test.
        MockPushHandler.response_code = 403
        denied = apprise.Apprise()
        denied.add(f"ntfy://{host}:{port}/s0-denied-topic")
        denied_result = await denied.async_notify(
            title="SeekPulse S0", body="expected local denial"
        )
        result["denied_ntfy_result"] = result_summary(denied_result)
        result["loopback_requests_seen"] = len(MockPushHandler.requests_seen)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = asyncio.run(run_probe())
    data = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(data, encoding="utf-8")
    else:
        print(data, end="")
    tests = result["service_tests"]
    passed = len(tests) == 2 and result["loopback_requests_seen"] >= 2 and all(
        t.get("config_accepted") and t.get("success_response", {}).get("ok")
        for t in tests
    ) and not result["denied_ntfy_result"]["ok"]
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
