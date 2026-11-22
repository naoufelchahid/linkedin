"""Opération locale de saisie, indépendante du contexte envoyé au modèle."""

import hashlib
import json
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from portal import BASE

PROOF = Path("/preuve")


class State(TypedDict):
    instruction: str
    verified: bool


async def fill_secret(browser, rpc, expect):
    # Seul ce nœud manipule la valeur, jamais le schéma d’état du graphe.
    async def input_node(state):
        tab = browser.json_result(
            await browser.use(rpc, "page_openTab", {"url": BASE + "/secret"})
        )
        if await browser.current_url(rpc, tab["tabId"]) != BASE + "/secret":
            raise RuntimeError("Destination de recette incorrecte")
        secret = (PROOF / "canary").read_bytes()
        await browser.use(
            rpc,
            "page_fillInput",
            {
                "target": {"selector": "input[type=password]#secret"},
                "value": secret.decode(),
            },
        )
        await expect(hashlib.sha256(secret).hexdigest())
        return {"verified": True}

    def prompt_node(state):
        # Le banc local enregistre le contexte exact qui serait remis au modèle.
        with (PROOF / "prompts.jsonl").open("a") as prompts:
            prompts.write(json.dumps(state) + "\n")
        return {}

    graph = StateGraph(State)
    graph.add_node("saisie", input_node)
    graph.add_node("demande", prompt_node)
    graph.add_node("suite", prompt_node)
    graph.add_edge(START, "demande")
    graph.add_edge("demande", "saisie")
    graph.add_edge("saisie", "suite")
    graph.add_edge("suite", END)
    config = {"configurable": {"thread_id": "inscription-test"}}
    async with AsyncSqliteSaver.from_conn_string(
        str(PROOF / "checkpoints.sqlite3")
    ) as saver:
        workflow = graph.compile(checkpointer=saver)
        await workflow.ainvoke(
            {"instruction": "Renseigner le secret de recette.", "verified": False},
            config,
        )
        snapshot = await workflow.aget_state(config)
        if not snapshot.values["verified"]:
            raise RuntimeError("Checkpoint final de vérification absent")
