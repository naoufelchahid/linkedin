"""Interface locale du graphe, exposée par le même serveur LangGraph."""

import asyncio
import json
import os
import re
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import asdict
from importlib.resources import files
from uuid import UUID

import httpx
from langgraph_sdk import get_client
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .config import Config
from .launch import Search
from .retained import retained_rows
from .store import Store

ASSETS = files("linkedin_discovery.resources")


def snapshot(config, cycle, offer_key, cycles_only=False):
    path = config.data / "discovery.sqlite3"
    output = dict(offers=[], cycles=[])
    if not path.exists():
        return output
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        output["cycles"] = [
            dict(r)
            for r in db.execute("""
            SELECT c.id,c.created_at,c.status,c.settings,
            (SELECT count(*) FROM cycle_items WHERE cycle_id=c.id) qualified,
            (SELECT count(*) FROM reports WHERE cycle_id=c.id) reports,
            (SELECT count(*) FROM cycle_items i JOIN qualifications q ON q.id=i.qualification_id WHERE i.cycle_id=c.id AND q.status IN ('error','data_problem')) qualification_errors,
            (SELECT count(*) FROM runs WHERE cycle_id=c.id AND error!='') errors
            FROM cycles c ORDER BY c.created_at DESC
        """)
        ]
        if cycles_only:
            return output
        for row in retained_rows(db, cycle):
            offer = json.loads(row["content"])
            if offer_key:
                if offer["key"] != offer_key:
                    continue
                raw = [
                    dict(r)
                    for r in db.execute(
                        """
                    SELECT o.profile,o.cycle_id,o.observed_at,o.raw FROM occurrences o
                    JOIN versions v ON v.id=o.version_id WHERE v.offer_key=?
                    ORDER BY o.observed_at DESC
                """,
                        (offer_key,),
                    )
                ]
                for observation in raw:
                    observation["raw"] = json.loads(observation["raw"])
                output["detail"] = dict(
                    offer=offer,
                    result=json.loads(row["result"] or "{}"),
                    human=row["human"],
                    observations=raw,
                )
                break
            output["offers"].append(
                {
                    **{
                        k: offer.get(k)
                        for k in ("key", "title", "company", "location", "posted_at")
                    },
                    "description": offer.get("description", ""),
                    "since": row["retained_since"],
                }
            )
    return output


def asset(request):
    name = request.path_params.get("asset", "html")
    types = {"html": "text/html", "css": "text/css", "js": "application/javascript"}
    if name not in types:
        return Response(status_code=404)
    return Response(ASSETS.joinpath("dashboard." + name).read_bytes(), media_type=types[name])


def data(request):
    if not trusted(request):
        return Response(status_code=403)
    config = Config.load()
    params = request.query_params
    output = snapshot(config, params.get("cycle", ""), params.get("offer", ""), "cycles" in params)
    if "metrics" in params:
        try:
            output["applications"] = applications("metrics")
        except (OSError, subprocess.SubprocessError, ValueError):
            output["applications"] = None
    output["defaults"] = asdict(Search(list(config.profiles), "Morocco", "r604800", config.limit))
    output["favorites"] = {}
    favorites = config.data / "dashboard.sqlite3"
    if favorites.exists():
        with closing(sqlite3.connect(favorites)) as db:
            output["favorites"] = {
                key: json.loads(value)
                for key, value in db.execute("SELECT name,search FROM favorites")
            }
    return JSONResponse(output, headers={"Cache-Control": "no-store"})


def trusted(request):
    return request.url.hostname in {"127.0.0.1", "localhost", "::1"} and (
        request.headers.get("origin", str(request.base_url).rstrip("/"))
        == str(request.base_url).rstrip("/")
    )


def save_favorite(payload):
    search = Search(**payload["search"])
    name = payload["name"].strip()
    if not name:
        raise ValueError
    folder = Config.load().data
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / "dashboard.sqlite3"
    path.touch(mode=0o600, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS favorites(name TEXT PRIMARY KEY,search TEXT)")
        db.execute(
            "INSERT OR REPLACE INTO favorites VALUES(?,?)",
            (name, json.dumps(asdict(search))),
        )


def check_cycle(ident):
    with closing(Store(Config.load().data)) as store:
        store.cycle(ident)


def applications(command, cycle="", mode="", offers=()):
    config = Config.load()
    root = config.root.parent / "graphe2"
    binary = os.environ.get("APPLICATIONS_CLI", str(root / ".venv/bin/linkedin-applications"))
    state = os.environ.get("APPLICATIONS_STATE", str(root / "var"))
    args = [
        binary,
        "--state",
        state,
        command,
        "--discovery",
        str(config.data),
    ]
    if cycle:
        args.extend(["--cycle", cycle])
    if mode:
        args.extend(["--mode", mode])
    for key in offers:
        args.extend(["--offer", key])
    process = subprocess.run(args, capture_output=True, timeout=15, check=True)
    return json.loads(process.stdout)


async def action(request):
    if not trusted(request) or request.headers.get("content-type") != "application/json":
        return Response(status_code=403)
    try:
        payload = await request.json()
        command = request.path_params["command"]
        if command == "favorite":
            await asyncio.to_thread(save_favorite, payload)
            return JSONResponse({"saved": True})
        ident = UUID(payload["cycle"])
        if command in {"application-status", "applications"}:
            mode = payload.get("mode", "") if command == "applications" else ""
            if command == "applications" and mode not in {"recipe", "production"}:
                raise ValueError
            offers = payload.get("offers", [])
            if (
                not isinstance(offers, list)
                or (offers and mode != "recipe")
                or any(
                    not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key)
                    for key in offers
                )
                or (mode == "recipe" and not offers)
            ):
                raise ValueError
            try:
                result = await asyncio.to_thread(
                    applications, "launch" if mode else "status", ident.hex, mode, offers
                )
            except (OSError, subprocess.SubprocessError):
                return JSONResponse(
                    {"error": "Graphe de candidatures indisponible."}, status_code=503
                )
            return JSONResponse(result)
        client = get_client(url=str(request.base_url).rstrip("/"))
        if command == "progress":
            run = await client.runs.get(str(ident), str(UUID(payload["run"])))
            return JSONResponse({"status": run["status"]})
        state = {"cycle_id": ident.hex}
        if command == "launch":
            state["search"] = asdict(Search(**payload["search"]))
        elif command == "resume":
            await asyncio.to_thread(check_cycle, ident.hex)
        else:
            return Response(status_code=404)
        run = await client.runs.create(
            str(ident), "graphe1", input=state, if_not_exists="create", multitask_strategy="reject"
        )
        return JSONResponse({"run": run["run_id"], "cycle": ident.hex})
    except (KeyError, ValueError, TypeError, AttributeError):
        return JSONResponse({"error": "Paramètres invalides."}, status_code=400)
    except httpx.HTTPError:
        return JSONResponse(
            {"error": "Exécution LangGraph indisponible. Vérifiez le suivi du cycle."},
            status_code=502,
        )


app = Starlette(
    routes=[
        Route("/dashboard", asset),
        Route("/dashboard/assets/{asset}", asset),
        Route("/dashboard/data", data),
        Route("/dashboard/actions/{command}", action, methods=["POST"]),
    ]
)
