"""The SHIPIT Workspace — point an agent at a repo and it just works.

- ``load_project_memory`` — auto-load ``SHIPIT.md`` / ``AGENTS.md`` instructions.
- ``expand_command`` / ``discover_commands`` — ``/slash`` commands from ``.shipit/commands/``.
- ``load_settings`` / ``WorkspaceSettings`` — declarative ``.shipit/settings.json`` policy.
"""

from .commands import commands_dir, discover_commands, expand_command, skills_dir
from .project_memory import PROJECT_FILES, USER_FILES, load_project_memory
from .settings import WorkspaceSettings, load_settings, settings_path

__all__ = [
    "load_project_memory",
    "PROJECT_FILES",
    "USER_FILES",
    "discover_commands",
    "expand_command",
    "commands_dir",
    "skills_dir",
    "WorkspaceSettings",
    "load_settings",
    "settings_path",
]
