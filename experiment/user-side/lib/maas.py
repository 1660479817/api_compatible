#!/usr/bin/env python3
"""Site registry and config helpers for t_* launchers (sites.json)."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def workspace_root() -> Path:
    return repo_root().parent.parent


REPORT_TITLES: dict[str, str] = {
    "source": "源评估报告",
}


def site_domain_label(site_id: str, site: dict[str, Any]) -> str:
    """Filename domain segment: report_domain, else site id or base_url host."""
    if site.get("report_domain"):
        return str(site["report_domain"])
    if "." in site_id:
        return site_id
    from urllib.parse import urlparse

    host = urlparse(site.get("base_url", "")).hostname
    return host or site_id


def report_basename(
    site_id: str,
    site: dict[str, Any],
    kind: str = "source",
    date: str | None = None,
) -> str:
    """Stable report filename: {domain}-{title}-{YYYY-MM-DD}.md"""
    domain = site_domain_label(site_id, site)
    title = REPORT_TITLES.get(kind)
    if not title:
        raise SystemExit(f"Unknown report kind: {kind!r}")
    day = date or datetime.date.today().isoformat()
    return f"{domain}-{title}-{day}.md"


def report_path(
    site_id: str,
    site: dict[str, Any],
    kind: str = "source",
    date: str | None = None,
) -> Path:
    return workspace_root() / "docs" / "reports" / report_basename(site_id, site, kind, date)


def cmd_report_path(args: argparse.Namespace, sites: dict[str, Any]) -> None:
    sid, site = site_entry(sites, args.site)
    path = report_path(sid, site, kind=args.kind, date=args.date or None)
    if args.relative:
        try:
            print(path.relative_to(workspace_root()))
        except ValueError:
            print(path)
    else:
        print(path)


def load_sites(root: Path | None = None) -> dict[str, Any]:
    path = (root or repo_root()) / "sites.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_dotenv(root: Path | None = None) -> None:
    path = (root or repo_root()) / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def apply_proxy_env() -> None:
    if os.environ.get("MAAS_PROXY_SKIP"):
        return
    proxy = (
        os.environ.get("MAAS_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("ALL_PROXY")
    )
    if not proxy:
        import socket

        for port in (10808, 10809, 7890, 1087):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    proxy = f"socks5h://127.0.0.1:{port}"
                    break
            except OSError:
                continue
    if not proxy:
        return
    os.environ.setdefault("MAAS_PROXY", proxy)
    os.environ.setdefault("ALL_PROXY", proxy)
    os.environ.setdefault("HTTPS_PROXY", proxy)
    os.environ.setdefault("HTTP_PROXY", proxy)


def site_entry(sites: dict[str, Any], site_id: str | None) -> tuple[str, dict[str, Any]]:
    sid = site_id or sites.get("default_site")
    if not sid:
        raise SystemExit("No site specified and sites.json has no default_site")
    entry = sites.get("sites", {}).get(sid)
    if not entry:
        raise SystemExit(f"Unknown site: {sid}")
    return sid, entry


def api_key_for(site: dict[str, Any]) -> str:
    env_name = site["api_key_env"]
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise SystemExit(
            f"Missing API key: set {env_name} in .env (see .env.example)"
        )
    return key


def _http_opener(url: str = "") -> urllib.request.OpenerDirector:
    from urllib.parse import urlparse

    host = urlparse(url).hostname if url else ""
    if host in {"127.0.0.1", "localhost", "::1"}:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    proxy = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("ALL_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("MAAS_PROXY")
    )
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener()


def http_json(
    method: str,
    url: str,
    api_key: str,
    body: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: float = 60,
) -> tuple[int, Any, float]:
    """Return (http_status, payload, latency_ms)."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    t0 = time.perf_counter()
    try:
        with _http_opener(url).open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            return resp.status, json.loads(raw) if raw else None, latency_ms
    except urllib.error.HTTPError as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload: Any = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw
        return exc.code, payload, latency_ms
    except (TimeoutError, socket.timeout) as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return 0, {"error": {"message": str(exc), "type": "timeout"}}, latency_ms
    except urllib.error.URLError as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return 0, {"error": {"message": str(reason), "type": "timeout"}}, latency_ms
        if "timed out" in str(reason).lower():
            return 0, {"error": {"message": str(reason), "type": "timeout"}}, latency_ms
        raise SystemExit(f"Network error for {url}: {reason}") from exc


def wire_probe_timeout_sec(*, via_relay: bool, root: Path | None = None) -> float:
    """HTTP timeout for Layer 2/3 wire probes (relay hops need more headroom)."""
    plan = load_assess_plan(root)
    raw = plan.get("relay_probe_timeout_sec" if via_relay else "source_probe_timeout_sec")
    default = 180.0 if via_relay else 120.0
    try:
        return max(30.0, float(raw))
    except (TypeError, ValueError):
        return default


def cmd_list_sites(sites: dict[str, Any]) -> None:
    default = sites.get("default_site")
    for sid, entry in sites.get("sites", {}).items():
        mark = " (default)" if sid == default else ""
        name = entry.get("name", sid)
        base = entry.get("base_url", "")
        print(f"{sid}{mark}\t{name}\t{base}")


def cmd_get(args: argparse.Namespace, sites: dict[str, Any]) -> None:
    if args.field == "default_site":
        print(sites.get("default_site", ""))
        return
    sid, site = site_entry(sites, args.site)
    field = args.field
    if field == "json":
        print(json.dumps(site, ensure_ascii=False, indent=2))
    elif field == "api_key_env":
        print(site["api_key_env"])
    elif field == "base_url":
        print(site["base_url"])
    elif field == "anthropic_base_url":
        print(
            site.get(
                "anthropic_base_url",
                site["base_url"].rstrip("/").removesuffix("/v1"),
            )
        )
    elif field == "default_model":
        agent = args.agent
        if not agent:
            raise SystemExit("--agent required for default_model")
        fam = assess_family_from_args(args) or resolve_family_for_site_agent(
            sid, site, agent
        )
        print(layer3_models(sid, site, family=fam, profile=fam).get(agent, ""))
    elif field == "default_family":
        agent = args.agent
        if not agent:
            raise SystemExit("--agent required for default_family")
        fam = assess_family_from_args(args) or resolve_family_for_site_agent(
            sid, site, agent
        )
        print(fam or "")
    elif field == "notes":
        print(site.get("notes", ""))
    elif field == "litellm_master_key":
        print(litellm_master_key(sid))
    elif field == "litellm_port":
        print(litellm_port(site))
    elif field == "litellm_relay_base":
        print(litellm_relay_base(site))
    elif field == "protocol":
        print(resolve_protocol(sid, site))
    elif field == "assess_agents":
        fam = assess_family_from_args(args)
        if fam:
            print(",".join(agents_for_assess(sid, site, family=fam, profile=fam)))
        else:
            print(",".join(agents_in_scope_for_site(sid, site)))
    elif field in ("families", "profiles"):
        print(",".join(list_assess_families(sid)))
    elif field == "primary_agent":
        fam = assess_family_from_args(args)
        if not fam:
            fams = list_assess_families(sid)
            if len(fams) == 1:
                fam = fams[0]
            else:
                raise SystemExit(
                    f"--family required for primary_agent (site has families: {fams})"
                )
        entry = plan_site_entry(sid, site=site, family=fam, profile=fam)
        primary = entry.get("primary_agent")
        if not primary and fam:
            primary = family_meta(fam, load_assess_plan()).get("primary_agent")
        print(primary or "")
    elif field == "opencode_provider_id":
        fam = assess_family_from_args(args) or resolve_family_for_site_agent(
            sid, site, "opencode"
        )
        oc = opencode_provider(sid, site, family=fam, profile=fam)
        print(oc.get("provider_id", "custom"))
    elif field == "opencode_model":
        fam = assess_family_from_args(args) or resolve_family_for_site_agent(
            sid, site, "opencode"
        )
        model = layer3_models(sid, site, family=fam, profile=fam).get("opencode", "")
        provider = opencode_provider(
            sid, site, family=fam, profile=fam
        ).get("provider_id", "custom")
        if not model:
            raise SystemExit("No layer3.models.opencode for site")
        print(f"{provider}/{model}")
    else:
        raise SystemExit(f"Unknown field: {field}")


def cmd_list_models(args: argparse.Namespace, sites: dict[str, Any]) -> None:
    load_dotenv()
    sid, site = site_entry(sites, args.site)
    key = api_key_for(site)
    base = site["base_url"].rstrip("/")
    status, payload, _latency = http_json("GET", f"{base}/models", key)
    if status != 200:
        raise SystemExit(f"GET /v1/models failed ({status}): {payload}")
    models = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(models, list):
        raise SystemExit(f"Unexpected /v1/models payload: {payload!r}")
    for item in models[: args.limit or None]:
        if isinstance(item, dict):
            print(item.get("id", item))
        else:
            print(item)


def litellm_master_key(site_id: str) -> str:
    return f"sk-litellm-{site_id}"


def litellm_port(site: dict[str, Any]) -> int:
    return int(site.get("litellm", {}).get("port", 4000))


def litellm_relay_base(site: dict[str, Any]) -> str:
    port = litellm_port(site)
    return f"http://127.0.0.1:{port}"


