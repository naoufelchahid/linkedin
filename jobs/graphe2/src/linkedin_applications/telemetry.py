"""Événements techniques au format LangSmith pour le collecteur local de recette."""

from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx


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
