"""Configuration that can always be deleted.

The contract this module enforces is narrow and worth stating plainly: **removing
every config file must leave a working agent.** Defaults are not "what you get
when you have not configured anything yet" — they are the shipped behaviour, and
the file only ever overrides. That is what makes "no hardcoding" mean something
beyond moving constants into YAML: nothing here is required, and nothing that
matters is unreachable.

Three layers, highest precedence first:

1. explicit ``overrides`` passed by the caller (tests, a host embedding this);
2. the user's file — ``$SHIPIT_CONFIG``, ``./shipit.yaml``, or
   ``~/.shipit/config.yaml``, whichever is found first;
3. the shipped defaults below.

Merging is deep for mappings and replacing for scalars and lists. A list that
merged element-wise would make it impossible to *shorten* one — a user removing
a region from ``regions`` would find it still present.

PyYAML is optional. Without it, the defaults apply and a debug line explains
why the file was ignored, because a missing optional dependency should degrade
configuration, not break startup.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)

__all__ = ["DEFAULTS", "AgentConfig", "load_config", "deep_merge", "find_config_file"]


#: Every knob the upgrade modules read, with the value that ships.
DEFAULTS: dict[str, Any] = {
    "providers": {
        "bedrock_mantle": {
            "base_url": "https://bedrock-mantle.{region}.api.aws/openai/v1",
            "regions": ["us-east-1", "us-east-2", "us-west-2", "eu-central-1"],
            "auth": "bearer",
            "token_ttl_seconds": 43_200,
            "refresh_at": 0.8,
        }
    },
    "service_tiers": {
        "default": "standard",
        "by_purpose": {
            "main": "priority",
            "subagent": "flex",
            "summarizer": "flex",
            "memory": "flex",
            "assessor": "flex",
            "progress": "flex",
            "title": "flex",
            "verifier": "standard",
        },
    },
    "retry": {
        "token_quota": {"max_attempts": 4, "base_delay": 20.0, "max_delay": 120.0},
        "capacity": {"max_attempts": 6, "base_delay": 1.0, "max_delay": 45.0},
        "auth": {"max_attempts": 2, "base_delay": 0.0, "refresh_credentials_first": True},
        "bad_request": {"max_attempts": 1},
        "transient": {"max_attempts": 4, "base_delay": 1.0},
        "unknown": {"max_attempts": 2, "base_delay": 2.0},
    },
    "skills": {
        "catalog_entries": 200,
        "description_chars": 120,
        "body_chars": 24_000,
        "always_apply": 20,
        "manual": 10,
        "primed_per_turn": 30,
    },
    "tools": {
        "max_output_chars": 16_000,
        "max_output_group_chars": 48_000,
        "max_call_arg_bytes": 65_536,
        "per_tool_arg_bytes": {
            "write_file": 262_144,
            "edit_file": 262_144,
            "document_builder": 262_144,
        },
        "enforce_read_before_write": True,
    },
    "context": {
        "reserve_ratio": 0.05,
        "compact_at": 0.85,
        "retain_recent_turns": 4,
    },
    "checkpoint": {
        "enabled": True,
        "directory": ".shipit/checkpoints",
    },
    "prefix": {
        "sort_tools": True,
        "assert_stability": False,  # on in tests and CI, off in production
    },
}


def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Merge *overlay* onto *base*: deep for mappings, replacing otherwise.

    Lists replace rather than concatenate, so a user can shorten a shipped list.
    """
    merged: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


#: Searched in order; the first that exists wins.
_SEARCH_PATHS = (
    "shipit.yaml",
    "shipit.yml",
    ".shipit/config.yaml",
)


