"""Reading a SKILL.md front-matter block without a YAML dependency."""

from __future__ import annotations

from typing import Any


def _parse_front_matter(text: str) -> dict[str, Any]:
    """YAML when available, a minimal key/value reader when it is not.

    A skill folder must not become unreadable because an optional dependency is
    missing, so the fallback handles the shapes front-matter actually uses:
    scalars, inline lists, and dash lists.
    """
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text)
        return loaded if isinstance(loaded, dict) else {}
    except ImportError:
        pass

    data: dict[str, Any] = {}
    current_key: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_key:
            data.setdefault(current_key, [])
            if isinstance(data[current_key], list):
                data[current_key].append(stripped[2:].strip().strip("\"'"))
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        current_key = key
        if not value:
            data[key] = []
        elif value.startswith("[") and value.endswith("]"):
            data[key] = [v.strip().strip("\"'") for v in value[1:-1].split(",") if v.strip()]
        elif value.lower() in ("true", "false"):
            data[key] = value.lower() == "true"
        else:
            data[key] = value.strip("\"'")
    return data
