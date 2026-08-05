"""The Narrator's renderer — live on a TTY, clean when piped."""

from __future__ import annotations

import io

import pytest

from shipit_agent.models import AgentEvent
from shipit_agent.narrate.renderer import LiveRegion, NarratorRenderer, render_transcript


def called(tool: str, call_id: str, **arguments) -> AgentEvent:
    return AgentEvent(
        type="tool_called",
        message="",
        payload={"tool": tool, "call_id": call_id, "arguments": arguments},
    )


def completed(tool: str, call_id: str, output: str = "ok") -> AgentEvent:
    return AgentEvent(
        type="tool_completed",
        message="",
        payload={"tool": tool, "call_id": call_id, "output": output, "duration_ms": 12},
    )


def text(chunk: str) -> AgentEvent:
    return AgentEvent(type="text_delta", message="", payload={"chunk": chunk})


def done(output: str = "", **usage) -> AgentEvent:
    return AgentEvent(
        type="run_completed", message="", payload={"output": output, "usage": usage}
    )


class FakeTTY(io.StringIO):
    def isatty(self) -> bool:  # noqa: D102
        return True


def render(events, **kwargs) -> str:
    buffer = kwargs.pop("file", None) or io.StringIO()
    renderer = NarratorRenderer(file=buffer, style=kwargs.pop("style", "plain"), **kwargs)
    for event in events:
        renderer.feed(event)
    renderer.close()
    return buffer.getvalue()


ACCOUNTS_AT_RISK = [
    called("read_file", "1", path="Enterprise Accounts"),
    completed("read_file", "1"),
    called("read_file", "2", path="Open Tickets"),
    completed("read_file", "2"),
    called("read_file", "3", path="Usage by Account"),
    completed("read_file", "3"),
    text("Let me look at usage trends, open tickets and renewal dates together."),
    called("run_code", "4", code="const risk = scoreAccounts(usage, tickets)"),
    completed("run_code", "4"),
    text("Three I would put on your list:\n  • Northwind: usage down 38% since March."),
    done(total_tokens=18_240),
]


class TestPipedOutput:
    def test_matches_the_reference_transcript(self) -> None:
        # An all-observation run takes the search glyph, as in the reference UI.
        assert render(ACCOUNTS_AT_RISK) == (
            "  ⌕ Read 3 files ›\n"
            "    Enterprise Accounts · Open Tickets · Usage by Account\n"
            "\n"
            "Let me look at usage trends, open tickets and renewal dates together.\n"
            "\n"
            "  ❯ Ran code const risk = scoreAccounts(usage, tickets) ›\n"
            "\n"
            "Three I would put on your list:\n"
            "  • Northwind: usage down 38% since March.\n"
            "\n"
            + " " * (78 - len("18,240 tokens"))
            + "18,240 tokens\n"
        )

    def test_no_escape_codes_when_piped(self) -> None:
        assert "\033" not in render(ACCOUNTS_AT_RISK)

    def test_no_cursor_motion_when_piped(self) -> None:
        output = render(ACCOUNTS_AT_RISK)
        assert "[A" not in output and "[J" not in output

    def test_output_is_stable_across_runs(self) -> None:
        assert render(ACCOUNTS_AT_RISK) == render(ACCOUNTS_AT_RISK)

    def test_render_transcript_matches_the_renderer(self) -> None:
        assert render_transcript(ACCOUNTS_AT_RISK) == render(ACCOUNTS_AT_RISK)


class TestLiveOutput:
    def test_tty_draws_and_rewinds_the_in_flight_row(self) -> None:
        buffer = FakeTTY()
        renderer = NarratorRenderer(file=buffer, style="auto")
        renderer.feed(called("read_file", "1", path="app.py"))
        drawn = buffer.getvalue()
        assert "Reading app.py" in drawn  # present tense while in flight

        renderer.feed(completed("read_file", "1"))
        renderer.feed(text("Done."))
        renderer.close()
        final = buffer.getvalue()
        assert "\033[1A\033[J" in final  # rewound the live region
        assert final.rstrip().endswith("Done.") or "Read app.py" in final

    def test_settled_rows_are_past_tense(self) -> None:
        buffer = FakeTTY()
        renderer = NarratorRenderer(file=buffer, style="auto", show_footer=False)
        for event in ACCOUNTS_AT_RISK:
            renderer.feed(event)
        renderer.close()
        assert "Read 3 files" in buffer.getvalue()

    def test_live_region_is_inert_when_disabled(self) -> None:
        buffer = io.StringIO()
        region = LiveRegion(buffer.write, enabled=False)
        region.draw(["one", "two"])
        region.clear()
        assert buffer.getvalue() == ""
        assert not region.active

    def test_live_region_rewinds_exactly_what_it_drew(self) -> None:
        buffer = io.StringIO()
        region = LiveRegion(buffer.write, enabled=True)
        region.draw(["one", "two", "three"])
        region.clear()
        assert buffer.getvalue() == "one\ntwo\nthree\n\033[3A\033[J"
        assert not region.active

    def test_clearing_an_empty_region_is_a_no_op(self) -> None:
        buffer = io.StringIO()
        LiveRegion(buffer.write, enabled=True).clear()
        assert buffer.getvalue() == ""


