"""Paramètres publics d'un cycle de découverte."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Search:
    profiles: list[str]
    location: str
    period: str
    limit: int

    def __post_init__(self):
        if (
            not isinstance(self.profiles, list)
            or not self.profiles
            or any(not isinstance(p, str) or not p.strip() for p in self.profiles)
        ):
            raise ValueError("Mots-clés requis")
        if len(set(self.profiles)) != len(self.profiles):
            raise ValueError("Mots-clés en double")
        if not isinstance(self.location, str) or not self.location.strip():
            raise ValueError("Lieu requis")
        if self.period not in ("r86400", "r604800", "r2592000"):
            raise ValueError("Période invalide")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError("Limite attendue entre 1 et 100")
