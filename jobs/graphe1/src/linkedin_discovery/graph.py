"""Définition du graphe ; les dépendances sont injectées par le service."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class State(TypedDict, total=False):
    search: dict
    cycle_id: str
    report_id: str
    report_path: str
    status: str
    collection: dict
    qualification_counts: dict[str, int]


def build_graph(service, checkpointer=None, report_node=None):
    return (
        StateGraph(State)
        .add_node("collect", service.collect)
        .add_node("qualify", service.qualify)
        .add_node("report", report_node or service.report)
        .add_edge(START, "collect")
        .add_edge("collect", "qualify")
        .add_edge("qualify", "report")
        .add_edge("report", END)
        .compile(name="graphe1.discovery", checkpointer=checkpointer)
    )