def write_claude_config(
    site: dict[str, Any],
    api_key: str,
    out: Path,
    relay_base: str | None = None,
) -> None:
    if relay_base:
        anthropic_base = relay_base.rstrip("/")
    else:
        anthropic_base = site.get(
            "anthropic_base_url",
            site["base_url"].rstrip("/").removesuffix("/v1"),
        )
    payload = {
        "env": {
            "ANTHROPIC_BASE_URL": anthropic_base,
            "ANTHROPIC_AUTH_TOKEN": api_key,
            "ANTHROPIC_API_KEY": api_key,
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_codex_config(
    site: dict[str, Any],
    model: str,
    out: Path,
    relay_base: str | None = None,
) -> None:
    if relay_base:
        openai_base = f"{relay_base.rstrip('/')}/v1"
    else:
        openai_base = site["base_url"]
    lines = [
        f'model = "{model}"',
        f'openai_base_url = "{openai_base}"',
        "",
    ]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")


def write_opencode_config(
    site_id: str,
    site: dict[str, Any],
    api_key: str,
    model: str,
    out: Path,
    relay_base: str | None = None,
    family: str | None = None,
) -> None:
    oc = opencode_provider(site_id, site, family=family)
    provider_id = oc.get("provider_id", site.get("name", "custom").lower())
    provider_name = oc.get("provider_name", site.get("name", provider_id))
    npm = oc.get("npm", "@ai-sdk/openai-compatible")
    base_url = f"{relay_base.rstrip('/')}/v1" if relay_base else site["base_url"]
    payload = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{provider_id}/{model}",
        "provider": {
            provider_id: {
                "npm": npm,
                "name": provider_name,
                "options": {
                    "baseURL": base_url,
                    "apiKey": api_key,
                },
                "models": {
                    model: {"name": model},
                },
            }
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def litellm_relay_model_name(
    site_id: str,
    site: dict[str, Any],
    agent: str,
    *,
    family: str | None = None,
    profile: str | None = None,
) -> str:
    """LiteLLM model_name exposed to Agent; disambiguate Codex bridge when id collides."""
    dm = layer3_models(site_id, site, family=family, profile=profile)
    model = dm.get(agent, "")
    if not model:
        return ""
    if agent == "codex" and dm.get("opencode") == model:
        return f"{model}-codex-relay"
    return model


def write_litellm_config(
    site_id: str,
    site: dict[str, Any],
    out: Path,
    port: int | None = None,
    profile: str | None = None,
    family: str | None = None,
) -> None:
    """Generate LiteLLM proxy config: upstream relay + protocol conversion hooks."""
    api_key_env = site["api_key_env"]
    base_url = site["base_url"].rstrip("/")
    anthropic_base = site.get("anthropic_base_url", base_url.removesuffix("/v1"))
    defaults = layer3_models(
        site_id, site, profile=profile, family=family
    )
    listen_port = port if port is not None else litellm_port(site)
    master_key = litellm_master_key(site_id)
    upstream_key = os.environ.get(api_key_env, "").strip()
    if not upstream_key:
        raise SystemExit(
            f"Missing {api_key_env} in environment — source .env before write-litellm-config"
        )

    # (litellm model_name, upstream model id, api_base, bridge)
    model_entries: list[tuple[str, str, str, bool]] = []
    protocol = resolve_protocol(site_id, site)
    allowed_agents = set(PROTOCOL_PROFILES[protocol]["agents"])

    profile_agents = agents_for_assess(
        site_id, site, profile=profile, family=family
    )
    for agent in profile_agents:
        if agent not in allowed_agents:
            continue
        upstream = defaults.get(agent, "")
        if not upstream:
            continue
        relay_name = litellm_relay_model_name(
            site_id, site, agent, family=family, profile=family
        )
        upstream_base = anthropic_base if agent == "claude" else base_url
        bridge = agent == "codex"
        model_entries.append((relay_name, upstream, upstream_base, bridge))

    lines = [
        "# Generated by lib/maas.py write-litellm-config — do not commit secrets",
        f"# Topology: Agent → 127.0.0.1:{listen_port} (LiteLLM) → {base_url}",
        "# Metering: proxy stdout → .runtime/litellm.<site>.log; full spend DB needs PostgreSQL",
        "",
        "model_list:",
    ]
    for relay_name, upstream_model, upstream_base, bridge in model_entries:
        lines.extend([
            f"  - model_name: {relay_name}",
            "    litellm_params:",
            f"      model: {upstream_model}",
            f"      api_base: {upstream_base}",
            f"      api_key: os.environ/{api_key_env}",
        ])
        if bridge:
            lines.append("      custom_llm_provider: custom")
        else:
            lines.append("      custom_llm_provider: openai")
        lines.append("")

    lines.extend([
        "general_settings:",
        f"  master_key: {master_key}",
        "",
        "litellm_settings:",
        "  drop_params: true",
        "",
    ])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")


def cmd_write_config(args: argparse.Namespace, sites: dict[str, Any]) -> None:
    load_dotenv()
    sid, site = site_entry(sites, args.site)
    agent = args.kind
    fam = assess_family_from_args(args) or resolve_family_for_site_agent(
        sid, site, agent
    )
    relay_base = litellm_relay_base(site)
    api_key = litellm_master_key(sid)
    out = Path(args.out)
    if args.kind == "claude":
        write_claude_config(site, api_key, out, relay_base=relay_base)
    elif args.kind == "codex":
        dm = layer3_models(sid, site, family=fam, profile=fam)
        model = (
            args.model
            or litellm_relay_model_name(sid, site, "codex", family=fam, profile=fam)
            or dm.get("codex", "")
        )
        if not model:
            raise SystemExit("No model specified and assess-plan has no layer3.models.codex")
        write_codex_config(site, model, out, relay_base=relay_base)
    elif args.kind == "opencode":
        model = args.model or layer3_models(
            sid, site, family=fam, profile=fam
        ).get("opencode", "")
        if not model:
            raise SystemExit("No model specified and assess-plan has no layer3.models.opencode")
        write_opencode_config(
            sid, site, api_key, model, out, relay_base=relay_base, family=fam
        )
    print(out)


def cmd_write_litellm_config(args: argparse.Namespace, sites: dict[str, Any]) -> None:
    load_dotenv()
    sid, site = site_entry(sites, args.site)
    api_key_for(site)
    out = Path(args.out)
    port = args.port if args.port else litellm_port(site)
    fam = assess_family_from_args(args)
    write_litellm_config(sid, site, out, port=port, family=fam, profile=fam)
    print(out)


def probe_label(status: int, ok_codes: set[int]) -> str:
    if status in ok_codes:
        return "OK"
    if status == 0:
        return "TIMEOUT"
    if status in {401, 403}:
        return f"HTTP {status}"
    if status == 404:
        return "HTTP 404"
    return f"HTTP {status}"


def wire_probe_url(
    site: dict[str, Any],
    base: str,
    agent_id: str,
    endpoint: str,
    *,
    via_relay: bool = False,
) -> str:
    if via_relay:
        return f"{base.rstrip('/')}{endpoint.removeprefix('/v1')}"
    if agent_id == "claude":
        anthropic = site.get(
            "anthropic_base_url",
            base.rstrip("/").removesuffix("/v1"),
        ).rstrip("/")
        return f"{anthropic}/v1/messages"
    return f"{base.rstrip('/')}{endpoint.removeprefix('/v1')}"


def load_assess_plan(root: Path | None = None) -> dict[str, Any]:
    base = root or repo_root()
    for name in ("assess-plan.json", "assess-models.json"):
        path = base / name
        if path.is_file():
            with path.open(encoding="utf-8") as fh:
                return json.load(fh)
    raise SystemExit("Missing assess-plan.json (see CONFIG.md)")


def load_assess_models(root: Path | None = None) -> dict[str, Any]:
    """Alias for load_assess_plan (legacy name)."""
    return load_assess_plan(root)


def site_family_map(entry: dict[str, Any]) -> dict[str, Any]:
    """Per-site model families (profiles is a deprecated alias)."""
    fam = entry.get("families")
    if isinstance(fam, dict):
        return fam
    prof = entry.get("profiles")
    if isinstance(prof, dict):
        return prof
    return {}


def list_assess_families(site_id: str, plan: dict[str, Any] | None = None) -> list[str]:
    cfg = plan if plan is not None else load_assess_plan()
    entry = cfg.get("sites", {}).get(site_id, {})
    return sorted(site_family_map(entry))


def list_assess_profiles(site_id: str, plan: dict[str, Any] | None = None) -> list[str]:
    """Deprecated alias for list_assess_families."""
    return list_assess_families(site_id, plan)


def family_meta(family_key: str, plan: dict[str, Any]) -> dict[str, Any]:
    builtin: dict[str, dict[str, Any]] = {
        "gpt": {
            "label": "GPT / OpenAI",
            "primary_agent": "codex",
            "layer2_wires": ["chat", "responses"],
            "layer3_agents": ["opencode", "codex"],
        },
        "anthropic": {
            "label": "Anthropic / Claude",
            "primary_agent": "claude",
            "layer2_wires": ["chat", "messages"],
            "layer3_agents": ["opencode", "claude"],
        },
        "other": {
            "label": "Other (OpenCode probe)",
            "primary_agent": "opencode",
            "layer2_wires": ["chat"],
            "layer3_agents": ["opencode"],
        },
    }
    global_defs = plan.get("model_families", {})
    if family_key in global_defs:
        base = dict(builtin.get(family_key, {}))
        base.update(global_defs[family_key])
        return base
    if family_key in builtin:
        return builtin[family_key]
    raise SystemExit(
        f"Unknown model family {family_key!r}; expected one of: "
        f"{sorted({*builtin, *global_defs})}"
    )


def assess_family_from_args(args: argparse.Namespace) -> str | None:
    return getattr(args, "family", None) or getattr(args, "profile", None) or None


def resolve_assess_family(
    site_id: str,
    entry: dict[str, Any],
    plan: dict[str, Any],
    *,
    family: str | None = None,
    profile: str | None = None,
) -> str | None:
    key = family or profile
    fam_map = site_family_map(entry)
    if key:
        if key not in fam_map:
            raise SystemExit(
                f"Unknown model family {key!r} for site {site_id}; "
                f"available: {sorted(fam_map) or '(none — omit --family)'}"
            )
        return key
    if len(fam_map) == 1:
        return next(iter(fam_map))
    return None


def resolve_family_for_site_agent(
    site_id: str,
    site: dict[str, Any],
    agent: str,
    plan: dict[str, Any] | None = None,
    *,
    family: str | None = None,
    profile: str | None = None,
) -> str | None:
    """Resolve model family: explicit flag, single-family site, or agent default."""
    cfg = plan if plan is not None else load_assess_plan()
    entry = cfg.get("sites", {}).get(site_id, {})
    key = family or profile
    if key:
        resolve_assess_family(site_id, entry, cfg, family=key, profile=profile)
        return key
    auto = resolve_assess_family(site_id, entry, cfg)
    if auto:
        return auto

    fam_map = site_family_map(entry)
    if not fam_map:
        return None

    matches: list[str] = []
    for fam_key in sorted(fam_map):
        if agent in agents_for_assess(site_id, site, cfg, family=fam_key):
            matches.append(fam_key)
    if len(matches) == 1:
        return matches[0]

    preferred = {"codex": "gpt", "claude": "anthropic"}.get(agent)
    if preferred and preferred in matches:
        return preferred

    if agent == "opencode":
        for candidate in ("gpt", "anthropic", "other"):
            if candidate in matches:
                return candidate

    if not matches:
        raise SystemExit(
            f"Agent {agent!r} is not in any model family for site {site_id}; "
            "check assess-plan.json families.*.layer3.agents"
        )

    raise SystemExit(
        f"Agent {agent!r} is valid in multiple families {matches} for site {site_id}; "
        "pass --family (e.g. --family gpt)"
    )


def expand_family_overlay(
    site_entry: dict[str, Any],
    family_key: str,
    fam_cfg: dict[str, Any],
    plan: dict[str, Any],
    site_id: str,
    site: dict[str, Any],
) -> dict[str, Any]:
    meta = family_meta(family_key, plan)
    protocol = resolve_protocol(site_id, site)
    proto_wires = set(PROTOCOL_PROFILES[protocol]["wires"])

    models = fam_cfg.get("models", [])
    if isinstance(models, str):
        models = [models]
    wires = fam_cfg.get("layer2_wires") or meta.get("layer2_wires", ["chat"])
    filtered_wires = [w for w in wires if w in proto_wires]
    targets = [{"model": str(m), "wires": filtered_wires or ["chat"]} for m in models]

    base_l3 = dict(site_entry.get("layer3") or {})
    ol3 = fam_cfg.get("layer3") or {}
    if not isinstance(ol3, dict):
        ol3 = {}
    models_map = dict(ol3.get("models") or {})
    default_model = str(models[0]) if models else ""
    if default_model:
        models_map.setdefault("opencode", default_model)
        primary = meta.get("primary_agent")
        if primary:
            models_map.setdefault(str(primary), default_model)

    agents = ol3.get("agents") or meta.get("layer3_agents", ["opencode"])
    allowed = set(PROTOCOL_PROFILES[protocol]["agents"])
    agents = [str(a) for a in agents if a in allowed]

    merged_l3: dict[str, Any] = {
        k: v for k, v in base_l3.items() if k not in ("models", "agents", "opencode")
    }
    merged_l3.update({k: v for k, v in ol3.items() if k not in ("models", "agents", "opencode")})
    merged_l3["models"] = models_map
    merged_l3["agents"] = agents
    if ol3.get("opencode"):
        merged_l3["opencode"] = ol3["opencode"]
    elif base_l3.get("opencode"):
        merged_l3["opencode"] = base_l3["opencode"]

    primary = fam_cfg.get("primary_agent") or meta.get("primary_agent")
    return {
        "layer2": {"targets": targets},
        "layer3": merged_l3,
        "assess_family": family_key,
        "assess_family_label": meta.get("label", family_key),
        "primary_agent": primary,
    }


def plan_site_entry(
    site_id: str,
    plan: dict[str, Any] | None = None,
    site: dict[str, Any] | None = None,
    *,
    family: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    cfg = plan if plan is not None else load_assess_plan()
    entry = dict(cfg.get("sites", {}).get(site_id, {}))
    if site is None:
        sites = load_sites()
        _, site = site_entry(sites, site_id)

    fam_key = resolve_assess_family(
        site_id, entry, cfg, family=family, profile=profile
    )
    fam_map = site_family_map(entry)

    if fam_key:
        expanded = expand_family_overlay(
            entry, fam_key, fam_map[fam_key], cfg, site_id, site
        )
        entry["layer2"] = expanded["layer2"]
        entry["layer3"] = expanded["layer3"]
        entry["assess_family"] = expanded["assess_family"]
        entry["assess_family_label"] = expanded["assess_family_label"]
        entry["primary_agent"] = expanded["primary_agent"]
        return entry

    if fam_map and not layer2_raw_targets(entry):
        raise SystemExit(
            f"Site {site_id} has model families {sorted(fam_map)}; "
            "pass --family for Layer 2–3 (e.g. --family gpt)"
        )
    return entry


def agents_for_assess(
    site_id: str,
    site: dict[str, Any],
    plan: dict[str, Any] | None = None,
    profile: str | None = None,
    family: str | None = None,
) -> list[str]:
    protocol = resolve_protocol(site_id, site)
    entry = plan_site_entry(
        site_id, plan, site, family=family, profile=profile
    )
    custom = entry.get("layer3", {}).get("agents")
    allowed = PROTOCOL_PROFILES[protocol]["agents"]
    if isinstance(custom, list) and custom:
        return [str(a) for a in custom if a in allowed]
    return list(allowed)


def agents_in_scope_for_site(
    site_id: str,
    site: dict[str, Any],
    plan: dict[str, Any] | None = None,
) -> list[str]:
    cfg = plan if plan is not None else load_assess_plan()
    entry = cfg.get("sites", {}).get(site_id, {})
    fam_map = site_family_map(entry)
    if fam_map:
        agents: set[str] = set()
        for fam_key in fam_map:
            agents.update(
                agents_for_assess(site_id, site, cfg, family=fam_key)
            )
        return sorted(agents)
    return list(PROTOCOL_PROFILES[resolve_protocol(site_id, site)]["agents"])


def layer3_models(
    site_id: str,
    site: dict[str, Any],
    plan: dict[str, Any] | None = None,
    profile: str | None = None,
    family: str | None = None,
) -> dict[str, Any]:
    entry = plan_site_entry(
        site_id, plan, site, family=family, profile=profile
    )
    models = entry.get("layer3", {}).get("models")
    if isinstance(models, dict) and models:
        return models
    legacy = site.get("default_models")
    if isinstance(legacy, dict):
        return legacy
    return {}


def opencode_provider(
    site_id: str,
    site: dict[str, Any],
    plan: dict[str, Any] | None = None,
    profile: str | None = None,
    family: str | None = None,
) -> dict[str, Any]:
    entry = plan_site_entry(
        site_id, plan, site, family=family, profile=profile
    )
    oc = entry.get("layer3", {}).get("opencode") or entry.get("opencode")
    if isinstance(oc, dict):
        return oc
    legacy = site.get("opencode")
    if isinstance(legacy, dict):
        return legacy
    return {}


def layer2_raw_targets(entry: dict[str, Any]) -> list[dict[str, Any]] | None:
    l2 = entry.get("layer2", {})
    if l2.get("targets"):
        return l2["targets"]
    if entry.get("targets"):
        return entry["targets"]
    return None


def parse_models_catalog(payload: Any) -> list[str]:
    models: list[Any] = []
    if isinstance(payload, dict):
        models = payload.get("data", []) or []
    elif isinstance(payload, list):
        models = payload
    ids: list[str] = []
    for item in models:
        if isinstance(item, dict):
            mid = item.get("id", "")
            if mid:
                ids.append(str(mid))
        elif item:
            ids.append(str(item))
    return ids


def fetch_models_catalog(
    site: dict[str, Any], key: str
) -> tuple[str, int, list[str], Any, float]:
    """Return (branch, http_status, model_ids, raw_payload, latency_ms).

    branch: listed | empty | unavailable
    """
    base = site["base_url"].rstrip("/")
    st, payload, latency_ms = http_json("GET", f"{base}/models", key)
    if st != 200:
        return "unavailable", st, [], payload, latency_ms
    ids = parse_models_catalog(payload)
    if ids:
        return "listed", st, ids, payload, latency_ms
    return "empty", st, [], payload, latency_ms


AGENT_LABELS = {
    "claude": "Claude Code",
    "codex": "Codex",
    "opencode": "OpenCode",
}

AGENT_WIRES = {
    "claude": "/v1/messages",
    "codex": "/v1/responses",
    "opencode": "/v1/chat/completions",
}

AGENT_TO_WIRES = {
    "opencode": ["chat"],
    "claude": ["messages"],
    "codex": ["responses"],
}


PROTOCOL_PROFILES: dict[str, dict[str, Any]] = {
    "anthropic": {
        "label": "Anthropic-compatible",
        "agents": ["opencode", "claude"],
        "wires": ["chat", "messages"],
    },
    "openai": {
        "label": "OpenAI-compatible",
        "agents": ["opencode", "codex"],
        "wires": ["chat", "responses"],
    },
    "chat": {
        "label": "Chat Completions only",
        "agents": ["opencode"],
        "wires": ["chat"],
    },
}


def resolve_protocol(site_id: str, site: dict[str, Any]) -> str:
    proto = site.get("protocol") or "openai"
    if proto not in PROTOCOL_PROFILES:
        raise SystemExit(
            f"Unknown protocol {proto!r} for site {site_id}; "
            f"expected anthropic | openai | chat (sites.json)"
        )
    return str(proto)


def wire_default_model(wire: str, default_models: dict[str, Any]) -> str | None:
    if wire == "chat":
        return default_models.get("opencode")
    if wire == "messages":
        return default_models.get("claude")
    if wire == "responses":
        return default_models.get("codex")
    return None


def default_assess_targets(
    site_id: str, site: dict[str, Any], protocol: str
) -> list[dict[str, Any]]:
    dm = layer3_models(site_id, site)
    wires = PROTOCOL_PROFILES[protocol]["wires"]
    by_model: dict[str, list[str]] = {}
    for wire in wires:
        model = wire_default_model(wire, dm)
        if not model:
            continue
        by_model.setdefault(str(model), []).append(wire)
    return [{"model": model, "wires": ws} for model, ws in by_model.items()]


def expand_assess_targets(
    raw_targets: list[dict[str, Any]], protocol: str
) -> list[dict[str, Any]]:
    allowed = PROTOCOL_PROFILES[protocol]["wires"]
    out: list[dict[str, Any]] = []
    for target in raw_targets:
        model = target["model"]
        wires = target.get("wires") or list(allowed)
        filtered = [w for w in wires if w in allowed]
        if filtered:
            out.append({"model": model, "wires": filtered})
    return out


def relay_model_and_wire_for_agent(
    site_id: str,
    site: dict[str, Any],
    agent: str,
    root: Path | None = None,
    profile: str | None = None,
    family: str | None = None,
) -> tuple[str, str]:
    """Layer 3 model+wire: assess-plan layer3.models[agent], else layer2 fallback."""
    plan = load_assess_plan(root)
    models = layer3_models(site_id, site, plan, profile=profile, family=family)
    model = models.get(agent)
    if model:
        wires = AGENT_TO_WIRES.get(agent, [])
        if wires:
            return str(model), wires[0]
    protocol, targets = assess_targets_for_site(
        site_id, site, root, profile=profile, family=family
    )
    relay_target = relay_target_for_agent(targets, agent)
    if relay_target:
        return relay_target
    fam = family or profile
    raise SystemExit(
        f"No model for agent {agent!r} (set layer3.models.{agent} or layer2 target "
        f"with wire in {AGENT_TO_WIRES.get(agent, [])!r}; family={fam or 'default'})"
    )


def assess_targets_for_site(
    site_id: str,
    site: dict[str, Any],
    root: Path | None = None,
    profile: str | None = None,
    family: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    cfg = load_assess_plan(root)
    protocol = resolve_protocol(site_id, site)
    entry = plan_site_entry(
        site_id, cfg, site, family=family, profile=profile
    )
    raw = layer2_raw_targets(entry)
    if raw:
        targets = expand_assess_targets(raw, protocol)
    else:
        targets = default_assess_targets(site_id, site, protocol)
    return protocol, targets


def relay_target_for_agent(
    targets: list[dict[str, Any]], agent: str
) -> tuple[str, str] | None:
    """Return (model, wire) from Layer 2 targets for the given agent."""
    allowed = AGENT_TO_WIRES.get(agent, [])
    for target in targets:
        model = target["model"]
        for wire in target.get("wires", []):
            if wire in allowed:
                return model, wire
    return None


WIRE_TO_AGENT = {
    "chat": "opencode",
    "messages": "claude",
    "responses": "codex",
}

WIRE_TO_ENDPOINT = {
    "chat": "/v1/chat/completions",
    "messages": "/v1/messages",
    "responses": "/v1/responses",
}


def probe_wire_body(wire: str, model: str) -> tuple[dict[str, Any], dict[str, str] | None]:
    return smoke_wire_body(wire, model, "Reply OK", max_tokens=16)


def smoke_wire_body(
    wire: str,
    model: str,
    prompt: str,
    *,
    max_tokens: int = 512,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    if wire == "chat":
        return (
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
            },
            None,
        )
    if wire == "messages":
        return (
            {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            {"anthropic-version": "2023-06-01"},
        )
    if wire == "responses":
        return ({"model": model, "input": prompt, "max_output_tokens": max_tokens}, None)
    raise ValueError(f"Unknown wire: {wire}")


def error_detail(payload: Any) -> str:
    if not payload:
        return ""
    if isinstance(payload, dict):
        err = payload.get("error", payload)
        if isinstance(err, dict):
            msg = err.get("message") or err.get("code") or str(err)
            return str(msg)[:160]
        return str(err)[:160]
    return str(payload)[:160]


def response_excerpt(payload: Any, limit: int = 160) -> str:
    if not payload:
        return ""
    text = str(payload) if not isinstance(payload, dict) else json.dumps(payload, ensure_ascii=False)
    return text[:limit]


def format_probe_body_summary(wire: str, body: dict[str, Any]) -> str:
    model = body.get("model", "?")
    if wire == "chat":
        n_msg = len(body.get("messages") or [])
        return (
            f"model={model!r}, messages[{n_msg}], "
            f"max_tokens={body.get('max_tokens', '?')}, stream={body.get('stream', False)}"
        )
    if wire == "messages":
        n_msg = len(body.get("messages") or [])
        return (
            f"model={model!r}, messages[{n_msg}], "
            f"max_tokens={body.get('max_tokens', '?')}, stream={body.get('stream', False)}"
        )
    if wire == "responses":
        inp = body.get("input", "")
        inp_len = len(inp) if isinstance(inp, str) else "?"
        return (
            f"model={model!r}, input_len={inp_len}, "
            f"max_output_tokens={body.get('max_output_tokens', '?')}, "
            f"stream={body.get('stream', False)}"
        )
    return json.dumps(body, ensure_ascii=False)[:120]


def payload_top_level_summary(payload: Any) -> str:
    if payload is None:
        return "(empty body)"
    if not isinstance(payload, dict):
        return f"non-JSON body ({type(payload).__name__}): {str(payload)[:120]}"
    keys = sorted(payload.keys())
    parts = [f"keys=[{', '.join(keys)}]"]
    if "object" in payload:
        parts.append(f"object={payload.get('object')!r}")
    if "error" in payload:
        parts.append(f"error={error_detail(payload)!r}")
    data = payload.get("data")
    if isinstance(data, list):
        parts.append(f"data[{len(data)}]")
    choices = payload.get("choices")
    if isinstance(choices, list):
        parts.append(f"choices[{len(choices)}]")
    output = payload.get("output")
    if isinstance(output, list):
        parts.append(f"output[{len(output)}]")
    usage = payload.get("usage")
    if isinstance(usage, dict) and usage:
        usage_bits = [
            f"{k}={usage[k]}"
            for k in (
                "total_tokens",
                "input_tokens",
                "output_tokens",
                "prompt_tokens",
                "completion_tokens",
            )
            if k in usage
        ]
        if usage_bits:
            parts.append("usage{" + ", ".join(usage_bits) + "}")
    return "; ".join(parts)


def describe_facet_lines(wire: str, facets: dict[str, Any], http_status: int) -> list[str]:
    shape = facets.get("shape", "?")
    usage = facets.get("usage", "?")
    stream = facets.get("stream", "?")
    lines: list[str] = []
    if http_status != 200:
        lines.append(f"shape={shape}: skipped (HTTP {http_status})")
    elif shape == "ok":
        if wire == "chat":
            lines.append("shape=ok: choices[0] has message.content or text")
        elif wire == "messages":
            lines.append("shape=ok: content block or string present")
        elif wire == "responses":
            lines.append("shape=ok: output[] or output_text present")
        else:
            lines.append("shape=ok")
    elif shape == "empty":
        lines.append(f"shape=empty: HTTP 200 but no extractable {wire} payload text")
    else:
        lines.append(f"shape={shape}: response not in expected {wire} envelope")

    if usage == "ok":
        lines.append("usage=ok: usage block reports token counts > 0")
    elif usage == "zero":
        lines.append("usage=zero: usage present but all token fields are 0")
    elif usage == "missing":
        lines.append("usage=missing: no usage block or no recognized token fields")
    else:
        lines.append(f"usage={usage}")

    if stream == "ok":
        ms = facets.get("stream_latency_ms")
        suffix = f" ({ms} ms)" if ms is not None else ""
        lines.append(f"stream=ok: SSE follow-up saw data:/event: markers{suffix}")
    elif stream == "fail":
        ms = facets.get("stream_latency_ms")
        suffix = f" ({ms} ms)" if ms is not None else ""
        lines.append(f"stream=fail: SSE follow-up missing expected markers{suffix}")
    elif stream == "skip":
        lines.append("stream=skip: not probed (sync call failed or stream check disabled)")
    else:
        lines.append(f"stream={stream}")
    return lines


def print_wire_protocol_exchange(
    model: str,
    wire: str,
    endpoint: str,
    probe: dict[str, Any],
    *,
    hop: str = "source direct",
    auth_note: str = "Authorization: Bearer <api_key_env>",
) -> None:
    """Terminal-only protocol detail (not used by report markdown)."""
    req = probe.get("request") or {}
    body = req.get("body") or {}
    extra = req.get("extra_headers") or {}
    url = probe.get("url", "")
    st = probe.get("http_status", 0)
    print("")
    print(f"  ▶ {model} · {wire} · {endpoint} ({hop})")
    print(f"    POST {url}")
    print(f"    Request: {format_probe_body_summary(wire, body)}")
    if extra:
        print(f"    Extra headers: {', '.join(f'{k}={v!r}' for k, v in extra.items())}")
    print(f"    Auth: {auth_note}")
    print(
        f"    Sync response: HTTP {st} · {probe.get('latency_ms', 0)} ms · "
        f"result={probe.get('result', '?')}"
    )
    print(f"    Envelope: {payload_top_level_summary(probe.get('payload'))}")
    detail = probe.get("detail") or ""
    if detail:
        print(f"    Excerpt: {detail}")
    facets = probe.get("facets") or {}
    for line in describe_facet_lines(wire, facets, st):
        print(f"    · {line}")
    stream_body = probe.get("stream_request")
    if stream_body:
        print(f"    Stream follow-up: POST {url}")
        print(
            f"    Stream request: {format_probe_body_summary(wire, stream_body)}; "
            "Accept=text/event-stream"
        )


def wire_response_shape(wire: str, payload: Any) -> str:
    """Hard-gate facet: ok | empty | missing."""
    if not isinstance(payload, dict):
        return "missing"
    if wire == "chat":
        choices = payload.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return "missing"
        choice = choices[0]
        msg = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        content = msg.get("content") or choice.get("text") or choice.get("delta")
        return "ok" if content else "empty"
    if wire == "messages":
        content = payload.get("content")
        if isinstance(content, list) and content:
            return "ok"
        if isinstance(content, str) and content.strip():
            return "ok"
        return "empty" if content is not None else "missing"
    if wire == "responses":
        output = payload.get("output")
        if isinstance(output, list) and output:
            return "ok"
        text = payload.get("output_text") or payload.get("text")
        return "ok" if text else "empty"
    return "missing"


def wire_usage_facet(payload: Any) -> str:
    """Soft facet: ok | zero | missing."""
    if not isinstance(payload, dict):
        return "missing"
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return "missing"
    for key in ("total_tokens", "input_tokens", "output_tokens", "prompt_tokens", "completion_tokens"):
        val = usage.get(key)
        if isinstance(val, (int, float)) and val > 0:
            return "ok"
    if usage:
        return "zero"
    return "missing"


def probe_wire_stream(
    site: dict[str, Any],
    key: str,
    model: str,
    wire: str,
    *,
    probe_base: str | None = None,
    root: Path | None = None,
) -> tuple[str, float]:
    """Soft facet: ok | fail | skip. Returns (status, latency_ms)."""
    via_relay = probe_base is not None
    base = (probe_base or site["base_url"]).rstrip("/")
    agent_id = WIRE_TO_AGENT[wire]
    endpoint = WIRE_TO_ENDPOINT[wire]
    body, extra = probe_wire_body(wire, model)
    body["stream"] = True
    url = wire_probe_url(site, base, agent_id, endpoint, via_relay=via_relay)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if extra:
        headers.update(extra)
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    stream_timeout = wire_probe_timeout_sec(via_relay=via_relay, root=root)
    t0 = time.perf_counter()
    try:
        with _http_opener(url).open(req, timeout=stream_timeout) as resp:
            chunk = resp.read(2048)
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    except (TimeoutError, socket.timeout, urllib.error.HTTPError, urllib.error.URLError):
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return "fail", latency_ms
    markers = (b"data:", b"event:", b"content_block_delta", b"response.output_text.delta")
    if any(m in chunk for m in markers):
        return "ok", latency_ms
    return "fail", latency_ms


def probe_model_wire(
    site: dict[str, Any],
    key: str,
    model: str,
    wire: str,
    *,
    probe_base: str | None = None,
    check_stream: bool = True,
    root: Path | None = None,
) -> dict[str, Any]:
    via_relay = probe_base is not None
    base = (probe_base or site["base_url"]).rstrip("/")
    agent_id = WIRE_TO_AGENT[wire]
    endpoint = WIRE_TO_ENDPOINT[wire]
    body, extra = probe_wire_body(wire, model)
    url = wire_probe_url(site, base, agent_id, endpoint, via_relay=via_relay)
    timeout = wire_probe_timeout_sec(via_relay=via_relay, root=root)
    st, payload, latency_ms = http_json(
        "POST", url, key, body, extra_headers=extra, timeout=timeout
    )
    shape = wire_response_shape(wire, payload) if st == 200 else "missing"
    usage = wire_usage_facet(payload) if st == 200 else "missing"
    hard_ok = st == 200 and shape == "ok"
    if st != 200:
        result = probe_label(st, {200})
        detail = error_detail(payload)
    elif not hard_ok:
        result = "EMPTY"
        detail = f"HTTP 200 but shape={shape}"
    else:
        result = "OK"
        detail = response_excerpt(payload)
    facets: dict[str, Any] = {"shape": shape, "usage": usage}
    if check_stream and hard_ok:
        stream_status, stream_ms = probe_wire_stream(
            site, key, model, wire, probe_base=probe_base, root=root
        )
        facets["stream"] = stream_status
        facets["stream_latency_ms"] = stream_ms
    else:
        facets["stream"] = "skip"
    stream_request: dict[str, Any] | None = None
    if check_stream and hard_ok:
        stream_request = dict(body)
        stream_request["stream"] = True
    return {
        "http_status": st,
        "result": result,
        "detail": detail,
        "latency_ms": latency_ms,
        "facets": facets,
        "url": url,
        "payload": payload,
        "request": {"method": "POST", "body": body, "extra_headers": extra or {}},
        "stream_request": stream_request,
    }


def site_supported_models(site: dict[str, Any]) -> list[str]:
    """Vendor-documented model ids from sites.json (not asserted by GET /v1/models)."""
    raw = site.get("supported_models", [])
    if not isinstance(raw, list):
        return []
    return [str(m) for m in raw if m]


def print_supported_vs_catalog(
    supported: list[str], catalog_ids: list[str], *, catalog_label: str = "catalog"
) -> None:
    if not supported:
        return
    print("")
    print("Supported models (sites.json / vendor docs, not /v1/models):")
    for mid in supported:
        print(f"  - {mid}")
    if not catalog_ids:
        return
    doc_set = set(supported)
    cat_set = set(catalog_ids)
    print("")
    print(f"Documentation vs {catalog_label}:")
    for mid in sorted(doc_set & cat_set):
        print(f"  {mid}: in both")
    for mid in sorted(doc_set - cat_set):
        print(f"  {mid}: docs only")
    for mid in sorted(cat_set - doc_set):
        print(f"  {mid}: {catalog_label} only")


def run_layer1(sid: str, site: dict[str, Any], key: str) -> dict[str, Any]:
    branch, st, ids, payload, latency_ms = fetch_models_catalog(site, key)
    protocol = resolve_protocol(sid, site)
    proto_prof = PROTOCOL_PROFILES[protocol]
    plan = load_assess_plan()
    families = list_assess_families(sid, plan)
    supported = site_supported_models(site)
    doc_set, cat_set = set(supported), set(ids)
    platform_ok = st == 200
    if branch == "listed":
        catalog_verdict = "PASS"
    elif branch == "empty":
        catalog_verdict = "WARN"
    else:
        catalog_verdict = "FAIL"
    return {
        "pass": platform_ok and branch != "unavailable",
        "platform_link": platform_ok,
        "catalog_verdict": catalog_verdict,
        "http_status": st,
        "latency_ms": latency_ms,
        "catalog_branch": branch,
        "catalog_ids": ids,
        "supported_models": supported,
        "docs_only": sorted(doc_set - cat_set),
        "catalog_only": sorted(cat_set - doc_set),
        "in_both": sorted(doc_set & cat_set),
        "protocol": protocol,
        "protocol_label": proto_prof["label"],
        "model_families": families,
        "agents_in_scope": [
            AGENT_LABELS[a] for a in agents_in_scope_for_site(sid, site, plan)
        ],
        "error_detail": error_detail(payload) if branch == "unavailable" else "",
        "catalog_envelope": payload_top_level_summary(payload) if st == 200 else "",
    }


def print_layer1(
    sid: str, site: dict[str, Any], result: dict[str, Any], *, verbose: bool = False
) -> None:
    print("Layer 1 — Platform link (/v1/models)")
    print(f"Site: {sid} ({site.get('name', sid)})")
    print(f"Base: {site['base_url']}")
    print(f"Auth: {site['api_key_env']} (Bearer)")
    print("")
    models_url = f"{site['base_url'].rstrip('/')}/models"
    print(f"GET /v1/models: {probe_label(result['http_status'], {200})} ({result['latency_ms']} ms)")
    if verbose:
        print(f"  GET {models_url}")
        print(f"  Auth: Authorization: Bearer ({site['api_key_env']})")
        if result.get("catalog_envelope"):
            print(f"  Response envelope: {result['catalog_envelope']}")
    elif result["http_status"] != 200 and result.get("error_detail"):
        print(f"  Error: {result['error_detail']}")
    print(f"Catalog branch: {result['catalog_branch']}")
    print(f"Transport protocol: {result['protocol']} ({result['protocol_label']})")
    if result.get("model_families"):
        print(f"Model families: {', '.join(result['model_families'])}")
    print(f"Agents in scope (all families): {', '.join(result['agents_in_scope'])}")
    branch = result["catalog_branch"]
    ids = result["catalog_ids"]
    supported = result["supported_models"]
    if branch == "listed":
        print(f"Catalog count: {len(ids)}")
        print("Catalog ids:")
        for mid in ids[:20]:
            print(f"  - {mid}")
        print_supported_vs_catalog(supported, ids)
        print("")
        print("Platform link: PASS")
        print(f"Catalog: {result['catalog_verdict']} (listed)")
    elif branch == "empty":
        print("Catalog count: 0")
        print_supported_vs_catalog(supported, [])
        print("")
        print("Platform link: PASS")
        print(f"Catalog: {result['catalog_verdict']} (empty → Layer 2 blind-tests assess-plan.json layer2)")
    else:
        print("")
        if result["error_detail"]:
            print(f"Detail: {result['error_detail']}")
        print_supported_vs_catalog(supported, [])
        print("Platform link: FAIL")
        print(f"Catalog: {result['catalog_verdict']} (unavailable → Layer 2 blind-tests assess-plan.json layer2)")


def cmd_assess_platform(args: argparse.Namespace, sites: dict[str, Any]) -> None:
    """Layer 1: GET /v1/models — platform link + catalog branch."""
    load_dotenv()
    sid, site = site_entry(sites, args.site)
    key = api_key_for(site)
    result = run_layer1(sid, site, key)
    print_layer1(sid, site, result, verbose=getattr(args, "verbose", False))
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))


def run_layer2(
    sid: str,
    site: dict[str, Any],
    key: str,
    root: Path | None = None,
    assess_family: str | None = None,
    assess_profile: str | None = None,
) -> dict[str, Any]:
    fam = assess_family or assess_profile
    branch, _, catalog_ids, _, _catalog_ms = fetch_models_catalog(site, key)
    catalog_set = set(catalog_ids)
    protocol, targets = assess_targets_for_site(
        sid, site, root, family=fam, profile=fam
    )
    prof = PROTOCOL_PROFILES[protocol]
    plan_agents = agents_for_assess(sid, site, family=fam, profile=fam)
    plan_entry = plan_site_entry(
        sid, load_assess_plan(root), site, family=fam, profile=fam
    )
    supported = site_supported_models(site)
    rows: list[dict[str, Any]] = []
    wire_best: dict[str, tuple[str, str]] = {}

    for target in targets:
        model = target["model"]
        for wire in target.get("wires", []):
            endpoint = WIRE_TO_ENDPOINT.get(wire, wire)
            probe = probe_model_wire(site, key, model, wire, root=root)
            rows.append({
                "model": model,
                "wire": wire,
                "endpoint": endpoint,
                "result": probe["result"],
                "detail": probe["detail"],
                "latency_ms": probe["latency_ms"],
                "http_status": probe["http_status"],
                "facets": probe["facets"],
                "interaction": probe,
            })
            if probe["result"] == "OK":
                wire_best[wire] = (model, probe["result"])
            elif wire not in wire_best:
                wire_best[wire] = (model, probe["result"])

    agent_readiness: dict[str, bool] = {}
    for agent_id in plan_agents:
        agent_wires = AGENT_TO_WIRES[agent_id]
        agent_readiness[agent_id] = any(
            r["result"] == "OK" and r["wire"] in agent_wires for r in rows
        )
    any_ok = any(agent_readiness.values())

    target_catalog: list[dict[str, str]] = []
    for t in targets:
        mid = t["model"]
        target_catalog.append({
            "model": mid,
            "in_catalog": "yes" if mid in catalog_set else "no",
            "in_supported_models": "yes" if mid in supported else "no",
        })

    return {
        "pass": any_ok,
        "catalog_branch": branch,
        "protocol": protocol,
        "protocol_label": prof["label"],
        "agents_in_scope": [AGENT_LABELS[a] for a in plan_agents],
        "wires_in_scope": prof["wires"],
        "targets": targets,
        "target_catalog": target_catalog,
        "rows": rows,
        "wire_best": {
            w: {"model": wire_best[w][0], "result": wire_best[w][1]}
            for w in wire_best
        },
        "agent_readiness": agent_readiness,
        "assess_family": plan_entry.get("assess_family") or fam,
        "assess_family_label": plan_entry.get("assess_family_label", ""),
        "primary_agent": plan_entry.get("primary_agent", ""),
        "assess_profile": fam,
    }


def print_layer2(
    sid: str,
    site: dict[str, Any],
    result: dict[str, Any],
    *,
    verbose: bool = False,
) -> None:
    print("Layer 2 — Model × wire (source direct)")
    if result.get("assess_family"):
        label = result.get("assess_family_label") or result["assess_family"]
        primary = result.get("primary_agent", "")
        extra = f" · primary Agent: {primary}" if primary else ""
        print(f"Model family: {result['assess_family']} ({label}){extra}")
    elif result.get("assess_profile"):
        print(f"Model family: {result['assess_profile']}")
    print(f"Site: {sid} ({site.get('name', sid)})")
    print(f"OpenAI base: {site['base_url']}")
    print(
        f"Anthropic base: {site.get('anthropic_base_url', site['base_url'].rstrip('/').removesuffix('/v1'))}"
    )
    print(f"Catalog branch: {result['catalog_branch']}")
    print(f"Protocol profile: {result['protocol']} ({result['protocol_label']})")
    print(f"Agents in scope: {', '.join(result['agents_in_scope'])}")
    print(f"Wires in scope: {', '.join(result['wires_in_scope'])}")
    print(f"Config: assess-plan.json → sites.{sid}.layer2")
    print("")

    if result["catalog_branch"] == "listed":
        print("Model list comparison (assess-plan layer2 vs /v1/models):")
        for row in result["target_catalog"]:
            if row["in_catalog"] == "yes":
                print(f"  {row['model']}: in catalog")
            else:
                print(f"  {row['model']}: NOT in catalog (still probed)")
        if any(r["in_supported_models"] == "yes" for r in result["target_catalog"]):
            print("")
            print("Assess targets vs supported_models (vendor docs):")
            for row in result["target_catalog"]:
                if row["in_supported_models"] == "yes":
                    print(f"  {row['model']}: in supported_models")
                else:
                    print(f"  {row['model']}: NOT in supported_models (still probed)")
        print("")

    if result["catalog_branch"] in {"empty", "unavailable"}:
        print("Blind test mode: using assess-plan.json layer2 targets")
        print("")

    print(f"{'Model':<22} {'Wire':<12} {'Endpoint':<22} {'HTTP':<6} {'ms':<8} Result   Facets")
    print("-" * 118)
    for row in result["rows"]:
        facets = row.get("facets") or {}
        facet_str = (
            f"shape={facets.get('shape','?')} "
            f"usage={facets.get('usage','?')} "
            f"stream={facets.get('stream','?')}"
        )
        http_st = row.get("http_status", "—")
        line = (
            f"{row['model']:<22} {row['wire']:<12} {row['endpoint']:<22} "
            f"{http_st!s:<6} {row.get('latency_ms', 0):<8} {row['result']:<8} {facet_str}"
        )
        print(line)
        if not verbose and row.get("detail") and row["result"] != "OK":
            print(f"  ↳ {row['detail'][:140]}")

    if verbose:
        print("")
        print("Protocol exchanges (sync POST + optional SSE follow-up):")
        auth_note = f"Authorization: Bearer ({site['api_key_env']})"
        for row in result["rows"]:
            interaction = row.get("interaction")
            if interaction:
                print_wire_protocol_exchange(
                    row["model"],
                    row["wire"],
                    row["endpoint"],
                    interaction,
                    hop="source direct",
                    auth_note=auth_note,
                )
    else:
        print("")
        print("  (use --verbose for per-wire protocol exchange detail)")

    print("")
    print("Wire summary (best result per wire among tested models):")
    for wire in result["wires_in_scope"]:
        if wire in result["wire_best"]:
            wb = result["wire_best"][wire]
            agent = AGENT_LABELS[WIRE_TO_AGENT[wire]]
            print(f"  {wire} ({agent}): {wb['result']} via model {wb['model']}")
        else:
            print(f"  {wire}: not tested")

    print("")
    print("Agent native readiness (any OK on wire):")
    for agent_id, ok in result["agent_readiness"].items():
        print(f"  {AGENT_LABELS[agent_id]}: {'yes' if ok else 'no'}")

    print("")
    verdict = "PASS" if result["pass"] else "FAIL"
    print(f"Layer 2 verdict: {verdict} (any wire OK in protocol scope)")


def cmd_assess_protocol(args: argparse.Namespace, sites: dict[str, Any]) -> None:
    """Layer 2: model × wire on source (assess-plan.json layer2)."""
    load_dotenv()
    root = repo_root()
    sid, site = site_entry(sites, args.site)
    key = api_key_for(site)
    fam = assess_family_from_args(args)
    result = run_layer2(sid, site, key, root, assess_family=fam)
    print_layer2(sid, site, result, verbose=getattr(args, "verbose", False))
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["pass"]:
        raise SystemExit(1)


def ensure_litellm_proxy(
    site_id: str,
    profile: str | None = None,
    family: str | None = None,
) -> None:
    root = repo_root()
    script = root / "scripts" / "litellm-proxy.sh"
    cmd = [str(script), "start", "--site", site_id]
    fam = family or profile
    if fam:
        cmd.extend(["--family", fam])
    subprocess.run(cmd, cwd=str(root), check=True)


def run_layer3_relay(
    sid: str,
    site: dict[str, Any],
    agent: str,
    root: Path | None = None,
    port: int | None = None,
    profile: str | None = None,
    family: str | None = None,
) -> dict[str, Any]:
    fam = family or profile
    protocol = resolve_protocol(sid, site)
    prof = PROTOCOL_PROFILES[protocol]
    scope = agents_for_assess(sid, site, family=fam, profile=fam)
    if agent not in scope:
        raise SystemExit(
            f"Agent {agent!r} not in assess scope for {sid!r} "
            f"(family={fam or 'default'}; in scope: {', '.join(scope)})"
        )
    model, wire = relay_model_and_wire_for_agent(
        sid, site, agent, root, family=fam, profile=fam
    )
    plan_entry = plan_site_entry(
        sid, load_assess_plan(root), site, family=fam, profile=fam
    )
    listen_port = port if port is not None else litellm_port(site)
    key = litellm_master_key(sid)
    probe_base = f"http://127.0.0.1:{listen_port}/v1"
    endpoint = WIRE_TO_ENDPOINT[wire]
    bridge = agent == "codex"
    probe = probe_model_wire(
        site, key, model, wire, probe_base=probe_base, root=root
    )
    return {
        "pass": probe["result"] == "OK",
        "agent": agent,
        "agent_label": AGENT_LABELS[agent],
        "model": model,
        "wire": wire,
        "endpoint": endpoint,
        "wire_label": AGENT_WIRES[agent],
        "relay_base": probe_base,
        "upstream": site["base_url"],
        "protocol": protocol,
        "protocol_label": prof["label"],
        "relay_mode": "bridge" if bridge else "passthrough",
        "result": probe["result"],
        "detail": probe["detail"],
        "latency_ms": probe["latency_ms"],
        "facets": probe["facets"],
        "http_status": probe["http_status"],
        "interaction": probe,
        "assess_family": plan_entry.get("assess_family") or fam,
        "primary_agent": plan_entry.get("primary_agent", ""),
        "profile": fam,
    }


def print_layer3_relay(
    sid: str, site: dict[str, Any], result: dict[str, Any], *, verbose: bool = False
) -> None:
    print("Layer 3 — Relay wire probe (Agent → LiteLLM → source)")
    if result.get("assess_family"):
        primary = result.get("primary_agent", "")
        extra = f" · primary: {primary}" if primary else ""
        print(f"Model family: {result['assess_family']}{extra}")
    elif result.get("profile"):
        print(f"Model family: {result['profile']}")
    print(f"Site: {sid} ({site.get('name', sid)})")
    print(f"Protocol profile: {result['protocol']} ({result['protocol_label']})")
    print(f"Relay: {result['relay_base']}")
    print(f"Upstream: {result['upstream']}")
    print(f"Agent: {result['agent_label']} ({result['wire_label']})")
    print(f"Model: {result['model']}")
    if result["relay_mode"] == "bridge":
        print("Relay mode: bridge (Codex Responses → upstream Chat via LiteLLM)")
    else:
        print("Relay mode: passthrough (same wire to upstream)")
    print("")
    print(f"{'Method':<6} {'Endpoint':<24} {'HTTP':<6} {'ms':<8} Result   Facets")
    print("-" * 96)
    facets = result.get("facets") or {}
    facet_str = (
        f"shape={facets.get('shape','?')} "
        f"usage={facets.get('usage','?')} "
        f"stream={facets.get('stream','?')}"
    )
    http_st = result.get("http_status", "—")
    print(
        f"{'POST':<6} {result['endpoint']:<24} "
        f"{http_st!s:<6} {result.get('latency_ms', 0):<8} {result['result']:<8} {facet_str}"
    )
    if not verbose and result.get("detail") and result["result"] != "OK":
        print(f"  ↳ {result['detail'][:140]}")
    interaction = result.get("interaction")
    if verbose and interaction:
        hop = (
            "Agent → LiteLLM → source (passthrough)"
            if result.get("relay_mode") == "passthrough"
            else "Agent → LiteLLM → source (Codex bridge)"
        )
        auth_note = f"Authorization: Bearer (LiteLLM master_key sk-litellm-{sid})"
        print("")
        print("Protocol exchange (relay hop):")
        print_wire_protocol_exchange(
            result["model"],
            result["wire"],
            result["endpoint"],
            interaction,
            hop=hop,
            auth_note=auth_note,
        )
        print(f"    Upstream target: {result['upstream']} (platform key via LiteLLM config)")
    elif not verbose:
        print("  (use --verbose for relay protocol exchange detail)")
    print("")
    verdict = "PASS" if result["pass"] else "FAIL"
    print(f"Layer 3 relay wire: {verdict}")


def cmd_probe_relay(args: argparse.Namespace, sites: dict[str, Any]) -> None:
    """Layer 3: probe one Agent main wire via LiteLLM relay."""
    load_dotenv()
    root = repo_root()
    sid, site = site_entry(sites, args.site)
    agent = args.agent
    if not agent:
        raise SystemExit("--agent required for probe-relay")
    port = args.port if args.port else litellm_port(site)
    fam = assess_family_from_args(args) or resolve_family_for_site_agent(
        sid, site, agent
    )
    result = run_layer3_relay(sid, site, agent, root, port=port, family=fam)
    print_layer3_relay(sid, site, result, verbose=getattr(args, "verbose", False))
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["pass"]:
        raise SystemExit(1)


DEFAULT_SMOKE_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "model_probe",
        "tags": ["anti-speculation", "identity"],
        "required": True,
        "model_probe": True,
        "prompt": (
            "Respond with ONLY one JSON object — no markdown fences, no extra text. "
            'Required keys: "model" (your exact model identifier as you know it), '
            '"release_date" (ISO-8601 date when you were released, or "unknown"), '
            '"knowledge_cutoff" (your knowledge cutoff date, or "unknown"). '
            "Be factual about your identity; do not claim to be a different model."
        ),
        "expect_json_keys": ["model", "release_date"],
        "expect_model_match": True,
    },
    {
        "id": "explain",
        "tags": ["generation"],
        "required": True,
        "prompt": "Explain what an API gateway does in two short sentences.",
        "min_output_chars": 40,
    },
    {
        "id": "structured",
        "tags": ["format"],
        "required": True,
        "prompt": 'Reply with only one line of valid JSON: {"status":"ok"}',
        "expect_json_key": "status",
        "expect_json_value": "ok",
    },
    {
        "id": "code",
        "tags": ["code"],
        "required": True,
        "prompt": (
            "Write a Python function named add that takes a and b. "
            "Output only the code block."
        ),
        "expect_contains": "def add",
    },
    {
        "id": "tool",
        "tags": ["tool"],
        "required": False,
        "agent_only": True,
        "agents": {
            "opencode": {
                "prompt": (
                    "List the file names in the current directory only, "
                    "one per line. Do not use markdown."
                ),
            },
            "codex": {
                "argv": [
                    "exec",
                    "Create /tmp/maas-smoke.txt containing TOOL_OK, then print TOOL_OK",
                ],
            },
            "claude": {
                "prompt": (
                    "Read CONFIG.md in the current directory and reply with "
                    "its first markdown heading text only."
                ),
            },
        },
    },
]


def load_smoke_mode(root: Path | None = None) -> str:
    plan = load_assess_plan(root)
    mode = str(plan.get("smoke_mode", "relay")).strip().lower()
    if mode not in {"relay", "agent"}:
        return "relay"
    return mode


def normalize_model_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def model_ids_match(reported: str, expected: str) -> bool:
    reported_n = normalize_model_id(reported)
    expected_n = normalize_model_id(expected)
    if not reported_n or not expected_n:
        return False
    return expected_n in reported_n or reported_n in expected_n


def wire_response_text(wire: str, payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    if wire == "chat":
        choices = payload.get("choices") or []
        if choices and isinstance(choices[0], dict):
            choice = choices[0]
            msg = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            return str(msg.get("content") or choice.get("text") or "")
        return ""
    if wire == "messages":
        content = payload.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            return "".join(parts)
        return ""
    if wire == "responses":
        output = payload.get("output")
        if isinstance(output, list):
            parts = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "message" and isinstance(item.get("content"), list):
                    for block in item["content"]:
                        if isinstance(block, dict) and block.get("text"):
                            parts.append(str(block["text"]))
                elif item.get("text"):
                    parts.append(str(item["text"]))
            if parts:
                return "".join(parts)
        return str(payload.get("output_text") or payload.get("text") or "")
    return ""


def run_smoke_scenario_relay(
    site_id: str,
    site: dict[str, Any],
    agent: str,
    prompt: str,
    root: Path | None = None,
    profile: str | None = None,
) -> tuple[str, float, int, dict[str, Any]]:
    """Run one smoke prompt via Agent main wire through LiteLLM relay."""
    model, wire = relay_model_and_wire_for_agent(site_id, site, agent, root, profile)
    listen_port = litellm_port(site)
    key = litellm_master_key(site_id)
    probe_base = f"http://127.0.0.1:{listen_port}/v1"
    via_relay = True
    base = probe_base.rstrip("/")
    agent_id = WIRE_TO_AGENT[wire]
    endpoint = WIRE_TO_ENDPOINT[wire]
    body, extra = smoke_wire_body(wire, model, prompt)
    url = wire_probe_url(site, base, agent_id, endpoint, via_relay=via_relay)
    st, payload, latency_ms = http_json("POST", url, key, body, extra_headers=extra)
    text = wire_response_text(wire, payload) if st == 200 else error_detail(payload)
    response_model = str(payload.get("model", "")) if isinstance(payload, dict) else ""
    meta = {
        "mode": "relay",
        "model": model,
        "wire": wire,
        "endpoint": endpoint,
        "http_status": st,
        "response_model": response_model,
    }
    return text, latency_ms, 0 if st == 200 and text else 1, meta


def load_smoke_scenarios(site_id: str, root: Path | None = None) -> list[dict[str, Any]]:
    plan = load_assess_plan(root)
    entry = plan_site_entry(site_id, plan)
    custom = entry.get("layer3", {}).get("scenarios")
    if isinstance(custom, list) and custom:
        return custom
    global_scenarios = plan.get("smoke_scenarios")
    if isinstance(global_scenarios, list) and global_scenarios:
        return global_scenarios
    return DEFAULT_SMOKE_SCENARIOS


def resolve_smoke_scenario(
    scenario: dict[str, Any], agent: str
) -> dict[str, Any] | None:
    agents_block = scenario.get("agents")
    if isinstance(agents_block, dict) and agent in agents_block:
        merged = {**scenario, **agents_block[agent]}
    elif scenario.get("prompt") or scenario.get("argv"):
        merged = dict(scenario)
    else:
        return None
    merged.pop("agents", None)
    return merged


def smoke_timeout_sec(root: Path | None = None) -> int:
    plan = load_assess_plan(root)
    raw = plan.get("smoke_timeout_sec", 120)
    try:
        return max(30, int(raw))
    except (TypeError, ValueError):
        return 120


def opencode_model_ref(
    site_id: str,
    root: Path | None = None,
    family: str | None = None,
) -> str:
    plan = load_assess_plan(root)
    sites = load_sites(root)
    _, site = site_entry(sites, site_id)
    fam = family or resolve_family_for_site_agent(site_id, site, "opencode", plan)
    models = layer3_models(site_id, site, plan, family=fam, profile=fam)
    model = models.get("opencode", "")
    provider = opencode_provider(
        site_id, site, plan, family=fam, profile=fam
    ).get("provider_id", "custom")
    return f"{provider}/{model}"


def parse_opencode_json_output(text: str) -> str:
    """Collect assistant text from opencode --format json line events."""
    parts: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        part = event.get("text") or event.get("content") or event.get("delta")
        if isinstance(part, str) and part:
            parts.append(part)
        msg = event.get("message")
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, str):
                parts.append(content)
        data = event.get("data")
        if isinstance(data, dict):
            inner = data.get("text") or data.get("content")
            if isinstance(inner, str):
                parts.append(inner)
    if parts:
        return "".join(parts)
    return text


def smoke_agent_command(
    root: Path,
    site_id: str,
    agent: str,
    resolved: dict[str, Any],
    family: str | None = None,
) -> list[str]:
    base = [str(root / f"t_{agent}"), "--site", site_id, "-y"]
    if family:
        base.extend(["--family", family])
    base.append("--")
    if agent == "claude":
        return base + [
            "--print",
            "--max-budget-usd",
            "1.00",
            str(resolved["prompt"]),
        ]
    if agent == "codex":
        argv = resolved.get("argv")
        if isinstance(argv, list) and argv:
            return base + [str(x) for x in argv]
        return base + ["exec", str(resolved["prompt"])]
    model_ref = opencode_model_ref(site_id, root, family=family)
    extra = resolved.get("opencode_args") or ["run", "--format", "json", "-m", model_ref]
    if isinstance(extra, list):
        cmd = base + [str(x) for x in extra]
    else:
        cmd = base + ["run", "--format", "json", "-m", model_ref]
    cmd.append(str(resolved["prompt"]))
    return cmd


def extract_json_object(text: str) -> Any | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{[^{}]*\}", text)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            return None
    return None


def is_generic_model_name(reported: str) -> bool:
    n = normalize_model_id(reported)
    if len(n) < 3:
        return True
    return n in {
        "chatgpt",
        "openai",
        "assistant",
        "unknown",
        "aichatbot",
        "languagemodel",
    }


def evaluate_smoke_output(
    resolved: dict[str, Any],
    output: str,
    exit_code: int,
    *,
    response_model: str = "",
) -> tuple[bool, str, dict[str, Any]]:
    extra: dict[str, Any] = {}
    if exit_code != 0:
        return False, f"exit {exit_code}", extra
    text = output.strip()
    expect = resolved.get("expect_contains")
    if expect and str(expect) not in text:
        return False, f"missing substring {expect!r}", extra
    min_chars = resolved.get("min_output_chars")
    if isinstance(min_chars, int) and len(text) < min_chars:
        return False, f"output shorter than {min_chars} chars", extra

    json_keys = resolved.get("expect_json_keys")
    json_key = resolved.get("expect_json_key")
    if json_keys or json_key:
        obj = extract_json_object(text)
        if not isinstance(obj, dict):
            return False, "no JSON object in output", extra
        keys = json_keys if isinstance(json_keys, list) else ([json_key] if json_key else [])
        for key in keys:
            if key not in obj or obj.get(key) in (None, ""):
                return False, f"JSON missing key {key!r}", extra
        if json_key and not json_keys:
            expect_val = resolved.get("expect_json_value")
            if expect_val is not None and obj.get(json_key) != expect_val:
                return False, f"JSON {json_key}!={expect_val!r}", extra
        if resolved.get("model_probe") or resolved.get("expect_model_match"):
            reported = str(obj.get("model", ""))
            expected = str(resolved.get("expect_model_id", ""))
            extra["reported_model"] = reported
            extra["reported_release_date"] = obj.get("release_date")
            extra["reported_knowledge_cutoff"] = obj.get("knowledge_cutoff")
            if response_model:
                extra["response_model"] = response_model
            # Hard fail: API response model id disagrees with catalog target
            if response_model and expected and not model_ids_match(response_model, expected):
                return (
                    False,
                    f"API model mismatch: {response_model!r} vs expected {expected!r}",
                    extra,
                )
            # Self-report: warn on mismatch unless clearly same family or generic brand
            if expected and reported:
                if model_ids_match(reported, expected):
                    extra["model_match"] = True
                elif response_model and model_ids_match(reported, response_model):
                    extra["model_match"] = True
                elif is_generic_model_name(reported):
                    extra["model_match"] = "generic"
                    extra["model_probe_note"] = f"generic self-report {reported!r}"
                else:
                    extra["model_match"] = False
                    extra["model_probe_note"] = (
                        f"self-report {reported!r} vs expected {expected!r}"
                    )
    return True, "", extra


def output_excerpt(text: str, limit: int = 240) -> str:
    compact = re.sub(r"\s+", " ", text.strip())
    return compact[:limit]


def run_layer3_smoke(
    site_id: str,
    agent: str,
    root: Path | None = None,
    profile: str | None = None,
    family: str | None = None,
) -> dict[str, Any]:
    root = root or repo_root()
    sites = load_sites(root)
    _, site = site_entry(sites, site_id)
    fam = (
        family
        or profile
        or resolve_family_for_site_agent(site_id, site, agent)
    )
    scenarios = load_smoke_scenarios(site_id, root)
    smoke_mode = load_smoke_mode(root)
    expected_model = layer3_models(
        site_id, site, profile=fam, family=fam
    ).get(agent, "")
    if fam:
        print(f"Model family: {fam}")
    rows: list[dict[str, Any]] = []
    required_failed = 0
    optional_failed = 0
    required_total = 0

    print(f"Smoke mode: {smoke_mode} (agent={agent}, expected_model={expected_model or '?'})")

    for scenario in scenarios:
        resolved = resolve_smoke_scenario(scenario, agent)
        if not resolved:
            continue
        sid = str(resolved.get("id", scenario.get("id", "unknown")))
        required = bool(resolved.get("required", scenario.get("required", True)))
        if required:
            required_total += 1
        prompt = resolved.get("prompt") or " ".join(resolved.get("argv") or [])
        req_mark = "required" if required else "optional"

        if resolved.get("agent_only") and smoke_mode != "agent":
            rows.append({
                "id": sid,
                "tags": resolved.get("tags") or scenario.get("tags") or [],
                "required": required,
                "prompt": str(prompt),
                "latency_ms": 0,
                "pass": not required,
                "reason": "skipped (agent_only; smoke_mode=relay)",
                "output_excerpt": "",
                "skipped": True,
            })
            if required:
                required_failed += 1
            print(f"  [{sid}] SKIP ({req_mark}) — agent_only in relay mode")
            continue

        if resolved.get("model_probe") or resolved.get("expect_model_match"):
            resolved["expect_model_id"] = expected_model

        t0 = time.perf_counter()
        meta: dict[str, Any] = {"mode": smoke_mode}
        timeout = smoke_timeout_sec(root)
        if not required and resolved.get("timeout_sec"):
            try:
                timeout = max(30, int(resolved["timeout_sec"]))
            except (TypeError, ValueError):
                pass

        if smoke_mode == "relay":
            try:
                text, latency_ms, exit_code, meta = run_smoke_scenario_relay(
                    site_id, site, agent, str(prompt), root, profile
                )
                output = text
                eval_text = text
            except SystemExit as exc:
                latency_ms = round((time.perf_counter() - t0) * 1000, 1)
                ok, reason, probe_extra = False, str(exc), {}
                if required:
                    required_failed += 1
                else:
                    optional_failed += 1
                row = {
                    "id": sid,
                    "tags": resolved.get("tags") or scenario.get("tags") or [],
                    "required": required,
                    "prompt": str(prompt),
                    "latency_ms": latency_ms,
                    "pass": ok,
                    "reason": reason,
                    "output_excerpt": "",
                    **probe_extra,
                }
                rows.append(row)
                print(f"  [{sid}] FAIL ({req_mark}, {latency_ms} ms) — {reason}")
                continue
        else:
            cmd = smoke_agent_command(root, site_id, agent, resolved, family=fam)
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                latency_ms = round((time.perf_counter() - t0) * 1000, 1)
                output = (exc.stdout or "") + (exc.stderr or "")
                ok, reason, probe_extra = False, f"timeout {timeout}s", {}
                if required:
                    required_failed += 1
                else:
                    optional_failed += 1
                rows.append({
                    "id": sid,
                    "tags": resolved.get("tags") or scenario.get("tags") or [],
                    "required": required,
                    "prompt": str(prompt),
                    "latency_ms": latency_ms,
                    "pass": ok,
                    "reason": reason,
                    "output_excerpt": output_excerpt(output),
                    **probe_extra,
                })
                print(f"  [{sid}] FAIL ({req_mark}, {latency_ms} ms) — {reason}")
                continue
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            output = (proc.stdout or "") + (proc.stderr or "")
            eval_text = parse_opencode_json_output(output) if agent == "opencode" else output
            exit_code = proc.returncode

        if smoke_mode == "relay":
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)

        ok, reason, probe_extra = evaluate_smoke_output(
            resolved,
            eval_text,
            exit_code,
            response_model=str(meta.get("response_model", "")),
        )
        if ok and probe_extra.get("model_match") is False:
            optional_failed += 1
            reason = probe_extra.get("model_probe_note") or reason
        if not ok:
            if required:
                required_failed += 1
            else:
                optional_failed += 1
        row = {
            "id": sid,
            "tags": resolved.get("tags") or scenario.get("tags") or [],
            "required": required,
            "prompt": str(prompt),
            "latency_ms": latency_ms,
            "pass": ok,
            "reason": reason,
            "output_excerpt": output_excerpt(output if smoke_mode == "relay" else eval_text),
            "smoke_mode": meta.get("mode", smoke_mode),
            **probe_extra,
        }
        if meta.get("model"):
            row["wire_model"] = meta["model"]
        if meta.get("response_model"):
            row["response_model"] = meta["response_model"]
        rows.append(row)
        status = "PASS" if ok else "FAIL"
        detail = f" — {reason}" if reason else ""
        if probe_extra.get("reported_model"):
            detail += f" (reported={probe_extra['reported_model']!r})"
        if probe_extra.get("response_model"):
            detail += f" (api_model={probe_extra['response_model']!r})"
        print(f"  [{sid}] {status} ({req_mark}, {latency_ms} ms){detail}")

    if not rows:
        return {"pass": False, "status": "fail", "scenarios": rows}

    if required_failed:
        status = "fail"
    elif optional_failed:
        status = "warn"
    else:
        status = "pass"

    passed = sum(1 for r in rows if r["pass"])
    skipped = sum(1 for r in rows if r.get("skipped"))
    executed = len(rows) - skipped
    passed_executed = sum(1 for r in rows if r["pass"] and not r.get("skipped"))
    return {
        "pass": status != "fail",
        "status": status,
        "passed": passed,
        "total": len(rows),
        "executed": executed,
        "passed_executed": passed_executed,
        "skipped": skipped,
        "smoke_mode": smoke_mode,
        "expected_model": expected_model,
        "required_failed": required_failed,
        "optional_failed": optional_failed,
        "scenarios": rows,
    }


def print_layer3_smoke(result: dict[str, Any]) -> None:
    print("")
    print("Layer 3 smoke — Agent scenarios")
    executed = result.get("executed", result.get("total", 0))
    passed_exec = result.get("passed_executed", result.get("passed", 0))
    skipped = result.get("skipped", 0)
    summary = f"Summary: {passed_exec}/{executed} executed passed"
    if skipped:
        summary += f"; {skipped} skipped (smoke_mode={result.get('smoke_mode', '?')})"
    summary += f" (status={result.get('status')})"
    print(summary)
    print("")
    print(f"{'ID':<12} {'Req':<5} {'ms':<8} {'Result':<6} Prompt")
    print("-" * 100)
    for row in result.get("scenarios", []):
        req = "yes" if row.get("required") else "no"
        if row.get("skipped"):
            mark = "SKIP"
        else:
            mark = "PASS" if row.get("pass") else "FAIL"
        prompt = str(row.get("prompt", ""))[:50]
        print(
            f"{row.get('id',''):<12} {req:<5} {row.get('latency_ms', 0):<8} "
            f"{mark:<6} {prompt}"
        )


def cmd_run_smoke(args: argparse.Namespace, sites: dict[str, Any]) -> None:
    """Layer 3 smoke: run assess-plan smoke scenarios through t_* launchers."""
    load_dotenv()
    root = repo_root()
    sid, _site = site_entry(sites, args.site)
    agent = args.agent
    fam = assess_family_from_args(args) or resolve_family_for_site_agent(
        sid, site, agent
    )
    ensure_litellm_proxy(sid, family=fam)
    result = run_layer3_smoke(sid, agent, root, family=fam)
    print_layer3_smoke(result)
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "fail":
        raise SystemExit(1)


def smoke_result_label(row: dict[str, Any]) -> str:
    if row.get("skipped"):
        return "SKIP"
    return "PASS" if row.get("pass") else "FAIL"


def factual_test_summary(
    layer1: dict[str, Any],
    layer2: dict[str, Any],
    layer3: dict[str, Any],
    *,
    smoke: str | None = None,
) -> str:
    l1 = "PASS" if layer1["pass"] else "FAIL"
    l2 = "PASS" if layer2["pass"] else "FAIL"
    l3 = "PASS" if layer3["pass"] else "FAIL"
    smoke_part = smoke.upper() if smoke else "NOT_RUN"
    return f"Layer1={l1}; Layer2={l2}; Layer3={l3}; smoke={smoke_part}"


def layer1_summary_note(layer1: dict[str, Any]) -> str:
    parts = [
        f"platform {'PASS' if layer1.get('platform_link') else 'FAIL'}",
        f"catalog {layer1.get('catalog_verdict', '?')} ({layer1.get('catalog_branch', '?')}, "
        f"{len(layer1.get('catalog_ids', []))} ids)",
    ]
    if layer1.get("docs_only"):
        parts.append("docs_only: " + ", ".join(f"`{m}`" for m in layer1["docs_only"]))
    if layer1.get("catalog_only"):
        parts.append("catalog_only: " + ", ".join(f"`{m}`" for m in layer1["catalog_only"]))
    return "; ".join(parts)


def smoke_summary_note(
    smoke: str | None,
    layer3_smoke: dict[str, Any] | None,
) -> str:
    if not smoke or not layer3_smoke:
        return "NOT_RUN"
    executed = layer3_smoke.get("executed", layer3_smoke.get("total", 0))
    passed_exec = layer3_smoke.get("passed_executed", layer3_smoke.get("passed", 0))
    skipped_n = layer3_smoke.get("skipped", 0)
    smoke_mode = layer3_smoke.get("smoke_mode", "relay")
    parts = [f"status={smoke.upper()}", f"executed {passed_exec}/{executed} PASS"]
    if skipped_n:
        parts.append(f"{skipped_n} SKIP")
    parts.append(f"smoke_mode={smoke_mode}")
    return "; ".join(parts)


def render_source_report(
    sid: str,
    site: dict[str, Any],
    day: str,
    layer1: dict[str, Any],
    layer2: dict[str, Any],
    layer3: dict[str, Any],
    *,
    agent: str,
    assess_family: str | None = None,
    smoke: str | None = None,
    layer3_smoke: dict[str, Any] | None = None,
    log_rel: str | None = None,
) -> str:
    fam = assess_family or layer2.get("assess_family")
    test_summary = factual_test_summary(layer1, layer2, layer3, smoke=smoke)
    domain = site_domain_label(sid, site)
    anthropic_base = site.get(
        "anthropic_base_url", site["base_url"].rstrip("/").removesuffix("/v1")
    )
    models_tested = sorted({r["model"] for r in layer2["rows"]})
    l1_verdict = "PASS" if layer1["pass"] else "FAIL"
    l2_verdict = "PASS" if layer2["pass"] else "FAIL"
    l3_verdict = "PASS" if layer3["pass"] else "FAIL"
    smoke_verdict = smoke.upper() if smoke else "NOT_RUN"

    lines: list[str] = [
        f"# {domain} 源评估报告",
        "",
        "| 项目 | 内容 |",
        "|------|------|",
        f"| **报告文件** | `{domain}-源评估报告-{day}.md` |",
        f"| **评估对象** | 上游源 `{domain}`（`experiment/user-side/sites.json`） |",
        f"| **站点 ID** | `{sid}` |",
        f"| **OpenAI Base** | `{site['base_url']}` |",
        f"| **Anthropic Base** | `{anthropic_base}` |",
        "| **评估方法** | [用户侧三层评估法](../experiment/EC2-用户侧隔离实验点设计.md#21-三层评估法) |",
        f"| **评估环境** | LiteLLM relay（`{layer3.get('relay_base', '127.0.0.1:4000/v1')}`）；"
        "`maas.py assess-source` 自动生成 |",
        f"| **评估日期** | {day} |",
        f"| **测试结果** | `{test_summary}` |",
        "",
        f"> **测试范围**：站点 `{sid}`"
        + (
            f"；模型族 `{layer2.get('assess_family')}`"
            f"（主 Agent `{layer2.get('primary_agent', '—')}`）"
            if layer2.get("assess_family")
            else ""
        )
        + f"；Layer 2 探测模型 {', '.join(f'`{m}`' for m in models_tested) or '（无）'}"
        f"；Layer 3 Agent `{agent}`"
        + (f"；smoke_mode `{layer3_smoke.get('smoke_mode')}`" if layer3_smoke else "")
        + "。",
        "",
        "---",
        "",
        "## 1. 执行摘要",
        "",
        "| 层 | 判定 | 说明 |",
        "|----|------|------|",
        f"| **1 平台链接** | {l1_verdict} | {layer1_summary_note(layer1)} |",
        f"| **2 基础协议** | {l2_verdict} | "
        + (
            f"family `{layer2.get('assess_family')}` · transport `{layer2['protocol']}`"
            if layer2.get("assess_family")
            else f"transport `{layer2['protocol']}`"
        )
        + " |",
        f"| **3 指定 Agent** | {l3_verdict} | `{agent}` · relay_mode `{layer3['relay_mode']}` · "
        f"result `{layer3['result']}` |",
        f"| **4 smoke** | {smoke_verdict} | {smoke_summary_note(smoke, layer3_smoke)} |",
        "",
        "---",
        "",
        "## 2. 第 1 层 — 平台链接",
        "",
        "| 检查项 | 结果 |",
        "|--------|------|",
        f"| Platform link | {'PASS' if layer1.get('platform_link') else 'FAIL'} |",
        f"| Catalog verdict | {layer1.get('catalog_verdict', '—')} |",
        f"| `GET /v1/models` | HTTP {layer1['http_status']} · **{layer1.get('latency_ms', '—')} ms** |",
        f"| Catalog 分支 | **{layer1['catalog_branch']}** |",
        f"| Catalog 条数 | {len(layer1['catalog_ids'])} |",
        "",
    ]

    if layer1["catalog_ids"]:
        lines.append("**Catalog ids**：")
        lines.append("")
        for mid in layer1["catalog_ids"][:30]:
            lines.append(f"- `{mid}`")
        lines.append("")

    if layer1["supported_models"]:
        lines.append("**supported_models（文档）vs catalog**：")
        lines.append("")
        for mid in layer1["in_both"]:
            lines.append(f"- `{mid}`：in both")
        for mid in layer1["docs_only"]:
            lines.append(f"- `{mid}`：docs only")
        for mid in layer1["catalog_only"]:
            lines.append(f"- `{mid}`：catalog only")
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 3. 第 2 层 — 源原生 wire",
        "",
        f"Protocol profile：**{layer2['protocol']}**（{layer2['protocol_label']}）",
        "",
        "| 模型 | Wire | 端点 | 耗时 | 结果 | 协议面 |",
        "|------|------|------|------|------|--------|",
    ])
    for row in layer2["rows"]:
        facets = row.get("facets") or {}
        facet_str = (
            f"shape={facets.get('shape','?')}, "
            f"usage={facets.get('usage','?')}, "
            f"stream={facets.get('stream','?')}"
        )
        lines.append(
            f"| `{row['model']}` | {row['wire']} | `{row['endpoint']}` | "
            f"{row.get('latency_ms', '—')} ms | {row['result']} | {facet_str} |"
        )
    lines.append("")
    lines.append("**Wire 汇总**（protocol scope，任一模型 OK 即记 yes）：")
    lines.append("")
    for agent_id, ok in layer2["agent_readiness"].items():
        lines.append(f"- {AGENT_LABELS[agent_id]}: **{'yes' if ok else 'no'}**")
    lines.append("")
    lines.append(
        f"**Layer 2 判定**：{'PASS' if layer2['pass'] else 'FAIL'}"
    )
    lines.extend([
        "",
        "---",
        "",
        "## 4. 第 3 层 — LiteLLM relay",
        "",
        f"拓扑：Agent → `{layer3['relay_base']}` → `{layer3['upstream']}`",
        "",
        "| 项 | 值 |",
        "|----|-----|",
        f"| Agent | {layer3['agent_label']} (`{agent}`) |",
        f"| Model | `{layer3['model']}` |",
        f"| Wire | `{layer3['endpoint']}` |",
        f"| Relay 模式 | {layer3['relay_mode']} |",
        f"| 耗时 | **{layer3.get('latency_ms', '—')} ms** |",
        f"| 结果 | **{layer3['result']}** |",
        "",
    ])
    l3_facets = layer3.get("facets") or {}
    if l3_facets:
        lines.extend([
            "**Relay 协议面**："
            f" shape={l3_facets.get('shape','?')},"
            f" usage={l3_facets.get('usage','?')},"
            f" stream={l3_facets.get('stream','?')}",
            "",
        ])
    lines.extend([
        f"**Layer 3 判定**：{'PASS' if layer3['pass'] else 'FAIL'}",
        "",
        "---",
        "",
    ])

    if layer3_smoke and layer3_smoke.get("scenarios"):
        executed = layer3_smoke.get("executed", layer3_smoke.get("total", 0))
        passed_exec = layer3_smoke.get("passed_executed", layer3_smoke.get("passed", 0))
        skipped_n = layer3_smoke.get("skipped", 0)
        smoke_mode_label = layer3_smoke.get("smoke_mode", "relay")
        expected_model = layer3_smoke.get("expected_model", "")
        summary = (
            f"Agent `{agent}` · smoke_mode `{smoke_mode_label}`"
            f" · expected_model `{expected_model}`"
            f" · executed {passed_exec}/{executed} PASS"
        )
        if skipped_n:
            summary += f" · {skipped_n} SKIP"
        lines.extend([
            "## 5. 第 4 层 — Agent smoke",
            "",
            summary,
            "",
            "| ID | 必选 | 耗时 | 判定 | API model | 自报 model | reason | 输出摘要 |",
            "|----|------|------|------|-----------|------------|--------|----------|",
        ])
        for row in layer3_smoke["scenarios"]:
            req = "是" if row.get("required") else "否"
            label = smoke_result_label(row)
            api_model = str(row.get("response_model") or "—").replace("|", "\\|")
            reported = str(row.get("reported_model", "—")).replace("|", "\\|")
            reason = str(row.get("reason") or row.get("model_probe_note") or "—").replace("|", "\\|")
            excerpt = str(row.get("output_excerpt", "")).replace("|", "\\|")
            lines.append(
                f"| `{row.get('id','')}` | {req} | {row.get('latency_ms', '—')} ms | "
                f"{label} | {api_model} | {reported} | {reason} | {excerpt} |"
            )
        lines.extend([
            "",
            f"**Smoke 判定**：{layer3_smoke.get('status', 'unknown').upper()}",
            "",
            "---",
            "",
            "## 6. 复现",
        ])
    else:
        lines.extend([
            "## 5. 复现",
        ])
    lines.extend([
        "",
        "```bash",
        "cd experiment/user-side",
        "source .env",
        f"python3 lib/maas.py assess-source --site {sid}"
        + (f" --family {fam}" if fam else "")
        + f" --agent {agent} --write-report",
        "# 含 smoke：",
        f"python3 lib/maas.py assess-source --site {sid}"
        + (f" --family {fam}" if fam else "")
        + f" --agent {agent} --smoke --write-report",
        "```",
        "",
        "机器可读结果：`.runtime/` 下同日前缀 `*-assess-*.json`。",
        "",
    ])
    if log_rel:
        lines.extend([
            f"合并日志（若使用 `--out`）：`{log_rel}`",
            "",
        ])
    lines.extend([
        "---",
        "",
        "## 参考",
        "",
        "- [CONFIG.md](../../experiment/user-side/CONFIG.md)",
        "- [报告命名规范](./README.md#源评估报告命名)",
        "",
    ])
    return "\n".join(lines)


