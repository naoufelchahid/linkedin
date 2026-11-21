"""Codes d’erreur stables, sans contenu privé ni détails réseau bruts."""


class ConnectorError(RuntimeError):
    """Échec d’un fournisseur ou d’une pièce source."""
