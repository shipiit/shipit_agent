"""Skill-to-tool bundle mapping for stronger runtime defaults.

Each entry maps a skill ID to the list of built-in tool names that
the skill needs at runtime.  When a skill is selected, the agent
automatically attaches these tools — so the LLM can actually act
on the skill's guidance without the caller having to wire tools
manually.

Keep tool names in sync with the default names in each tool class
(e.g. ``FileReadTool.name = "read_file"``).
"""

from __future__ import annotations


from .skill import Skill

# ── core file & code tools (reused across many bundles) ────────────
_FILE_CORE = ["read_file", "edit_file", "write_file", "glob_files", "grep_files"]
_CODE_CORE = [*_FILE_CORE, "bash", "run_code"]
_WEB_CORE = ["web_search", "open_url", "playwright_browse"]

SKILL_TOOL_BUNDLES: dict[str, list[str]] = {
    # ── web / scraping ─────────────────────────────────────────────
    "web-scraper-pro": [
        *_WEB_CORE,
        "bash",
        "glob_files",
        "grep_files",
        "read_file",
        "edit_file",
        "write_file",
        "run_code",
    ],
    # ── code / development ─────────────────────────────────────────
    "code-workflow-assistant": [
        *_CODE_CORE,
        "workspace_files",
        "plan_task",
        "verify_output",
    ],
    "full-stack-developer": [
        *_CODE_CORE,
        "workspace_files",
        *_WEB_CORE,
        "plan_task",
        "verify_output",
    ],
    "database-architect": [
        "bash",
        "read_file",
        "glob_files",
        "grep_files",
        "run_code",
    ],
    "api-test-assistant": [
        *_CODE_CORE,
        *_WEB_CORE,
        "verify_output",
    ],
    "mcp-server-builder": [
        *_CODE_CORE,
        "workspace_files",
        "plan_task",
        "verify_output",
    ],
    # ── devops / security ──────────────────────────────────────────
    "devops-automation": [
        *_CODE_CORE,
        *_WEB_CORE,
        "plan_task",
        "verify_output",
    ],
    "security-engineer": [
        "bash",
        *_WEB_CORE,
        "read_file",
        "grep_files",
        "glob_files",
        "run_code",
        "verify_output",
    ],
    "backup-manager": [
        "bash",
        "read_file",
        "write_file",
        "glob_files",
        "run_code",
        "plan_task",
    ],
    # ��─ website / frontend ─────────────────────────────────────────
    "portfolio-website-builder": [
        *_CODE_CORE,
        "workspace_files",
    ],
    "app-store-screenshots": [
        *_WEB_CORE,
        "write_file",
        "run_code",
        "build_artifact",
    ],
    "ui-and-ux-design-guide": [
        *_FILE_CORE,
        *_WEB_CORE,
        "build_artifact",
        "plan_task",
    ],
    # ── writing / docs ─────────────────────────────────────────────
    "technical-writer": [
        *_FILE_CORE,
        "build_artifact",
        "verify_output",
    ],
    "brand-voice-guide": [
        "read_file",
        "write_file",
        "glob_files",
        "grep_files",
        "verify_output",
    ],
    # ── research / intelligence ────────────────────────────────────
    "startup-idea-scout": [
        *_WEB_CORE,
        "read_file",
        "write_file",
        "run_code",
        "synthesize_evidence",
        "decision_matrix",
    ],
    "competitor-intelligence-tracker": [
        *_WEB_CORE,
        "grep_files",
        "read_file",
        "write_file",
        "run_code",
        "synthesize_evidence",
    ],
    "seo-growth-guide": [
        *_WEB_CORE,
        "read_file",
        "write_file",
        "run_code",
        "synthesize_evidence",
    ],
    # ── lead gen / sales ───────────────────────────────────────────
    "google-maps-lead-finder": [
        *_WEB_CORE,
        "bash",
        "write_file",
        "run_code",
    ],
    "lead-enrichment": [
        *_WEB_CORE,
        "write_file",
        "run_code",
        "build_artifact",
    ],
    "deal-strategist": [
        *_WEB_CORE,
        "read_file",
        "write_file",
        "synthesize_evidence",
        "decision_matrix",
        "build_artifact",
    ],
    "x-search-and-sentiment-tool": [
        *_WEB_CORE,
        "write_file",
        "run_code",
        "synthesize_evidence",
    ],
    # ── marketing / social ─────────────────────────────────────────
    "marketing-advisor": [
        *_WEB_CORE,
        "read_file",
        "write_file",
        "synthesize_evidence",
        "decision_matrix",
        "build_artifact",
    ],
    "social-media-post-manager": [
        *_WEB_CORE,
        "read_file",
        "write_file",
        "build_artifact",
    ],
    "tiktok-app-marketing-agent": [
        *_WEB_CORE,
        "write_file",
        "run_code",
        "build_artifact",
    ],
    "amazon-affiliate-marketing-agent": [
        *_WEB_CORE,
        "write_file",
        "run_code",
        "build_artifact",
    ],
    # ── productivity / connectors ──────────────────────────────────
    "gmail-and-calendar-agent": [
        "gmail_search",
        "google_calendar",
        "write_file",
        "build_artifact",
    ],
    "notion-workspace-manager": [
        "notion",
        "read_file",
        "write_file",
        "glob_files",
    ],
    "obsidian-vault-manager": [
        *_FILE_CORE,
        "bash",
        "run_code",
    ],
    "expense-tracker": [
        "read_file",
        "write_file",
        "run_code",
        "build_artifact",
    ],
    "analytics-setup-assistant": [
        *_WEB_CORE,
        *_CODE_CORE,
        "build_artifact",
        "verify_output",
    ],
    # ── media / creative ───────────────────────────────────────────
    "ugc-video-ad-agent": [
        *_WEB_CORE,
        "write_file",
        "run_code",
    ],
    "video-clone-agent": [
        *_WEB_CORE,
        "write_file",
        "run_code",
    ],
    "ai-music-generator": [
        *_WEB_CORE,
        "write_file",
        "run_code",
    ],
    "ai-video-prompt-builder": [
        *_WEB_CORE,
        "write_file",
        "run_code",
        "build_artifact",
    ],
    "video-downloader": [
        *_WEB_CORE,
        "bash",
        "write_file",
        "run_code",
    ],
    # ── multi-agent / product ──────────────────────────────────────
    "multi-agent-manager": [
        *_CODE_CORE,
        "sub_agent",
        "plan_task",
        "decompose_problem",
        "verify_output",
    ],
    "product-development-guide": [
        *_WEB_CORE,
        "read_file",
        "write_file",
        "plan_task",
        "synthesize_evidence",
        "decision_matrix",
        "build_artifact",
    ],
}


