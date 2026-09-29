# Composing a custom Shipit agent harness

Shipit supports composition through ordinary `Agent`, not a separate `Harness`
API. Applications supply their provider, authorized tools, MCP servers, hooks,
skills and history/session owner.

```python
from shipit_agent import Agent, FunctionTool
from shipit_agent.plugins import Plugin

def register(registrar):
    registrar.add_tool(FunctionTool.from_callable(
        lambda: "Service is ready", name="service_status", read_only=True,
    ))

agent = Agent(
    llm=llm,
    plugins=[Plugin(name="service-tools", register=register)],
    mcps=authorized_servers,
    permissions=permissions,
    skill_registry=registry,
    progressive_skills=True,
    max_task_tokens=50_000,
    auto_project_memory=False,
    auto_project_skills=False,
)
with agent:
    for event in agent.stream("Check service status"):
        handle_event(event)
```

The host must provide the variables above. Give each conversation its own
history/session identity and tenant-scoped tool/server configuration. Plugins
are trusted Python code, not sandboxed user uploads. Do not expose arbitrary
plugin installation to untrusted users. Mutable plugin closures are also the
plugin author's responsibility; hook-list isolation does not isolate arbitrary
external state.

Hooks can observe calls or deny/rewrite them. Existing permission checks still
apply. Progressive skill loading does not grant tool permissions. DRK already
owns an authorization-aware `load_skill`, so do not install the ordinary
progressive loader alongside DRK's loader.

For streaming, treat text deltas as provisional and reconcile against the final
answer. Track actual tool lifecycle events; prose claiming a tool ran is not
execution evidence. Token limits are soft per-run limits, not a spending cap.

## Compatibility boundary

There is no built-in adapter that executes the Claude Code or Codex CLI/SDK as
a backend, nor a promise of their plugin-manifest compatibility. Such an
adapter needs an explicit execution environment, permission mapping,
cancellation, session persistence and output-protocol validation. Existing
support for tool/plugin composition is not equivalent to that integration.

## Validation

The combined streaming regression exercises a plugin tool followed by an MCP
tool, with and without a plugin hook denying the remote call. It verifies
actual execution, hook invocation, emitted text deltas and one final answer.
This is a scripted runtime contract test, not live model reasoning validation.
Real Bedrock/Gemma with fixture MCP is covered separately in
[the validation report](../progressive-agent-controls.md).
