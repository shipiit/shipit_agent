"""Guidance surfaced to the model for the video_generate tool."""

VIDEO_GENERATE_PROMPT = (
    "Use video_generate to CREATE a short video clip from a description — a "
    "product shot, an animation, b-roll, a concept scene. Write a specific "
    "prompt (subject, motion, camera, style). Generation takes time; the call "
    "blocks until the clip is ready, then saves an MP4 and returns its path with "
    "a MEDIA: tag a chat surface can play. Keep clips short (a few seconds). "
    "It does not edit existing footage."
)
