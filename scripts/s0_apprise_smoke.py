#!/usr/bin/env python3
"""S0-only, isolated Apprise Bark/ntfy loopback; never sends real push notifications."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time


class MockPushHandler(BaseHTTPRequestHandler):
    """Local-only HTTP mock: read requests without storing body, path or credentials."""

    requests_seen: list[dict[str, int]] = []
    response_code = 200
    delay_seconds = 0.0

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("content-length", "0"))
        except ValueError:
            self.send_error(400)
            return
        if length < 0 or length > 100_000:
            self.send_error(413)
            return
        self.rfile.read(length)
        self.requests_seen.append({"bytes": length, "status": self.response_code})
        status, delay = self.response_code, self.delay_seconds
        if delay:
            time.sleep(delay)
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if status == 429:
                self.send_header("Retry-After", "1")
            self.end_headers()
            message = "success" if status == 200 else "simulated_failure"
            self.wfile.write(json.dumps({
                "code": status, "message": message, "id": "s0"
            }).encode("ascii"))
        except (BrokenPipeError, ConnectionResetError, OSError):
            # Client deliberately timed out; never log the request or URL.
            pass

    def log_message(self, format: str, *args: object) -> None:
        return


def result_summary(result: object) -> dict[str, object]:
    """Apprise 2.0.1 returns a result object, not necessarily literal True."""
    status = getattr(result, "status", None)
    services = list(result) if hasattr(result, "__iter__") else []
    return {
        "ok": bool(result),
        "result_type": type(result).__name__,
        "status": getattr(status, "name", str(status) if status is not None else "UNKNOWN"),
        "services": len(services),
        "service_results": [bool(s) for s in services],
    }


def classify_case(expected_ok: bool, configured: bool, attempts: int,
                  response: dict[str, object]) -> bool:
    """Contract: configured, exactly one local POST, correctly reported outcome."""
    return (configured and attempts == 1
            and response.get("ok") is expected_ok
            and (response.get("services") == 1
                 or response.get("status") == "LOCAL_DEADLINE_TIMEOUT"))


def memory_observation() -> dict[str, object]:
    """Optional Linux process/cgroup samples: not a real low-memory VPS benchmark."""
    report: dict[str, object] = {}
    for label, path in [
        ("vm_rss_kib", "/proc/self/status"),
        ("cgroup_memory_max_bytes", "/sys/fs/cgroup/memory.max"),
        ("cgroup_memory_peak_bytes", "/sys/fs/cgroup/memory.peak"),
        ("cgroup_cpu_max", "/sys/fs/cgroup/cpu.max"),
    ]:
        try:
            data = Path(path).read_text(encoding="ascii")
            if label == "vm_rss_kib":
                entry = next(row for row in data.splitlines() if row.startswith("VmRSS:"))
                report[label] = int(entry.split()[1])
            elif label == "cgroup_cpu_max":
                report[label] = data.strip()
            else:
                report[label] = int(data.strip()) if data.strip().isdigit() else data.strip()
        except (OSError, ValueError, StopIteration):
            report[label] = None
    try:
        import resource
        report["process_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ImportError, OSError):
        report["process_peak_rss_kib"] = None
    return report


async def run_probe() -> dict[str, object]:
    import apprise

    server = ThreadingHTTPServer(("127.0.0.1", 0), MockPushHandler)
    server.daemon_threads = True
    MockPushHandler.requests_seen = []
    MockPushHandler.response_code = 200
    MockPushHandler.delay_seconds = 0.0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    cases = [
        ("bark", "success", 200, 0.0, True),
        ("ntfy", "success", 200, 0.0, True),
        ("bark", "denied", 403, 0.0, False),
        ("ntfy", "denied", 403, 0.0, False),
        ("bark", "rate_limited", 429, 0.0, False),
        ("ntfy", "rate_limited", 429, 0.0, False),
        ("bark", "server_error", 503, 0.0, False),
        ("ntfy", "server_error", 503, 0.0, False),
        ("bark", "slow_response", 200, 3.0, False),
        ("ntfy", "slow_response", 200, 3.0, False),
    ]

    report: dict[str, object] = {
        "kind": "S0_ISOLATED_LOOPBACK_NO_REAL_DEVICE",
        "version_pinned": "2.0.1",
        "apprise_version": getattr(apprise, "__version__", "UNKNOWN"),
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cases": [],
        "scenario_counts": {"total": len(cases), "passed": 0},
        "no_external_targets": True,
    }
    began_all = time.monotonic()
    try:
        for provider, scenario, status, delay, expected_ok in cases:
            MockPushHandler.response_code = status
            MockPushHandler.delay_seconds = delay
            # No operator-supplied URL, no real device token, no redirect.
            url = (f"{provider}://{host}:{port}/s0-local-{scenario}"
                   "?retry=0&cto=1&rto=1&redirect=no")
            asset = apprise.AppriseAsset(service_timeout=2)
            instance = apprise.Apprise(asset=asset)
            configured = bool(instance.add(url))
            before = len(MockPushHandler.requests_seen)
            elapsed_start = time.monotonic()
            if configured:
                try:
                    value = await asyncio.wait_for(
                        instance.async_notify(
                            title="S0 isolated notification",
                            body="Only local HTTP test (not a push)"),
                        timeout=4.0,
                    )
                    result = result_summary(value)
                except asyncio.TimeoutError:
                    result = {
                        "ok": False, "status": "LOCAL_DEADLINE_TIMEOUT",
                        "services": 0, "result_type": "Timeout",
                        "service_results": [],
                    }
            else:
                result = {
                    "ok": False, "status": "CONFIG_REJECTED",
                    "services": 0, "result_type": "None",
                    "service_results": [],
                }
            attempts = len(MockPushHandler.requests_seen) - before
            passed = classify_case(expected_ok, configured, attempts, result)
            observation = {
                "channel": provider,
                "scenario": scenario,
                "simulated_http_status": status,
                "configured": configured,
                "local_post_count": attempts,
                "result": result,
                "elapsed_ms": round((time.monotonic() - elapsed_start) * 1000),
                "passed": passed,
            }
            report["cases"].append(observation)
            report["scenario_counts"]["passed"] += int(passed)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    report["run_seconds"] = round(time.monotonic() - began_all, 3)
    report["resource_observation"] = memory_observation()
    report["limitations"] = (
        "HTTP mock result is NOT mobile delivery, APNs, durable retries, or "
        "security approval for arbitrary notification endpoints. "
        "CPU/memory measurements are indicative only; verify actual VPS separately."
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(run_probe())
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    print("S0_APPRISE_RESULT:",
          json.dumps({
              "cases": report["scenario_counts"],
              "version": report["apprise_version"],
              "resource": report["resource_observation"],
          }, sort_keys=True))
    return 0 if (report["scenario_counts"]["passed"] == report["scenario_counts"]["total"]
                 and report["apprise_version"] == report["version_pinned"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
