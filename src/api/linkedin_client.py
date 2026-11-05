"""Client LinkedIn minimal pour publier et récupérer les statistiques.

La publication est volontairement protégée : ``create_text_post`` ne fait qu'un
dry-run tant que ``confirm=True`` n'est pas fourni explicitement.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import requests
from dotenv import load_dotenv

if __package__:
    from .publication_archive import read_publishable_text, publish_archived, archive_pending
else:
    from publication_archive import read_publishable_text, publish_archived, archive_pending


load_dotenv()

DEFAULT_API_VERSION = "202608"
DEFAULT_TIMEOUT_SECONDS = 20
SUPPORTED_IMAGE_MIME_TYPES = {"image/gif", "image/jpeg", "image/png"}
SUPPORTED_MEMBER_METRICS = (
    "IMPRESSION",
    "MEMBERS_REACHED",
    "RESHARE",
    "REACTION",
    "COMMENT",
    "POST_SAVE",
    "POST_SEND",
    "LINK_CLICKS",
    "PREMIUM_CTA_CLICKS",
    "FOLLOWER_GAINED_FROM_CONTENT",
    "PROFILE_VIEW_FROM_CONTENT",
)


class LinkedInAPIError(RuntimeError):
    """Erreur HTTP LinkedIn avec un message exploitable sans exposer le jeton."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class LinkedInAPI:
    def __init__(
        self,
        access_token: str | None = None,
        author_urn: str | None = None,
        api_version: str | None = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
    ) -> None:
        self.access_token = access_token or os.getenv("LINKEDIN_ACCESS_TOKEN")
        self.author_urn = (
            author_urn
            or os.getenv("LINKEDIN_AUTHOR_URN")
            or os.getenv("LINKEDIN_PERSON_URN")  # Compatibilité avec l'ancien nom.
        )
        self.api_version = api_version or os.getenv(
            "LINKEDIN_API_VERSION", DEFAULT_API_VERSION
        )
        self.timeout = timeout
        self.session = session or requests.Session()

        if not self.access_token:
            raise ValueError("LINKEDIN_ACCESS_TOKEN est absent.")
        if not re.fullmatch(r"\d{6}", self.api_version):
            raise ValueError("LINKEDIN_API_VERSION doit être au format YYYYMM.")

        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": self.api_version,
        }

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        """Exécute une requête avec timeout et reprises limitées sur 429/5xx."""
        kwargs.setdefault("headers", self.headers)
        kwargs.setdefault("timeout", self.timeout)

        response: requests.Response | None = None
        # Un POST de publication peut avoir réussi malgré un timeout/5xx.
        attempts = 1 if method == 'POST' and url == 'https://api.linkedin.com/rest/posts' else 3
        for attempt in range(attempts):
            try:
                response = self.session.request(method, url, **kwargs)
            except requests.RequestException as exc:
                if attempt == attempts - 1:
                    raise LinkedInAPIError(f"Erreur réseau LinkedIn: {exc}") from exc
                time.sleep(2**attempt)
                continue

            if response.status_code != 429 and response.status_code < 500:
                break
            if attempt < attempts - 1:
                retry_after = response.headers.get("Retry-After")
                delay = min(float(retry_after), 10) if retry_after else 2**attempt
                time.sleep(delay)

        assert response is not None
        if not response.ok:
            try:
                error = response.json()
                detail = error.get("message") or error.get("code") or response.reason
            except ValueError:
                detail = response.text[:500] or response.reason
            raise LinkedInAPIError(
                f"LinkedIn HTTP {response.status_code}: {detail}", response.status_code
            )
        return response

    def check_auth(self) -> dict[str, Any]:
        """Vérifie le jeton via l'endpoint OpenID Connect en lecture seule."""
        response = self._request("GET", "https://api.linkedin.com/v2/userinfo")
        return response.json()

    def build_text_post_payload(self, text_content: str) -> dict[str, Any]:
        """Construit et valide le payload d'un post texte."""
        if not self.author_urn:
            raise ValueError(
                "LINKEDIN_AUTHOR_URN (ou LINKEDIN_PERSON_URN) est absent."
            )
        if not self.author_urn.startswith(("urn:li:person:", "urn:li:organization:")):
            raise ValueError("L'URN auteur LinkedIn est invalide.")
        text_content = text_content.strip()
        if not text_content:
            raise ValueError("Le contenu du post est vide.")

        return {
            "author": self.author_urn,
            "commentary": text_content,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

    def build_image_post_payload(
        self, text_content: str, image_urn: str, alt_text: str
    ) -> dict[str, Any]:
        """Construit le payload Posts API pour une publication avec image."""
        if not image_urn.startswith("urn:li:image:"):
            raise ValueError("L'URN de l'image LinkedIn est invalide.")
        alt_text = alt_text.strip()
        if not alt_text:
            raise ValueError("Le texte alternatif de l'image est obligatoire.")
        if len(alt_text) > 4086:
            raise ValueError("Le texte alternatif ne peut pas dépasser 4 086 caractères.")

        payload = self.build_text_post_payload(text_content)
        payload["content"] = {
            "media": {
                "altText": alt_text,
                "id": image_urn,
            }
        }
        return payload

    def _validate_image_path(self, image_path: Path) -> str:
        """Valide localement le fichier et renvoie son type MIME."""
        if not image_path.is_file():
            raise ValueError(f"Image introuvable: {image_path}")
        mime_type, _ = mimetypes.guess_type(image_path.name)
        if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
            supported = ", ".join(sorted(SUPPORTED_IMAGE_MIME_TYPES))
            raise ValueError(f"Format d'image non pris en charge ({supported}).")
        return mime_type

    def initialize_image_upload(self) -> dict[str, str]:
        """Initialise un upload Images API et renvoie l'URL et l'URN."""
        if not self.author_urn:
            raise ValueError(
                "LINKEDIN_AUTHOR_URN (ou LINKEDIN_PERSON_URN) est absent."
            )
        if not self.author_urn.startswith(("urn:li:person:", "urn:li:organization:")):
            raise ValueError("L'URN auteur LinkedIn est invalide.")
        response = self._request(
            "POST",
            "https://api.linkedin.com/rest/images?action=initializeUpload",
            json={"initializeUploadRequest": {"owner": self.author_urn}},
        )
        try:
            value = response.json()["value"]
            upload_url = value["uploadUrl"]
            image_urn = value["image"]
        except (KeyError, TypeError, ValueError) as exc:
            raise LinkedInAPIError(
                "Réponse LinkedIn invalide lors de l'initialisation de l'image."
            ) from exc
        if not upload_url or not image_urn.startswith("urn:li:image:"):
            raise LinkedInAPIError(
                "LinkedIn n'a pas renvoyé une URL et un URN d'image valides."
            )
        return {"upload_url": upload_url, "image_urn": image_urn}

    def upload_image(self, image_path: Path) -> str:
        """Transfère une image vers LinkedIn et renvoie son URN média."""
        image_path = Path(image_path)
        mime_type = self._validate_image_path(image_path)
        upload = self.initialize_image_upload()
        upload_headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": mime_type,
        }
        image_bytes = image_path.read_bytes()
        self._request(
            "PUT",
            upload["upload_url"],
            headers=upload_headers,
            data=image_bytes,
        )
        return upload["image_urn"]

    def create_text_post(
        self, text_content: str, *, confirm: bool = False
    ) -> dict[str, Any]:
        """Prépare un post ou le publie uniquement après confirmation explicite."""
        payload = self.build_text_post_payload(text_content)
        if not confirm:
            return {"dry_run": True, "payload": payload}

        response = self._request(
            "POST", "https://api.linkedin.com/rest/posts", json=payload
        )
        return {
            "dry_run": False,
            "post_urn": response.headers.get("x-restli-id"),
            "status_code": response.status_code,
        }

    def create_image_post(
        self,
        text_content: str,
        image_path: Path,
        alt_text: str,
        *,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Prépare ou publie un post avec image après confirmation explicite."""
        image_path = Path(image_path)
        self._validate_image_path(image_path)
        alt_text = alt_text.strip()
        if not alt_text:
            raise ValueError("Le texte alternatif de l'image est obligatoire.")
        if len(alt_text) > 4086:
            raise ValueError("Le texte alternatif ne peut pas dépasser 4 086 caractères.")

        if not confirm:
            payload = self.build_text_post_payload(text_content)
            payload["content"] = {
                "media": {
                    "altText": alt_text,
                    "id": "urn:li:image:<uploadé-lors-de-la-publication>",
                }
            }
            return {
                "dry_run": True,
                "image_path": str(image_path),
                "payload": payload,
            }

        image_urn = self.upload_image(image_path)
        payload = self.build_image_post_payload(text_content, image_urn, alt_text)
        response = self._request(
            "POST", "https://api.linkedin.com/rest/posts", json=payload
        )
        return {
            "dry_run": False,
            "image_urn": image_urn,
            "post_urn": response.headers.get("x-restli-id"),
            "status_code": response.status_code,
        }

    def get_social_actions(self, post_urn: str) -> dict[str, Any]:
        """Récupère le résumé likes/commentaires d'un post."""
        encoded_urn = quote(post_urn, safe="")
        response = self._request(
            "GET", f"https://api.linkedin.com/rest/socialActions/{encoded_urn}"
        )
        return response.json()

    def get_member_post_stats(
        self,
        post_urn: str | None = None,
        metrics: Iterable[str] = ("IMPRESSION", "REACTION", "COMMENT", "RESHARE"),
    ) -> dict[str, Any]:
        """Récupère les vraies statistiques créateur, agrégées ou par post."""
        results: dict[str, Any] = {}
        for metric in metrics:
            metric = metric.upper()
            if metric not in SUPPORTED_MEMBER_METRICS:
                raise ValueError(f"Métrique LinkedIn non prise en charge: {metric}")

            params: dict[str, str] = {
                "q": "entity" if post_urn else "me",
                "queryType": metric,
                "aggregation": "TOTAL",
            }
            if post_urn:
                if post_urn.startswith("urn:li:ugcPost:"):
                    params["entity"] = f"(ugc:{post_urn})"
                elif post_urn.startswith("urn:li:share:"):
                    params["entity"] = f"(share:{post_urn})"
                else:
                    raise ValueError("Le post doit être un URN share ou ugcPost.")

            response = self._request(
                "GET",
                "https://api.linkedin.com/rest/memberCreatorPostAnalytics",
                params=params,
            )
            results[metric] = response.json()
        return results

    def get_post_stats(self, post_urn: str) -> dict[str, Any]:
        """Alias rétrocompatible vers les statistiques créateur complètes."""
        return self.get_member_post_stats(post_urn)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tester le client LinkedIn officiel")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("auth", help="Vérifier le jeton (lecture seule)")
    subparsers.add_parser("archive", help="Reprendre les exports locaux sans publication ni appel API")

    stats = subparsers.add_parser("stats", help="Récupérer les statistiques")
    stats.add_argument("--post-urn", help="URN share/ugcPost; sinon stats agrégées")
    stats.add_argument(
        "--metrics",
        nargs="+",
        default=["IMPRESSION", "REACTION", "COMMENT", "RESHARE"],
    )

    dry_run = subparsers.add_parser("dry-run", help="Valider un payload sans publier")
    dry_run.add_argument("--file", type=Path, required=True)
    dry_run.add_argument("--image", type=Path, help="Image PNG, JPEG ou GIF")
    dry_run.add_argument("--alt-file", type=Path, help="Fichier contenant le texte alternatif")
    dry_run.add_argument("--alt-text", help="Texte alternatif de l'image")

    publish = subparsers.add_parser("publish", help="Publier un brouillon validé")
    publish.add_argument("--file", type=Path, required=True)
    publish.add_argument("--image", type=Path, help="Image PNG, JPEG ou GIF")
    publish.add_argument("--alt-file", type=Path, help="Fichier contenant le texte alternatif")
    publish.add_argument("--alt-text", help="Texte alternatif de l'image")
    publish.add_argument(
        "--confirm-publish",
        action="store_true",
        help="Confirmation explicite obligatoire pour envoyer le POST",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        if args.command == 'archive':
            print(json.dumps(archive_pending(), ensure_ascii=False, indent=2))
            return 0
        api = LinkedInAPI()
        if args.command == "auth":
            profile = api.check_auth()
            print(json.dumps({"ok": True, "subject": profile.get("sub")}, indent=2))
        elif args.command == "stats":
            print(
                json.dumps(
                    api.get_member_post_stats(args.post_urn, args.metrics), indent=2
                )
            )
        else:
            text = read_publishable_text(args.file)
            if args.command == "publish" and not args.confirm_publish:
                raise ValueError("Ajoutez --confirm-publish après validation humaine.")
            if args.alt_file and args.alt_text:
                raise ValueError("Utilisez soit --alt-file, soit --alt-text, pas les deux.")
            if (args.alt_file or args.alt_text) and not args.image:
                raise ValueError("--alt-file et --alt-text nécessitent --image.")
            if args.image:
                if not args.alt_file and not args.alt_text:
                    raise ValueError(
                        "Une image nécessite --alt-file ou --alt-text."
                    )
                alt_text = (
                    args.alt_file.read_text(encoding="utf-8")
                    if args.alt_file
                    else args.alt_text
                )
                result = (publish_archived(api, text, args.image, alt_text)
                          if args.command == 'publish' else
                          api.create_image_post(text, args.image, alt_text, confirm=False))
            else:
                result = (publish_archived(api, text) if args.command == 'publish' else
                          api.create_text_post(text, confirm=False))
            print(json.dumps(result, indent=2, ensure_ascii=False))
    except (LinkedInAPIError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
