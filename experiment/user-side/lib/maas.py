#!/usr/bin/env python3
"""Provider profile assessment.

This is intentionally scoped to direct provider API checks.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import math
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


USER_SIDE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]

WIRE_TO_ENDPOINT = {
    "chat": "/v1/chat/completions",
    "responses": "/v1/responses",
    "messages": "/v1/messages",
}

PROTOCOL_WIRES = {
    "openai": ["chat", "responses"],
    "openai-compatible": ["chat", "responses"],
    "anthropic": ["messages"],
    "anthropic-compatible": ["messages"],
    "claude": ["messages"],
    "mixed": ["chat", "responses", "messages"],
}

WIRE_HEADERS = {
    "messages": {"anthropic-version": "2023-06-01"},
}

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

PROVIDER_SMOKE_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "generation",
        "required": True,
        "prompt": "Explain what an API gateway does in two short sentences.",
        "min_output_chars": 40,
    },
    {
        "id": "json",
        "required": True,
        "prompt": 'Reply with only one line of valid JSON: {"status":"ok"}',
        "expect_json_key": "status",
        "expect_json_value": "ok",
    },
    {
        "id": "code",
        "required": True,
        "prompt": (
            "Write a Python function named add that takes a and b. "
            "Output only the code block."
        ),
        "expect_contains": "def add",
    },
    {
        "id": "model_probe",
        "required": False,
        "model_probe": True,
        "prompt": (
            "Respond with ONLY one JSON object. Required keys: "
            '"model", "knowledge_cutoff".'
        ),
        "expect_json_keys": ["model", "knowledge_cutoff"],
        "expect_model_match": True,
    },
]


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or USER_SIDE_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def provider_config_path(path: str | None = None) -> Path:
    return Path(path).expanduser().resolve() if path else USER_SIDE_ROOT / "provider-profiles.json"


def load_provider_config(path: str | None = None) -> dict[str, Any]:
    cfg_path = provider_config_path(path)
    if not cfg_path.is_file():
        raise SystemExit(
            f"Missing provider config: {cfg_path}. "
            "Copy provider-profiles.example.json to provider-profiles.json first."
        )
    with cfg_path.open(encoding="utf-8") as fh:
        return json.load(fh)


def iter_provider_profiles(
    cfg: dict[str, Any],
    *,
    platform: str | None = None,
    profile: str | None = None,
) -> list[tuple[str, str, dict[str, Any]]]:
    raw_platforms = cfg.get("platforms")
    if isinstance(raw_platforms, dict):
        platforms = raw_platforms
    else:
        pid = str(cfg.get("platform_id") or "default")
        platforms = {pid: cfg}

    out: list[tuple[str, str, dict[str, Any]]] = []
    for platform_id, platform_cfg in platforms.items():
        if platform and platform_id != platform:
            continue
        if not isinstance(platform_cfg, dict):
            raise SystemExit(f"Platform {platform_id!r} must be an object")
        profiles = platform_cfg.get("profiles")
        if not isinstance(profiles, dict) or not profiles:
            raise SystemExit(f"Platform {platform_id!r} has no profiles")
        defaults = {
            k: v
            for k, v in platform_cfg.items()
            if k not in {"profiles", "platform_id", "name"}
        }
        for profile_id, profile_cfg in profiles.items():
            if profile and profile_id != profile:
                continue
            if not isinstance(profile_cfg, dict):
                raise SystemExit(f"Profile {platform_id}.{profile_id} must be an object")
            merged = dict(defaults)
            merged.update(profile_cfg)
            merged["platform_id"] = platform_id
            merged["profile_id"] = profile_id
            merged.setdefault("name", profile_id)
            out.append((platform_id, profile_id, merged))
    if not out:
        raise SystemExit("No provider profiles matched filters")
    return out


def provider_profile_key(profile: dict[str, Any]) -> str:
    env_name = str(profile.get("api_key_env") or "").strip()
    if not env_name:
        raise SystemExit(f"profile {profile.get('profile_id')} missing api_key_env")
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise SystemExit(f"Missing API key: set {env_name} in experiment/user-side/.env")
    return key


def provider_profile_wires(profile: dict[str, Any]) -> list[str]:
    raw_protocol = str(profile.get("protocol") or "openai").strip().lower()
    allowed = PROTOCOL_WIRES.get(raw_protocol, PROTOCOL_WIRES["mixed"])
    raw_wires = profile.get("wires") or allowed
    wires = [str(w).strip() for w in raw_wires if str(w).strip() in WIRE_TO_ENDPOINT]
    wires = [w for w in wires if w in allowed or raw_protocol not in PROTOCOL_WIRES]
    if not wires:
        raise SystemExit(
            f"profile {profile.get('profile_id')} has no usable wires for protocol {raw_protocol}"
        )
    return wires


def provider_profile_models(profile: dict[str, Any]) -> list[str]:
    models = profile.get("models")
    if isinstance(models, str):
        return [models]
    if isinstance(models, list):
        return [str(m) for m in models if str(m).strip()]
    raise SystemExit(f"profile {profile.get('profile_id')} missing models")


def provider_endpoint_url(profile: dict[str, Any], endpoint: str) -> str:
    base = str(profile.get("base_url") or "").rstrip("/")
    if not base:
        raise SystemExit(f"profile {profile.get('profile_id')} missing base_url")
    if endpoint.startswith("/v1/") and base.endswith("/v1"):
        return base + endpoint.removeprefix("/v1")
    return base + endpoint


def proxy_handler_for(url: str) -> urllib.request.ProxyHandler:
    if os.environ.get("MAAS_PROXY_SKIP"):
        return urllib.request.ProxyHandler({})
    proxy = os.environ.get("MAAS_PROXY", "").strip()
    if not proxy:
        return urllib.request.ProxyHandler({})
    return urllib.request.ProxyHandler({"http": proxy, "https": proxy})


def http_opener(url: str) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(proxy_handler_for(url))


def parse_json_payload(raw: bytes, headers: Any | None = None) -> Any:
    text = raw.decode("utf-8", errors="replace")
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def http_json(
    method: str,
    url: str,
    key: str,
    body: dict[str, Any] | None = None,
    *,
    extra_headers: dict[str, str] | None = None,
    timeout: float = 120,
) -> tuple[int, Any, float]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": os.environ.get("MAAS_USER_AGENT", DEFAULT_USER_AGENT),
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if extra_headers:
        headers.update(extra_headers)

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    t0 = time.perf_counter()
    try:
        with http_opener(url).open(req, timeout=timeout) as resp:
            raw = resp.read()
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            return getattr(resp, "status", 200), parse_json_payload(raw, resp.headers), latency_ms
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return exc.code, parse_json_payload(raw, exc.headers), latency_ms
    except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return 0, {"error": str(exc)}, latency_ms


def parse_models_catalog(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        raw = payload.get("data", payload.get("models", []))
    else:
        raw = payload
    out: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("id"):
                out.append(str(item["id"]))
            elif isinstance(item, str):
                out.append(item)
    return sorted(set(out))


def payload_top_level_summary(payload: Any) -> str:
    if isinstance(payload, dict):
        keys = ", ".join(sorted(str(k) for k in payload.keys())[:8])
        return f"object({keys})"
    if isinstance(payload, list):
        return f"array({len(payload)})"
    if payload is None:
        return "empty"
    if isinstance(payload, str):
        stripped = payload.lstrip().lower()
        if stripped.startswith("<!doctype") or stripped.startswith("<html"):
            return "html"
        return f"text({len(payload)})"
    return type(payload).__name__


def response_payload_shape(payload: Any) -> str:
    if isinstance(payload, (dict, list)):
        return "json"
    if isinstance(payload, str):
        text = payload.lstrip().lower()
        return "html" if text.startswith(("<!doctype", "<html")) else "text"
    if payload is None:
        return "empty"
    return type(payload).__name__


def error_detail(payload: Any) -> str:
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("type") or err)[:300]
        if isinstance(err, str):
            return err[:300]
        if payload.get("message"):
            return str(payload["message"])[:300]
        return json.dumps(payload, ensure_ascii=False)[:300]
    if payload is None:
        return ""
    return str(payload)[:300]


def content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(content_text(v) for v in value)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("content"), str):
            return value["content"]
        if isinstance(value.get("output_text"), str):
            return value["output_text"]
        return "\n".join(content_text(v) for v in value.values())
    return ""


def smoke_wire_body(
    wire: str,
    model: str,
    prompt: str,
    *,
    max_tokens: int = 256,
) -> tuple[dict[str, Any], dict[str, str]]:
    if wire == "chat":
        return {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0,
        }, {}
    if wire == "responses":
        return {
            "model": model,
            "input": prompt,
            "max_output_tokens": max_tokens,
            "temperature": 0,
        }, {}
    if wire == "messages":
        return {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0,
        }, dict(WIRE_HEADERS["messages"])
    raise ValueError(f"Unknown wire: {wire}")


def wire_response_text(wire: str, payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    if wire == "chat":
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0]
            if isinstance(choice, dict):
                msg = choice.get("message") or choice.get("delta") or {}
                if isinstance(msg, dict):
                    return content_text(msg.get("content", ""))
        return content_text(payload.get("output") or payload.get("content"))
    if wire == "responses":
        if isinstance(payload.get("output_text"), str):
            return payload["output_text"]
        return content_text(payload.get("output") or payload.get("content"))
    if wire == "messages":
        return content_text(payload.get("content"))
    return ""


def wire_response_shape(wire: str, payload: Any) -> str:
    if not isinstance(payload, dict):
        return response_payload_shape(payload)
    text = wire_response_text(wire, payload)
    if text.strip():
        return "ok"
    if payload.get("error"):
        return "error"
    return "missing"


def request_body_text(wire: str, body: dict[str, Any]) -> str:
    if wire == "responses":
        return content_text(body.get("input", ""))
    parts: list[str] = []
    if isinstance(body.get("system"), str):
        parts.append(str(body["system"]))
    messages = body.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, dict):
                parts.append(content_text(msg.get("content", "")))
    return "\n".join(p for p in parts if p)


def rough_token_count(text: str) -> int:
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = max(0, len(text) - cjk)
    return max(1, math.ceil(cjk + other / 4))


def usage_estimate(wire: str, body: dict[str, Any], response_text: str) -> dict[str, Any]:
    input_text = request_body_text(wire, body)
    return {
        "input_tokens_est": rough_token_count(input_text),
        "output_tokens_est": rough_token_count(response_text),
        "method": "rough_cjk_char_plus_other_div4",
    }


def nested_value(data: Any, path: tuple[str, ...]) -> Any:
    cur = data
    for part in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def first_int(data: Any, paths: list[tuple[str, ...]]) -> int | None:
    for path in paths:
        value = int_value(nested_value(data, path))
        if value is not None:
            return value
    return None


def normalize_provider_usage(payload: Any) -> dict[str, Any]:
    raw = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return {
            "source": "missing",
            "usage_schema": "missing",
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
            "raw_usage": raw,
        }

    input_tokens = first_int(raw, [("input_tokens",), ("prompt_tokens",)])
    output_tokens = first_int(raw, [("output_tokens",), ("completion_tokens",)])
    total_tokens = first_int(raw, [("total_tokens",)])
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    cache_read = first_int(raw, [
        ("cache_read_input_tokens",),
        ("prompt_tokens_details", "cached_tokens"),
        ("input_tokens_details", "cached_tokens"),
        ("cached_tokens",),
    ]) or 0
    cache_write = first_int(raw, [
        ("cache_creation_input_tokens",),
        ("input_tokens_details", "cache_creation_tokens"),
        ("input_tokens_details", "cache_creation_input_tokens"),
    ]) or 0
    reasoning = first_int(raw, [
        ("reasoning_tokens",),
        ("completion_tokens_details", "reasoning_tokens"),
        ("output_tokens_details", "reasoning_tokens"),
    ]) or 0

    if "cache_read_input_tokens" in raw or "cache_creation_input_tokens" in raw:
        schema = "anthropic"
    elif isinstance(raw.get("input_tokens_details"), dict):
        schema = "openai_responses"
    elif isinstance(raw.get("prompt_tokens_details"), dict):
        schema = "openai_chat"
    else:
        schema = "unknown"

    return {
        "source": "provider_usage",
        "usage_schema": schema,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "reasoning_tokens": reasoning,
        "raw_usage": raw,
    }


def usage_plausibility(
    provider_usage: dict[str, Any],
    estimate: dict[str, Any],
) -> dict[str, Any]:
    notes: list[str] = []
    status = "ok"
    if provider_usage.get("source") == "missing":
        return {"status": "missing", "notes": ["provider usage missing"]}

    input_tokens = provider_usage.get("input_tokens")
    output_tokens = provider_usage.get("output_tokens")
    total_tokens = provider_usage.get("total_tokens")
    cache_read = provider_usage.get("cache_read_tokens") or 0
    cache_write = provider_usage.get("cache_write_tokens") or 0

    if input_tokens is None or output_tokens is None:
        status = "partial"
        notes.append("core usage fields are partial")
    if total_tokens is not None and output_tokens is not None and total_tokens < output_tokens:
        status = "invalid"
        notes.append("total_tokens < output_tokens")
    if input_tokens is not None and cache_read > input_tokens:
        status = "invalid"
        notes.append("cache_read_tokens > input_tokens")
    if input_tokens is not None and cache_write > input_tokens:
        status = "invalid"
        notes.append("cache_write_tokens > input_tokens")
    if input_tokens == 0 and output_tokens == 0 and total_tokens == 0 and status != "invalid":
        status = "suspicious"
        notes.append("all provider usage token fields are zero")

    est_input = estimate.get("input_tokens_est") or 0
    est_output = estimate.get("output_tokens_est") or 0
    if input_tokens and est_input:
        ratio = input_tokens / est_input
        notes.append(f"input_ratio={ratio:.2f}")
        if ratio > 3 or ratio < 0.33:
            status = "suspicious" if status == "ok" else status
            notes.append("provider input usage differs from local estimate by >3x")
    if output_tokens and est_output:
        ratio = output_tokens / est_output
        notes.append(f"output_ratio={ratio:.2f}")
        if ratio > 3 or ratio < 0.33:
            status = "suspicious" if status == "ok" else status
            notes.append("provider output usage differs from local estimate by >3x")

    if not notes:
        notes.append("provider usage present")
    return {"status": status, "notes": notes}


def output_excerpt(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    return compact[:limit] + ("..." if len(compact) > limit else "")


def provider_fetch_models(profile: dict[str, Any], key: str, timeout: float) -> dict[str, Any]:
    url = provider_endpoint_url(profile, "/v1/models")
    st, payload, latency_ms = http_json("GET", url, key, timeout=timeout)
    ids = parse_models_catalog(payload) if st == 200 else []
    branch = "unavailable" if st != 200 else "listed" if ids else "empty"
    return {
        "pass": st == 200,
        "branch": branch,
        "http_status": st,
        "latency_ms": latency_ms,
        "model_ids": ids,
        "payload_shape": payload_top_level_summary(payload),
        "error_detail": error_detail(payload) if st != 200 else "",
        "error_shape": response_payload_shape(payload),
    }


def provider_sync_probe(
    profile: dict[str, Any],
    key: str,
    model: str,
    wire: str,
    prompt: str,
    *,
    timeout: float = 120,
    body_override: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    body, headers = smoke_wire_body(wire, model, prompt)
    if body_override is not None:
        body = body_override
    if extra_headers:
        headers = {**headers, **extra_headers}
    endpoint = WIRE_TO_ENDPOINT[wire]
    url = provider_endpoint_url(profile, endpoint)
    st, payload, latency_ms = http_json(
        "POST", url, key, body, extra_headers=headers, timeout=timeout
    )
    text = wire_response_text(wire, payload) if st == 200 else error_detail(payload)
    shape = wire_response_shape(wire, payload) if st == 200 else "missing"
    ok = st == 200 and shape == "ok"
    provider_usage = normalize_provider_usage(payload)
    estimate = usage_estimate(wire, body, text if ok else "")
    usage_check = usage_plausibility(provider_usage, estimate)
    response_model = str(payload.get("model", "")) if isinstance(payload, dict) else ""
    return {
        "model": model,
        "wire": wire,
        "endpoint": endpoint,
        "url": url,
        "http_status": st,
        "ok": ok,
        "result": "OK" if ok else "FAIL",
        "latency_ms": latency_ms,
        "response_shape": shape,
        "response_text": text,
        "response_excerpt": output_excerpt(text),
        "response_model": response_model,
        "payload_shape": payload_top_level_summary(payload),
        "error_shape": response_payload_shape(payload),
        "provider_usage": provider_usage,
        "local_estimate": estimate,
        "usage_plausibility": usage_check,
    }


def provider_stream_probe(
    profile: dict[str, Any],
    key: str,
    model: str,
    wire: str,
    *,
    timeout: float = 120,
) -> dict[str, Any]:
    body, extra = smoke_wire_body(wire, model, "Reply OK", max_tokens=64)
    body["stream"] = True
    endpoint = WIRE_TO_ENDPOINT[wire]
    url = provider_endpoint_url(profile, endpoint)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": os.environ.get("MAAS_USER_AGENT", DEFAULT_USER_AGENT),
    }
    headers.update(extra)
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with http_opener(url).open(req, timeout=timeout) as resp:
            first = resp.read(2048)
            ttfb_ms = round((time.perf_counter() - t0) * 1000, 1)
            tail = resp.read(4096)
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            chunk = first + tail
            http_status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "model": model,
            "wire": wire,
            "ok": False,
            "stream": "fail",
            "http_status": exc.code,
            "latency_ms": latency_ms,
            "ttfb_ms": None,
            "stream_duration_ms": None,
            "detail": error_detail(parse_json_payload(exc.read(), exc.headers)),
        }
    except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "model": model,
            "wire": wire,
            "ok": False,
            "stream": "fail",
            "http_status": 0,
            "latency_ms": latency_ms,
            "ttfb_ms": None,
            "stream_duration_ms": None,
            "detail": str(exc)[:160],
        }
    markers = (
        b"data:",
        b"event:",
        b"content_block_delta",
        b"response.output_text.delta",
        b"chat.completion.chunk",
    )
    ok = any(m in chunk for m in markers)
    return {
        "model": model,
        "wire": wire,
        "ok": ok,
        "stream": "ok" if ok else "fail",
        "http_status": http_status,
        "latency_ms": latency_ms,
        "ttfb_ms": ttfb_ms,
        "stream_duration_ms": round(latency_ms - ttfb_ms, 1),
        "detail": "" if ok else "missing SSE markers",
    }


def extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if "\n" in stripped:
            stripped = stripped.split("\n", 1)[1]
    candidates = [stripped]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        candidates.append(stripped[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def normalized_id(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def evaluate_smoke_output(
    scenario: dict[str, Any],
    text: str,
    exit_code: int,
    *,
    response_model: str = "",
) -> tuple[bool, str, dict[str, Any]]:
    extra: dict[str, Any] = {}
    if exit_code != 0:
        return False, "request failed", extra
    if len(text.strip()) < int(scenario.get("min_output_chars", 0)):
        return False, "output too short", extra
    if scenario.get("expect_contains") and scenario["expect_contains"] not in text:
        return False, f"missing {scenario['expect_contains']!r}", extra
    parsed: dict[str, Any] | None = None
    if (
        scenario.get("expect_json_key")
        or scenario.get("expect_json_keys")
        or scenario.get("expect_json_value") is not None
    ):
        parsed = extract_json_object(text)
        if parsed is None:
            return False, "invalid JSON output", extra
    if scenario.get("expect_json_key"):
        key = str(scenario["expect_json_key"])
        if parsed is None or key not in parsed:
            return False, f"missing JSON key {key}", extra
        expected = scenario.get("expect_json_value")
        if expected is not None and parsed.get(key) != expected:
            return False, f"unexpected JSON value for {key}", extra
    for key in scenario.get("expect_json_keys", []):
        if parsed is None or key not in parsed:
            return False, f"missing JSON key {key}", extra
    if scenario.get("expect_model_match"):
        expected_model = str(scenario.get("expect_model_id") or "")
        reported = response_model or str((parsed or {}).get("model") or "")
        if expected_model and reported:
            match = normalized_id(expected_model) in normalized_id(reported) or normalized_id(
                reported
            ) in normalized_id(expected_model)
            extra["model_match"] = match
            extra["reported_model"] = reported
            if not match:
                extra["model_probe_note"] = (
                    f"reported model {reported!r} differs from requested {expected_model!r}"
                )
        else:
            extra["model_match"] = None
            extra["model_probe_note"] = "model id not available in response"
    return True, "ok", extra


def primary_wire_by_model(protocol_rows: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    preferred = {"responses": 0, "messages": 1, "chat": 2}
    for row in protocol_rows:
        if not row.get("ok"):
            continue
        model = row["model"]
        wire = row["wire"]
        if model not in out or preferred.get(wire, 9) < preferred.get(out[model], 9):
            out[model] = wire
    return out


def run_provider_smoke(
    profile: dict[str, Any],
    key: str,
    wire_map: dict[str, str],
    *,
    timeout: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    required_failed = 0
    optional_failed = 0
    for model, wire in wire_map.items():
        for scenario in PROVIDER_SMOKE_SCENARIOS:
            resolved = dict(scenario)
            if resolved.get("model_probe") or resolved.get("expect_model_match"):
                resolved["expect_model_id"] = model
            probe = provider_sync_probe(
                profile, key, model, wire, str(resolved["prompt"]), timeout=timeout
            )
            ok, reason, extra = evaluate_smoke_output(
                resolved,
                probe["response_text"],
                0 if probe["ok"] else 1,
                response_model=probe.get("response_model", ""),
            )
            if ok and extra.get("model_match") is False:
                optional_failed += 1
                reason = extra.get("model_probe_note") or reason
            elif not ok:
                if resolved.get("required", True):
                    required_failed += 1
                else:
                    optional_failed += 1
            rows.append({
                "model": model,
                "wire": wire,
                "id": resolved["id"],
                "required": bool(resolved.get("required", True)),
                "pass": ok,
                "reason": reason,
                "latency_ms": probe["latency_ms"],
                "output_excerpt": probe["response_excerpt"],
                "provider_usage": probe["provider_usage"],
                "usage_plausibility": probe["usage_plausibility"],
                **extra,
            })
    status = "fail" if required_failed else "warn" if optional_failed else "pass"
    return {
        "status": status,
        "pass": status != "fail",
        "required_failed": required_failed,
        "optional_failed": optional_failed,
        "scenarios": rows,
    }


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * pct) - 1))
    return round(ordered[idx], 1)


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [
        float(r["latency_ms"])
        for r in records
        if isinstance(r.get("latency_ms"), (int, float))
    ]
    successes = sum(1 for r in records if r.get("ok") is True or r.get("pass") is True)
    usage_status: dict[str, int] = {}
    token_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
    }
    for row in records:
        check = row.get("usage_plausibility")
        if isinstance(check, dict):
            st = str(check.get("status") or "unknown")
            usage_status[st] = usage_status.get(st, 0) + 1
        usage = row.get("provider_usage")
        if isinstance(usage, dict) and usage.get("source") == "provider_usage":
            for key in token_totals:
                value = usage.get(key)
                if isinstance(value, int):
                    token_totals[key] += value
    return {
        "requests": len(records),
        "success": successes,
        "success_rate": round(successes / len(records), 3) if records else 0,
        "latency_avg_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
        "latency_p50_ms": percentile(latencies, 0.50),
        "latency_p95_ms": percentile(latencies, 0.95),
        "latency_max_ms": round(max(latencies), 1) if latencies else None,
        "usage_status": usage_status,
        "token_totals": token_totals,
    }


def run_provider_reliability(
    profile: dict[str, Any],
    key: str,
    wire_map: dict[str, str],
    *,
    repeat: int,
    concurrency: int,
    timeout: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

    def one(model: str, wire: str, idx: int, mode: str) -> dict[str, Any]:
        row = provider_sync_probe(
            profile,
            key,
            model,
            wire,
            f"Reliability probe {idx}. Reply with exactly OK.",
            timeout=timeout,
        )
        row["probe_kind"] = mode
        row["attempt"] = idx
        return row

    for model, wire in wire_map.items():
        for idx in range(1, max(0, repeat) + 1):
            rows.append(one(model, wire, idx, "sequential"))
        if concurrency > 0:
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [
                    pool.submit(one, model, wire, idx, "concurrent")
                    for idx in range(1, concurrency + 1)
                ]
                for future in concurrent.futures.as_completed(futures):
                    rows.append(future.result())
    return {"rows": rows, "summary": summarize_records(rows)}


def fixed_cache_prefix() -> str:
    line = (
        "Stable cache prefix for provider assessment. Keep every byte identical "
        "between requests. "
    )
    return (line * 90).strip()


def openai_cache_body(wire: str, model: str, prefix: str, suffix: str) -> dict[str, Any]:
    prompt = prefix + "\n\n" + suffix
    body, _ = smoke_wire_body(wire, model, prompt, max_tokens=64)
    return body


def anthropic_cache_body(model: str, prefix: str, suffix: str) -> dict[str, Any]:
    return {
        "model": model,
        "max_tokens": 64,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prefix,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": "\n\n" + suffix},
                ],
            }
        ],
    }


def run_openai_cache_observation(
    profile: dict[str, Any],
    key: str,
    model: str,
    wire: str,
    *,
    timeout: float,
) -> dict[str, Any]:
    prefix = fixed_cache_prefix()
    p1 = provider_sync_probe(
        profile,
        key,
        model,
        wire,
        "",
        timeout=timeout,
        body_override=openai_cache_body(wire, model, prefix, "Question A: reply OK."),
    )
    p2 = provider_sync_probe(
        profile,
        key,
        model,
        wire,
        "",
        timeout=timeout,
        body_override=openai_cache_body(wire, model, prefix, "Question B: reply OK."),
    )
    read1 = p1["provider_usage"].get("cache_read_tokens") or 0
    read2 = p2["provider_usage"].get("cache_read_tokens") or 0
    notes = [f"request1_cache_read={read1}", f"request2_cache_read={read2}"]
    if not p1["ok"] or not p2["ok"]:
        status = "unsupported"
        notes.append("cache observation request failed")
    elif read2 > 0:
        status = "observed"
    elif p1["provider_usage"].get("source") == "missing":
        status = "unsupported_or_hidden"
    else:
        status = "not_observed"
    return {
        "type": "openai_auto_prefix",
        "model": model,
        "wire": wire,
        "status": status,
        "notes": notes,
        "requests": [p1, p2],
    }


def run_anthropic_cache_observation(
    profile: dict[str, Any],
    key: str,
    model: str,
    *,
    timeout: float,
) -> dict[str, Any]:
    prefix = fixed_cache_prefix()
    extra = {"anthropic-version": "2023-06-01"}
    p1 = provider_sync_probe(
        profile,
        key,
        model,
        "messages",
        "",
        timeout=timeout,
        body_override=anthropic_cache_body(model, prefix, "Question A: reply OK."),
        extra_headers=extra,
    )
    p2 = provider_sync_probe(
        profile,
        key,
        model,
        "messages",
        "",
        timeout=timeout,
        body_override=anthropic_cache_body(model, prefix, "Question B: reply OK."),
        extra_headers=extra,
    )
    write1 = p1["provider_usage"].get("cache_write_tokens") or 0
    read2 = p2["provider_usage"].get("cache_read_tokens") or 0
    notes = [f"request1_cache_write={write1}", f"request2_cache_read={read2}"]
    if not p1["ok"] or not p2["ok"]:
        status = "unsupported"
        notes.append("cache_control request failed")
    elif write1 > 0 and read2 > 0:
        status = "observed"
    elif write1 > 0:
        status = "creation_only"
    elif p1["provider_usage"].get("source") == "missing":
        status = "unsupported_or_hidden"
    else:
        status = "not_observed"
    return {
        "type": "anthropic_ephemeral",
        "model": model,
        "wire": "messages",
        "status": status,
        "notes": notes,
        "requests": [p1, p2],
    }


def run_provider_cache_observation(
    profile: dict[str, Any],
    key: str,
    wire_map: dict[str, str],
    *,
    timeout: float,
) -> dict[str, Any] | None:
    if not wire_map:
        return None
    cache_kind = str(profile.get("cache_test") or "").strip()
    if not cache_kind:
        protocol = str(profile.get("protocol") or "")
        cache_kind = "anthropic_ephemeral" if protocol.startswith("anthropic") else "openai_auto_prefix"
    model = next(iter(wire_map))
    wire = wire_map[model]
    if cache_kind == "anthropic_ephemeral":
        if wire != "messages" and "messages" in provider_profile_wires(profile):
            wire = "messages"
        if wire != "messages":
            return {
                "type": cache_kind,
                "status": "unsupported",
                "notes": ["anthropic cache check requires messages wire"],
            }
        return run_anthropic_cache_observation(profile, key, model, timeout=timeout)
    return run_openai_cache_observation(profile, key, model, wire, timeout=timeout)


def profile_grade(profile_result: dict[str, Any]) -> str:
    protocol_ok = any(r.get("ok") for r in profile_result.get("protocol", []))
    if not protocol_ok:
        return "D"
    if any(
        r.get("usage_plausibility", {}).get("status") == "invalid"
        for r in profile_result.get("all_request_records", [])
    ):
        return "D"
    reliability = profile_result.get("reliability", {}).get("summary", {})
    if reliability and reliability.get("success_rate", 1) <= 0.6:
        return "D"
    if profile_result.get("smoke", {}).get("status") == "fail":
        return "C"
    if reliability and reliability.get("success_rate", 1) < 1:
        return "B"
    if any(
        r.get("usage_plausibility", {}).get("status") in {"suspicious", "missing", "partial"}
        for r in profile_result.get("all_request_records", [])
    ):
        return "B"
    if any(s.get("stream") == "fail" for s in profile_result.get("stream", [])):
        return "B"
    return "A"


def run_provider_profile(
    platform_id: str,
    profile_id: str,
    profile: dict[str, Any],
    *,
    repeat: int,
    concurrency: int,
    timeout: float,
    cache_check: bool,
) -> dict[str, Any]:
    key = provider_profile_key(profile)
    catalog = provider_fetch_models(profile, key, timeout)
    models = provider_profile_models(profile)
    wires = provider_profile_wires(profile)
    catalog_set = set(catalog.get("model_ids") or [])

    protocol_rows: list[dict[str, Any]] = []
    for model in models:
        for wire in wires:
            protocol_rows.append(
                provider_sync_probe(profile, key, model, wire, "Reply OK", timeout=timeout)
            )

    stream_rows: list[dict[str, Any]] = []
    for row in protocol_rows:
        if row.get("ok"):
            stream_rows.append(
                provider_stream_probe(profile, key, row["model"], row["wire"], timeout=timeout)
            )

    wire_map = primary_wire_by_model(protocol_rows)
    if wire_map:
        smoke = run_provider_smoke(profile, key, wire_map, timeout=timeout)
        reliability = run_provider_reliability(
            profile,
            key,
            wire_map,
            repeat=repeat,
            concurrency=concurrency,
            timeout=timeout,
        )
    else:
        smoke = {
            "status": "fail",
            "pass": False,
            "scenarios": [],
            "required_failed": 1,
            "optional_failed": 0,
        }
        reliability = {"rows": [], "summary": summarize_records([])}
    cache = (
        run_provider_cache_observation(profile, key, wire_map, timeout=timeout)
        if cache_check and wire_map
        else None
    )

    records: list[dict[str, Any]] = []
    records.extend(protocol_rows)
    records.extend(smoke.get("scenarios", []))
    records.extend(reliability.get("rows", []))
    if cache:
        records.extend(cache.get("requests", []))

    result = {
        "platform_id": platform_id,
        "profile_id": profile_id,
        "name": profile.get("name", profile_id),
        "base_url": profile.get("base_url"),
        "api_key_env": profile.get("api_key_env"),
        "protocol_name": profile.get("protocol", "openai"),
        "models": models,
        "wires": wires,
        "catalog": catalog,
        "model_catalog": [
            {"model": m, "in_catalog": m in catalog_set} for m in models
        ],
        "protocol": protocol_rows,
        "stream": stream_rows,
        "smoke": smoke,
        "reliability": reliability,
        "cache_observation": cache,
        "metrics": summarize_records(records),
        "all_request_records": records,
    }
    result["grade"] = profile_grade(result)
    return result


def platform_grade(profile_results: list[dict[str, Any]]) -> str:
    grades = [r.get("grade", "D") for r in profile_results]
    if not grades or "D" in grades:
        return "D"
    if "C" in grades:
        return "C"
    if "B" in grades:
        return "B"
    return "A"


def provider_report_path(platform_id: str, day: str) -> Path:
    return REPO_ROOT / "docs" / "reports" / f"{platform_id}-平台评估报告-{day}.md"


def render_provider_report(result: dict[str, Any]) -> str:
    day = result["date"]
    platform_id = result["platform_id"]
    lines = [
        f"# {platform_id} 平台评估报告 - {day}",
        "",
        f"- Overall grade: **{result['grade']}**",
        f"- Cache check: **{'yes' if result.get('cache_check') else 'no'}**",
        "- Scope: direct provider API/profile checks only.",
        "- Usage note: token usage is provider-reported plus local plausibility checks, not billing audit.",
        "",
        "## Profiles",
        "",
        "| Profile | Protocol | Models | Wires | Grade | Success | Avg ms | Usage |",
        "|---|---|---:|---|---:|---:|---:|---|",
    ]
    for prof in result["profiles"]:
        metrics = prof.get("metrics", {})
        usage_status = ", ".join(
            f"{k}:{v}" for k, v in sorted((metrics.get("usage_status") or {}).items())
        )
        avg = metrics.get("latency_avg_ms")
        lines.append(
            f"| `{prof['profile_id']}` | {prof['protocol_name']} | "
            f"{len(prof['models'])} | {', '.join(prof['wires'])} | "
            f"**{prof['grade']}** | {metrics.get('success_rate', 0)} | "
            f"{avg if avg is not None else '-'} | {usage_status or '-'} |"
        )

    for prof in result["profiles"]:
        catalog = prof["catalog"]
        lines.extend([
            "",
            f"## Profile `{prof['profile_id']}`",
            "",
            f"- Base URL: `{prof['base_url']}`",
            f"- API key env: `{prof['api_key_env']}`",
            f"- Catalog: `{catalog['branch']}` HTTP {catalog['http_status']} - {catalog['latency_ms']} ms",
            "",
            "### Protocol",
            "",
            "| Model | Wire | HTTP | Shape | ms | Result | Usage |",
            "|---|---|---:|---|---:|---|---|",
        ])
        for row in prof["protocol"]:
            usage_st = row.get("usage_plausibility", {}).get("status", "?")
            result_label = "PASS" if row.get("ok") else "FAIL"
            lines.append(
                f"| `{row['model']}` | `{row['wire']}` | {row['http_status']} | "
                f"{row['response_shape']} | {row['latency_ms']} | {result_label} | {usage_st} |"
            )

        lines.extend([
            "",
            "### Stream",
            "",
            "| Model | Wire | Status | TTFB ms | Total ms |",
            "|---|---|---|---:|---:|",
        ])
        for row in prof["stream"]:
            lines.append(
                f"| `{row['model']}` | `{row['wire']}` | {row['stream']} | "
                f"{row.get('ttfb_ms') if row.get('ttfb_ms') is not None else '-'} | "
                f"{row.get('latency_ms') if row.get('latency_ms') is not None else '-'} |"
            )

        smoke = prof.get("smoke", {})
        lines.extend([
            "",
            f"### Smoke: `{smoke.get('status', 'not_run')}`",
            "",
            "| Model | Scenario | Required | Result | ms | Note |",
            "|---|---|---|---|---:|---|",
        ])
        for row in smoke.get("scenarios", []):
            lines.append(
                f"| `{row['model']}` | `{row['id']}` | {row['required']} | "
                f"{'PASS' if row['pass'] else 'FAIL'} | {row['latency_ms']} | "
                f"{row.get('reason') or row.get('model_probe_note') or ''} |"
            )

        rel = prof.get("reliability", {}).get("summary", {})
        lines.extend([
            "",
            "### Reliability",
            "",
            f"- Requests: {rel.get('requests', 0)}",
            f"- Success rate: {rel.get('success_rate', 0)}",
            "- Latency avg/p50/p95/max ms: "
            f"{rel.get('latency_avg_ms') or '-'} / "
            f"{rel.get('latency_p50_ms') or '-'} / "
            f"{rel.get('latency_p95_ms') or '-'} / "
            f"{rel.get('latency_max_ms') or '-'}",
        ])

        cache = prof.get("cache_observation")
        if cache:
            lines.extend([
                "",
                "### Cache Observation",
                "",
                f"- Type: `{cache.get('type')}`",
                f"- Status: **{cache.get('status')}**",
            ])
            for note in cache.get("notes", []):
                lines.append(f"- {note}")

        totals = prof.get("metrics", {}).get("token_totals", {})
        lines.extend([
            "",
            "### Provider-Reported Token Totals",
            "",
            f"- input_tokens: {totals.get('input_tokens', 0)}",
            f"- output_tokens: {totals.get('output_tokens', 0)}",
            f"- total_tokens: {totals.get('total_tokens', 0)}",
            f"- cache_read_tokens: {totals.get('cache_read_tokens', 0)}",
            f"- cache_write_tokens: {totals.get('cache_write_tokens', 0)}",
            f"- reasoning_tokens: {totals.get('reasoning_tokens', 0)}",
        ])
    return "\n".join(lines) + "\n"


def print_provider_assessment(result: dict[str, Any]) -> None:
    print(f"Provider assessment: {result['platform_id']} grade={result['grade']}")
    for prof in result["profiles"]:
        metrics = prof.get("metrics", {})
        rel = prof.get("reliability", {}).get("summary", {})
        ok_count = sum(1 for r in prof["protocol"] if r.get("ok"))
        print(
            f"- {prof['profile_id']}: grade={prof['grade']} "
            f"protocol_ok={ok_count}/{len(prof['protocol'])} "
            f"smoke={prof.get('smoke', {}).get('status')} "
            f"success_rate={rel.get('success_rate', 0)} "
            f"avg_ms={metrics.get('latency_avg_ms') or '-'}"
        )
        cache = prof.get("cache_observation")
        if cache:
            print(f"  cache={cache.get('status')} ({cache.get('type')})")


def cmd_list_profiles(args: argparse.Namespace) -> None:
    cfg = load_provider_config(args.config)
    selected = iter_provider_profiles(
        cfg, platform=args.platform, profile=args.provider_profile
    )
    for platform_id, profile_id, profile in selected:
        models = ", ".join(provider_profile_models(profile))
        wires = ", ".join(provider_profile_wires(profile))
        print(
            f"{platform_id}.{profile_id} "
            f"protocol={profile.get('protocol', 'openai')} wires={wires} models={models}"
        )


def cmd_assess_provider(args: argparse.Namespace) -> None:
    cfg = load_provider_config(args.config)
    day = args.date or dt.date.today().isoformat()
    selected = iter_provider_profiles(
        cfg, platform=args.platform, profile=args.provider_profile
    )
    repeat = args.repeat if args.repeat is not None else int(cfg.get("repeat", 5))
    concurrency = (
        args.concurrency if args.concurrency is not None else int(cfg.get("concurrency", 0))
    )
    timeout = float(args.timeout or cfg.get("timeout_sec", 120))

    by_platform: dict[str, list[dict[str, Any]]] = {}
    for platform_id, profile_id, profile in selected:
        by_platform.setdefault(platform_id, []).append(
            run_provider_profile(
                platform_id,
                profile_id,
                profile,
                repeat=int(profile.get("repeat", repeat)),
                concurrency=int(profile.get("concurrency", concurrency)),
                timeout=float(profile.get("timeout_sec", timeout)),
                cache_check=args.cache_check,
            )
        )

    outputs: list[dict[str, Any]] = []
    for platform_id, profiles in by_platform.items():
        result = {
            "platform_id": platform_id,
            "date": day,
            "grade": platform_grade(profiles),
            "cache_check": args.cache_check,
            "repeat": repeat,
            "concurrency": concurrency,
            "profiles": profiles,
        }
        out_json = USER_SIDE_ROOT / ".runtime" / (
            f"{platform_id}-provider-assess-{day.replace('-', '')}.json"
        )
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["json_path"] = str(out_json)
        if args.write_report:
            rp = provider_report_path(platform_id, day)
            rp.parent.mkdir(parents=True, exist_ok=True)
            rp.write_text(render_provider_report(result), encoding="utf-8")
            result["report_path"] = str(rp)
        outputs.append(result)
        print_provider_assessment(result)
        print(f"  JSON: {out_json}")
        if args.write_report:
            print(f"  Report: {result['report_path']}")
    if args.json:
        print(json.dumps(outputs, ensure_ascii=False, indent=2))
    if any(r["grade"] == "D" for r in outputs):
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Direct third-party provider profile assessment"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common: dict[str, Any] = {
        "help": "Provider profile config JSON (default: provider-profiles.json)",
    }
    p = sub.add_parser("list-profiles", help="List configured provider profiles")
    p.add_argument("--config", **common)
    p.add_argument("--platform")
    p.add_argument("--provider-profile")
    p.set_defaults(func=cmd_list_profiles)

    p = sub.add_parser(
        "assess-provider",
        help="Run direct provider API checks for configured profiles",
    )
    p.add_argument("--config", **common)
    p.add_argument("--platform")
    p.add_argument("--provider-profile")
    p.add_argument("--repeat", type=int)
    p.add_argument("--concurrency", type=int)
    p.add_argument("--timeout", type=float)
    p.add_argument("--cache-check", action="store_true")
    p.add_argument("--write-report", action="store_true")
    p.add_argument("--date")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_assess_provider)
    return parser


def main() -> None:
    load_dotenv()
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
