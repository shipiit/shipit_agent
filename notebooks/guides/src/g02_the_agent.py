"""Guide 02: the Agent, run(), stream(), results and events."""

from cells import code, md

TITLE = "The Agent: run, stream, results and events"

CELLS = [
    md("""
    # Guide 02 · The Agent: `run()`, `stream()`, results and events

    `Agent` is the whole runtime: a model, a system prompt, tools, and a loop that calls the model, runs the
    tools it asks for, and feeds the results back until it answers. This guide takes one agent apart.

    **What you'll learn**

    1. The parts of an `Agent` and the defaults it starts with
    2. Everything inside an `AgentResult`
    3. Streaming: every event type, its message and its payload
    4. Async: `arun()` and `astream()`
    5. Multi-turn chats, copies of an agent, and an agent used as a tool
    6. Readable transcript rows with `narrate()`, and health checks with `doctor()`
    7. The same agent on Gemma 4 on AWS Bedrock

    Every output below is real: the notebook was run end to end on Haiku 5.5 (Anthropic) and Gemma 4 31B.
    """),
    md("""
    ## 1 · The model

    Guide 01 covers providers. Here, Haiku 5.5 (Anthropic) from the environment, and Gemma 4 on Bedrock for the
    comparison at the end.
    """),
    code("""
    import os

    from shipit_agent import Agent
    from shipit_agent.llms import build_llm_from_env
    from shipit_agent.llms.factory import build_llm_from_settings

    os.environ["SHIPIT_ANTHROPIC_MODEL"] = "claude-haiku-5-5"
    llm = build_llm_from_env("anthropic")
    gemma = build_llm_from_settings({"model": "google.gemma-4-31b"}, provider="bedrock")
    print(llm.model, "|", gemma.model)
    """),
    md("""
    ## 2 · The smallest agent

    An agent needs only `llm`. `prompt` is its system prompt and `name` labels it in traces and logs.
    """),
    code("""
    agent = Agent(llm=llm, prompt="You are a terse release engineer.", name="releaser")
    print(agent.name, "| tools:", len(agent.tools), "| max_iterations:", agent.max_iterations, "(None = no limit)")
    """),
    md("""
    ## 3 · `run()` returns an `AgentResult`
    """),
    code("""
    result = agent.run("What is a semantic version? One sentence.")
    print(result.output)
    """),
    md("""
    ## 4 · What's in the result

    | field | what it holds |
    |---|---|
    | `output` | the final answer text |
    | `messages` | the conversation the model saw, including tool calls and results |
    | `events` | every event the run emitted, the same ones `stream()` yields |
    | `tool_results` | each tool call's output |
    | `artifacts` | files and objects tools produced |
    | `metadata` | usage, timing and run details |
    | `parsed` | the typed answer when you pass `output_schema` (Guide 08) |
    | `rag_sources` | the passages a RAG answer used (Guide 06) |
    """),
    code("""
    print("messages:", [m.role for m in result.messages])
    print("events:  ", len(result.events))
    print("metadata keys:", sorted(result.metadata))
    print("usage:", result.metadata["usage"])
    """),
    md("""
    ## 5 · Give it a tool

    Any typed Python function becomes a tool: its name, docstring and type hints are what the model sees.
    Guide 03 goes deep on tools.
    """),
    code("""
    from shipit_agent.tools import FunctionTool

    RELEASES = {"shipit-agent": "3.0.0", "vouchline": "1.4.2"}

    def latest_release(package: str) -> str:
        \"\"\"Return the latest released version of a package we publish.\"\"\"
        return RELEASES.get(package, f"no release found for {package}")

    tool = FunctionTool.from_callable(latest_release, read_only=True)

    def release_agent(**changes) -> Agent:
        \"\"\"A fresh agent with the release tool: a new conversation each time.\"\"\"
        settings = {"llm": llm, "prompt": "Answer with the tools; be brief.", "tools": [tool]}
        return Agent(**{**settings, **changes})

    agent = release_agent()

    result = agent.run("What's the latest shipit-agent release, and what would the next minor be?")
    print(result.output)
    """),
    md("""
    ## 6 · Tool calls in the result

    `tool_results` holds each call's output; the tool call itself is in `messages`.
    """),
    code("""
    for r in result.tool_results:
        print(r.name, "->", r.output)
    for m in result.messages:
        if m.role == "tool":
            print("tool message:", m.content[:80])
    """),
    md("""
    ## 7 · One agent is one conversation

    An `Agent` keeps its conversation in a session between calls, so a second `run()` sees the first. That's
    what you want for a chat, and not what you want for unrelated jobs: give those a fresh agent (or a new
    `session_id`). The rest of this guide uses `release_agent()` for each independent example.
    """),
    code("""
    memo = Agent(llm=llm)
    memo.run("Remember the code word: kiwi.")
    print("same agent:  ", memo.run("What was the code word? One word.").output)
    print("fresh agent: ", Agent(llm=llm).run("What was the code word? One word.").output[:90])
    """),
    md("""
    ## 8 · Stream the run

    `stream()` runs the same loop and yields each event as it happens. Every event has a `type`, a human
    `message`, a `payload` dict and a `timestamp`.
    """),
    code("""
    from collections import Counter

    events = list(release_agent().stream("What's the latest vouchline release?"))
    for e in events:
        if e.type != "text_delta":
            print(f"{e.type:22} {e.message[:60]}")
    print("\\ncounts:", dict(Counter(e.type for e in events)))
    """),
    md("""
    ## 9 · Event payloads

    The payload carries the details a UI needs. A tool call and its completion, in full:
    """),
    code("""
    import json

    for e in events:
        if e.type in ("tool_called", "tool_completed"):
            print(e.type, json.dumps(e.payload, default=str)[:300])
    """),
    md("""
    ## 10 · The final event

    `run_completed` closes every run. Its payload has the answer and the usage, so a streaming UI never needs a
    second call.
    """),
    code("""
    final = events[-1]
    print(final.type)
    print({k: final.payload[k] for k in final.payload if k in ("output", "usage")})
    """),
    md("""
    ## 11 · Text as it is written

    `text_delta` events carry the answer chunk by chunk. Print them with `end=""` to watch it appear.
    """),
    code("""
    for e in Agent(llm=llm).stream("Count from one to five in words, comma separated."):
        if e.type == "text_delta":
            print(e.payload.get("chunk", ""), end="", flush=True)
    print()
    """),
    md("""
    ## 12 · Async: `arun()` and `astream()`

    Inside an event loop, use the async versions. Notebooks run top-level `await` directly. Two runs at once:
    """),
    code("""
    import asyncio
    import time

    started = time.perf_counter()
    a, b = await asyncio.gather(
        release_agent().arun("Latest shipit-agent release?"),
        release_agent().arun("Latest vouchline release?"),
    )
    print(a.output.strip(), "|", b.output.strip())
    print(f"both in {time.perf_counter() - started:.1f}s")
    """),
    code("""
    kinds = []
    async for e in release_agent().astream("Latest vouchline release?"):
        kinds.append(e.type)
    print(kinds[0], "…", kinds[-1], f"({len(kinds)} events)")
    """),
    md("""
    ## 13 · A multi-turn chat

    `chat_session()` keeps the conversation between `send()` calls. Guide 07 adds stores so it survives a restart.
    """),
    code("""
    chat = release_agent().chat_session(session_id="release-chat")
    print(chat.send("Our package is shipit-agent. What's its latest release?").output)
    print(chat.send("And what would the next patch release be called?").output)
    print("turns in history:", len(chat.history()))
    """),
    md("""
    ## 14 · Seed a conversation with `history`

    Pass earlier messages to start an agent mid-conversation. (The built-in system prompt tells the model to
    trust only what tools show it, so a plain prompt suits a seeded chat better.)
    """),
    code("""
    from shipit_agent.models import Message

    seeded = Agent(llm=llm, prompt="You are a helpful assistant.", history=[
        Message(role="user", content="Hi, I'm Ada. I'm planning the 3.1 release for next Tuesday."),
        Message(role="assistant", content="Hi Ada, got it: 3.1, next Tuesday."),
    ])
    print(seeded.run("Remind me: which release am I planning, and when?").output)
    """),
    md("""
    ## 15 · Copies with `clone()`

    `clone(**changes)` returns a new agent with the same setup and some parameters changed; the original is
    untouched. A clone continues the original's conversation, so clone a fresh agent for a clean start.
    """),
    code("""
    base = release_agent()
    formal = base.clone(prompt="Answer with the tools, formally, in one sentence.", name="formal")
    print(base.name, "->", formal.name)
    print(formal.run("Latest vouchline release?").output)
    """),
    md("""
    ## 16 · An agent as a tool

    `as_tool()` wraps an agent so another agent can call it. The inner agent runs its own loop with its own
    tools and returns its answer.
    """),
    code("""
    releases_expert = release_agent().as_tool(name="releases_expert", description="Knows our package release versions.")
    lead = Agent(llm=llm, prompt="Delegate release questions to your expert.", tools=[releases_expert])
    result = lead.run("Ask the expert for the latest shipit-agent and vouchline releases, then list them.")
    print(result.output)
    print("tools the lead called:", [r.name for r in result.tool_results])
    """),
    md("""
    ## 17 · Limits

    `max_iterations` caps the loop's tool-calling steps; `max_turns` is another name for the same
    limit. With a limit of 1, the agent makes one round of lookups and then has to answer with what it has,
    so it can't finish a two-step job: the run ends instead of looping.
    """),
    code("""
    result = release_agent(max_turns=1).run("Look up shipit-agent, then vouchline, one call at a time, then compare them.")
    print(result.output[:300])
    print("finish:", result.metadata.get("finish_reason"), "|", result.metadata["run_summary"])
    """),
    md("""
    ## 18 · Transcript rows with `narrate()`

    `narrate()` streams the same run as readable rows, the ones `shipit chat` prints: verbs, tool work and the
    answer, already grouped.
    """),
    code("""
    for row in release_agent().narrate("Compare the latest shipit-agent and vouchline releases."):
        print(type(row).__name__, "|", str(row)[:110])
    """),
    md("""
    ## 19 · Health check with `doctor()`

    `doctor()` checks the agent's setup (model credentials, tools, MCP servers, settings) without calling the
    model.
    """),
    code("""
    report = release_agent().doctor()
    summary = report.to_dict()
    print("passed:", summary["passed"], "| checks:", summary["check_count"],
          "| failures:", summary["failure_count"], "| warnings:", summary["warning_count"])
    for check in summary["checks"][:6]:
        print(" ", check)
    """),
    md("""
    ## 20 · The same agent on Gemma 4

    Nothing changes but the model. Gemma 4 31B on Bedrock calls the same tool.
    """),
    code("""
    on_gemma = release_agent(llm=gemma)
    result = on_gemma.run("What's the latest shipit-agent release?")
    print(result.output)
    print("tool calls:", [r.name for r in result.tool_results], "| usage:", result.metadata["usage"])
    """),
    md("""
    ## 21 · Summary

    - One agent is one conversation; use a fresh agent or a new `session_id` for unrelated jobs.
    - `run()` returns an `AgentResult`; `stream()` yields the same run as events.
    - Events carry `type`, `message` and `payload`; `run_completed` has the answer and usage.
    - `arun()` / `astream()` for async; `chat_session()` for multi-turn; `clone()` and `as_tool()` to compose.
    - `narrate()` gives readable rows; `doctor()` checks the setup.

    **Next:** Guide 03 — tools: built-in, custom, errors and parallel calls.
    """),
]
