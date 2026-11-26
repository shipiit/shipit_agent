"""Guide 16: task lists, watched commands, background work and async chat, new in 4.0."""

from cells import code, md

TITLE = "Tasks, background work and async chat"
SINCE = "4.0"

CELLS = [
    md("""
    # Guide 16 · Tasks, background work and async chat

    Long jobs need three things a single prompt and answer don't: a plan the model can keep, a way to watch
    something that takes time, and work that carries on in the background. 4.0 adds all three, plus async
    forms of the chat session for web handlers.

    **What you'll learn**

    1. A task list the model keeps, one task at a time
    2. `monitor`: watching a command's output as it is printed
    3. A command in the background, and the message that says it finished
    4. A chat session from async code: `asend` and `astream`

    Every output below is real, from Haiku 5.5 (Anthropic).
    """),
    md("""
    ## 1 · A model and a demo project

    Two scripts stand in for slow work: one prints progress as it goes, one takes a few seconds and passes.
    """),
    code("""
    import os
    import shutil
    from pathlib import Path

    from shipit_agent.llms import build_llm_from_env
    from shipit_agent.sdk import AgentOptions, AssistantMessage, ResultMessage, SystemMessage, ToolUseBlock, query

    os.environ["SHIPIT_ANTHROPIC_MODEL"] = "claude-haiku-5-5"
    haiku = build_llm_from_env("anthropic")

    project = Path("tasks_demo").resolve()
    shutil.rmtree(project, ignore_errors=True)
    project.mkdir()
    (project / "deploy_check.py").write_text(
        "import time\\n"
        "for step in ('building', 'migrating', 'ready on port 5173'):\\n"
        "    print(step, flush=True)\\n"
        "    time.sleep(0.4)\\n"
    )
    (project / "slow_tests.py").write_text("import time\\ntime.sleep(3)\\nprint('42 passed in 3.0s')\\n")
    (project / "notes.txt").write_text("Release 4.0 ships on Friday. Owner: Ada.\\n")
    print(sorted(p.name for p in project.iterdir()))


    async def show(prompt, **options):
        \"\"\"Run one prompt and print each tool call and the final answer.\"\"\"
        async for message in query(prompt=prompt, options=AgentOptions(llm=haiku, cwd=str(project), max_turns=12, **options)):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        print(f"{block.name:12} {str(block.input)[:96]}")
            elif isinstance(message, ResultMessage):
                print("answer:", (message.result or "").strip()[:300])
    """),
    md("""
    ## 2 · A task list the model keeps

    `TaskCreate`, `TaskUpdate`, `TaskGet` and `TaskList` give the model a plan it changes one task at a time,
    where one task can block another. They are not in the default tool set, so name them in `tools`.
    """),
    code("""
    tasks = ["TaskCreate", "TaskUpdate", "TaskGet", "TaskList"]

    await show(
        "Plan this release as three tasks: run the tests, write the changelog, publish. "
        "Publishing is blocked by the other two. Mark the first one in progress, then list the tasks.",
        tools=tasks,
        allowed_tools=tasks,
    )
    """),
    md("""
    ## 3 · `monitor`: watching a command

    `monitor` runs a command in the background and sends each line it prints to a log the model can read as
    it happens. It goes through the same checks as `bash`, so a `Bash(...)` rule covers it too.
    """),
    code("""
    await show(
        "Use the monitor tool to run `python3 deploy_check.py`, wait for it to finish, "
        "and tell me the last line it printed.",
        tools=["Bash", "Monitor", "Read"],
        allowed_tools=["Monitor(python3 *)", "Read"],
    )
    """),
    md("""
    ## 4 · A command in the background

    A command started with `background=True` returns at once. The run carries on, and the stream reports the
    job as system messages: `task_started` when it begins, `task_notification` when it ends. The model is
    told too, so it can use the result without polling.
    """),
    code("""
    from shipit_agent.sdk import AgentClient

    options = AgentOptions(llm=haiku, cwd=str(project), tools=["Bash", "Read"], allowed_tools=["Bash(python3 *)", "Read"], max_turns=12)

    async with AgentClient(options) as client:
        await client.query(
            "Start `python3 slow_tests.py` with the bash tool in the background (background=true). "
            "While it runs, read notes.txt. When the tests finish, tell me who owns the release and whether the tests passed."
        )
        async for message in client.receive_response():
            if isinstance(message, SystemMessage) and message.subtype in ("task_started", "task_notification"):
                print(f"{message.subtype:18} {message.data.get('task_id')} {message.data.get('status', '')}")
            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ToolUseBlock):
                        print(f"{block.name:18} {str(block.input)[:80]}")
            elif isinstance(message, ResultMessage):
                print("answer:", (message.result or "").strip()[:300])
    """),
    md("""
    ## 5 · A chat session from async code

    The `Agent` class's chat session keeps history across turns. 4.0 adds its async forms, for a FastAPI
    handler or a WebSocket: `asend` for a reply, `astream` for events as they happen. They run on the event
    loop instead of a thread.
    """),
    code("""
    from shipit_agent import Agent

    agent = Agent(llm=haiku, prompt="Answer in one short sentence.")
    chat = agent.chat_session(session_id="release-4-0")

    reply = await chat.asend("The release is called Harbor and it ships on Friday.")
    print("1:", reply.output)

    reply = await chat.asend("What is the release called, and when does it ship?")
    print("2:", reply.output)

    events = [str(event.type) async for event in chat.astream("Reply with the release name only.")]
    print("3:", " · ".join(dict.fromkeys(events)))
    """),
    md("""
    ## What to read next

    - [Agent SDK API](https://agent.shipiit.com/docs/guides/agent-sdk): the task tools, `monitor` and background tasks in full.
    - [Sessions](https://agent.shipiit.com/docs/agent/sessions): saving, resuming and forking a conversation.
    - Guide 14, *The async SDK API*.
    """),
    code("""
    shutil.rmtree(project, ignore_errors=True)
    """),
]