def find_config_file(explicit: str | Path | None = None) -> Path | None:
    """Locate a config file, or ``None``. Never raises."""
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    env = os.getenv("SHIPIT_CONFIG")
    if env:
        path = Path(env).expanduser()
        if path.is_file():
            return path
    for candidate in _SEARCH_PATHS:
        path = Path.cwd() / candidate
        if path.is_file():
            return path
    home = Path.home() / ".shipit" / "config.yaml"
    return home if home.is_file() else None


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError:
        logger.debug("PyYAML not installed; ignoring %s and using defaults", path)
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — a bad file must not break startup
        logger.warning("Could not read %s (%s); using defaults", path, exc)
        return {}
    return loaded if isinstance(loaded, dict) else {}


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Resolved configuration, with typed accessors for the common reads."""

    data: Mapping[str, Any]
    source: Path | None = None

    # -- generic access ----------------------------------------------------

    def get(self, path: str, default: Any = None) -> Any:
        """Dotted lookup: ``config.get("skills.catalog_entries")``."""
        node: Any = self.data
        for part in path.split("."):
            if not isinstance(node, Mapping) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> dict[str, Any]:
        value = self.get(name, {})
        return dict(value) if isinstance(value, Mapping) else {}

    # -- typed views used by the upgrade modules ---------------------------

    def mantle_regions(self) -> frozenset[str]:
        regions = self.get("providers.bedrock_mantle.regions", ()) or ()
        return frozenset(str(r).strip().lower() for r in regions)

    def mantle_url_template(self) -> str:
        return str(self.get("providers.bedrock_mantle.base_url"))

    def skill_caps(self) -> Any:
        from shipit_agent.skills.catalog import SkillCaps

        section = self.section("skills")
        return SkillCaps(
            always_apply=int(section.get("always_apply", 20)),
            manual=int(section.get("manual", 10)),
            primed_per_turn=int(section.get("primed_per_turn", 30)),
            catalog_entries=int(section.get("catalog_entries", 200)),
            description_chars=int(section.get("description_chars", 120)),
            body_chars=int(section.get("body_chars", 24_000)),
        )

    def tier_policy(self) -> Any:
        from shipit_agent.usage import Purpose, ServiceTier, TierPolicy

        section = self.section("service_tiers")
        default = ServiceTier(str(section.get("default", "standard")))
        mapping: dict[Purpose, ServiceTier] = {}
        for name, tier in (section.get("by_purpose") or {}).items():
            try:
                mapping[Purpose(str(name))] = ServiceTier(str(tier))
            except ValueError:
                logger.warning("Unknown purpose or tier in config: %s=%s", name, tier)
        return TierPolicy(default=default, by_purpose=mapping)

    def retry_schedule(self) -> Any:
        from shipit_agent.llms.throttle import BackoffPolicy, RetrySchedule, ThrottleKind

        policies: dict[ThrottleKind, BackoffPolicy] = {}
        for name, values in self.section("retry").items():
            try:
                kind = ThrottleKind(str(name))
            except ValueError:
                logger.warning("Unknown throttle kind in config: %s", name)
                continue
            values = values if isinstance(values, Mapping) else {}
            policies[kind] = BackoffPolicy(
                max_attempts=int(values.get("max_attempts", 3)),
                base_delay=float(values.get("base_delay", 1.0)),
                multiplier=float(values.get("multiplier", 2.0)),
                max_delay=float(values.get("max_delay", 60.0)),
                jitter=bool(values.get("jitter", True)),
                refresh_credentials_first=bool(
                    values.get("refresh_credentials_first", False)
                ),
            )
        for kind in ThrottleKind:
            policies.setdefault(kind, BackoffPolicy())
        return RetrySchedule(policies)

    def tool_arg_limit(self, tool_name: str) -> int:
        per_tool = self.get("tools.per_tool_arg_bytes", {}) or {}
        if isinstance(per_tool, Mapping) and tool_name in per_tool:
            return int(per_tool[tool_name])
        return int(self.get("tools.max_call_arg_bytes", 65_536))


def load_config(
    path: str | Path | None = None,
    *,
    overrides: Mapping[str, Any] | None = None,
) -> AgentConfig:
    """Resolve configuration from defaults, an optional file, and overrides."""
    found = find_config_file(path)
    merged = dict(DEFAULTS)
    if found is not None:
        merged = deep_merge(merged, _read_yaml(found))
    if overrides:
        merged = deep_merge(merged, overrides)
    return AgentConfig(data=merged, source=found)
