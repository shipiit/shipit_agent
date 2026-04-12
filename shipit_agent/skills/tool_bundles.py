"""Skill-to-tool bundle mapping for stronger runtime defaults."""

from __future__ import annotations

from .skill import Skill


SKILL_TOOL_BUNDLES: dict[str, list[str]] = {
    "web-scraper-pro": [
        "web_search",
        "open_url",
        "playwright_browse",
        "bash",
        "glob_files",
        "grep_files",
        "read_file",
        "edit_file",
        "write_file",
        "run_code",
    ],
    "code-workflow-assistant": [
        "bash",
        "read_file",
        "edit_file",
        "write_file",
        "glob_files",
        "grep_files",
        "workspace_files",
        "run_code",
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
    "portfolio-website-builder": [
        "bash",
        "read_file",
        "edit_file",
        "write_file",
        "glob_files",
        "grep_files",
        "workspace_files",
        "run_code",
    ],
    "google-maps-lead-finder": [
        "web_search",
        "open_url",
        "playwright_browse",
        "bash",
        "write_file",
        "run_code",
    ],
    "startup-idea-scout": [
        "web_search",
        "open_url",
        "playwright_browse",
        "read_file",
        "write_file",
        "run_code",
        "synthesize_evidence",
        "decision_matrix",
    ],
    "competitor-intelligence-tracker": [
        "web_search",
        "open_url",
        "playwright_browse",
        "grep_files",
        "read_file",
        "write_file",
        "run_code",
        "synthesize_evidence",
    ],
    "lead-enrichment": [
        "web_search",
        "open_url",
        "playwright_browse",
        "write_file",
        "run_code",
        "build_artifact",
    ],
    "technical-writer": [
        "read_file",
        "edit_file",
        "write_file",
        "glob_files",
        "grep_files",
        "build_artifact",
        "verify_output",
    ],
    "security-engineer": [
        "bash",
        "web_search",
        "open_url",
        "read_file",
        "grep_files",
        "glob_files",
        "run_code",
        "verify_output",
    ],
}


def tool_names_for_skills(skills: list[Skill]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        for name in [*skill.tools, *SKILL_TOOL_BUNDLES.get(skill.id, [])]:
            if name in seen:
                continue
            names.append(name)
            seen.add(name)
    return names


__all__ = ["SKILL_TOOL_BUNDLES", "tool_names_for_skills"]
