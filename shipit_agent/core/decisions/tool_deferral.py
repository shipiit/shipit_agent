"""Deferred tool loading: advertise a few tools, load the rest when the model searches for them.

Mixed into :class:`~shipit_agent.core.runtime_core.RuntimeCore`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from typing import Any


class ToolDeferralMixin:
    """Deferred tool loading: advertise a few tools, load the rest when the model searches for them."""

    def restore_discovery(self, checkpoint: Any) -> None:
        """Restore names/hashes only; setup revalidates the current catalog.

        SessionStore authorization remains the caller's responsibility.
        Checkpoints carry no tool results, credentials, or permissions.
        """
        if not isinstance(checkpoint, dict) or checkpoint.get("version") != 1:
            return
        session_id = str(getattr(self, "session_id", ""))
        if checkpoint.get("session_id") != session_id:
            return
        entries = checkpoint.get("schemas")
        if not isinstance(entries, dict):
            return
        valid = {
            name: digest
            for name, digest in list(entries.items())[-64:]
            if isinstance(name, str)
            and len(name) <= 256
            and isinstance(digest, str)
            and len(digest) == 64
        }
        sessions = self._session_runtime_state.setdefault("discovery_sessions", {})
        sessions[session_id] = valid
        while len(sessions) > 32:
            sessions.pop(next(iter(sessions)))

    def discovery_checkpoint(self) -> dict[str, Any]:
        session_id = str(getattr(self, "session_id", ""))
        schemas = self._session_runtime_state.get("discovery_sessions", {}).get(
            session_id, {}
        )
        return {"version": 1, "session_id": session_id, "schemas": dict(schemas)}

    def setup_deferral(self, registry: Any, shared_state: dict[str, Any]) -> str:
        """Activate deferred tool loading for this run, if configured.

        Publishes the deferred/loaded name sets and a schema lookup into
        the shared tool state (so ``tool_search`` can load tools and print
        signatures), and returns the name-only index section for the
        system prompt — empty when deferral is off or nothing qualifies.

        Code mode already collapses the catalogue its own way; when both
        are enabled, code mode wins and this is a no-op.
        """
        from shipit_agent.deferral import (
            DEFERRED_NAMES_KEY,
            LOADED_NAMES_KEY,
            SCHEMAS_BY_NAME_KEY,
            deferred_index,
            resolve_deferred_names,
        )

        permissions = getattr(self, "permissions", None)
        visibility = getattr(permissions, "discoverable", None)
        hidden = {
            t.name
            for t in registry.values()
            if callable(visibility) and not visibility(t.name, t)
        }
        shared_state["discovery_hidden"] = hidden
        shared_state["available_tools"] = [
            t
            for t in shared_state.get("available_tools", [])
            if t.get("name") not in hidden
        ]
        if self.code_mode or not getattr(self, "deferred_tools", False):
            return ""
        tools = [t for t in registry.values() if t.name not in hidden]
        from shipit_agent.deferral import DEFAULT_CORE_TOOLS
        from shipit_agent.deferral.policy import (
            DiscoveryPolicy,
            schema_fingerprint,
            schema_tokens,
            select_resident,
        )

        policy = (
            self.deferred_tools
            if isinstance(self.deferred_tools, DiscoveryPolicy)
            else DiscoveryPolicy()
        )
        automatic = self.deferred_tools == "auto" or isinstance(
            self.deferred_tools, DiscoveryPolicy
        )
        schemas = {
            (s.get("function") or {}).get("name"): s
            for s in registry.schemas()
            if (s.get("function") or {}).get("name") not in hidden
        }
        model = getattr(self.llm, "model", None)
        if automatic:
            # Small catalogs can still have very expensive schemas.
            needs_search = (
                len(tools) > policy.initial_tools
                or sum(schema_tokens(s, model) for s in schemas.values())
                > policy.schema_tokens
            )
            deferred = {t.name for t in tools} if needs_search else set()
        else:
            deferred = resolve_deferred_names(tools, self.deferred_tools)
        if not deferred:
            return ""
        from shipit_agent.tools.tool_search import ToolSearchTool

        # By marker, not isinstance: hosts wrap tools (ShipIt Cloud's CompactTool),
        # and a missed one meant two search tools on every call.
        search = next((t for t in tools if getattr(t, "is_tool_search", False) is True), None)
        if search is None:
            # Do not replace a user tool sharing the preferred name.
            name = "search_tools"
            existing = {getattr(t, "name", "") for t in registry.values()}
            while name in existing:
                name = "_" + name
            search = ToolSearchTool(name=name, default_limit=3)
            registry.register(search)
        schemas[search.name] = search.schema()
        shared_state["discovery_search_name"] = search.name
        if automatic:
            # Session ID isolates concurrent conversations on one Agent. The
            # current registry and schema fingerprint invalidate stale entries.
            sessions = self._session_runtime_state.setdefault("discovery_sessions", {})
            session_key = str(getattr(self, "session_id", ""))
            cached = sessions.get(session_key, {})
            valid = {
                name: digest
                for name, digest in cached.items()
                if name in schemas and digest == schema_fingerprint(schemas[name])
            }
            recent = (
                list(valid)[-policy.reuse_tools :][::-1] if policy.reuse_tools else []
            )
            resident = select_resident(
                tools,
                schemas,
                policy,
                core=DEFAULT_CORE_TOOLS,
                search_name=search.name,
                recent=recent,
                model=model,
            )
            deferred = set(schemas) - resident
            shared_state["discovery_policy"] = policy
            shared_state["discovery_session_key"] = session_key
            shared_state["discovery_fingerprints"] = {
                name: schema_fingerprint(schema) for name, schema in schemas.items()
            }
            shared_state["discovery_cached"] = valid
        deferred.discard(search.name)
        shared_state[DEFERRED_NAMES_KEY] = deferred
        shared_state[LOADED_NAMES_KEY] = set()
        shared_state[SCHEMAS_BY_NAME_KEY] = schemas
        return deferred_index(
            tools,
            deferred,
            search_name=search.name,
            compact=automatic,
        )

    def select_step_schemas(
        self, tool_schemas: list[Any], shared_state: dict[str, Any]
    ) -> list[Any]:
        """The schemas this step advertises: core + everything loaded so far.

        Re-evaluated every iteration because the loaded set grows mid-run —
        a tool_search result on step 2 must be callable on step 3.
        """
        from shipit_agent.deferral import (
            DEFERRED_NAMES_KEY,
            LOADED_NAMES_KEY,
            select_schemas,
        )

        selected = select_schemas(
            [
                s
                for s in tool_schemas
                if (s.get("function") or {}).get("name")
                not in shared_state.get("discovery_hidden", set())
            ],
            shared_state.get(DEFERRED_NAMES_KEY),
            shared_state.get(LOADED_NAMES_KEY),
        )
        policy = shared_state.get("discovery_policy")
        if policy is not None:
            # Persist only loaded definitions, bounded per session and globally.
            cache = dict(shared_state.get("discovery_cached", {}))
            fingerprints = shared_state.get("discovery_fingerprints", {})
            for schema in selected:
                name = (schema.get("function") or {}).get("name")
                if name in (
                    shared_state.get(LOADED_NAMES_KEY) or set()
                ) and name != shared_state.get("discovery_search_name"):
                    cache.pop(name, None)
                    cache[name] = fingerprints[name]
            cache = (
                dict(list(cache.items())[-policy.reuse_tools :])
                if policy.reuse_tools
                else {}
            )
            sessions = self._session_runtime_state.setdefault("discovery_sessions", {})
            key = shared_state["discovery_session_key"]
            sessions.pop(key, None)
            sessions[key] = cache
            while len(sessions) > 32:
                sessions.pop(next(iter(sessions)))
        if not shared_state.get(DEFERRED_NAMES_KEY):
            return selected
        # Append new definitions after previously advertised ones. Inserting a
        # discovered schema into the middle of the prefix wastes cache reuse.
        by_name = {
            (schema.get("function") or {}).get("name"): schema for schema in selected
        }
        order = [
            name
            for name in shared_state.get("advertised_tool_order", [])
            if name in by_name
        ]
        seen = set(order)
        order.extend(name for name in by_name if name not in seen)
        shared_state["advertised_tool_order"] = order
        return [by_name[name] for name in order]
