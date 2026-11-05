"""Installing code mode: the model writes one script that calls tools, instead of calling them one by one.

Mixed into :class:`~shipit_agent.core.async_runtime.AsyncAgentRuntime`;
the methods run on the runtime instance.
"""

from __future__ import annotations

import asyncio
from typing import Any

from shipit_agent.core.registry import ToolRegistry
from shipit_agent.core.state import (
    RuntimeState,
)
from shipit_agent.core.tool_runner import ToolRunner
from shipit_agent.tools import ToolContext


class CodeModeMixin:
    """Installing code mode: the model writes one script that calls tools, instead of calling them one by one."""

    def _install_code_mode(
        self,
        *,
        state: RuntimeState,
        registry: ToolRegistry,
        tool_runner: ToolRunner,
        shared_state: dict[str, Any],
        user_prompt: str,
        base_prompt: str,
        loop: asyncio.AbstractEventLoop,
    ) -> str:
        """Install code-mode bindings without bypassing the async tool gates.

        ``execute_code`` itself runs outside the event loop. Calls made through
        its synchronous ``env`` bridge are therefore submitted back to this
        runtime's loop, where they use the same permission, approval, retry,
        guardrail, and transcript path as direct async tool calls.
        """
        from shipit_agent.codemode import CORE_TOOLS, binding_index, build_bindings
        from shipit_agent.codemode.catalog import load_catalog
        from shipit_agent.tools.describe_binding.describe_binding_tool import (
            BINDINGS_STATE_KEY,
        )
        from shipit_agent.tools.execute_code.execute_code_tool import (
            INVOKER_STATE_KEY,
        )

        bound_tools = [
            tool
            for tool in registry.values()
            if getattr(tool, "name", "") not in CORE_TOOLS
        ]
        if not bound_tools:
            return ""

        catalogs = {
            getattr(tool, "name", ""): load_catalog(tool) for tool in bound_tools
        }
        bindings = build_bindings(bound_tools, catalogs=catalogs)
        counter = {"n": 0}

        def _invoke(
            binding_name: str, method: str, kwargs: dict[str, Any]
        ) -> tuple[str, dict[str, Any]]:
            binding = bindings.get(binding_name)
            if binding is None:
                raise KeyError(f"no binding named {binding_name!r}")
            if method not in binding.methods:
                raise AttributeError(f"env.{binding_name} has no method {method!r}")

            arguments = dict(kwargs)
            if method != "call":
                arguments["action"] = method
            counter["n"] += 1
            record = {"id": f"env_{counter['n']}", "name": binding.tool_name}
            call = type(
                "EnvToolCall",
                (),
                {"name": binding.tool_name, "arguments": arguments},
            )()
            future = asyncio.run_coroutine_threadsafe(
                self._execute_single_tool(
                    state=state,
                    registry=registry,
                    tool_runner=tool_runner,
                    tool_call=call,
                    tool_call_record=record,
                    context=ToolContext(
                        prompt=user_prompt,
                        system_prompt=base_prompt,
                        metadata=dict(self.metadata),
                        state=shared_state,
                        session_id=self.session_id,
                    ),
                    iteration=0,
                ),
                loop,
            )
            result, message = future.result()
            if result is None:
                raise PermissionError(message.content)
            if result.is_error:
                raise RuntimeError(result.output)
            return result.output, dict(result.metadata)

        shared_state[BINDINGS_STATE_KEY] = bindings
        shared_state[INVOKER_STATE_KEY] = _invoke
        return binding_index(bindings)
