"""Tests for security hardening: URL scheme guards and exec gating."""

from __future__ import annotations

import pytest

from shipit_agent.deep.adaptive_agent import AdaptiveAgent
from shipit_agent.tools.research_brief.research_brief_tool import (
    ResearchBriefTool,
    _NetError,
)


class TestResearchBriefSchemeGuard:
    def test_file_scheme_blocked(self) -> None:
        tool = ResearchBriefTool()
        with pytest.raises(_NetError, match="blocked non-http"):
            tool._fetch("file:///etc/passwd")

    def test_custom_scheme_blocked(self) -> None:
        tool = ResearchBriefTool()
        with pytest.raises(_NetError, match="blocked non-http"):
            tool._fetch("ftp://example.com/data")

    def test_schemeless_blocked(self) -> None:
        tool = ResearchBriefTool()
        with pytest.raises(_NetError, match="none"):
            tool._fetch("/etc/passwd")


class TestCreateToolGating:
    class _L:
        def complete(self, **_kw):
            return None

    def test_disabled_flag_blocks_exec(self) -> None:
        agent = AdaptiveAgent(llm=self._L(), can_create_tools=False)
        with pytest.raises(PermissionError, match="can_create_tools"):
            agent.create_tool("t", "d", "def f():\n    return 1")

    def test_enabled_flag_still_works(self) -> None:
        agent = AdaptiveAgent(llm=self._L(), can_create_tools=True)
        tool = agent.create_tool("doubler", "doubles", "def f(x=1, **kw):\n    return x * 2")
        assert tool.name == "doubler"
