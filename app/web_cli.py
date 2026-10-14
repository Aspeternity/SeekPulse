"""S5 explicitly opt-in local-only ASGI preview.

Not launched by app.main, Dockerfile, or Compose. An operator must separately
approve and supply a protected password hash and administrator TG ID.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.web_auth import AdminWebConfig
from app.web import create_web_app


def main() -> None:
    config = AdminWebConfig.from_environment()
    try:
        port = int(os.getenv("SEEKPULSE_WEB_PORT", "8765"))
    except ValueError as exc:
        raise RuntimeError("invalid local Web port") from exc
    if not 1024 <= port <= 65535:
        raise RuntimeError("local Web port must be 1024..65535")
    database_path = Path(os.getenv("DATABASE_PATH", "data/bot.db"))
    app = create_web_app(database_path, config)
    import uvicorn

    # Fixed loopback binding, no proxy header trust, one worker.
    uvicorn.run(
        app, host="127.0.0.1", port=port, workers=1,
        proxy_headers=False, access_log=False, log_level="warning",
    )


if __name__ == "__main__":
    main()
