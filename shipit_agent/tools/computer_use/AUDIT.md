# computer_use, playwright_browser, open_url — audit

Three tools in the existing tree overlap on "reach something outside the
process". Keeping all three is worse than keeping one: overlapping tools make
every relevant call a coin flip, and two of the three carry heavy dependencies.

## What each actually does

| Tool | Mechanism | Dependency | Breaks when |
|---|---|---|---|
| `computer_use` | screenshots + synthetic mouse/keyboard | display server, screen capture | anything moves; resolution differs; a dialog steals focus |
| `playwright_browser` | a real browser driven by DOM selectors | Playwright + browser binary (~400 MB) | a selector changes |
| `open_url` / `download_file` | one HTTP GET | none | the page needs JavaScript |

They are not three points on one scale. They are three different failure
surfaces, and the cheapest one answers most questions.

## Recommendation

**Keep `fetch_url`** (shipped in `tools/fetch_url/`). It replaces `open_url` and
`download_file`, has no dependency, and answers the overwhelming majority of
"what does this page say" — which is what the model actually asks.

**Keep `playwright_browser`**, bound only for agents that genuinely need a
browser, or deferred behind `tool_search`. Its schemas are large and most runs
never touch it.

**Drop `computer_use`** unless controlling a screen is a product requirement
rather than a capability wish. Three reasons:

1. **It is the least reliable path to any goal that has another path.** Clicking
   coordinates derived from a screenshot breaks when a window moves, a font
   renders differently, or a notification appears. A DOM selector or an HTTP
   request does not.
2. **It costs tokens on every turn it is bound.** Screenshot-driven tools carry
   large schemas and return image results, and both are re-sent as the
   conversation grows.
3. **It has the widest blast radius in the tool list.** Synthetic input can click
   anything the logged-in user can click, and no path-scoped rule can constrain
   it — unlike `bash`, where a rule can forbid `rm -rf`, or `edit_file`, where
   the workspace boundary is enforced in code.

If it stays: deferred by default, gated behind an approval callback, and scoped
to a named window or a virtual display rather than the whole desktop.

## Migration

```python
# before
tools = [open_url, download_file, computer_use, playwright_browser]

# after
tools = core_tools(".") + [FetchUrlTool()]
deferred_tools = ["playwright_browser"]   # found via tool_search when needed
```

Two dependencies removed, roughly 3–4k schema tokens off every turn, and the
capability still reachable.
