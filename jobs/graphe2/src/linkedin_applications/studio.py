"""Expose la topologie utilisée par le worker sans transmettre de candidature."""

from .graph import build


def inspection(state):
    raise RuntimeError("Vue de consultation. Lancer un lot depuis le tableau de bord.")


class InspectionWorkflow:
    def __getattr__(self, name):
        return inspection


graph = build(InspectionWorkflow(), checkpointer=None)
