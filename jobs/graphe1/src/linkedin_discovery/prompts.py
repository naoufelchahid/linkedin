"""Prompt embarqué, indépendant des documents de conception et du checkout."""

from importlib.resources import files
from pathlib import Path


def qualification_prompt(root=None, *, prompt_file=None):
    # root est conservé pour les anciens appelants ; le runtime ne lit plus Markdown.
    text = (
        Path(prompt_file).read_text(encoding="utf-8")
        if prompt_file
        else files("linkedin_discovery.resources")
        .joinpath("qualification.txt")
        .read_text(encoding="utf-8")
    )
    if not text.strip():
        raise ValueError("qualification_prompt_missing")
    return text.rstrip("\n")
