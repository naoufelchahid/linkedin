"""Événements techniques au format LangSmith pour le collecteur local de recette."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from uuid import UUID, uuid4

import httpx
from langgraph.errors import GraphInterrupt
from langsmith import Client
from langsmith.run_trees import RunTree


class AttemptTrace:
    def __init__(self, port=None):
        self.client = None
        self.root = None
        if port:
            self.client = httpx.Client(
                base_url=f"http://127.0.0.1:{int(port)}/",
                timeout=1,
                trust_env=False,
                follow_redirects=False,
            )

    def close(self):
        if self.client:
            self.client.close()

    def send(self, method, path, body):
        try:
            response = self.client.request(method, path, json=body)
            return response.is_success or (
                method == "POST" and response.status_code == 409
            )
        except httpx.HTTPError:
            return False

    @contextmanager
    def step(self, dossier, attempt, stage):
        if self.client is None or not attempt or not attempt.get("started_at"):
            yield
            return
        root = str(UUID(attempt["id"]))
        dossier = str(UUID(dossier))
        start = datetime.now(UTC).isoformat()
        metadata = {
            "thread_id": dossier,
            "dossier_id": dossier,
            "attempt_id": root,
            "mode": "production",
        }
        fields = {
            "session_name": "graphe2-recette",
            "run_type": "chain",
            "inputs": {},
            "extra": {"metadata": metadata},
        }
        if self.root != root:
            if not self.send(
                "POST",
                "runs",
                {
                    **fields,
                    "id": root,
                    "name": "graphe2.tentative",
                    "start_time": attempt["started_at"],
                },
            ):
                yield
                return
            self.root = root
        child = str(uuid4())
        emitted = self.send(
            "POST",
            "runs",
            {
                **fields,
                "id": child,
                "parent_run_id": root,
                "name": "graphe2." + stage,
                "start_time": start,
            },
        )
        failed = True
        try:
            yield
            failed = False
        finally:
            if emitted:
                end = datetime.now(UTC).isoformat()
                done = {"end_time": end, "outputs": {}}
                if failed:
                    done["error"] = "interruption"
                self.send("PATCH", f"runs/{child}", done)
                self.send("PATCH", f"runs/{root}", {"end_time": end, "outputs": {}})


# Ces listes excluent les textes saisis, les coordonnées et les données du portail.
STATE_LABELS = {
    "mode": {"recipe", "production"},
    "status": {
        "preparing",
        "ready",
        "recipe_ready",
        "waiting",
        "blocked",
        "submitted",
        "deferred",
        "submission_uncertain",
        "waiting_account_confirmation",
        "waiting_account_agent",
        "version_conflict",
    },
    "next_node": {
        "fill",
        "agent_compte",
        "letter",
        "wait",
        "prepare_submission",
        "submission",
        "draft",
        "prepare_mail",
        "send_mail",
        "__end__",
    },
    "mail_status": {
        "unavailable",
        "draft_failed",
        "waiting",
        "revision",
        "recipe_ready",
        "sent",
        "uncertain",
    },
}
QUESTION_KINDS = {
    "question",
    "challenge",
    "registration",
    "obstacle",
    "uncertain",
    "mail",
    "recipe_mail",
}


def state_summary(state):
    summary = {
        key: value
        for key, labels in STATE_LABELS.items()
        if isinstance(value := state.get(key), str) and value in labels
    }
    for key in ("cv", "letter", "evidence", "draft", "planned_action", "submission"):
        if key in state:
            summary["has_" + key] = bool(state[key])
    question = state.get("question")
    if isinstance(question, dict):
        kind = question.get("kind")
        if isinstance(kind, str) and kind in QUESTION_KINDS:
            summary["question_kind"] = kind
    if isinstance(answers := state.get("answers"), list):
        summary["answer_count"] = len(answers)
    return summary


class GraphTrace:
    def __init__(self, env):
        self.client = None
        self.project = env.get("LANGSMITH_PROJECT")
        self.parent = ContextVar("graphe2_trace", default=None)
        if (
            env.get("LANGSMITH_TRACING", "").lower() == "true"
            and env.get("LANGSMITH_API_KEY")
            and self.project
        ):
            self.client = Client(
                api_key=env["LANGSMITH_API_KEY"],
                api_url=env.get("LANGSMITH_ENDPOINT"),
                workspace_id=env.get("LANGSMITH_WORKSPACE_ID"),
            )

    def close(self):
        if self.client is not None:
            self.client.close(timeout=5)

    @staticmethod
    def publish(run, method):
        try:
            getattr(run, method)()
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "Publication de la trace LangSmith impossible"
            )

    @contextmanager
    def record(self, run):
        self.publish(run, "post")
        try:
            yield
        except GraphInterrupt:
            run.end(outputs={"interrupted": True})
            raise
        except Exception:
            run.end(error="execution_failed")
            raise
        finally:
            self.publish(run, "patch")

    def invoke(self, graph, value, config, **kwargs):
        if self.client is None:
            return graph.invoke(value, config, **kwargs)

        thread_id = config["configurable"]["thread_id"]
        run = RunTree(
            name="graphe2.applications",
            run_type="chain",
            client=self.client,
            project_name=self.project,
            inputs=state_summary(value)
            if isinstance(value, dict)
            else {"resume": True},
            extra={"metadata": {"thread_id": thread_id}},
        )
        token = self.parent.set(run)
        try:
            with self.record(run):
                result = graph.invoke(value, config, **kwargs)
                run.end(
                    outputs={
                        **state_summary(result),
                        "interrupted": bool(result.get("__interrupt__")),
                    }
                )
                return result
        finally:
            self.parent.reset(token)

    def node(self, name, function):
        @wraps(function)
        def traced(state):
            parent = self.parent.get()
            if parent is None:
                return function(state)
            run = parent.create_child(
                name,
                inputs=state_summary(state),
                extra={"metadata": parent.metadata},
            )
            with self.record(run):
                update = function(state)
                run.end(outputs=state_summary(update))
                return update

        return traced
