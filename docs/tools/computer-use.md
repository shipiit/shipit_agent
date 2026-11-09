---
title: computer_use
description: Drive the local desktop — screenshots, clicks, typing, key chords. Platform-aware backends for macOS (cliclick / osascript), Linux (xdotool / scrot), and Windows (PowerShell).
---

# `computer_use`

Desktop automation. Capture screenshots, move the
cursor, click, type, press key chords — on macOS, Linux, or Windows.
When the target has no API, CLI, or web path, `computer_use` is the
reach of last resort.

> **TL;DR** — `ComputerUseTool().run(ctx, action="screenshot")` writes
> a PNG to `~/.shipit_agent/computer_use/`. Other actions (`click`,
> `type`, `drag`, `key`, `scroll`, `wait`) drive the active desktop.

---

## Backends

| Platform | Primitives | Install |
| --- | --- | --- |
| macOS | `screencapture` + `cliclick` (with AppleScript fallback) | `brew install cliclick` |
| Linux | `scrot` or `import` (ImageMagick) + `xdotool` | `apt install scrot xdotool` |
| Windows | PowerShell (`System.Windows.Forms`) | built-in |

Missing dependency? The tool returns an explicit install hint instead
of silently failing — `Error: cliclick required for drag (install: brew install cliclick)`.

---

## Actions

| Action | Required params | What it does |
| --- | --- | --- |
| `screenshot` / `capture` | — | PNG to `~/.shipit_agent/computer_use/shot-<ts>.png` |
| `mouse_move` / `move` | `x`, `y` | Move cursor |
| `click` | `x`, `y` | Optional `button` (`left`/`right`/`middle`), `double` (bool) |
| `drag` | `x`, `y`, `to_x`, `to_y` | Press-move-release |
| `type` | `text` | Type a string |
| `key` | `keys` (e.g. `"cmd+shift+4"`) | Press a key chord |
| `scroll` | `x`, `y`, `dx`, `dy` | Scroll at a position |
| `wait` | `seconds` | Sleep (max 60s) between actions for animations |

Mouse coordinates are **top-left-origin pixel-absolute**. On a Retina
display you pass logical pixels (1/2 of the raw resolution).

---

## Quickstart

```python
from shipit_agent.tools.computer_use import ComputerUseTool
from shipit_agent.tools.base import ToolContext

computer = ComputerUseTool()
ctx = ToolContext(prompt="demo")

# 1. Take a screenshot
out = computer.run(ctx, action="screenshot")
print(out.metadata["path"])         # /Users/you/.shipit_agent/computer_use/shot-…png

# 2. Click at coordinates
computer.run(ctx, action="click", x=640, y=480)

# 3. Type text
computer.run(ctx, action="type", text="hello from shipit_agent")

# 4. Press a chord
computer.run(ctx, action="key", keys="cmd+shift+4")

# 5. Scroll down a page
computer.run(ctx, action="key", keys="pagedown")
```

---

## Recommended workflow

1. **Screenshot first.** The agent doesn't know where to click until
   it sees the screen. Re-send the PNG through your LLM's vision API
   so the model can reason over pixels.
2. **Prefer keyboard shortcuts.** Layout-independent, faster, more
   reliable than mouse clicks.
3. **Use `computer_use` as the LAST RESORT.** For web tasks, reach
   for `playwright_browser`. For files, use `read_file` / `write_file`.
4. **Wrap long flows in an Autopilot** so budgets and checkpoints
   protect against stuck GUI states.

---

## Auto-screenshot mode

If you want every action to be followed by a fresh screenshot — handy
for verification chains — pass `auto_screenshot_after_action=True`:

```python
computer = ComputerUseTool(auto_screenshot_after_action=True)
out = computer.run(ctx, action="click", x=100, y=200)
print(out.metadata["screenshot"])   # path to the fresh PNG
```

---

## Using it with a specialist

The `design-reviewer` specialist pairs well with `computer_use` for UI
verification runs:

```python
from shipit_agent import Agent
from shipit_agent.agents import AgentRegistry
from shipit_agent.tools.computer_use import ComputerUseTool

registry = AgentRegistry.default()
def_ = registry.get("design-reviewer")
ui_agent = Agent(
    llm=llm,
    prompt=def_.prompt,
    tools=[ComputerUseTool()],
    max_iterations=8,
    name=def_.name,
)
ui_agent.run("Open the Preferences pane, enable dark mode, screenshot the final state.")
```

---

## Vision feedback — the screenshot's PNG bytes travel with the result

Every `screenshot` action now embeds the **base64-encoded PNG** in the
tool output's metadata so a vision-capable LLM can actually *see* what
got captured — not just read a file path.

```python
out = computer.run(ctx, action="screenshot")
out.metadata["vision"]        # True
out.metadata["media_type"]    # "image/png"
out.metadata["image_base64"]  # "iVBORw0KGgoAAAANS..."  ← feed this into the next LLM call
out.metadata["path"]          # "/Users/you/.shipit_agent/computer_use/shot-…png"
```

Opt out for large captures (saves tokens when you only need the path):

```python
computer.run(ctx, action="screenshot", vision=False)
```

Guardrails:

- Images over **4 MB** auto-skip the embed — `metadata["vision"] == False`
  with a `vision_skip_reason` telling you why.
- Failures to read the PNG from disk (very rare) don't raise — they set
  `vision=False` and include the error in `vision_skip_reason`.

This lands the missing piece for real GUI automation: before 1.0.6,
an agent captured screens it couldn't interpret. Now it can.

---

## Output directory

- Default: `~/.shipit_agent/computer_use/`
- Override: `ComputerUseTool(output_dir="/tmp/shots")`
- One PNG per `screenshot` action; never deletes.

The directory is created on first use.

---

## Notebook

- `notebooks/42_power_tools_computer_use_hubspot_research.ipynb` — `computer_use` alongside the other power tools.
- `notebooks/44_complete_tour.ipynb` — cross-tool example with Autopilot.
