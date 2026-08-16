"""Video generation — a tool + a small provider registry.

    from shipit_agent import Agent
    from shipit_agent.tools.video_generate import VideoGenerateTool

    agent = Agent(llm=llm, tools=[VideoGenerateTool()])   # needs FAL_KEY / REPLICATE_API_TOKEN
    agent.run("A 5-second clip of coffee being poured in slow motion.")

Backends live in ``providers`` (Fal and Replicate built in; others register in).
The tool is availability-gated: with no backend key set it's hidden from the
model. Generation is slow — the backend blocks (submit → poll → download) and the
tool returns a saved MP4 path plus a ``MEDIA:<path>`` tag.
"""

from .providers import (
    FalVideoProvider,
    ReplicateVideoProvider,
    VideoProvider,
    available_providers,
    build_video_provider,
    register_video_provider,
    validate_video_model,
)
from .video_gen_tool import VideoGenerateTool

__all__ = [
    "FalVideoProvider",
    "ReplicateVideoProvider",
    "VideoGenerateTool",
    "VideoProvider",
    "available_providers",
    "build_video_provider",
    "register_video_provider",
    "validate_video_model",
]
