"""Collecte Apify ; aucun POST n’est rejoué automatiquement."""

import time

import requests

from ..errors import ConnectorError


class Apify:
    TERMINAL = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}

    def __init__(self, token, actor="valig/linkedin-jobs-scraper"):
        self.actor = actor
        self.session = requests.Session()
        self.session.headers.update({"Authorization": "Bearer " + token})
        self.token = token

    def _request(self, method, path, **kwargs):
        if not self.token:
            raise ConnectorError("apify_token_missing")
        attempts = 3 if method == "GET" else 1
        for attempt in range(attempts):
            try:
                response = self.session.request(
                    method, "https://api.apify.com/v2/" + path, timeout=(10, 30), **kwargs
                )
            except requests.RequestException:
                if attempt + 1 < attempts:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise ConnectorError("apify_network_error") from None
            if not response.ok:
                if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < attempts:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise ConnectorError("apify_http_" + str(response.status_code))
            try:
                return response.json()
            except ValueError:
                raise ConnectorError("apify_invalid_json") from None

    def start(self, profile, limit, *, location="Morocco", period="r604800"):
        return self._request(
            "POST",
            "acts/" + self.actor.replace("/", "~") + "/runs",
            json={
                "keywords": profile,
                "location": location,
                "datePosted": period,
                "limit": min(100, limit),
            },
        )["data"]

    def run(self, ident):
        return self._request("GET", "actor-runs/" + ident)["data"]

    def actor_id(self, actor):
        return self._request("GET", "acts/" + actor.replace("/", "~"))["data"]["id"]

    def run_input(self, store_id):
        return self._request("GET", "key-value-stores/" + store_id + "/records/INPUT")

    def items(self, dataset_id, limit):
        result = []
        while len(result) < limit:
            batch = self._request(
                "GET",
                "datasets/" + dataset_id + "/items",
                params={
                    "format": "json",
                    "clean": "true",
                    "offset": len(result),
                    "limit": min(100, limit - len(result)),
                },
            )
            if not isinstance(batch, list):
                raise ConnectorError("apify_invalid_dataset")
            if not batch:
                break
            result.extend(batch)
        return result[:limit]
