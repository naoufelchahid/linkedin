"""Mandat public figé à l’ouverture du tour de dépôt."""

from hashlib import sha256
from importlib.resources import files

VERSION = "submission-v13"
TEXT = (
    files(__package__)
    .joinpath("resources", VERSION + ".txt")
    .read_text(encoding="utf-8")
)
SHA256 = sha256(TEXT.encode()).hexdigest()
