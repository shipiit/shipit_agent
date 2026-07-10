"""Regression: every LLM adapter must accept raw dict messages.

Components like ``ComputerUseAgent`` build plain ``{"role", "content"}`` dicts
(sometimes with multimodal list content). Adapters used to access
``message.role`` directly and crashed with ``'dict' object has no attribute
'role'``. These tests pin the fix across all adapter families and the
browser-session-in-asyncio fix.
"""

from __future__ import annotations

import asyncio

import pytest

from shipit_agent.llms import ShipitLLM
from shipit_agent.llms.anthropic_adapter import AnthropicChatLLM
from shipit_agent.llms.base import coerce_message, coerce_messages
from shipit_agent.llms.litellm_adapter import _normalize_content, _serialize_message
from shipit_agent.models import Message


# The exact shapes ComputerUseAgent builds.
SYS = {"role": "system", "content": "You are a computer-use agent."}
USER = {"role": "user", "content": "Goal: find the price"}
SCREENSHOT = {
    "role": "user",
    "content": [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "B64DATA"},
        },
        {"type": "text", "text": "What's the next action?"},
    ],
}
ASSISTANT = {"role": "assistant", "content": "CLICK 10 20"}
HISTORY = [SYS, USER, SCREENSHOT, ASSISTANT]


class TestCoerce:
    def test_dict_to_message(self) -> None:
        m = coerce_message({"role": "user", "content": "hi", "name": "x"})
        assert isinstance(m, Message) and m.role == "user" and m.content == "hi"
        assert m.name == "x"

    def test_message_passthrough(self) -> None:
        src = Message(role="user", content="hi")
        assert coerce_message(src) is src

    def test_coerce_messages_mixed(self) -> None:
        out = coerce_messages([{"role": "user", "content": "a"}, Message(role="user", content="b")])
        assert all(isinstance(m, Message) for m in out) and len(out) == 2


class TestNormalizeContent:
    def test_anthropic_image_block_to_image_url(self) -> None:
        out = _normalize_content(SCREENSHOT["content"])
        assert out[0]["type"] == "image_url"
        assert out[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert out[1] == {"type": "text", "text": "What's the next action?"}

    def test_string_content_unchanged(self) -> None:
        assert _normalize_content("plain") == "plain"


class TestLiteLLMFamilyAcceptsDicts:
    """Covers litellm + bedrock/gemini/vertex/groq/together/ollama + openai."""

    def test_serialize_dict_messages(self) -> None:
        payload = [_serialize_message(m) for m in HISTORY]
        roles = [p["role"] for p in payload]
        assert roles == ["system", "user", "user", "assistant"]
        # the screenshot's anthropic image block is translated for portability
        img = payload[2]["content"]
        assert [b["type"] for b in img] == ["image_url", "text"]

    def test_serialize_message_object_still_works(self) -> None:
        p = _serialize_message(Message(role="user", content="hi"))
        assert p == {"role": "user", "content": "hi"}


class TestAnthropicAcceptsDicts:
    def test_convert_messages_no_crash(self) -> None:
        llm = AnthropicChatLLM(model="claude-opus-4-1", api_key="test")
        converted = llm._convert_messages(HISTORY)
        # system is passed via the top-level kwarg, so it's skipped here
        assert [c["role"] for c in converted] == ["user", "user", "assistant"]
        # the multimodal block is preserved (anthropic-native shape)
        assert isinstance(converted[1]["content"], list)


class TestShipitLLMAcceptsDicts:
    def test_complete_with_dicts(self) -> None:
        # The last user message has list content; the stub must not crash.
        r = ShipitLLM().complete(messages=[SYS, USER, ASSISTANT])
        assert "find the price" in r.content


class TestBrowserSessionInAsyncioLoop:
    """The Playwright sync API can't run in a live asyncio loop (Jupyter).

    The session runs Playwright on a dedicated loop-free thread so it works.
    Skipped if Playwright / chromium aren't installed.
    """

    def test_launch_inside_running_loop(self) -> None:
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except Exception:
            pytest.skip("playwright not installed")
        from shipit_agent.computer_use import PlaywrightBrowserSession

        async def _run() -> int:
            try:
                with PlaywrightBrowserSession.launch(headless=True) as b:
                    shot = b.screenshot()
                    b.navigate("data:text/html,<h1>hi</h1>")
                    b.click(5, 5)
                    return len(shot)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc).lower()
                # Skip cleanly when the Chromium binary isn't installed for
                # this Python (CI / minimal envs), rather than failing.
                if any(
                    s in msg
                    for s in (
                        "requires playwright",
                        "playwright install",
                        "executable doesn't exist",
                        "browsertype.launch",
                        "looks like playwright",
                    )
                ):
                    pytest.skip(f"chromium not installed: {exc}")
                raise

        # Running inside asyncio.run reproduces the Jupyter condition.
        assert asyncio.run(_run()) > 0
