"""present_file — surface a finished file to the user as a downloadable deliverable.

    from shipit_agent.tools.present_file import PresentFileTool
    # returns a path + a MEDIA: tag; the runtime tracks it as an artifact/download

The file must already exist; this tool labels it and hands it to the user, the
way ChatGPT/Codex surface an artifact. Images preview inline via the vision bridge.
"""

from .present_file_tool import PresentFileTool

__all__ = ["PresentFileTool"]
