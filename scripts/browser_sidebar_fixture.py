"""Local browser test server. --live opts into real, billable Bedrock calls."""

import argparse
import os
import threading
from pathlib import Path

from shipit_agent import Agent
from shipit_agent.browser_bridge import BrowserBridge
from shipit_agent.llms.base import LLMResponse
from shipit_agent.models import ToolCall


class FixtureModel:
    def complete(self, *, messages, text_delta_callback=None, **kwargs):
        starts = [
            (index, message)
            for index, message in enumerate(messages)
            if message.role == "user" and message.metadata.get("turn_start")
        ]
        index, latest = starts[-1] if starts else (0, messages[-1])
        content = latest.content
        text = (
            " ".join(
                block.get("text", "")
                for block in content
                if block.get("type") == "text"
            )
            if isinstance(content, list)
            else str(content)
        )
        if "prepare change" in text.lower() and not any(
            m.role == "tool" for m in messages[index + 1 :]
        ):
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        name="google_workspace",
                        arguments={
                            "action": "propose_update",
                            "service": "docs",
                            "file_id": "fixture123",
                            "requests": [
                                {
                                    "insertText": {
                                        "endOfSegmentLocation": {},
                                        "text": "Reviewed change",
                                    }
                                }
                            ],
                        },
                    )
                ]
            )
        if "prepare change" in text.lower():
            answer = "## Change ready\nReview the exact changes below, then choose **Apply changes**."
        elif isinstance(content, list) and any(
            block.get("type") == "image" for block in content
        ):
            answer = "## Image received\nThe backend received an image content block and the question in this chat."
        else:
            answer = "## Context retained\n" + "\n".join(
                str(m.content) for m in messages if m.role == "user"
            )
        if text_delta_callback:
            for offset in range(0, len(answer), 20):
                text_delta_callback(answer[offset : offset + 20])
        return LLMResponse(
            content=answer,
            usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        )


class FixtureGoogle:
    connected = True

    def request(self, method, url, body=None):
        if method == "GET":
            return {"revisionId": "fixture-revision", "title": "Fixture document"}
        return {"documentId": "fixture123", "replies": [{}]}


class BrowserTestBridge(BrowserBridge):
    """Serve one synthetic page on the bridge origin for capture verification."""

    def _handler(self):
        parent = super()._handler()
        fixture = (
            Path(__file__).resolve().parents[1] / "extensions/chrome/page-fixture.html"
        )

        class Handler(parent):
            def do_GET(self):
                if self.path != "/test-page":
                    self.reply(404, {"error": "Unknown test page"})
                    return
                data = fixture.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    llm = FixtureModel()
    agent = Agent(
        llm=llm,
        auto_use_skills=False,
        auto_project_memory=False,
        auto_project_skills=False,
    )
    models = {
        name: {"label": label, "llm": llm, "vision": True}
        for name, label in [
            ("google.gemma-4-31b", "Gemma 4 31B · Fixture"),
            ("google.gemma-4-26b-a4b", "Gemma 4 26B-A4B · Fixture"),
        ]
    }
    token, workspace = "browser-fixture-token-for-local-tests", FixtureGoogle()
    if args.live:
        from shipit_agent.llms import BedrockChatLLM
        from shipit_agent.llms.bedrock_token import resolve_region
        from shipit_agent.browser_workspace import GoogleWorkspaceClient

        token = os.environ.get("SHIPIT_BROWSER_TOKEN", "")
        if len(token) < 24:
            parser.error("Set a random SHIPIT_BROWSER_TOKEN before live testing")
        models = {
            name: {
                "label": name,
                "vision": True,
                "llm": BedrockChatLLM(
                    model=name,
                    aws_region_name=resolve_region(),
                    max_tokens=600,
                ),
            }
            for name in models
        }
        agent = Agent(
            llm=next(iter(models.values()))["llm"],
            max_iterations=3,
            auto_use_skills=False,
            auto_project_memory=False,
            auto_project_skills=False,
        )
        workspace = GoogleWorkspaceClient("~/.shipit_browser/google_token.json")
    bridge = BrowserTestBridge(
        agent, api_key=token, models=models, workspace_client=workspace
    )
    bridge.start()
    print(
        f"{'LIVE Bedrock' if args.live else 'OFFLINE fixture'} test server at 127.0.0.1:8400",
        flush=True,
    )
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        bridge.stop()