class TestColor:
    def test_no_color_env_suppresses_ansi(self, monkeypatch) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        buffer = FakeTTY()
        renderer = NarratorRenderer(file=buffer, style="live")
        for event in ACCOUNTS_AT_RISK:
            renderer.feed(event)
        renderer.close()
        # Cursor motion is still allowed; colour is not.
        assert "\033[2m" not in buffer.getvalue()
        assert "\033[38;5;" not in buffer.getvalue()

    def test_force_color_adds_ansi_off_a_tty(self, monkeypatch) -> None:
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert "\033[2m" in render(ACCOUNTS_AT_RISK)


class TestEncoding:
    def test_ascii_terminal_gets_ascii_chrome(self) -> None:
        """The renderer's own glyphs transliterate; the model's prose does not.

        Rewriting what the model said would be a correctness bug, so only the
        chrome — gutter icons, expand hint, separators — falls back.
        """

        class AsciiBuffer(io.StringIO):
            encoding = "ascii"

        output = render(ACCOUNTS_AT_RISK, file=AsciiBuffer())
        chrome = [line for line in output.splitlines() if line.startswith("  ") and ">" in line]
        assert chrome and all(line.isascii() for line in chrome)
        assert ">_" in output  # the code glyph's ASCII stand-in
        assert " | " in output  # the detail separator's stand-in
        for glyph in ("⌕", "❯", "›", " · "):
            assert glyph not in output


class TestFooter:
    def test_tokens_are_thousands_separated(self) -> None:
        assert "18,240 tokens" in render([done(total_tokens=18_240)])

    def test_tokens_are_summed_when_no_total_is_given(self) -> None:
        out = render([done(prompt_tokens=17_000, completion_tokens=1_240)])
        assert "18,240 tokens" in out

    def test_footer_omitted_when_there_is_nothing_to_report(self) -> None:
        assert render([done("hi")]).rstrip().endswith("hi")

    def test_footer_can_be_disabled(self) -> None:
        assert "tokens" not in render([done(total_tokens=99)], show_footer=False)

    def test_model_is_appended(self) -> None:
        out = render([done(total_tokens=10)], model="claude-opus-5")
        assert "claude-opus-5" in out

    def test_cost_is_rendered_from_the_tracker(self) -> None:
        class Tracker:
            def calculate_cost(self, *, model, input_tokens, output_tokens):
                return 0.1234

        out = render(
            [done(prompt_tokens=1000, completion_tokens=100)],
            model="claude-opus-5",
            cost_tracker=Tracker(),
        )
        assert "$0.12" in out

    def test_sub_cent_cost_keeps_four_decimals(self) -> None:
        class Tracker:
            def calculate_cost(self, **_):
                return 0.0007

        out = render([done(total_tokens=5)], model="m", cost_tracker=Tracker())
        assert "$0.0007" in out

    def test_a_broken_cost_tracker_never_breaks_the_transcript(self) -> None:
        class Tracker:
            def calculate_cost(self, **_):
                raise RuntimeError("no pricing for this model")

        out = render([done(total_tokens=10)], model="m", cost_tracker=Tracker())
        assert "10 tokens" in out
        assert "$" not in out


class TestRobustness:
    def test_empty_stream_renders_nothing(self) -> None:
        assert render([]) == ""

    def test_unknown_event_types_are_ignored(self) -> None:
        weird = AgentEvent(type="something_new", message="", payload={})
        assert render([weird, done("hi")]).strip() == "hi"

    def test_missing_payload_fields_do_not_raise(self) -> None:
        bare = AgentEvent(type="tool_called", message="", payload={})
        assert render([bare, done()])

    @pytest.mark.parametrize("style", ["auto", "live", "plain"])
    def test_every_style_renders(self, style) -> None:
        assert render(ACCOUNTS_AT_RISK, style=style)

    def test_error_is_marked_in_the_row(self) -> None:
        out = render(
            [
                called("bash", "1", command="ls /nope"),
                AgentEvent(
                    type="tool_failed",
                    message="",
                    payload={"tool": "bash", "call_id": "1", "error": "no such dir"},
                ),
                done(),
            ]
        )
        assert "Ran ls /nope" in out and "✗" in out
