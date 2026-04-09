from __future__ import annotations

from shipit_agent.tools import Tool


def build_tools_prompt(tools: list[Tool]) -> str:
    if not tools:
        return ""

    lines = ["Available tools:"]
    for tool in tools:
        lines.append(f"- {tool.name}: {tool.description}")
        prompt = getattr(tool, "prompt", "").strip()
        prompt_instructions = getattr(tool, "prompt_instructions", "").strip()
        if prompt:
            lines.append(f"  Guidance: {prompt}")
        elif prompt_instructions:
            lines.append(f"  Guidance: {prompt_instructions}")
    return "\n".join(lines)