def cmd_assess_source(args: argparse.Namespace, sites: dict[str, Any]) -> None:
    """Run Layer 1–3 and optionally write docs/reports markdown from structured results."""
    load_dotenv()
    root = repo_root()
    sid, site = site_entry(sites, args.site)
    agent = args.agent
    day = args.date or datetime.date.today().isoformat()
    fam = assess_family_from_args(args) or resolve_family_for_site_agent(
        sid, site, agent
    )

    scope = agents_for_assess(sid, site, family=fam, profile=fam)
    if agent not in scope:
        raise SystemExit(
            f"Agent {agent!r} not in assess scope for {sid!r} "
            f"(family={fam or 'default'}; in scope: {', '.join(scope)})"
        )

    key = api_key_for(site)
    failed = False

    print("========== Layer 1: Platform ==========")
    verbose = getattr(args, "verbose", False)
    layer1 = run_layer1(sid, site, key)
    print_layer1(sid, site, layer1, verbose=verbose)
    if not layer1["pass"]:
        failed = True
    print("")

    print("========== Layer 2: Protocol ==========")
    if fam:
        print(f"(family={fam} — Layer 2 from assess-plan families.{fam})")
    layer2 = run_layer2(sid, site, key, root, assess_family=fam)
    print_layer2(sid, site, layer2, verbose=verbose)
    if not layer2["pass"]:
        failed = True
    print("")

    print(f"========== Layer 3: Agent ({agent}) ==========")
    if fam:
        print(f"(family={fam})")
    print("==> Starting LiteLLM relay")
    ensure_litellm_proxy(sid, family=fam)
    layer3 = run_layer3_relay(sid, site, agent, root, family=fam)
    print_layer3_relay(sid, site, layer3, verbose=verbose)
    if not layer3["pass"]:
        failed = True

    smoke_status: str | None = None
    layer3_smoke: dict[str, Any] | None = None
    if args.smoke:
        print("")
        print("==> Layer 3 smoke scenarios")
        layer3_smoke = run_layer3_smoke(sid, agent, root, family=fam)
        print_layer3_smoke(layer3_smoke)
        smoke_status = layer3_smoke.get("status")
        if smoke_status == "fail":
            failed = True
            print("==> Smoke FAIL", file=sys.stderr)
        elif smoke_status == "warn":
            print("==> Smoke WARN (optional scenario failed)")
        else:
            print("==> Smoke PASS")

    payload = {
        "site_id": sid,
        "date": day,
        "agent": agent,
        "assess_family": fam,
        "layer1": layer1,
        "layer2": layer2,
        "layer3": layer3,
        "layer3_smoke": layer3_smoke,
        "smoke": smoke_status,
    }
    json_path = root / ".runtime" / f"{sid}-assess-{day.replace('-', '')}.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    report_rel = ""
    if args.write_report:
        body = render_source_report(
            sid, site, day, layer1, layer2, layer3,
            agent=agent,
            assess_family=fam,
            smoke=smoke_status,
            layer3_smoke=layer3_smoke,
            log_rel=args.out or None,
        )
        out_path = report_path(sid, site, date=day)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(body, encoding="utf-8")
        try:
            report_rel = str(out_path.relative_to(workspace_root()))
        except ValueError:
            report_rel = str(out_path)
        print("")
        print(f"Report written: {report_rel}")
        print(f"JSON written: {json_path.relative_to(root)}")

    if args.out:
        # append summary path hint when tee handled by shell wrapper
        pass

    print("")
    print(f"Evidence JSON: experiment/user-side/.runtime/{sid}-assess-{day.replace('-', '')}.json")
    if report_rel:
        print(f"Report file: {report_rel}")
    elif args.write_report:
        rp = report_path(sid, site, date=day)
        try:
            print(f"Report file: {rp.relative_to(workspace_root())}")
        except ValueError:
            print(f"Report file: {rp}")

    if failed and not args.write_report:
        raise SystemExit(1)
    if failed and args.write_report:
        print("", file=sys.stderr)
        print("Assessment had failures; report still written.", file=sys.stderr)
        raise SystemExit(1)


