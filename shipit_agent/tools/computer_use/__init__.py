"""`computer_use` — control the local desktop like Claude Desktop does.

Lets the agent take screenshots, move the cursor, click, type, and press
keys. This is the "eyes and hands" primitive that makes multi-step GUI
automation possible — filling a form in the Finder, driving a native app
that has no API, verifying visual changes in an Electron build.

Backends (auto-selected by platform):

  - macOS   → `screencapture` for screenshots, `cliclick` for mouse/keyboard
              (install via `brew install cliclick`). Falls back to an
              AppleScript `System Events` path if `cliclick` isn't present.
  - Linux   → `scrot` or `import` (ImageMagick) for screenshots, `xdotool`
              for input. Wayland users should set `WAYLAND_USE_YDOTOOL=1`
              and install `ydotool` with its daemon running.
  - Windows → `powershell` screen capture + SendKeys (basic; complex flows
              belong in `playwright_browser`).

Every action takes a hard timeout and returns structured output so the
agent can decide what to do next. Screenshots are written to disk under
`.shipit_agent/computer_use/` and the tool result contains the absolute
path — the agent can then send the image back to the model for vision-
based interpretation.
"""

from .computer_use_tool import ComputerUseTool, TAKE_SCREENSHOT_ACTIONS
from .prompt import COMPUTER_USE_PROMPT

__all__ = ["ComputerUseTool", "COMPUTER_USE_PROMPT", "TAKE_SCREENSHOT_ACTIONS"]
