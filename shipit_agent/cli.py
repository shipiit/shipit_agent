from __future__ import annotations

import argparse
import json

from shipit_agent import Agent
from shipit_agent.llms import SimpleEchoLLM


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shipit", description="Run a simple shipit_agent prompt.")
    parser.add_argument("prompt", nargs="?", default="Hello from shipit_agent")
    parser.add_argument("--system-prompt", default="You are Shipit, a clean and capable agent runtime.")
    parser.add_argument("--json", action="store_true", help="Print the full result as JSON.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    agent = Agent(llm=SimpleEchoLLM(), prompt=args.system_prompt, name="shipit")
    result = agent.run(args.prompt)

    if args.json:
        print(
            json.dumps(
                {
                    "output": result.output,
                    "events": [
                        {"type": event.type, "message": event.message, "payload": event.payload}
                        for event in result.events
                    ],
                },
                indent=2,
            )
        )
    else:
        print(result.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
