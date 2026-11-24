import json

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END
from linkedin_applications.graph import build
from linkedin_applications.telemetry import GraphTrace


class Workflow:
    def fill(self, state):
        return {"status": "blocked", "reason": "private reason", "next_node": END}

    def __getattr__(self, name):
        return self.fill


def test_graph_trace_exports_node_io_without_dossier_content(monkeypatch):
    events = []
    trace = GraphTrace({})
    trace.project = "test"
    monkeypatch.setattr(
        trace,
        "publish",
        lambda run, method: events.append((method, run.name, run.inputs, run.outputs)),
    )
    # RunTree validates the type of the client even with its network calls replaced.
    from langsmith import Client

    trace.client = Client(api_key="test", info={})
    try:
        graph = build(Workflow(), InMemorySaver(), trace=trace)
        result = trace.invoke(
            graph,
            {"mode": "recipe", "cv": "private path", "cv_text": "private CV"},
            {"configurable": {"thread_id": "synthetic"}},
            durability="sync",
        )
    finally:
        trace.close()

    assert result["reason"] == "private reason"
    assert ("post", "fill", {"mode": "recipe", "has_cv": True}, {}) in events
    assert (
        "patch",
        "fill",
        {"mode": "recipe", "has_cv": True},
        {"status": "blocked", "next_node": END},
    ) in events
    assert "private" not in json.dumps(events)
