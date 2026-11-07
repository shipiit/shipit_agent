"""What the model is sent each step: prompt hooks, labelled user turns, the step request, images and result recall.

Mixed into :class:`~shipit_agent.core.runtime_core.RuntimeCore`;
the methods run on the runtime instance.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Sequence

from shipit_agent.core.decisions.prior_outputs import _EVICT_MIN_CHARS, attach_reminder
from shipit_agent.core.models import Message


class StepMessagesMixin:
    """What the model is sent each step: prompt hooks, labelled user turns, the step request, images and result recall."""

    @staticmethod
    def install_result_recall(registry: Any, messages: Sequence[Message]) -> str:
        """Attach exact historical-result recall only when there is data for it."""
        from shipit_agent.tools.recall_result.recall_result_tool import (
            RecallToolResult,
            recallable_results,
        )

        results = recallable_results(list(messages), min_chars=_EVICT_MIN_CHARS)
        if not results or registry.get(RecallToolResult.name) is not None:
            return ""
        registry.register(RecallToolResult(results))
        return RecallToolResult.name

    def apply_user_prompt_hooks(
        self, state: Any, user_prompt: str
    ) -> tuple[str, str | None]:
        """Run ``on_user_prompt`` hooks: ``(prompt, None)`` or ``(prompt, refusal)``.

        The hooks were documented (redact or rewrite the incoming prompt, or
        block it) but no run path called them, so they silently did nothing.
        """
        hooks = getattr(self, "hooks", None)
        if (
            hooks is None
            or not getattr(hooks, "user_prompt", None)
            or not isinstance(user_prompt, str)
        ):
            return user_prompt, None
        rewritten, decision = hooks.run_user_prompt(user_prompt)
        if decision is not None and decision.denied:
            reason = decision.reason or "blocked by a prompt hook"
            self.emit(
                state, "prompt_blocked", f"Prompt blocked: {reason}", reason=reason
            )
            return rewritten, f"Request blocked: {reason}"
        return rewritten, None

    @staticmethod
    def label_user_turns(messages: Sequence[Message]) -> list[Message]:
        """Label user turns in the transient model view.

        Tool calls insert several assistant/tool messages between user turns,
        so an instruction such as "use facts from turns 1, 3, and 5" is
        otherwise ambiguous to a model counting raw messages. Copies are
        returned because these labels are navigation aids, not user content,
        and must never enter the runtime transcript or durable session record.
        """
        labelled: list[Message] = []
        human_user_indexes = [
            index
            for index, message in enumerate(messages)
            if message.role == "user"
            and not (
                message.metadata.get("internal")
                or message.metadata.get("compacted")
                or message.metadata.get("vision_bridge")
                or message.metadata.get("regrounding")
                or message.metadata.get("source") == "planner"
            )
        ]
        current_user_index = human_user_indexes[-1] if human_user_indexes else -1
        turn = 0
        for index, message in enumerate(messages):
            clone = deepcopy(message)
            synthetic = bool(
                clone.metadata.get("internal")
                or clone.metadata.get("compacted")
                or clone.metadata.get("vision_bridge")
                or clone.metadata.get("regrounding")
                or clone.metadata.get("source") == "planner"
            )
            if clone.role == "user" and not synthetic:
                turn += 1
                if index != current_user_index and isinstance(clone.content, str):
                    clone.content = f"[User turn {turn}]\n{clone.content}"
            labelled.append(clone)
        return labelled

    def step_request(
        self,
        *,
        messages: list[Message],
        tool_schemas: list[Any],
        iteration: int,
        ran_tools: bool,
    ) -> tuple[list[Message], list[Any]]:
        """The messages and schemas for one step.

        Two decisions live here rather than in either loop, because having
        them in both is how the loops drift apart.

        **The final step is sent without tools.** A tool call emitted there
        has no iteration left to run in: the run ends with the model having
        announced work instead of doing it, and the user gets no answer.
        Withholding the schemas forces the answer, and drops the largest
        fixed cost in the request from the longest prompt of the run. A run
        configured with a single step keeps its tools — dropping them there
        would mean the tool could never be called at all.

        **The reminder goes last.** Models attend most strongly to the tokens
        closest to generation. It is appended to the returned copy, never to
        the caller's list, so it is rebuilt each step and cannot stack.
        """
        from shipit_agent.prompts.reminders import (
            REANNOUNCE_DAMPER,
            build_reminder,
            is_reannouncing,
        )

        max_iterations = int(getattr(self, "max_iterations", 0) or 0)
        last_step = iteration == max_iterations and max_iterations > 1
        step_schemas = [] if last_step else list(tool_schemas)

        # Screenshots age fast; only the newest few are worth their tokens.
        # Applied to this per-call copy only — the originals stay stored.
        messages = self.prune_stale_images(list(messages))

        # The built-in reminders are about tool use, so they attach only when
        # tools exist — but a caller's own standing instruction applies to
        # every agent, tools or not. Dropping it silently for a tool-less
        # agent made `Agent(reminder=...)` a no-op in exactly the
        # configuration where the caller has no other end-of-context channel.
        if tool_schemas:
            reminder = build_reminder(
                ran_tools=ran_tools,
                out_of_steps=last_step,
                custom=self.reminder,
            )
            # Re-announcement damping: if the model keeps restating the same plan
            # across steps instead of acting, append a terse "act, don't restate"
            # line. Only with tools and not on the last step (which already tells
            # it to answer), and only once repetition is actually observed — a
            # first honest "here's my plan" is never discouraged.
            if not last_step and is_reannouncing(messages):
                reminder = (
                    f"{reminder}\n\n{REANNOUNCE_DAMPER}"
                    if reminder
                    else REANNOUNCE_DAMPER
                )
        else:
            reminder = (self.reminder or "").strip() or None
        if reminder:
            messages = attach_reminder(messages, reminder)
        return messages, step_schemas

    def vision_followup(self, tool_result: Any, tool_name: str) -> Message | None:
        """A user message carrying a tool result's image, or ``None``.

        Tools that produce something to LOOK AT (screenshots, image files,
        rendered pages) declare it: ``metadata["image_base64"]`` +
        ``metadata["media_type"]`` (the convention computer_use introduced),
        or the explicit ``metadata["vision"]`` flag. Providers want images
        in a *user* turn — Anthropic rejects rich blocks inside tool_result
        content on several transports — so the bridge is a synthetic user
        message appended right after the tool message.
        """
        metadata = dict(getattr(tool_result, "metadata", None) or {})
        data = metadata.get("image_base64")
        if not data or metadata.get("vision") is False:
            return None
        media_type = str(metadata.get("media_type") or "image/png")
        return Message(
            role="user",
            content=[
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": str(data),
                    },
                },
                {
                    "type": "text",
                    "text": f"[image returned by the {tool_name} tool]",
                },
            ],
            metadata={"vision_bridge": True, "internal": True, "tool": tool_name},
        )

    @classmethod
    def prune_stale_images(cls, messages: list[Message]) -> list[Message]:
        """Keep only the newest ``MAX_VISION_MESSAGES`` image messages.

        Applied to the per-request copy, never the stored conversation — the
        original screenshots stay in the session for replay. Older images
        are replaced by a one-line stub so the model still knows something
        was there (and can re-request it) without paying image tokens for a
        state of the world that no longer exists.
        """
        image_indexes = [
            i
            for i, m in enumerate(messages)
            if isinstance(m.content, list)
            and any(isinstance(b, dict) and b.get("type") == "image" for b in m.content)
        ]
        stale = set(image_indexes[: -cls.MAX_VISION_MESSAGES or None])
        if not stale:
            return messages
        pruned = list(messages)
        for i in stale:
            source = (pruned[i].metadata or {}).get("tool", "a tool")
            pruned[i] = Message(
                role=pruned[i].role,
                name=pruned[i].name,
                content=(
                    f"[an earlier image from {source} was shown here; it is "
                    "stale and has been removed — re-run the tool if you "
                    "need a fresh look]"
                ),
                metadata=dict(pruned[i].metadata or {}),
            )
        return pruned
