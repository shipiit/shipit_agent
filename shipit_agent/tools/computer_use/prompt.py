COMPUTER_USE_PROMPT = """Use the `computer_use` tool when you need to drive a native GUI app — one that has no API, no CLI flag, and no web surface. Think Finder, Photos, Messages, Preview, a native preferences pane, a packaged Electron app without automation hooks.

Action vocabulary (pass one `action` per call):

  - `screenshot`        — capture the current screen. Always do this FIRST. Returns an absolute PNG path; re-request it as an image so the model can see it.
  - `mouse_move`        — move the cursor to `(x, y)`.
  - `click`             — click at `(x, y)`. Optional `button`: left|right|middle. Optional `double: true`.
  - `drag`              — drag from `(x, y)` to `(to_x, to_y)`.
  - `scroll`            — scroll at `(x, y)` by `(dx, dy)` ticks.
  - `type`              — type a string (`text`).
  - `key`               — press a key chord (`keys`, e.g. "cmd+shift+4").
  - `wait`              — sleep `seconds` before the next action (for animations).

Rules:

1. Screenshot before every ambiguous action. You don't know where the button is until you look.
2. Coordinates are pixel-absolute from the TOP-LEFT. On a Retina display you'll get logical pixels (1/2 of the raw resolution).
3. Prefer keyboard shortcuts over mouse where possible — they don't depend on layout.
4. For web tasks, prefer `playwright_browser`. `computer_use` is for the LAST RESORT when nothing else can reach the UI.
5. If a platform primitive is missing (e.g. cliclick not installed on macOS), the tool returns a clear install instruction. Surface that to the user.
"""
