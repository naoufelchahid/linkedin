"""Configuration explicite, indépendante du répertoire d’installation du package."""

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

DEFAULT_PROFILES = ("architecte solutions IA", "consultant IA", "AI engineer")


@dataclass(frozen=True)
class Config:
    root: Path
    token: str = field(default="", repr=False)
    cv: Path | None = None
    data_dir: Path | None = None
    prompt_file: Path | None = None
    profiles: tuple[str, ...] = DEFAULT_PROFILES
    limit: int = 100
    collect_seconds: float = 900
    codex_seconds: float = 180
    poll_seconds: float = 5
    actor: str = "valig/linkedin-jobs-scraper"
    langsmith_key: str = field(default="", repr=False)
    langsmith_project: str = "linkedin-discovery-pilot"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_trace_content: bool = False

    postgres_dsn: str | None = field(default=None, repr=False)

    def __post_init__(self):
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError("discovery_limit_must_be_between_1_and_100")
        if not self.profiles or any(not isinstance(p, str) or not p.strip() for p in self.profiles):
            raise ValueError("discovery_profiles_invalid")
        if len(set(self.profiles)) != len(self.profiles):
            raise ValueError("discovery_profiles_invalid")
        for value, allow_zero in (
            (self.collect_seconds, True),
            (self.codex_seconds, False),
            (self.poll_seconds, False),
        ):
            if not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
                raise ValueError("discovery_timeout_invalid")

    @classmethod
    def load(cls, root=None, env_file=None):
        root = Path(root or os.environ.get("DISCOVERY_HOME") or Path.cwd()).resolve()
        env_file = Path(env_file).resolve() if env_file else root / ".env"
        if env_file.exists():
            env_file.chmod(0o600)
        values = {**dotenv_values(env_file), **os.environ}
        profiles = (
            json.loads(values["DISCOVERY_PROFILES"])
            if values.get("DISCOVERY_PROFILES")
            else list(DEFAULT_PROFILES)
        )
        if not isinstance(profiles, list):
            raise ValueError("discovery_profiles_must_be_json_array")

        def path(key):
            value = values.get(key)
            if not value:
                return None
            candidate = Path(value).expanduser()
            return (candidate if candidate.is_absolute() else root / candidate).resolve()

        return cls(
            root=root,
            postgres_dsn=values.get("DISCOVERY_POSTGRES_DSN") or None,
            token=values.get("APIFY_TOKEN") or "",
            cv=path("DISCOVERY_CV"),
            data_dir=path("DISCOVERY_DATA_DIR"),
            prompt_file=path("DISCOVERY_PROMPT_FILE"),
            profiles=tuple(profiles),
            limit=int(values.get("DISCOVERY_LIMIT") or 100),
            collect_seconds=float(values.get("DISCOVERY_COLLECT_SECONDS") or 900),
            codex_seconds=float(values.get("DISCOVERY_CODEX_SECONDS") or 180),
            poll_seconds=float(values.get("DISCOVERY_POLL_SECONDS") or 5),
            langsmith_key=values.get("LANGSMITH_API_KEY") or "",
            langsmith_project=values.get("LANGSMITH_PROJECT") or "linkedin-discovery-pilot",
            langsmith_endpoint=values.get("LANGSMITH_ENDPOINT")
            or "https://api.smith.langchain.com",
            langsmith_trace_content=(values.get("DISCOVERY_TRACE_CONTENT") or "false").lower()
            == "true",
        )

    @property
    def data(self):
        return (self.data_dir or self.root / "var").resolve()
