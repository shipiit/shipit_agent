"""Text-to-speech — a tool + a small provider registry.

    from shipit_agent import Agent
    from shipit_agent.tools.text_to_speech import TextToSpeechTool

    agent = Agent(llm=llm, tools=[TextToSpeechTool()])   # `pip install edge-tts` for free speech
    agent.run("Say 'welcome aboard' as audio.")

Backends live in ``providers`` (Edge free / OpenAI / ElevenLabs built in; others
register in). The tool is availability-gated: with no backend it's hidden.
"""

from .providers import (
    EdgeTTSProvider,
    ElevenLabsTTSProvider,
    OpenAITTSProvider,
    TTSProvider,
    available_providers,
    build_tts_provider,
    register_tts_provider,
)
from .tts_tool import TextToSpeechTool

__all__ = [
    "TextToSpeechTool",
    "TTSProvider",
    "EdgeTTSProvider",
    "OpenAITTSProvider",
    "ElevenLabsTTSProvider",
    "available_providers",
    "build_tts_provider",
    "register_tts_provider",
]
