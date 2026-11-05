"""Configuration locale ; aucun secret n'est écrit dans les journaux."""
from dataclasses import dataclass
from pathlib import Path
import os
import shutil
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Config:
    root: Path = ROOT
    token: str = ""
    chat_id: int = 0
    user_id: int = 0
    enabled: bool = True
    submit_enabled: bool = False

    @classmethod
    def load(cls, root=ROOT):
        values = {**dotenv_values(root / '.env.candidatures'), **os.environ}
        return cls(root=root, token=values.get('TELEGRAM_BOT_TOKEN', '') or '',
                   chat_id=int(values.get('TELEGRAM_CHAT_ID', '') or 0),
                   user_id=int(values.get('TELEGRAM_USER_ID', '') or 0),
                   enabled=values.get('CANDIDATURES_ENABLED', 'true').lower() == 'true',
                   submit_enabled=values.get('CANDIDATURES_SUBMIT_ENABLED', 'false').lower() == 'true')

    @property
    def data(self):
        path = self.root / 'data/candidatures'
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
        return path

    @property
    def cv(self):
        return self.root / 'output/pdf/Naoufel_Chahid_CV_Francais_Candidatures.pdf'

    @property
    def ready(self):
        return bool(self.token and self.chat_id > 0 and self.user_id > 0)

    @property
    def codex(self):
        return shutil.which('codex')
