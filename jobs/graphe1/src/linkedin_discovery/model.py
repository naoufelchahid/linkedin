"""Normalisation, identité et validation des résultats privés du pilote."""

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from jsonschema import validate


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    if not isinstance(value, str):
        return ""
    parser = _Text()
    parser.feed(value)
    return " ".join(" ".join(parser.parts).split())


def canonical_url(value, *, keep_fragment=False):
    if not isinstance(value, str):
        return ""
    try:
        url = urlsplit(value.strip())
    except ValueError:
        return ""
    if url.scheme not in ("http", "https") or not url.hostname:
        return ""
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(url.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in {"trk", "trackingid", "refid"}
        ]
    )
    return urlunsplit(
        (
            url.scheme,
            url.netloc.lower(),
            url.path.rstrip("/"),
            query,
            url.fragment if keep_fragment else "",
        )
    )


def offer_url(value):
    url = canonical_url(value, keep_fragment=True)
    parts = urlsplit(url)
    if parts.hostname == "linkedin.com" or (parts.hostname or "").endswith(".linkedin.com"):
        job = re.fullmatch(r"/jobs/view/(?:[^/]+-)?(\d+)", parts.path)
        if job:
            return urlunsplit(
                ("https", "www.linkedin.com", f"/jobs/view/{job[1]}", parts.query, parts.fragment)
            )
    return url


def normalize(raw):
    """Normaliser une annonce et identifier sa page d’offre."""
    if not isinstance(raw, dict):
        raise ValueError("item_not_object")

    def first(*keys):
        return next((raw[k] for k in keys if raw.get(k) not in (None, "")), "")

    url = offer_url(raw.get("url"))
    job_id = str(first("id", "jobId", "job_id"))
    match = re.search(
        r"(?:jobs/view/(?:[^/?]*-)?|currentJobId=)(\d+)",
        str(first("url", "jobUrl", "link", "job_url")),
    )
    if match:
        job_id = match[1]
    title = plain(first("title", "jobTitle"))
    company = first("companyName", "company")
    if isinstance(company, dict):
        company = company.get("name", "")
    company = plain(company)
    description = plain(
        first("descriptionText", "description", "descriptionHtml", "jobDescription")
    )
    poster = first("poster", "jobPoster", "recruiter")
    poster = poster if isinstance(poster, dict) else {"name": str(poster)} if poster else {}
    if not poster and raw.get("recruiterName"):
        poster = {"name": str(raw["recruiterName"])}
    poster_url = canonical_url(
        poster.get("profileUrl")
        or poster.get("url")
        or first("recruiterUrl", "posterProfileUrl", "jobPosterProfileUrl")
    )
    publisher = poster_url or str(poster.get("id") or "")
    destination = canonical_url(first("applyUrl", "applicationUrl", "externalApplyUrl"))
    requisition = str(first("requisitionId", "requisition", "reference"))
    work_mode = plain(first("workplaceType", "workplace", "workMode", "workType"))
    if raw.get("isRemote") is True or raw.get("remote") is True:
        work_mode = "Remote"
    if not work_mode or not re.search(
        r"\b(remote|teletravail|hybrid|hybride|on-site|sur site)\b", fold(work_mode)
    ):
        # L'acteur renseigne parfois le télétravail uniquement dans le texte.
        # Exiger une mention positive explicite ; ne pas déduire depuis le métier.
        for sentence in re.split(r"[.!?;\n]", description):
            text = fold(sentence)
            if re.search(r"\b(no|not|without|sans|aucun|impossible|interdit|non)\b", text):
                continue
            if re.search(
                r"\b(fully remote|full remote|100\s*%\s*remote|remote work|work from home|teletravail|travail a distance)\b",
                text,
            ):
                work_mode = "Remote / télétravail (mention explicite)"
                break
    if not job_id and not url:
        raise ValueError("announcement_identity_missing")
    # Les observations sans URL restent isolées, y compris entre deux publiants.
    identity = url or dump(raw)
    offer = dict(
        key=digest(identity),
        source_id=job_id,
        url=url,
        title=title,
        company=company,
        location=plain(first("location", "jobLocation")),
        work_mode=work_mode,
        posted_at=str(
            first("postedAt", "postedDate", "publishedAt", "datePosted", "publishedDate")
        ),
        description=description,
        publisher=publisher,
        poster=poster,
        destination=destination,
        requisition=requisition,
        deposit_key=digest(dump([company, requisition, destination]))
        if requisition and destination
        else "",
    )
    return offer


def fold(text):
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)
    )


def rank(offer):
    location = fold(offer["location"])
    mode = fold(offer["work_mode"] + " " + offer["location"])
    group = (
        0
        if re.search(r"\b(casablanca|rabat)\b", location)
        else 1
        if re.search(r"\b(remote|teletravail|a distance|work from home)\b", mode)
        else 2
    )
    try:
        date = datetime.fromisoformat(offer["posted_at"].replace("Z", "+00:00"))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        timestamp = date.timestamp()
    except (ValueError, TypeError):
        timestamp = float("-inf")
    return group, -timestamp, offer["key"]


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "verdict": {"type": ["string", "null"], "enum": ["retenir", "écarter", None]},
        "incertitude": {"type": "boolean"},
        "motif": {"type": "string"},
        "mission_citee": {"type": "string"},
        "competence_cv": {"type": "string"},
        "probleme_donnees": {"type": "string"},
    },
    "required": [
        "id",
        "verdict",
        "incertitude",
        "motif",
        "mission_citee",
        "competence_cv",
        "probleme_donnees",
    ],
}


def checked_result(result, offer, cv_text):
    validate(result, SCHEMA)
    if result["id"] != offer["key"] or not result["motif"].strip():
        raise ValueError("qualification_identity_or_reason_invalid")
    if result["verdict"] is None:
        if not result["probleme_donnees"].strip():
            raise ValueError("data_problem_missing")
    elif result["probleme_donnees"]:
        raise ValueError("data_problem_with_verdict")

    def contained(quote, source):
        return (
            not quote or " ".join(quote.split()).casefold() in " ".join(source.split()).casefold()
        )

    if not contained(result["mission_citee"], offer["description"]):
        raise ValueError("mission_quote_not_in_announcement")
    if not contained(result["competence_cv"], cv_text):
        raise ValueError("skill_quote_not_in_cv")
    if (
        result["verdict"] == "retenir"
        and not result["incertitude"]
        and not (result["mission_citee"] and result["competence_cv"])
    ):
        raise ValueError("evidence_missing")
    return result