def tool_names_for_skills(skills: list[Skill]) -> list[str]:
    """Return a deduplicated, ordered list of tool names for the given skills.

    Merges tool names declared in each skill's ``tools`` list *and* the
    matching entry in ``SKILL_TOOL_BUNDLES``.
    """
    names: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        for name in [*skill.tools, *SKILL_TOOL_BUNDLES.get(skill.id, [])]:
            if name in seen:
                continue
            names.append(name)
            seen.add(name)
    return names


def validate_tool_bundles(builtin_names: set[str]) -> list[str]:
    """Check every tool name in SKILL_TOOL_BUNDLES against a known set.

    Returns a list of ``"skill_id: unknown_tool_name"`` strings for any
    references that do not appear in *builtin_names*.  An empty list
    means everything is valid.

    Usage::

        from shipit_agent.builtins import get_builtin_tool_map
        from shipit_agent.skills.tool_bundles import validate_tool_bundles
        errors = validate_tool_bundles(set(get_builtin_tool_map().keys()))
    """
    errors: list[str] = []
    for skill_id, tool_list in SKILL_TOOL_BUNDLES.items():
        for name in tool_list:
            if name not in builtin_names:
                errors.append(f"{skill_id}: {name}")
    return errors


__all__ = ["SKILL_TOOL_BUNDLES", "tool_names_for_skills", "validate_tool_bundles"]
