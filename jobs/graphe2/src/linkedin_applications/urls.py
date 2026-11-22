"""Identité des pages du navigateur et compatibilité des dossiers SQLite."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


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
            if not k.lower().startswith("utm_")
            and k.lower() not in {"trk", "trackingid", "refid"}
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
    if parts.hostname == "linkedin.com" or (parts.hostname or "").endswith(
        ".linkedin.com"
    ):
        job = re.fullmatch(r"/jobs/view/(?:[^/]+-)?(\d+)", parts.path)
        if job:
            return urlunsplit(
                (
                    "https",
                    "www.linkedin.com",
                    f"/jobs/view/{job[1]}",
                    parts.query,
                    parts.fragment,
                )
            )
    return url
