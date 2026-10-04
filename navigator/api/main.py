"""FastAPI app (BACKEND_PLAN.md 3). Run with `python -m navigator api`.

Serves precomputed JSON from outputs/; no LLM in any request path (golden rule 5). The
only computation is the deterministic engine (`evaluate_address`) for an as_of other
than the precomputed one and for POST /lookup with user-entered facts. Missing files
give HTTP 503 with the command that produces them, never an empty "no rule applies".
Every response carries as_of, generated_at and the disclaimer (golden rule 10).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import queue
import tempfile
import threading
from typing import Any

from fastapi import Depends, FastAPI, Path, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from navigator.api import service as svc
from navigator.api.models import (
    AuditResponse,
    ChangeResponse,
    ChangesResponse,
    ErrorResponse,
    EvalResponse,
    HealthResponse,
    IngestRequest,
    LookupRequest,
    LookupResult,
    ResolveResponse,
    Role,
    RuleDetail,
    SearchResponse,
    SnapshotResponse,
    SnapshotsResponse,
    TimelineResponse,
)
from navigator.ingest import incremental
from navigator.api.store import PRODUCERS, DataUnavailable, Store, now_utc

ERRORS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}

# localhost / 127.0.0.1 on any port (Vite, Next, ...); deployed origins via env var
LOCAL_ORIGINS = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"


def _error(status: int, detail: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content=jsonable_encoder(
        {"detail": detail, "disclaimer": svc.disclaimer(), "as_of": svc.default_as_of()}))


_INGEST_LOCK = threading.Lock()   # the run rewrites every output and is not re-entrant


def _cleanup(path: str | None) -> None:
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def create_app(store: Store | None = None) -> FastAPI:
    app = FastAPI(
        title="Rental Housing Law Navigator API",
        version="0.1.0",
        description="Precomputed, cited answers on which rental housing rules apply to a sample "
                    "address on a date. Not legal advice.",
    )
    app.state.store = store or Store()
    extra = [o.strip() for o in os.environ.get("NAVIGATOR_CORS_ORIGINS", "").split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=extra, allow_origin_regex=LOCAL_ORIGINS,
                       allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"])

    @app.exception_handler(DataUnavailable)
    async def _unavailable(_: Request, exc: DataUnavailable):
        return _error(503, exc.message)

    @app.exception_handler(svc.NotFound)
    async def _not_found(_: Request, exc: svc.NotFound):
        return _error(404, str(exc))

    @app.exception_handler(svc.BadRequest)
    async def _bad(_: Request, exc: svc.BadRequest):
        return _error(422, str(exc))

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError):
        return _error(422, exc.errors())

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return _error(exc.status_code, exc.detail)

    _routes(app)
    return app


def get_store(request: Request) -> Store:
    return request.app.state.store


def _envelope(as_of: str | None = None, generated_at: str | None = None) -> dict[str, Any]:
    return {"as_of": as_of or svc.default_as_of(), "generated_at": generated_at, "disclaimer": svc.disclaimer()}


def _routes(app: FastAPI) -> None:  # noqa: C901 (route table)

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    def health(store: Store = Depends(get_store)):
        files = {n: store.exists(n) for n in PRODUCERS}
        required = ("rules_internal.json", "parcels.json", "lookups_internal.json", "docs.jsonl")
        ok = all(files[n] for n in required) and not store.is_stub()
        counts: dict[str, int | None] = {"rules": None, "addresses": None}
        if ok:
            try:
                counts = {"rules": len(store.rules()), "addresses": len(store.parcels())}
            except DataUnavailable:
                ok = False
        return {**_envelope(generated_at=store.mtime("lookups_internal.json")),
                "status": "ok" if ok else "degraded", "stub_outputs": store.is_stub(), "files": files, **counts}

    @app.get("/resolve", response_model=ResolveResponse, responses=ERRORS, tags=["address"])
    def resolve(lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180),
                store: Store = Depends(get_store)):
        """Nearest sample address within 30 m (offline, from parcels.json coordinates)."""
        p, d = svc.nearest(store, lat, lng)
        base = {**_envelope(generated_at=store.mtime("parcels.json")), "lat": lat, "lng": lng,
                "max_distance_m": svc.MAX_RESOLVE_M}
        if p is None or d is None or d > svc.MAX_RESOLVE_M:
            return {**base, "state": None, "city": None, "nearest_address_id": None, "distance_m": None,
                    "note": f"no sample address within {svc.MAX_RESOLVE_M:g} m; jurisdiction is resolved "
                            "only for sample addresses (no network lookups)"}
        aid = str(p["address_id"])
        return {**base, "state": p.get("state"), "city": p.get("city"), "nearest_address_id": aid,
                "distance_m": round(d, 1), "address": svc.address_line(p, store.zips().get(aid))}

    @app.get("/search", response_model=SearchResponse, responses=ERRORS, tags=["address"])
    def search(q: str = Query(min_length=1, max_length=200), limit: int = Query(20, ge=1, le=100),
               store: Store = Depends(get_store)):
        """Sample addresses by street text, city or ZIP. A ZIP only moves the map."""
        match, hits = svc.search(store, q, limit)
        note = "ZIP matches sample addresses only; a ZIP alone does not decide the legal city" \
            if match == "zip" else None
        return {**_envelope(generated_at=store.mtime("parcels.json")), "query": q, "match": match,
                "note": note, "results": hits}

    @app.get("/lookup", response_model=LookupResult, responses=ERRORS, tags=["lookup"])
    def lookup_get(address_id: str, as_of: str | None = None, role: Role = "tenant",
                   lang: str = Query("en", pattern=r"^[a-z]{2}$"), store: Store = Depends(get_store)):
        """Locus panel (rights label) for a sample address. Precomputed for the default as_of; other dates run
        the deterministic engine."""
        store.require_real()
        as_of = svc.parse_as_of(as_of, svc.default_as_of())
        parcel = svc.get_parcel(store, address_id)
        pre = svc.precomputed_rows(store, address_id, as_of)
        if pre is not None:
            rows, generated_at = pre
            computed = "precomputed"
        else:
            rows, generated_at, computed = svc.live_rows(store, parcel, as_of), now_utc(), "live"
        return svc.build_lookup(store, parcel, rows, as_of=as_of, role=role, lang=lang,
                                computed=computed, generated_at=generated_at)

    @app.post("/lookup", response_model=LookupResult, responses=ERRORS, tags=["lookup"])
    def lookup_post(body: LookupRequest, store: Store = Depends(get_store)):
        """Live engine run with user-entered building facts (deterministic, no LLM). The address
        is a sample address_id or the sample address within 30 m of lat/lng."""
        store.require_real()
        as_of = svc.parse_as_of(body.as_of, svc.default_as_of())
        if body.address_id:
            parcel = svc.get_parcel(store, body.address_id)
        elif body.lat is not None and body.lng is not None:
            p, d = svc.nearest(store, body.lat, body.lng)
            if p is None or d is None or d > svc.MAX_RESOLVE_M:
                raise svc.NotFound(f"no sample address within {svc.MAX_RESOLVE_M:g} m of ({body.lat}, {body.lng}); "
                                   "the legal jurisdiction cannot be resolved offline")
            parcel = p
        else:
            raise svc.BadRequest("give address_id, or lat and lng")
        facts = body.facts.model_dump()
        if facts.get("year_built") is not None and facts["year_built"] > dt.date.today().year:
            raise svc.BadRequest("year_built cannot be in the future")
        merged, used = svc.merge_facts(parcel, facts)
        rows = svc.live_rows(store, merged, as_of)
        return svc.build_lookup(store, merged, rows, as_of=as_of, role=body.role, lang=body.lang,
                                computed="live", generated_at=now_utc(), user_facts=used)

    @app.get("/rule/{team_rule_id}", response_model=RuleDetail, responses=ERRORS, tags=["rules"])
    def rule(team_rule_id: str = Path(), as_of: str | None = None, store: Store = Depends(get_store)):
        """Rule record, the source text around its quote, and span offsets (code points and UTF-16)."""
        as_of = svc.parse_as_of(as_of, svc.default_as_of())
        r = store.rule(team_rule_id)
        if r is None:
            raise svc.NotFound(f"rule {team_rule_id!r} is not in rules_internal.json")
        return svc.rule_detail(store, r, as_of)

    @app.get("/timeline", response_model=TimelineResponse, responses=ERRORS, tags=["time"])
    def timeline(address_id: str, store: Store = Depends(get_store)):
        """Dates on which any result changes for this address."""
        store.require_real()
        svc.get_parcel(store, address_id)
        data = store.timeline()
        return {**_envelope(generated_at=store.mtime("timeline.json")), "address_id": address_id,
                "dates": data.get("dates", []), "timeline": data.get("timeline", {}).get(address_id, [])}

    @app.get("/snapshots", response_model=SnapshotsResponse,
             responses={**ERRORS, 200: {"model": SnapshotsResponse}}, tags=["time"])
    def snapshots(store: Store = Depends(get_store)):
        """Per key date, per address, per category: the winning result (powers the date slider)."""
        store.require_real()

        def build() -> bytes:
            data = store.snapshots()
            payload = {**_envelope(generated_at=store.mtime("snapshots.json")),
                       "dates": data.get("dates", []), "snapshots": data.get("snapshots", {})}
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        body = store.cached("snapshots_payload", ("snapshots.json",), build)
        return Response(content=body, media_type="application/json")

    @app.get("/snapshots/{date}", response_model=SnapshotResponse, responses=ERRORS, tags=["time"])
    def snapshot(date: str, store: Store = Depends(get_store)):
        store.require_real()
        data = store.snapshots()
        snap = data.get("snapshots", {}).get(date)
        if snap is None:
            raise svc.NotFound(f"{date} is not a key date; key dates: {', '.join(data.get('dates', []))}")
        return {**_envelope(as_of=date, generated_at=store.mtime("snapshots.json")), "date": date,
                "snapshot": snap}

    @app.get("/changes", response_model=ChangesResponse, responses=ERRORS, tags=["changes"])
    def changes(store: Store = Depends(get_store)):
        """Change tests T1..T5: affected and conflict-flagged addresses, checks and notes."""
        store.require_real()
        tests, internal = svc.change_tests(store)
        gen = (internal or {}).get("generated_at") or store.mtime("changes.json")
        return {**_envelope(generated_at=gen), "mapping_reviewed": (internal or {}).get("mapping_reviewed"),
                "tests": tests}

    @app.get("/changes/{test_id}", response_model=ChangeResponse, responses=ERRORS, tags=["changes"])
    def change(test_id: str, store: Store = Depends(get_store)):
        store.require_real()
        tests, internal = svc.change_tests(store)
        found = [t for t in tests if t["test_id"] == test_id]
        if not found:
            raise svc.NotFound(f"test {test_id!r} is not in changes.json")
        gen = (internal or {}).get("generated_at") or store.mtime("changes.json")
        return {**_envelope(generated_at=gen), "mapping_reviewed": (internal or {}).get("mapping_reviewed"),
                "test": found[0]}

    @app.get("/audit", response_model=AuditResponse, responses=ERRORS, tags=["rules"])
    def audit(team_rule_id: str, store: Store = Depends(get_store)):
        """Audit trail for one rule: ingest, extraction (model, prompt version) and verify lines."""
        r = store.rule(team_rule_id)
        if r is None:
            raise svc.NotFound(f"rule {team_rule_id!r} is not in rules_internal.json")
        return {**_envelope(generated_at=store.mtime("audit.jsonl")), "team_rule_id": team_rule_id,
                "provenance": r.provenance, "entries": svc.audit_for(store, r),
                "note": "verify lines are matched by team_rule_id and this rule's candidate ids; "
                        "extract lines by chunk id; ingest lines by document id"}

    @app.get("/eval", response_model=EvalResponse, responses=ERRORS, tags=["meta"])
    def eval_report(store: Store = Depends(get_store)):
        """Latest self-evaluation report (team harness; the pack has no official scoring script)."""
        return {**_envelope(generated_at=store.mtime("eval_latest.txt")),
                "label": "Self-evaluation (team harness; the pack has no official scoring script)",
                "report": store.eval_report()}

    @app.post("/ingest", tags=["ingest"],
              responses={200: {"content": {"application/x-ndjson": {}},
                               "description": "one JSON progress event per line, then a final "
                                              "'finished' or 'failed' line"},
                         400: {"model": ErrorResponse}, 403: {"model": ErrorResponse},
                         409: {"model": ErrorResponse}})
    def ingest(body: IngestRequest):
        """Add one document in corpus format and re-run extract > verify > lookups > changes.

        The only request path that may call the LLM (CLAUDE.md golden rule 5 exception). The
        header is validated before anything is written; one run at a time."""
        if os.environ.get("NAVIGATOR_DISABLE_INGEST", "").strip() not in ("", "0"):
            return _error(403, "POST /ingest is disabled on this deployment (NAVIGATOR_DISABLE_INGEST); "
                               "use `python -m navigator ingest-doc <path>` locally")
        if not _INGEST_LOCK.acquire(blocking=False):
            return _error(409, "another document is being ingested; try again when it finishes")
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix=".txt", prefix="ingest-")
            with os.fdopen(fd, "wb") as fh:
                fh.write(body.text.encode("utf-8"))
            incremental.validate_file(tmp)
        except incremental.IngestError as exc:
            _cleanup(tmp)
            _INGEST_LOCK.release()
            return _error(400, f"rejected at {exc.step}: {exc.reason}")
        except Exception:
            _cleanup(tmp)
            _INGEST_LOCK.release()
            raise

        events: queue.Queue = queue.Queue()

        def work() -> None:
            try:
                summary = incremental.run(tmp, live=body.live, progress=events.put,
                                          jurisdiction=body.jurisdiction)
                events.put({"status": "finished", "summary": summary})
            except incremental.IngestError as exc:
                code = 400 if exc.step in ("validate", "register") else 500
                events.put({"status": "failed", "step": exc.step, "reason": exc.reason, "http_status": code})
            except Exception as exc:  # report, never hang the stream
                events.put({"status": "failed", "step": "unknown", "reason": repr(exc), "http_status": 500})
            finally:
                _cleanup(tmp)
                _INGEST_LOCK.release()
                events.put(None)

        threading.Thread(target=work, name="ingest", daemon=True).start()

        def stream():
            while (ev := events.get()) is not None:
                yield json.dumps({**jsonable_encoder(ev), "disclaimer": svc.disclaimer()},
                                 ensure_ascii=False) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson")

app = create_app()