def add_assess_verbose_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print protocol exchange detail (request/response envelope, facet notes)",
    )


def add_assess_family_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--family",
        metavar="NAME",
        dest="family",
        help="assess-plan.json site families.<NAME> (gpt | anthropic | other)",
    )
    p.add_argument(
        "--profile",
        metavar="NAME",
        help="Deprecated alias for --family",
    )


add_assess_profile_arg = add_assess_family_arg


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list-sites", help="List registered upstream sites")
    p.set_defaults(func=lambda a, s: cmd_list_sites(s))

    p = sub.add_parser("get", help="Print a site field")
    p.add_argument("field", choices=[
        "default_site",
        "json",
        "api_key_env",
        "base_url",
        "anthropic_base_url",
        "default_model",
        "default_family",
        "notes",
        "litellm_master_key",
        "litellm_port",
        "litellm_relay_base",
        "protocol",
        "assess_agents",
        "families",
        "profiles",
        "primary_agent",
        "opencode_provider_id",
        "opencode_model",
    ])
    p.add_argument("--site")
    p.add_argument("--agent", choices=["claude", "codex", "opencode"])
    add_assess_profile_arg(p)
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("list-models", help="List models from GET /v1/models")
    p.add_argument("--site")
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=cmd_list_models)

    for kind in ("claude", "codex", "opencode"):
        p = sub.add_parser(f"write-{kind}-config", help=f"Write {kind} temp config (via LiteLLM)")
        p.add_argument("--site")
        p.add_argument("--out", required=True)
        p.add_argument("--model")
        p.add_argument("--kind", default=kind)
        add_assess_family_arg(p)
        p.set_defaults(func=cmd_write_config)

    p = sub.add_parser("assess-platform", help="Layer 1: platform link (GET /v1/models)")
    p.add_argument("--site", required=True)
    p.add_argument("--json", action="store_true", help="Also print JSON result")
    add_assess_verbose_arg(p)
    p.set_defaults(func=cmd_assess_platform)

    p = sub.add_parser(
        "assess-protocol",
        help="Layer 2: native protocol surface on source (direct)",
    )
    p.add_argument("--site", required=True)
    p.add_argument("--json", action="store_true", help="Also print JSON result")
    add_assess_verbose_arg(p)
    add_assess_profile_arg(p)
    p.set_defaults(func=cmd_assess_protocol)

    p = sub.add_parser("write-litellm-config", help="Write LiteLLM proxy yaml for a site")
    p.add_argument("--site", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--port", type=int, default=0)
    add_assess_profile_arg(p)
    p.set_defaults(func=cmd_write_litellm_config)

    p = sub.add_parser("probe-relay", help="Layer 3: probe Agent wire via LiteLLM")
    p.add_argument("--site", required=True)
    p.add_argument("--agent", required=True, choices=["claude", "codex", "opencode"])
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--json", action="store_true", help="Also print JSON result")
    add_assess_verbose_arg(p)
    add_assess_profile_arg(p)
    p.set_defaults(func=cmd_probe_relay)

    p = sub.add_parser("run-smoke", help="Layer 3: Agent smoke scenarios via t_*")
    p.add_argument("--site", required=True)
    p.add_argument("--agent", required=True, choices=["claude", "codex", "opencode"])
    p.add_argument("--json", action="store_true", help="Also print JSON result")
    add_assess_profile_arg(p)
    p.set_defaults(func=cmd_run_smoke)

    p = sub.add_parser(
        "assess-source",
        help="Layer 1–3 assessment; optional --write-report for docs/reports markdown",
    )
    p.add_argument("--site", required=True)
    p.add_argument("--agent", required=True, choices=["claude", "codex", "opencode"])
    p.add_argument("--smoke", action="store_true", help="Run Agent smoke after relay probe")
    p.add_argument(
        "--write-report",
        action="store_true",
        help="Write docs/reports/{domain}-源评估报告-{date}.md from results",
    )
    p.add_argument("--date", help="YYYY-MM-DD (default: today)")
    p.add_argument("--out", help="Optional log path hint embedded in report")
    add_assess_verbose_arg(p)
    add_assess_profile_arg(p)
    p.set_defaults(func=cmd_assess_source)

    p = sub.add_parser("report-path", help="Print docs/reports path for source assessment")
    p.add_argument("--site", required=True)
    p.add_argument(
        "--kind",
        default="source",
        choices=list(REPORT_TITLES),
    )
    p.add_argument("--date", help="YYYY-MM-DD (default: today)")
    p.add_argument(
        "--relative",
        action="store_true",
        help="Print path relative to repo root",
    )
    p.set_defaults(func=cmd_report_path)

    return parser


def main() -> None:
    root = repo_root()
    sites = load_sites(root)
    parser = build_parser()
    args = parser.parse_args()
    if args.command not in ("list-sites", "get", "report-path"):
        load_dotenv(root)
        apply_proxy_env()
    args.func(args, sites)


if __name__ == "__main__":
    main()
