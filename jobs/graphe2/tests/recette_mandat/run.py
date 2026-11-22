"""Trois tours Codex sur deux formulaires synthétiques, dans un Chrome jetable."""

import argparse
import asyncio
import tempfile
from pathlib import Path

from linkedin_applications.browser import Browsentic


async def scenario(args, directory, slug, city, expected):
    proof = directory / "receptions.jsonl"
    proof.touch()
    command = [
        "node",
        str(Path(__file__).with_name("portail.cjs").resolve()),
        args.playwright,
        slug,
        str(proof),
        args.chrome,
    ]
    browser = Browsentic(directory, command, {})
    title = {"atelier": "Analyste Atelier", "bureau": "Consultant Bureau"}[slug]
    url = "https://recette.invalid/" + slug
    state = {
        "dossier": slug,
        "offer": {"url": url, "title": title, "company": "Recette"},
        "cv_text": "Nom confirmé : Camille Exemple. Travail à distance : Oui.",
        "answers": {"Ville de rattachement": city} if city else {},
    }
    result = await browser.agent_form(state, [])
    assert result["kind"] == expected, (slug, result["kind"], expected)
    assert len(proof.read_text().splitlines()) == int(expected != "question")
    if expected == "submitted":
        assert "A-237" in result["receipt"]["evidence"], "reçu de recette absent"
    if expected == "question":
        assert (
            not result["transmission_attempted"] and "ville" in result["text"].lower()
        )
    if expected == "unknown":
        assert result["transmission_attempted"] and "receipt" not in result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--playwright", required=True, help="Module Node Playwright installé"
    )
    parser.add_argument("--chrome", required=True)
    args = parser.parse_args()
    for slug, city, expected in [
        ("atelier", "", "question"),
        ("atelier", "Rabat", "submitted"),
        ("bureau", "Rabat", "unknown"),
    ]:
        with tempfile.TemporaryDirectory() as directory:
            await scenario(args, Path(directory), slug, city, expected)
            print(slug, expected, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
