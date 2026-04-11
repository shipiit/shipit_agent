"""
Compatibility re-exports for tool prompts.

The per-tool package `prompt.py` modules are the source of truth so each tool
owns its own prompt contract. This module keeps the original centralized import
surface available for callers that still rely on `shipit_agent.prompts`.
"""

from shipit_agent.tools.artifact_builder.prompt import ARTIFACT_BUILDER_PROMPT
from shipit_agent.tools.ask_user.prompt import ASK_USER_PROMPT
from shipit_agent.tools.code_execution.prompt import CODE_EXECUTION_PROMPT
from shipit_agent.tools.human_review.prompt import HUMAN_REVIEW_PROMPT
from shipit_agent.tools.memory.prompt import MEMORY_TOOL_PROMPT
from shipit_agent.tools.open_url.prompt import OPEN_URL_PROMPT
from shipit_agent.tools.planner.prompt import PLANNER_PROMPT
from shipit_agent.tools.playwright_browser.prompt import PLAYWRIGHT_BROWSER_PROMPT
from shipit_agent.tools.prompt.prompt import PROMPT_TOOL_PROMPT
from shipit_agent.tools.sub_agent.prompt import SUB_AGENT_PROMPT
from shipit_agent.tools.tool_search.prompt import TOOL_SEARCH_PROMPT
from shipit_agent.tools.verifier.prompt import VERIFIER_PROMPT
from shipit_agent.tools.web_search.prompt import WEB_SEARCH_PROMPT
from shipit_agent.tools.workspace_files.prompt import WORKSPACE_FILES_PROMPT

FUNCTION_TOOL_PROMPT = """
Call a direct Python function tool.

Use this when:
- a deterministic local function can solve the task directly
- code-free execution is preferable to a heavier tool or model call

Rules:
- pass only the needed arguments
- prefer these tools for stable utility operations
""".strip()

__all__ = [
    "ARTIFACT_BUILDER_PROMPT",
    "ASK_USER_PROMPT",
    "CODE_EXECUTION_PROMPT",
    "FUNCTION_TOOL_PROMPT",
    "HUMAN_REVIEW_PROMPT",
    "MEMORY_TOOL_PROMPT",
    "OPEN_URL_PROMPT",
    "PLANNER_PROMPT",
    "PLAYWRIGHT_BROWSER_PROMPT",
    "PROMPT_TOOL_PROMPT",
    "SUB_AGENT_PROMPT",
    "TOOL_SEARCH_PROMPT",
    "VERIFIER_PROMPT",
    "WEB_SEARCH_PROMPT",
    "WORKSPACE_FILES_PROMPT",
]
