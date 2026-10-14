"""V1.1 SQLite store setup shared by legacy-cutover and fresh-only preparation.

A caller must already hold the exclusive database lock and authorize writes.
No Bot, network client, Web listener or notification worker starts here.
"""

from __future__ import annotations

from pathlib import Path

from app.db import Database
from app.delivery import CoreStore
from app.gate_b_dispatch import ObservationDispatcher
from app.gate_b_targets import GateBTargetStore
from app.route_store import RouteStore
from app.source_state import SourceStore


async def initialize_stores(path: Path):
    db = Database(path)
    core = CoreStore(path)
    sources = SourceStore(path)
    routes = RouteStore(path)
    registry = GateBTargetStore(path)
    dispatcher = ObservationDispatcher(path, core, routes)
    await db.init()
    await core.init()
    await sources.init()
    await routes.init()
    await dispatcher.init()
    return db, core, sources, routes, registry, dispatcher
