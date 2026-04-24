"""`ask_user_async` — non-blocking variant of `ask_user`.

Call this when an Autopilot run needs a clarification from the user
but can't afford to block the loop. The question is written to a
side-channel file; the user answers later via
``shipit answer <run_id> "..."`` and Autopilot resumes on the next
iteration with the answer already in the channel.
"""

from .ask_user_async_tool import AskUserAsyncTool
from .prompt import ASK_USER_ASYNC_PROMPT

__all__ = ["AskUserAsyncTool", "ASK_USER_ASYNC_PROMPT"]
