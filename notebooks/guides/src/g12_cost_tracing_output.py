"""Guide 12: cost, tracing, transcripts and serving."""

from cells import code, md

TITLE = "Cost, tracing, serving and output"

CELLS = [
    md("""
    # Guide 12 · Cost, tracing, serving and output

    Running agents for real means knowing what each run cost, keeping a record of what happened, showing it to
    people, and sending it over the web. This guide covers all four.

    **What you'll learn**

    1. Track cost per call and per model, with a budget that warns and stops
    2. Record every run to a trace file, load it back, and compare two runs
    3. Turn a run into a transcript: text, a tree, or a standalone HTML page
    4. Send a run over the web: packets and Server-Sent Events

    Every output below is real, from Haiku 5.5 (Anthropic) and Gemma 4 31B (Bedrock).
    """),
    md("""
    ## 1 · Models and a small tool
    """),
    code("""
    import json
    import os
    import shutil
    from pathlib import Path

    from shipit_agent import Agent
    from shipit_agent.llms import build_llm_from_env
    from shipit_agent.llms.factory import build_llm_from_settings
    from shipit_agent.tools import FunctionTool

    os.environ["SHIPIT_ANTHROPIC_MODEL"] = "claude-haiku-5-5"
    haiku = build_llm_from_env("anthropic")
    gemma = build_llm_from_settings({"model": "google.gemma-4-31b"}, provider="bedrock")

    STOCK = {"widget": 42, "gadget": 0, "gizmo": 7}

    def stock(item: str) -> str:
        \"\"\"Units in stock for an item (widget, gadget or gizmo).\"\"\"
        return str(STOCK.get(item.lower(), "unknown item"))

    stock_tool = FunctionTool.from_callable(stock, read_only=True)
    WORK = Path("ops_demo")
    shutil.rmtree(WORK, ignore_errors=True)
    """),
    md("""
    ## 2 · Cost per run

    A `CostTracker` attached as hooks records every model call and prices it from shipit's pricing table,
    including prompt-cache reads and writes.
    """),
    code("""
    from shipit_agent.costs import Budget, CostTracker

    tracker = CostTracker()
    Agent(llm=haiku, tools=[stock_tool], hooks=tracker.as_hooks()).run("Which items are out of stock? Check each.")
    Agent(llm=gemma, tools=[stock_tool], hooks=tracker.as_hooks()).run("How many gizmos are left?")

    summary = tracker.summary()
    print(f"total: ${summary['total_cost_usd']:.5f} over {summary['total_calls']} model calls")
    print("tokens:", summary["total_tokens"])
    """),
    md("""
    ## 3 · Per-call breakdown
    """),
    code("""
    for row in tracker.breakdown():
        print(f"{row['model']:22} in {row['input_tokens']:6} out {row['output_tokens']:5} "
              f"cache-read {row['cache_read_tokens']:6}  ${row['cost_usd']:.5f}")
    """),
    md("""
    ## 4 · A budget that warns, then stops

    `Budget(max_dollars, warn_at)` calls your alert at the warning threshold and raises once the limit is passed.
    A tiny limit shows both.
    """),
    code("""
    alerts = []
    tight = CostTracker(budget=Budget(max_dollars=0.0003, warn_at=0.5),
                        on_cost_alert=lambda spent, limit: alerts.append(f"${spent:.5f} of ${limit:.5f}"))
    agent = Agent(llm=haiku, tools=[stock_tool], hooks=tight.as_hooks())
    try:
        for item in ("widget", "gadget", "gizmo"):
            agent.run(f"How many {item}s are in stock?")
            print(f"after {item}: ${tight.total_cost:.5f}")
    except Exception as error:
        print("stopped:", type(error).__name__, "-", str(error)[:100])
    print("alerts:", alerts)
    """),
    md("""
    `max_budget_usd=` on the agent is the simpler form: the run stops between steps once its own estimated cost
    reaches the limit.

    ## 5 · Record a run to a trace

    A `trace_store` saves every event of a run under its `trace_id`.
    """),
    code("""
    from shipit_agent import FileTraceStore

    traces = FileTraceStore(root_dir=WORK / "traces")
    Agent(llm=haiku, tools=[stock_tool], trace_store=traces, trace_id="stock-haiku").run("Is any widget left?")
    Agent(llm=gemma, tools=[stock_tool], trace_store=traces, trace_id="stock-gemma").run("Is any widget left?")
    print(sorted(p.name for p in (WORK / "traces").iterdir()))
    """),
    md("""
    ## 6 · Load a trace back

    A `TraceRecord` holds the trace id, metadata and every event, in order.
    """),
    code("""
    from collections import Counter

    record = traces.load("stock-haiku")
    print(record.trace_id, "|", len(record.events), "events")
    print(dict(Counter(e.type for e in record.events)))
    final = next(e for e in reversed(record.events) if e.type == "run_completed")
    print("answer:", final.payload["output"])
    """),
    md("""
    ## 7 · Compare two runs

    `diff_traces` lines up two runs, here the same question on two models.
    """),
    code("""
    from shipit_agent import TraceReplayer, diff_traces

    diff = diff_traces(TraceReplayer.from_store(traces, "stock-haiku"), TraceReplayer.from_store(traces, "stock-gemma"))
    print("same events before they diverge:", diff.matched, "| diverged at event", diff.diverged_at)
    print("only in the Haiku run:", Counter(e.type for _, e in diff.only_in_left))
    print("only in the Gemma run:", Counter(e.type for _, e in diff.only_in_right))
    """),
    md("""
    ## 8 · A transcript as text

    `render_transcript` turns events (a list, a trace, or a result) into the compact transcript a terminal shows.
    """),
    code("""
    from shipit_agent import render_transcript

    result = Agent(llm=haiku, tools=[stock_tool]).run("Check widget and gizmo stock, then say which to reorder first.")
    print(render_transcript(result.events, model="claude-haiku-5-5", width=100))
    """),
    md("""
    ## 9 · A transcript as a tree
    """),
    code("""
    from shipit_agent import render_tree

    print(render_tree(result.events, model="claude-haiku-5-5"))
    """),
    md("""
    ## 10 · A shareable HTML page

    `render_transcript_html` writes a self-contained page of the run: the prompt, each step, the tool calls and
    the answer. It renders here as live HTML.
    """),
    code("""
    from IPython.display import HTML

    from shipit_agent import render_transcript_html

    page = render_transcript_html(result.events, title="Stock check", model="claude-haiku-5-5",
                                  prompt="Check widget and gizmo stock, then say which to reorder first.")
    (WORK / "stock-check.html").write_text(page)
    print(len(page), "characters")
    HTML(page)
    """),
    md("""
    ## 11 · Packets for a web client

    `event_packet` and `result_packet` turn events and results into plain JSON dicts with a stable shape, for a
    browser or another service.
    """),
    code("""
    from shipit_agent import event_packet, result_packet

    called = next(e for e in result.events if e.type == "tool_called")
    print(json.dumps(event_packet(called), default=str)[:400])
    print(sorted(result_packet(result)))
    """),
    md("""
    ## 12 · Server-Sent Events

    `agent.stream_sse(prompt)` yields ready-to-send SSE frames. A web framework returns them as a streaming
    response with `content-type: text/event-stream`.
    """),
    code("""
    frames = list(Agent(llm=haiku, tools=[stock_tool]).stream_sse("How many gizmos?"))
    print(len(frames), "frames")
    for frame in frames[:3] + frames[-1:]:
        print(repr(frame[:150]))
    """),
    md("""
    In FastAPI, for example:

    ```python
    from fastapi.responses import StreamingResponse

    @app.post("/ask")
    def ask(body: Question):
        agent = Agent(llm=llm, tools=[stock_tool])     # one agent per request: one conversation per caller
        return StreamingResponse(agent.stream_sse(body.text), media_type="text/event-stream")
    ```

    `shipit serve` runs a ready-made server; see the deployment guide.

    ## 13 · Clean up
    """),
    code("""
    shutil.rmtree(WORK, ignore_errors=True)
    """),
    md("""
    ## 14 · Summary

    - `CostTracker` prices every call (with cache tokens), breaks it down, and enforces a `Budget`.
    - `trace_store` + `trace_id` record runs; `TraceReplayer` and `diff_traces` load and compare them.
    - `render_transcript`, `render_tree` and `render_transcript_html` show a run to people.
    - `event_packet`, `result_packet` and `stream_sse` send it over the web.

    **Next:** Guide 13 — chat history.
    """),
]
