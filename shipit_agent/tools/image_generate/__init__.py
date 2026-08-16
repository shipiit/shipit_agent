"""Image generation — a tool + a small provider registry.

    from shipit_agent import Agent
    from shipit_agent.tools.image_generate import ImageGenerateTool

    agent = Agent(llm=llm, tools=[ImageGenerateTool()])   # needs OPENAI_API_KEY
    agent.run("Draw a minimalist logo for a coffee shop called Orbit.")

Backends live in ``providers`` (OpenAI built in; others register in). The tool
is availability-gated: with no backend key set it's hidden from the model.
"""

from .image_gen_tool import ImageGenerateTool
from .providers import (
    ImageProvider,
    OpenAIImageProvider,
    available_providers,
    build_image_provider,
    register_image_provider,
    validate_image_model,
)

__all__ = [
    "ImageGenerateTool",
    "ImageProvider",
    "OpenAIImageProvider",
    "available_providers",
    "build_image_provider",
    "register_image_provider",
    "validate_image_model",
]
