from importlib import import_module

from shipit_agent import (
    AskUserTool,
    ArtifactBuilderTool,
    CodeExecutionTool,
    HumanReviewTool,
    MemoryTool,
    OpenURLTool,
    PlannerTool,
    PlaywrightBrowserTool,
    PromptTool,
    ToolSearchTool,
    VerifierTool,
    WebSearchTool,
    WorkspaceFilesTool,
)
from shipit_agent.llms import SimpleEchoLLM
from shipit_agent.tools.artifact_builder import ARTIFACT_BUILDER_PROMPT
from shipit_agent.tools.ask_user import ASK_USER_PROMPT
from shipit_agent.tools.code_execution import CODE_EXECUTION_PROMPT
from shipit_agent.tools.human_review import HUMAN_REVIEW_PROMPT
from shipit_agent.tools.memory import MEMORY_TOOL_PROMPT
from shipit_agent.tools.open_url import OPEN_URL_PROMPT
from shipit_agent.tools.planner import PLANNER_PROMPT
from shipit_agent.tools.playwright_browser import PLAYWRIGHT_BROWSER_PROMPT
from shipit_agent.tools.prompt import PROMPT_TOOL_PROMPT
from shipit_agent.tools.sub_agent import SUB_AGENT_PROMPT
from shipit_agent.tools.tool_search import TOOL_SEARCH_PROMPT
from shipit_agent.tools.verifier import VERIFIER_PROMPT
from shipit_agent.tools.web_search import WEB_SEARCH_PROMPT
from shipit_agent.tools.workspace_files import WORKSPACE_FILES_PROMPT


def test_all_builtin_tools_have_default_prompt_text() -> None:
    tools = [
        WebSearchTool(provider="duckduckgo"),
        OpenURLTool(),
        AskUserTool(),
        HumanReviewTool(),
        MemoryTool(),
        PlannerTool(),
        PlaywrightBrowserTool(),
        PromptTool(),
        VerifierTool(),
        ArtifactBuilderTool(),
        CodeExecutionTool(),
        ToolSearchTool(),
        WorkspaceFilesTool(),
    ]
    for tool in tools:
        assert getattr(tool, "prompt", "").strip()


def test_custom_prompt_override_is_supported() -> None:
    tool = OpenURLTool(prompt="Custom URL guidance")
    assert tool.prompt == "Custom URL guidance"


def test_each_tool_package_exposes_prompt_module() -> None:
    modules = [
        "shipit_agent.tools.artifact_builder.prompt",
        "shipit_agent.tools.ask_user.prompt",
        "shipit_agent.tools.code_execution.prompt",
        "shipit_agent.tools.human_review.prompt",
        "shipit_agent.tools.memory.prompt",
        "shipit_agent.tools.open_url.prompt",
        "shipit_agent.tools.planner.prompt",
        "shipit_agent.tools.playwright_browser.prompt",
        "shipit_agent.tools.prompt.prompt",
        "shipit_agent.tools.sub_agent.prompt",
        "shipit_agent.tools.tool_search.prompt",
        "shipit_agent.tools.verifier.prompt",
        "shipit_agent.tools.web_search.prompt",
        "shipit_agent.tools.workspace_files.prompt",
    ]
    for module_name in modules:
        module = import_module(module_name)
        assert module is not None


def test_builtin_tools_use_local_prompt_constants() -> None:
    assert WebSearchTool(provider="duckduckgo").prompt == WEB_SEARCH_PROMPT
    assert OpenURLTool().prompt == OPEN_URL_PROMPT
    assert AskUserTool().prompt == ASK_USER_PROMPT
    assert CodeExecutionTool().prompt == CODE_EXECUTION_PROMPT
    assert HumanReviewTool().prompt == HUMAN_REVIEW_PROMPT
    assert MemoryTool().prompt == MEMORY_TOOL_PROMPT
    assert PlannerTool().prompt == PLANNER_PROMPT
    assert PlaywrightBrowserTool().prompt == PLAYWRIGHT_BROWSER_PROMPT
    assert PromptTool().prompt == PROMPT_TOOL_PROMPT
    assert VerifierTool().prompt == VERIFIER_PROMPT
    assert ArtifactBuilderTool().prompt == ARTIFACT_BUILDER_PROMPT
    assert ToolSearchTool().prompt == TOOL_SEARCH_PROMPT
    assert WorkspaceFilesTool().prompt == WORKSPACE_FILES_PROMPT


def test_sub_agent_uses_local_prompt_constant() -> None:
    from shipit_agent import SubAgentTool

    assert SubAgentTool(llm=SimpleEchoLLM()).prompt == SUB_AGENT_PROMPT
