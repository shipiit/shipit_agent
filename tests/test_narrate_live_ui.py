"""The live notebook panel — what it draws, and what it must never do.

The animation itself is only observable in a real kernel. Everything else —
which rows appear, what a half-finished run looks like, whether the styles
could leak into the page around it — is a string, and is checked here.
"""

from __future__ import annotations

from shipit_agent.models import AgentEvent
from shipit_agent.narrate.live_ui import LiveView, render_chat_html, watch


def event(kind: str, **payload) -> AgentEvent:
    return AgentEvent(type=kind, message="", payload=payload)


def a_run() -> list[AgentEvent]:
    """A run with every kind of row in it."""
    return [
        event("run_started", prompt="Which accounts are at risk?"),
        event("tool_called", call_id="1", tool="read_file", arguments={"path": "a.py"}),
        event("tool_completed", call_id="1", tool="read_file", output="x = 1\ny = 2",
              duration_ms=4),
        event("tool_called", call_id="2", tool="grep_files",
              arguments={"pattern": "risk"}),
        event("tool_completed", call_id="2", tool="grep_files", output="a.py:1: risk",
              duration_ms=9),
        event("text_delta", chunk="Three I would "),
        event("text_delta", chunk="put on your list."),
        event("action_queued", action_id=7, tool="slack", title="Used Slack #eng",
              tag="comms.send"),
        event("run_completed", output="Three I would put on your list.",
              usage={"total_tokens": 18240}),
    ]


def feed(view: LiveView, events) -> LiveView:
    for item in events:
        view.feed(item)
    return view


class TestContent:
    def test_every_row_type_reaches_the_panel(self) -> None:
        page = render_chat_html(a_run(), model="gemma-4-26b")
        assert "Which accounts are at risk?" in page      # the ask
        assert "Read a.py" in page or "Read" in page      # work row
        assert "Three I would put on your list." in page  # prose
        assert "Used Slack #eng" in page                  # approval
        assert "comms.send" in page
        assert "18,240 tokens" in page
        assert "gemma-4-26b" in page

    def test_real_tool_output_is_included_not_summarized(self) -> None:
        # The whole point of the panel over a screenshot: the actual bytes.
        assert "x = 1" in render_chat_html(a_run())

    def test_output_can_be_withheld(self) -> None:
        assert "x = 1" not in render_chat_html(a_run(), show_output=False)

    def test_long_output_is_clipped(self) -> None:
        events = [
            event("tool_called", call_id="1", tool="read_file", arguments={}),
            event("tool_completed", call_id="1", tool="read_file", output="z" * 9000),
            event("run_completed", output="done", usage={}),
        ]
        page = render_chat_html(events)
        assert "z" * 9000 not in page
        assert "…" in page

    def test_a_failed_call_is_marked(self) -> None:
        events = [
            event("tool_called", call_id="1", tool="bash", arguments={"command": "ls"}),
            event("tool_failed", call_id="1", tool="bash", error="boom"),
            event("run_completed", output="", usage={}),
        ]
        page = render_chat_html(events)
        assert "sa-err" in page and "boom" in page

    def test_a_denied_call_is_marked(self) -> None:
        events = [
            event("tool_denied", tool="bash", call_id="1", reason="on the deny list"),
            event("run_completed", output="", usage={}),
        ]
        assert "on the deny list" in render_chat_html(events)

    def test_sub_agent_work_is_attributed_not_merged(self) -> None:
        events = [
            event("sub_agent_event", agent="researcher", task="find the owner",
                  inner_type="tool_called",
                  inner={"tool": "read_file", "call_id": "s1",
                         "arguments": {"path": "owners.md"}}),
            event("run_completed", output="Dana owns it.", usage={}),
        ]
        page = render_chat_html(events)
        assert "sa-sub" in page
        assert "researcher" in page

    def test_a_notice_is_surfaced(self) -> None:
        events = [
            event("lockdown_engaged", reason="read a private file"),
            event("run_completed", output="", usage={}),
        ]
        assert "Lockdown" in render_chat_html(events)


