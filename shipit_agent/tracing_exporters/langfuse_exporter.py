"""Langfuse trace exporter — works with BOTH Langfuse v2 and v3 servers.

Implements the :class:`shipit_agent.tracing.TraceStore` protocol. Agent runs
become Langfuse traces; every tool call becomes a child span (paired by
``call_id``, with real durations). No SDK dependency — plain HTTPS:

- **v3 servers** → OTLP/JSON to ``/api/public/otel/v1/traces`` (the native
  OpenTelemetry ingest; immune to the v2-SDK-payload 500s).
- **v2 servers** → the classic batch API at ``/api/public/ingestion``.
- ``api_version="auto"`` (default) probes ``/api/public/health`` once and
  picks the right wire format from the reported server version.

Usage::

    from shipit_agent.tracing_exporters import LangfuseExporter

    agent = Agent.with_builtins(
        llm=llm,
        trace_store=LangfuseExporter(   # keys default to LANGFUSE_* env vars
            host="https://my-langfuse.example.com",
        ),
    )
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import threading
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

from shipit_agent.models import AgentEvent
from shipit_agent.tracing import TraceRecord

logger = logging.getLogger(__name__)

_NS = 1_000_000_000


def _hex_id(seed: str, nbytes: int) -> str:
    return hashlib.md5(seed.encode("utf-8")).hexdigest()[: nbytes * 2]  # nosec B324 — id derivation, not security


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _clip(value: Any, limit: int = 4000) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


class LangfuseExporter:
    """Ship agent runs to Langfuse (v2 or v3) as traces with tool spans."""

    def __init__(
        self,
        *,
        public_key: str | None = None,
        secret_key: str | None = None,
        host: str | None = None,
        api_version: str = "auto",  # "auto" | "v2" | "v3"
        timeout_seconds: float = 5.0,
        transport: Callable[[str, dict[str, str], bytes], None] | None = None,
    ) -> None:
        self.public_key = public_key or os.environ.get("LANGFUSE_PUBLIC_KEY", "")
        self.secret_key = secret_key or os.environ.get("LANGFUSE_SECRET_KEY", "")
        self.host = (host or os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")).rstrip("/")
        if api_version not in ("auto", "v2", "v3"):
            raise ValueError("api_version must be 'auto', 'v2', or 'v3'")
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds
        self._transport = transport or self._http_post
        self._lock = threading.Lock()
        # per-trace state: {"start": ts, "name": str, "input": str,
        #                   "pending": {call_id: {...}}, "spans": [...]}
        self._traces: dict[str, dict[str, Any]] = {}
        self._resolved_version: str | None = (
            api_version if api_version != "auto" else None
        )

    # ------------------------------------------------------------------
    # TraceStore protocol
    # ------------------------------------------------------------------
    def append_event(
        self,
        trace_id: str,
        event: AgentEvent,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._handle(trace_id, event, metadata or {})
        except Exception as exc:  # observability must never break the run
            logger.warning("LangfuseExporter failed on %s: %s", event.type, exc)

    def load(self, trace_id: str) -> TraceRecord | None:
        return None  # write-only exporter

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------
    def _handle(
        self, trace_id: str, event: AgentEvent, metadata: dict[str, Any]
    ) -> None:
        with self._lock:
            state = self._traces.setdefault(
                trace_id,
                {"start": event.timestamp, "name": "shipit-agent", "input": "",
                 "output": "", "pending": {}, "spans": []},
            )
            if metadata.get("agent_name"):
                state["name"] = str(metadata["agent_name"])
            payload = event.payload

            if event.type == "run_started":
                state["start"] = event.timestamp
                state["input"] = _clip(payload.get("prompt", ""))
            elif event.type == "tool_called":
                key = str(payload.get("call_id") or len(state["pending"]))
                state["pending"][key] = {
                    "tool": str(payload.get("tool", "tool")),
                    "start": event.timestamp,
                    "input": _clip(payload.get("arguments", {})),
                }
            elif event.type in ("tool_completed", "tool_failed"):
                key = str(payload.get("call_id", ""))
                pending = state["pending"].pop(key, None) or {
                    "tool": str(payload.get("tool", "tool")),
                    "start": event.timestamp,
                    "input": "",
                }
                duration_ms = payload.get("duration_ms")
                start = (
                    event.timestamp - float(duration_ms) / 1000
                    if duration_ms is not None
                    else pending["start"]
                )
                state["spans"].append(
                    {
                        "id": _hex_id(f"{trace_id}:{key}:{len(state['spans'])}", 8),
                        "name": pending["tool"],
                        "start": start,
                        "end": event.timestamp,
                        "input": pending["input"],
                        "output": _clip(
                            payload.get("output", payload.get("error", ""))
                        ),
                        "error": event.type == "tool_failed",
                    }
                )
            elif event.type == "run_completed":
                state["output"] = _clip(payload.get("output", ""))
                state["end"] = event.timestamp
                finished = self._traces.pop(trace_id)
                self._send(trace_id, finished)

    # ------------------------------------------------------------------
    # Wire formats
    # ------------------------------------------------------------------
    def _resolve_version(self) -> str:
        if self._resolved_version is None:
            version = "v3"
            try:
                req = urllib.request.Request(f"{self.host}/api/public/health")
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:  # nosec B310 — https host from config
                    reported = str(json.loads(resp.read()).get("version", "3"))
                version = "v2" if reported.startswith("2") else "v3"
            except Exception as exc:
                logger.warning("Langfuse health probe failed (%s); assuming v3", exc)
            self._resolved_version = version
        return self._resolved_version

    def _send(self, trace_id: str, state: dict[str, Any]) -> None:
        version = self._resolve_version()
        if version == "v2":
            url = f"{self.host}/api/public/ingestion"
            body = self._v2_payload(trace_id, state)
        else:
            url = f"{self.host}/api/public/otel/v1/traces"
            body = self._v3_payload(trace_id, state)
        auth = base64.b64encode(
            f"{self.public_key}:{self.secret_key}".encode()
        ).decode()
        headers = {
            "content-type": "application/json",
            "authorization": f"Basic {auth}",
        }
        self._transport(url, headers, json.dumps(body).encode("utf-8"))

    def _v2_payload(self, trace_id: str, state: dict[str, Any]) -> dict[str, Any]:
        tid = _hex_id(trace_id, 16)
        end = state.get("end", state["start"])
        batch: list[dict[str, Any]] = [
            {
                "id": _hex_id(f"{trace_id}:evt:trace", 16),
                "timestamp": _iso(end),
                "type": "trace-create",
                "body": {
                    "id": tid,
                    "name": state["name"],
                    "timestamp": _iso(state["start"]),
                    "input": state["input"],
                    "output": state["output"],
                },
            }
        ]
        for span in state["spans"]:
            batch.append(
                {
                    "id": _hex_id(f"{trace_id}:evt:{span['id']}", 16),
                    "timestamp": _iso(span["end"]),
                    "type": "span-create",
                    "body": {
                        "id": span["id"],
                        "traceId": tid,
                        "name": span["name"],
                        "startTime": _iso(span["start"]),
                        "endTime": _iso(span["end"]),
                        "input": span["input"],
                        "output": span["output"],
                        **({"level": "ERROR"} if span["error"] else {}),
                    },
                }
            )
        return {"batch": batch}

    def _v3_payload(self, trace_id: str, state: dict[str, Any]) -> dict[str, Any]:
        tid = _hex_id(trace_id, 16)
        root_id = _hex_id(f"{trace_id}:root", 8)
        end = state.get("end", state["start"])

        def attr(key: str, value: str) -> dict[str, Any]:
            return {"key": key, "value": {"stringValue": value}}

        spans: list[dict[str, Any]] = [
            {
                "traceId": tid,
                "spanId": root_id,
                "name": state["name"],
                "kind": 1,
                "startTimeUnixNano": str(int(state["start"] * _NS)),
                "endTimeUnixNano": str(int(end * _NS)),
                "attributes": [
                    attr("langfuse.observation.type", "agent"),
                    attr("input.value", state["input"]),
                    attr("output.value", state["output"]),
                ],
                "status": {"code": 1},
            }
        ]
        for span in state["spans"]:
            spans.append(
                {
                    "traceId": tid,
                    "spanId": span["id"],
                    "parentSpanId": root_id,
                    "name": span["name"],
                    "kind": 1,
                    "startTimeUnixNano": str(int(span["start"] * _NS)),
                    "endTimeUnixNano": str(int(span["end"] * _NS)),
                    "attributes": [
                        attr("langfuse.observation.type", "tool"),
                        attr("input.value", span["input"]),
                        attr("output.value", span["output"]),
                    ],
                    "status": {"code": 2 if span["error"] else 1},
                }
            )
        return {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [attr("service.name", "shipit-agent")]
                    },
                    "scopeSpans": [
                        {"scope": {"name": "shipit_agent"}, "spans": spans}
                    ],
                }
            ]
        }

    # ------------------------------------------------------------------
    def _http_post(self, url: str, headers: dict[str, str], body: bytes) -> None:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:  # nosec B310 — https host from config
                resp.read()
        except Exception as exc:
            logger.warning("Langfuse export POST failed: %s", exc)
