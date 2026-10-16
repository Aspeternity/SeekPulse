"""Opt-in B Web-first entrypoint: independent control plane, no Bot runtime."""

from __future__ import annotations

import os
from pathlib import Path

from app.instance_lock import database_owner_lock
from app.web_first import create_web_first_app
from app.web_first_store import WebFirstStore


def main() -> None:
    data_dir = Path(os.environ.get("SEEKPULSE_DATA_DIR", "/app/data"))
    port_text = os.environ.get("SEEKPULSE_WEB_PORT", "8765")
    if not port_text.isascii() or not port_text.isdecimal():
        raise RuntimeError("invalid_web_port")
    port = int(port_text)
    if not 1024 <= port <= 65535:
        raise RuntimeError("invalid_web_port")

    store = WebFirstStore(data_dir)
    # Hold the lock for the entire Web process lifetime; no second writer.
    with database_owner_lock(store.path):
        store.prepare_locked()
        if store.admin_exists():
            print("SeekPulse Web ready. Sign in with your registered account.", flush=True)
        else:
            print("SeekPulse Web ready. Open /register to create your own administrator account.", flush=True)

        import uvicorn

        web = create_web_first_app(store)
        uvicorn.run(
            web, host="0.0.0.0", port=port, workers=1,
            proxy_headers=False, forwarded_allow_ips="",
            access_log=False, log_level="warning",
        )


if __name__ == "__main__":
    main()
