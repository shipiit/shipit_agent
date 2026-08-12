"""Media pipeline: images and files in, vision tool results bridged, and
block content surviving eviction/truncation/estimation.

Covers the wave that turned the orphaned multimodal package into a wired
feature: `agent.run(images=/files=)`, `read_file` returning pictures,
`vision_followup` bridging tool screenshots into user-turn image blocks,
recency pruning, and per-provider block translation.
"""

from __future__ import annotations

import base64

from shipit_agent.agent import Agent
from shipit_agent.compaction import estimate_tokens
from shipit_agent.llms.base import LLMResponse
from shipit_agent.llms.litellm_adapter import _normalize_content
from shipit_agent.models import Message, ToolCall
from shipit_agent.multimodal.builder import file_blocks_from, image_block_from
from shipit_agent.runtime import AgentRuntime
from shipit_agent.runtime_core import RuntimeCore, evict_prior_tool_outputs
from shipit_agent.tools.base import ToolOutput
from shipit_agent.tools.file_read import FileReadTool

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
    "h6FO1AAAAABJRU5ErkJggg=="
)  # a real 1x1 PNG


class RecordingLLM:
    def __init__(self, script=None):
        self.script = list(script or [])
        self.seen_messages: list[list[Message]] = []

    def complete(self, *, messages, tools=None, system_prompt=None, metadata=None):
        self.seen_messages.append(list(messages))
        text, calls = self.script.pop(0) if self.script else ("done", [])
        return LLMResponse(
            content=text,
            tool_calls=[ToolCall(name=n, arguments=dict(a)) for n, a in calls],
        )


class ScreenshotTool:
    name = "take_screenshot"
    description = "Capture the screen."

    def schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}},
            },
        }

    def run(self, context, **kwargs):
        return ToolOutput(
            text="[screenshot captured]",
            metadata={
                "image_base64": base64.b64encode(PNG_BYTES).decode(),
                "media_type": "image/png",
                "vision": True,
            },
        )


# ── Message and estimators ───────────────────────────────────────────────


def test_message_text_property_extracts_prose_from_blocks():
    msg = Message(
        role="user",
        content=[
            {"type": "text", "text": "look at"},
            {"type": "image", "source": {"type": "base64", "data": "x"}},
            {"type": "text", "text": "this"},
        ],
    )
    assert msg.text == "look at\nthis"
    assert Message(role="user", content="plain").text == "plain"


def test_estimate_tokens_prices_images_flat():
    blocks = [
        {"type": "text", "text": "x" * 400},
        {"type": "image", "source": {"type": "base64", "data": "y" * 100_000}},
    ]
    estimate = estimate_tokens(blocks)
    assert 1_500 <= estimate <= 1_700  # 1500 image + ~100 text, never 25k


# ── read_file media branch ───────────────────────────────────────────────


def test_read_file_returns_png_as_vision(tmp_path):
    path = tmp_path / "chart.png"
    path.write_bytes(PNG_BYTES)
    tool = FileReadTool(root_dir=str(tmp_path))
    from shipit_agent.tools.base import ToolContext

    output = tool.run(ToolContext(prompt="", state={}), path="chart.png")
    assert output.metadata.get("vision") is True
    assert output.metadata["media_type"] == "image/png"
    assert base64.b64decode(output.metadata["image_base64"]) == PNG_BYTES
    assert "�" not in output.text  # no UTF-8 soup