class TestLiveState:
    def test_a_running_call_shows_before_it_finishes(self) -> None:
        view = feed(
            LiveView(display=False),
            [event("tool_called", call_id="1", tool="read_file",
                   arguments={"path": "a.py"})],
        )
        page = view.html()
        assert "sa-run" in page          # in-flight styling
        assert "a.py" in page            # you can see what it is reading
        assert "Live" in page

    def test_streaming_prose_carries_a_caret_until_it_settles(self) -> None:
        caret = '<span class="sa-caret">'  # the element, not the CSS rule
        view = feed(LiveView(display=False), [event("text_delta", chunk="Thinking")])
        assert caret in view.html()
        view.close()
        assert caret not in view.html()

    def test_closing_flips_the_badge(self) -> None:
        view = LiveView(display=False)
        assert "Live" in view.html()
        view.close()
        assert "Done" in view.html()

    def test_nothing_is_lost_between_live_and_final(self) -> None:
        view = feed(LiveView(display=False), a_run())
        live = view.html()
        view.close()
        assert "Three I would put on your list." in live
        assert "Three I would put on your list." in view.html()

    def test_the_prompt_is_picked_up_from_the_run(self) -> None:
        view = feed(LiveView(display=False), a_run())
        assert view.prompt == "Which accounts are at risk?"


class TestSafety:
    def test_styles_cannot_escape_the_panel(self) -> None:
        """A bare `body {}` here would restyle the notebook around it."""
        page = render_chat_html(a_run())
        style = page[page.index("<style>") + 7 : page.index("</style>")]
        for block in style.split("}"):
            selector = block.split("{")[0].strip()
            if not selector or selector.startswith(("@", "0%", "50%", "100%")):
                continue
            for part in selector.split(","):
                assert part.strip().startswith(".sa-live"), part

    def test_tool_output_is_escaped(self) -> None:
        events = [
            event("tool_called", call_id="1", tool="read_file", arguments={}),
            event("tool_completed", call_id="1", tool="read_file",
                  output="<script>alert(1)</script>"),
            event("run_completed", output="", usage={}),
        ]
        page = render_chat_html(events)
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page

    def test_the_prompt_is_escaped(self) -> None:
        page = render_chat_html([], prompt="<img src=x onerror=1>")
        assert "<img src=x" not in page

    def test_an_empty_run_still_renders(self) -> None:
        assert "sa-live" in render_chat_html([])


class TestThrottle:
    def test_token_deltas_do_not_redraw_every_time(self) -> None:
        drawn: list[int] = []

        view = LiveView(display=False, min_interval=60.0)
        view._handle = _FakeHandle(drawn)  # type: ignore[assignment]
        for _ in range(50):
            view.feed(event("text_delta", chunk="x"))
        assert len(drawn) <= 2, "a redraw per token is O(n^2) DOM churn"

    def test_structural_events_always_redraw(self) -> None:
        drawn: list[int] = []
        view = LiveView(display=False, min_interval=60.0)
        view._handle = _FakeHandle(drawn)  # type: ignore[assignment]
        for index in range(5):
            view.feed(event("tool_called", call_id=str(index), tool="read_file",
                            arguments={}))
        assert len(drawn) == 5

    def test_close_always_redraws(self) -> None:
        drawn: list[int] = []
        view = LiveView(display=False, min_interval=60.0)
        view._handle = _FakeHandle(drawn)  # type: ignore[assignment]
        view.close()
        assert drawn


class _FakeHandle:
    """Stands in for an IPython display handle so `update` can be counted."""

    def __init__(self, log: list[int]) -> None:
        self._log = log

    def update(self, _payload) -> None:
        self._log.append(1)


class TestWatch:
    def test_watch_returns_the_answer_and_renders(self) -> None:
        class FakeAgent:
            llm = type("L", (), {"model": "gemma-4-26b"})()

            def stream(self, prompt):
                yield from a_run()

        assert watch(FakeAgent(), "Which accounts are at risk?").startswith("Three")

    def test_the_panel_closes_even_if_the_run_raises(self) -> None:
        class Exploding:
            llm = None

            def stream(self, prompt):
                yield event("text_delta", chunk="partial")
                raise RuntimeError("provider died")

        try:
            watch(Exploding(), "go")
        except RuntimeError:
            pass
        else:  # pragma: no cover
            raise AssertionError("the error should not be swallowed")
