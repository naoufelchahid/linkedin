"""Point d’entrée Studio ; ressources SQLite limitées à une exécution."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, asynccontextmanager
from contextvars import copy_context
from uuid import UUID

from .config import Config
from .graph import build_graph
from .launch import Search
from .workflow import DiscoveryService


@asynccontextmanager
async def make_graph():
    # Un même thread possède la connexion SQLite et le verrou pendant le run.
    # L’inspection du schéma et de la topologie n’ouvre aucun stockage.
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="discovery-studio")
    stack = ExitStack()
    service = None
    cycle_id = None

    async def in_worker(function, *args):
        context = copy_context()
        return await asyncio.get_running_loop().run_in_executor(
            executor, context.run, function, *args
        )

    def execute(name, state):
        nonlocal service, cycle_id
        requested = state.get("cycle_id")
        if not requested:
            raise ValueError("cycle_id_required_use_cli_discover_first")
        if state.get("search") is not None and UUID(requested).hex != requested:
            raise ValueError("cycle_id_must_be_uuid_hex")
        if service is None:
            service = DiscoveryService(Config.load())
            stack.callback(service.store.close)
            stack.callback(service.flush_traces)
            stack.enter_context(service.store.locked())
            if state.get("search") is not None:
                search = Search(**state["search"])
                existing = service.store.db.execute(
                    "SELECT settings FROM cycles WHERE id=?", (requested,)
                ).fetchone()
                if existing:
                    saved = json.loads(existing["settings"])
                    if any(saved.get(k) != v for k, v in state["search"].items()):
                        raise ValueError("cycle_search_changed")
                else:
                    service.create(search=search, ident=requested)
            service.store.cycle(requested)
            cycle_id = requested
        if requested != cycle_id:
            raise ValueError("cycle_id_changed_during_execution")
        with service.tracing(cycle_id):
            return getattr(service, name)(state)

    class Nodes:
        async def collect(self, state):
            return await in_worker(execute, "collect", state)

        async def qualify(self, state):
            return await in_worker(execute, "qualify", state)

        async def report(self, state):
            return await in_worker(execute, "report", state)

    try:
        yield build_graph(Nodes())
    finally:
        try:
            await in_worker(stack.close)
        finally:
            executor.shutdown(wait=True)
