"""US Census Geocoder client with a content-keyed disk cache (BACKEND_PLAN.md 2.7).

Every request is described by a plain dict (endpoint, params, body); its sha256 is the
cache key and the raw response text is stored under cache/geocode/<key>.json together
with the request. A cache hit never touches the network, so a run from the committed
cache is offline and byte-identical. `offline=True` turns a cache miss into an error
instead of a network call (tests, CI).

Three endpoints are used:
- addressbatch (geographies): one call for all rows -> match status, coordinates, block
  GEOIDs. The batch output carries no place codes, so:
- coordinates (geographies): one call per matched point -> state, county, incorporated
  place and county subdivision polygons that contain it.
- onelineaddress (locations): retry for rows the batch did not match.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from pathlib import Path
from typing import Any

from navigator import settings

BASE = "https://geocoding.geo.census.gov/geocoder"
BENCHMARK = "Public_AR_Current"
VINTAGE = "Current_Current"
LAYERS = "States,Counties,Incorporated Places,County Subdivisions"
BATCH_COLUMNS = ["id", "input_address", "match", "match_type", "matched_address",
                 "lonlat", "tiger_line_id", "side", "state", "county", "tract", "block"]


class CacheMiss(RuntimeError):
    """Offline mode and the request is not in cache/geocode/."""


def cache_dir() -> Path:
    return settings.REPO_ROOT / "cache" / "geocode"


def request_key(request: dict[str, Any]) -> str:
    blob = json.dumps(request, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Client:
    def __init__(self, offline: bool = False, cache: Path | None = None,
                 timeout: float = 600.0, retries: int = 3):
        self.offline = offline
        self.cache = cache or cache_dir()
        self.timeout = timeout
        self.retries = retries
        self.network_calls = 0
        self.cache_hits = 0
        self._http = None

    # ------------------------------------------------------------------ cache

    def _fetch(self, request: dict[str, Any]) -> str:
        key = request_key(request)
        path = self.cache / f"{key}.json"
        if path.is_file():
            self.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["response"]
        if self.offline:
            raise CacheMiss(f"geocode request not cached ({key[:12]}): {request['endpoint']}")
        text = self._send(request)
        self.network_calls += 1
        self.cache.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump({"request": request, "response": text}, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        tmp.replace(path)
        return text

    def _send(self, request: dict[str, Any]) -> str:
        import httpx

        if self._http is None:
            self._http = httpx.Client(timeout=self.timeout, follow_redirects=True)
        url = f"{BASE}/{request['endpoint']}"
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                if "body" in request:
                    files = {"addressFile": ("addresses.csv", request["body"].encode("utf-8"), "text/csv")}
                    resp = self._http.post(url, data=request["params"], files=files)
                else:
                    resp = self._http.get(url, params=request["params"])
                resp.raise_for_status()
                if request["params"].get("format") == "json":
                    json.loads(resp.text)  # never cache a truncated or HTML error page
                return resp.text
            except Exception as exc:  # noqa: BLE001 - network errors are retried, then raised
                last = exc
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"Census Geocoder request failed after {self.retries} tries: {last}")

    # -------------------------------------------------------------- endpoints

    def batch(self, rows: list[tuple[str, str, str, str, str]]) -> dict[str, dict[str, str]]:
        """rows: (id, street, city, state, zip) -> {id: parsed batch row}."""
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        for row in rows:
            writer.writerow(row)
        request = {"endpoint": "geographies/addressbatch",
                   "params": {"benchmark": BENCHMARK, "vintage": VINTAGE},
                   "body": buf.getvalue()}
        return parse_batch(self._fetch(request))

    def coordinates(self, lon: str, lat: str) -> dict[str, list[dict[str, Any]]]:
        request = {"endpoint": "geographies/coordinates",
                   "params": {"x": lon, "y": lat, "benchmark": BENCHMARK, "vintage": VINTAGE,
                              "layers": LAYERS, "format": "json"}}
        return json.loads(self._fetch(request))["result"]["geographies"]

    def oneline(self, address: str) -> list[dict[str, Any]]:
        request = {"endpoint": "locations/onelineaddress",
                   "params": {"address": address, "benchmark": BENCHMARK, "format": "json"}}
        return json.loads(self._fetch(request))["result"]["addressMatches"]


def parse_batch(text: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for rec in csv.reader(io.StringIO(text)):
        if not rec:
            continue
        rec = rec + [""] * (len(BATCH_COLUMNS) - len(rec))
        out[rec[0]] = dict(zip(BATCH_COLUMNS, rec))
    return out
