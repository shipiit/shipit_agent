"""Guidance surfaced to the model for the text_to_speech tool."""

TEXT_TO_SPEECH_PROMPT = (
    "Use text_to_speech to turn text into spoken audio — a summary read aloud, "
    "a voice reply, a narration. It saves an audio file and returns its path "
    "with a MEDIA: tag a chat surface can play. Keep the text natural to hear "
    "(short sentences, no markup). Pick a voice if the user asked for one."
)
