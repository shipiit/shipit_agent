"""Opt-in real Bedrock smoke test through the browser bridge HTTP/SSE boundary.

Run with the project's Python environment. Uses existing AWS credentials;
does not edit Google documents or read private browser content.
"""

from __future__ import annotations

import json
import secrets
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shipit_agent import Agent
from shipit_agent.browser_bridge import BrowserBridge
from shipit_agent.browser_workspace import GoogleWorkspaceClient
from shipit_agent.llms import BedrockChatLLM
from shipit_agent.llms.bedrock_token import resolve_region


def main():
    models = {
        model: {
            "label": model,
            "vision": True,
            "llm": BedrockChatLLM(
                model=model,
                aws_region_name=resolve_region(),
                max_tokens=600,
            ),
        }
        for model in ("google.gemma-4-31b", "google.gemma-4-26b-a4b")
    }
    token = secrets.token_urlsafe(32)
    bridge = BrowserBridge(
        Agent(
            llm=models["google.gemma-4-31b"]["llm"],
            tools=[],
            max_iterations=3,
            auto_use_skills=False,
            auto_project_memory=False,
            auto_project_skills=False,
        ),
        api_key=token,
        models=models,
        workspace_client=GoogleWorkspaceClient("~/.shipit_browser/google_token.json"),
    )
    port = bridge.start(0)

    def post(path, body):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token,
            },
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            return response.read().decode()

    try:
        sid = json.loads(post("/sessions", {}))["session_id"]
        prompts = [
            {
                "prompt": "Summarize the supplied page in one sentence, including owner and deadline.",
                "page": {
                    "title": "Apollo test page",
                    "url": "https://example.com/apollo",
                    "text": "Project Apollo is owned by Mira. Deadline: 14 October. Budget: 12,000 EUR.",
                    "mode": "page",
                },
            },
            {
                "prompt": "What was the owner's name and the budget on that page? One sentence."
            },
            {
                "prompt": "Change the deadline in our conversation to 21 October. Repeat the updated project facts briefly."
            },
            {
                "prompt": "What is the revised deadline and original owner? Use our earlier conversation.",
                "model": "google.gemma-4-26b-a4b",
            },
            {
                "prompt": "Have you edited any real Google document during this conversation? Answer honestly in one sentence."
            },
        ]
        for number, payload in enumerate(prompts, 1):
            started = time.monotonic()
            raw = post(
                "/chat", {"session_id": sid, "model": "google.gemma-4-31b", **payload}
            )
            events = [
                json.loads(line[6:])
                for line in raw.splitlines()
                if line.startswith("data: ")
            ]
            errors = [e for e in events if e["type"] in {"error", "tool_failed"}]
            complete = [e["payload"] for e in events if e["type"] == "run_completed"]
            print(
                json.dumps(
                    {
                        "turn": number,
                        "seconds": round(time.monotonic() - started, 2),
                        "deltas": sum(e["type"] == "text_delta" for e in events),
                        "completed": complete,
                        "errors": errors,
                        "done": any(e["type"] == "done" for e in events),
                    },
                    default=str,
                ),
                flush=True,
            )
            if errors or not complete:
                raise RuntimeError("Live browser bridge turn failed")
    finally:
        bridge.stop()


if __name__ == "__main__":
    main()
