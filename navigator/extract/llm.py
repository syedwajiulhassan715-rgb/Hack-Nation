"""Claude call for rule extraction: structured JSON output, disk cache, audit log.

Cache key (CLAUDE.md, NOTES.md phase 2): text_sha256, chunk id, chunker version, chunk char
range, prompt version and model. A cache hit never calls the API, so a run from a committed
cache is deterministic. Never delete the cache to retry; bump `prompt_version` instead.

The configured model does not accept sampling parameters (temperature), so determinism
comes from the cache, not from the API. See NOTES.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from navigator import audit, settings

_client = None
_client_lock = threading.Lock()


def stage_settings(stage: str) -> dict[str, Any]:
    """llm settings with the per-stage overrides under `llm.stages.<stage>` applied."""
    base = settings.load()["llm"]
    cfg = {k: v for k, v in base.items() if k != "stages"}
    cfg.update((base.get("stages") or {}).get(stage) or {})
    if not cfg.get("model"):
        raise RuntimeError(f"no LLM model configured for stage {stage!r} in config/settings.yaml")
    return cfg


def cache_key(parts: dict[str, Any]) -> str:
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cache_path(key: str) -> Path:
    return settings.path("cache") / f"{key}.json"


def _load_env() -> None:
    """Read .env (KEY=VALUE lines) without overriding real environment variables."""
    env = settings.REPO_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip())


def _get_client():
    global _client
    with _client_lock:
        if _client is None:
            import anthropic

            _load_env()
            _client = anthropic.Anthropic(max_retries=4, timeout=600.0)
        return _client


def call_json(*, system: str, user: str, schema: dict[str, Any], key_parts: dict[str, Any],
              use_cache: bool = True, label: str = "", stage: str = "extract") -> dict[str, Any]:
    """Return the model's JSON answer, from cache when possible.

    Result: {"data", "cache_key", "cached", "model", "served_model", "usage"}.
    Raises RuntimeError on refusal, truncation or invalid JSON (the caller logs and skips
    the chunk; nothing is guessed).
    """
    cfg = stage_settings(stage)
    key_parts = {**key_parts, "prompt_version": cfg["prompt_version"], "model": cfg["model"]}
    key = cache_key(key_parts)
    path = cache_path(key)

    if use_cache and path.exists():
        entry = json.loads(path.read_text(encoding="utf-8"))
        audit.log(stage, "llm_cache_hit", cache_key=key, label=label)
        return {"data": entry["response"], "cache_key": key, "cached": True,
                "model": entry["model"], "served_model": entry.get("served_model"),
                "usage": entry.get("usage")}

    client = _get_client()
    started = time.monotonic()
    with client.messages.stream(
        model=cfg["model"],
        max_tokens=cfg.get("max_tokens", 32000),
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={
            "effort": cfg.get("effort", "high"),
            "format": {"type": "json_schema", "schema": schema},
        },
    ) as stream:
        msg = stream.get_final_message()
    seconds = round(time.monotonic() - started, 1)
    usage = {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens}

    def fail(reason: str) -> RuntimeError:
        audit.log(stage, "llm_error", reason, cache_key=key, label=label,
                  request_id=getattr(msg, "_request_id", None), seconds=seconds, **usage)
        return RuntimeError(f"{label}: {reason}")

    if msg.stop_reason == "refusal":
        raise fail("model refused")
    if msg.stop_reason == "max_tokens":
        raise fail("output truncated at max_tokens")
    text = next((b.text for b in msg.content if b.type == "text"), None)
    if text is None:
        raise fail("no text block in response")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise fail(f"invalid JSON: {exc}") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"key_parts": key_parts, "model": cfg["model"], "served_model": msg.model,
             "request_id": getattr(msg, "_request_id", None), "usage": usage,
             "stop_reason": msg.stop_reason, "response": data}
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    audit.log(stage, "llm_call", cache_key=key, label=label, model=cfg["model"],
              served_model=msg.model, request_id=entry["request_id"], seconds=seconds, **usage)
    return {"data": data, "cache_key": key, "cached": False, "model": cfg["model"],
            "served_model": msg.model, "usage": usage}