def test_read_file_returns_pdf_as_document(tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    tool = FileReadTool(root_dir=str(tmp_path))
    from shipit_agent.tools.base import ToolContext

    output = tool.run(ToolContext(prompt="", state={}), path="paper.pdf")
    assert output.metadata["media_type"] == "application/pdf"
    assert "document_base64" in output.metadata


# ── vision bridge in the loop ────────────────────────────────────────────


def test_screenshot_reaches_model_as_image_block_next_step():
    llm = RecordingLLM(
        [("capturing", [("take_screenshot", {})]), ("done", [])]
    )
    runtime = AgentRuntime(
        llm=llm,
        prompt="You are helpful.",
        tools=[ScreenshotTool()],
        max_iterations=3,
    )
    runtime.run("what is on screen?")
    second_request = llm.seen_messages[1]
    image_messages = [
        m
        for m in second_request
        if isinstance(m.content, list)
        and any(b.get("type") == "image" for b in m.content)
    ]
    assert image_messages, "screenshot never reached the model"
    assert image_messages[0].role == "user"


def test_stale_images_are_pruned_to_the_newest_three():
    messages = [
        Message(
            role="user",
            content=[{"type": "image", "source": {"type": "base64", "data": str(i)}}],
            metadata={"tool": "take_screenshot"},
        )
        for i in range(5)
    ]
    pruned = RuntimeCore.prune_stale_images(messages)
    still_images = [m for m in pruned if isinstance(m.content, list)]
    assert len(still_images) == RuntimeCore.MAX_VISION_MESSAGES
    assert isinstance(pruned[0].content, str) and "stale" in pruned[0].content


# ── eviction / truncation guards ─────────────────────────────────────────


def test_eviction_never_touches_block_content():
    big_blocks = [{"type": "image", "source": {"type": "base64", "data": "x" * 9000}}]
    messages = [Message(role="tool", name="shot", content=big_blocks)]
    evicted = evict_prior_tool_outputs(messages)
    assert evicted[0].content is big_blocks  # untouched, not stringified


# ── adapter translation ──────────────────────────────────────────────────


def test_litellm_translates_url_images_and_degrades_documents():
    content = [
        {"type": "image", "source": {"type": "url", "url": "https://x.com/a.png"}},
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf"}},
        {"type": "audio", "source": {"type": "url", "url": "https://x.com/a.mp3"}},
        {"type": "text", "text": "hi"},
    ]
    normalized = _normalize_content(content)
    assert normalized[0] == {
        "type": "image_url",
        "image_url": {"url": "https://x.com/a.png"},
    }
    assert normalized[1]["type"] == "text" and "document" in normalized[1]["text"]
    assert normalized[2]["type"] == "text" and "audio" in normalized[2]["text"]
    assert normalized[3] == {"type": "text", "text": "hi"}


# ── public API ───────────────────────────────────────────────────────────


def test_agent_run_images_attaches_blocks(tmp_path):
    path = tmp_path / "shot.png"
    path.write_bytes(PNG_BYTES)
    llm = RecordingLLM()
    agent = Agent(
        llm=llm,
        auto_use_skills=False,
        auto_project_memory=False,
        skill_source=None,
        max_iterations=2,
    )
    agent.run("what is this?", images=[str(path)])
    user_msgs = [m for m in llm.seen_messages[0] if m.role == "user"]
    blocks = user_msgs[-1].content
    assert isinstance(blocks, list)
    kinds = [b["type"] for b in blocks]
    assert "image" in kinds and "text" in kinds


def test_agent_run_files_inlines_code_and_attaches_pdf(tmp_path):
    code = tmp_path / "app.py"
    code.write_text("def main():\n    return 42\n")
    pdf = tmp_path / "spec.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    llm = RecordingLLM()
    agent = Agent(
        llm=llm,
        auto_use_skills=False,
        auto_project_memory=False,
        skill_source=None,
        max_iterations=2,
    )
    agent.run("review these", files=[str(code), str(pdf)])
    blocks = [m for m in llm.seen_messages[0] if m.role == "user"][-1].content
    assert isinstance(blocks, list)
    joined = " ".join(b.get("text", "") for b in blocks if b["type"] == "text")
    assert "def main" in joined and "app.py" in joined
    assert any(b["type"] == "document" for b in blocks)


def test_agent_run_without_media_keeps_the_plain_string_path():
    llm = RecordingLLM()
    agent = Agent(
        llm=llm,
        auto_use_skills=False,
        auto_project_memory=False,
        skill_source=None,
        max_iterations=2,
    )
    agent.run("hello")
    user_msgs = [m for m in llm.seen_messages[0] if m.role == "user"]
    assert isinstance(user_msgs[-1].content, str)


def test_builder_block_helpers(tmp_path):
    assert image_block_from("https://x.com/a.png")["source"]["type"] == "url"
    path = tmp_path / "a.png"
    path.write_bytes(PNG_BYTES)
    block = image_block_from(str(path))
    assert block["source"]["type"] == "base64"
    md = tmp_path / "notes.md"
    md.write_text("# hi")
    [text_block] = file_blocks_from(str(md))
    assert "# hi" in text_block["text"] and "notes.md" in text_block["text"]
    assert file_blocks_from(str(tmp_path / "ghost.txt"))[0]["type"] == "text"


def test_agent_stream_accepts_images_and_files(tmp_path):
    img = tmp_path / "shot.png"
    img.write_bytes(PNG_BYTES)
    code = tmp_path / "app.py"
    code.write_text("def main():\n    return 42\n")
    llm = RecordingLLM()
    agent = Agent(
        llm=llm,
        auto_use_skills=False,
        auto_project_memory=False,
        skill_source=None,
        max_iterations=2,
    )
    list(agent.stream("review this", images=[str(img)], files=[str(code)]))
    blocks = [m for m in llm.seen_messages[0] if m.role == "user"][-1].content
    assert isinstance(blocks, list)
    kinds = [b["type"] for b in blocks]
    assert "image" in kinds
    joined = " ".join(b.get("text", "") for b in blocks if b["type"] == "text")
    assert "def main" in joined
