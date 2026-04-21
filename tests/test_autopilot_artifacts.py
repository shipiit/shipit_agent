"""Tests for the ArtifactCollector + Autopilot artifact integration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from shipit_agent.autopilot import (
    Autopilot, ArtifactCollector, BudgetPolicy, AutopilotResult,
)
from shipit_agent.autopilot.artifacts import Artifact, _iter_fences, _slug
from shipit_agent.deep.goal_agent import Goal


@dataclass
class _FakeResult:
    output: str = ""
    goal_status: str = "unknown"
    criteria_met: list[bool] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=lambda: {"usage": {"total_tokens": 10}})


class _OutputStub:
    """Inner agent whose successive runs emit progressively richer text."""

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.call = 0

    def run(self) -> _FakeResult:
        i = min(self.call, len(self.outputs) - 1)
        self.call += 1
        return _FakeResult(
            output=self.outputs[i],
            criteria_met=[True] if i >= len(self.outputs) - 1 else [False],
            goal_status="completed" if i >= len(self.outputs) - 1 else "in_progress",
        )


# ─────────────────────── ArtifactCollector unit ───────────────────────


class TestArtifactCollectorUnit:
    def test_add_caps_long_content(self) -> None:
        col = ArtifactCollector()
        big = "x" * (col.MAX_CONTENT_CHARS + 500)
        a = col.add(kind="code", name="big.py", content=big)
        assert len(a.content) <= col.MAX_CONTENT_CHARS + 50
        assert a.content.endswith("…(truncated)")

    def test_extract_code_fences(self) -> None:
        col = ArtifactCollector()
        text = (
            "Here is some prose.\n\n"
            "```python\nprint('hi')\n```\n"
            "More prose.\n\n"
            "```ts\nexport const x = 1;\n```\n"
        )
        added = col.extract_from_output(text, iteration=3)
        assert len(added) == 2
        assert added[0].kind == "code" and added[0].language == "python"
        assert added[0].name.endswith(".py")
        assert added[1].language == "ts" and added[1].name.endswith(".ts")
        assert added[0].iteration == 3

    def test_extract_markdown_doc(self) -> None:
        col = ArtifactCollector()
        body = "# A Real Report\n\n" + ("Some substantive text. " * 40)
        col.extract_from_output(body, iteration=1)
        mds = col.by_kind("markdown")
        assert len(mds) == 1
        assert mds[0].name.endswith(".md")

    def test_short_doc_not_captured_as_markdown(self) -> None:
        col = ArtifactCollector()
        col.extract_from_output("# Tiny\nHello.", iteration=1)
        assert col.by_kind("markdown") == []

    def test_ingest_tool_metadata_single(self) -> None:
        col = ArtifactCollector()
        added = col.ingest_tool_metadata(
            {"artifact": True, "kind": "file", "name": "out.csv", "content": "a,b\n1,2\n"},
            iteration=2,
        )
        assert len(added) == 1 and added[0].kind == "file" and added[0].iteration == 2

    def test_ingest_tool_metadata_list(self) -> None:
        col = ArtifactCollector()
        added = col.ingest_tool_metadata(
            [
                {"artifact": True, "kind": "file", "name": "a.txt", "content": "A"},
                {"artifact": False, "kind": "nope", "name": "skipped", "content": ""},
                {"artifact": True, "kind": "file", "name": "b.txt", "content": "B"},
            ],
            iteration=1,
        )
        assert [a.name for a in added] == ["a.txt", "b.txt"]

    def test_persist_to_disk(self, tmp_path: Path) -> None:
        col = ArtifactCollector(persist_dir=tmp_path)
        col.add(kind="code", name="foo.py", content="print('x')")
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["kind"] == "code" and data["name"] == "foo.py"

    def test_on_add_callback_fires(self) -> None:
        seen: list[Artifact] = []
        col = ArtifactCollector(on_add=seen.append)
        col.add(kind="code", name="x.py", content="pass")
        assert len(seen) == 1

    def test_slug_and_iter_fences_helpers(self) -> None:
        assert _slug("My Cool Title!!") == "my-cool-title"
        blocks = list(_iter_fences("```py\nprint(1)\n```\n```sh\nls -la\n```\n"))
        assert blocks == [("py", "print(1)"), ("sh", "ls -la")]


# ─────────────────────── Autopilot wiring ───────────────────────


class TestAutopilotArtifacts:
    def _autopilot(self, tmp_path: Path, outputs: list[str], *, artifacts: Any = True) -> Autopilot:
        stub = _OutputStub(outputs)
        return Autopilot(
            llm=None,
            goal=Goal(objective="x", success_criteria=["cA"]),
            checkpoint_dir=tmp_path,
            budget=BudgetPolicy(max_iterations=5, max_seconds=60),
            agent_factory=lambda **_: stub,
            artifacts=artifacts,
        )

    def test_artifacts_auto_extracted_from_output(self, tmp_path: Path) -> None:
        output = "Here's the fix:\n\n```python\nprint('fixed')\n```\n"
        autopilot = self._autopilot(tmp_path, [output])
        result = autopilot.run(run_id="art-1")
        assert len(result.artifacts) == 1
        assert result.artifacts[0]["kind"] == "code"
        assert result.artifacts[0]["language"] == "python"
        assert "print('fixed')" in result.artifacts[0]["content"]

    def test_none_artifacts_collector_means_no_extraction(self, tmp_path: Path) -> None:
        output = "Here:\n\n```python\nx = 1\n```\n"
        autopilot = self._autopilot(tmp_path, [output], artifacts=None)
        result = autopilot.run(run_id="art-2")
        assert result.artifacts == []

    def test_stream_emits_artifact_events(self, tmp_path: Path) -> None:
        output = "Done.\n\n```python\nprint('ok')\n```\n"
        autopilot = self._autopilot(tmp_path, [output])
        events = list(autopilot.stream(run_id="art-3"))
        kinds = [e["kind"] for e in events]
        assert "autopilot.artifact" in kinds
        final = [e for e in events if e["kind"] == "autopilot.result"][0]
        assert final["artifacts"], "final result should carry artifacts"
