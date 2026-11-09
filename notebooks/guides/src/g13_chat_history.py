"""Guide 13: chat history, passed in, read back, stored and trimmed."""

from cells import code, md

TITLE = "Chat history"

CELLS = [
    md("""
    # Guide 13 · Chat history

    A chat app keeps the conversation somewhere (your database, a session store) and hands it to the agent on
    each request. This guide covers every way history gets into and out of a shipit agent.

    **What you'll learn**

    1. How an agent keeps its own conversation between runs
    2. Pass history in with `history=`, built from your own records
    3. Read it back from a result and save it as JSON
    4. Chat sessions and session stores that survive a restart
    5. One conversation per user
    6. Long chats: keep the last turns, or summarise the older ones
    7. Tool calls in history, and switching models mid-conversation

    Every output below is real, from Haiku 5.5 (Anthropic) and Gemma 4 31B (Bedrock).
    """),
    md("""
    ## 1 · Models
    """),
    code("""
    import json
    import os
    import shutil
    from pathlib import Path

    from shipit_agent import Agent
    from shipit_agent.llms import build_llm_from_env
    from shipit_agent.llms.factory import build_llm_from_settings
    from shipit_agent.models import Message

    os.environ["SHIPIT_ANTHROPIC_MODEL"] = "claude-haiku-5-5"
    haiku = build_llm_from_env("anthropic")
    gemma = build_llm_from_settings({"model": "google.gemma-4-31b"}, provider="bedrock")
    PROMPT = "You are a friendly travel assistant. Be brief."
    WORK = Path("chat_demo")
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir()
    """),
    md("""
    ## 2 · One agent object is one conversation

    Runs on the same `Agent` share a conversation: the second run sees the first.
    """),
    code("""
    agent = Agent(llm=haiku, prompt=PROMPT)
    agent.run("I'm planning 4 days in Lisbon in May, on a mid-range budget.")
    print(agent.run("Which neighbourhood should I stay in?").output)
    """),
    md("""
    ## 3 · Pass history in

    In a web app each request usually builds a new agent, so you pass the earlier turns with `history=`. A turn
    is a `Message` with a role (`user` or `assistant`) and content.
    """),
    code("""
    history = [
        Message(role="user", content="I'm planning 4 days in Lisbon in May, on a mid-range budget."),
        Message(role="assistant", content="Great choice. May is warm and not too crowded. How can I help?"),
        Message(role="user", content="I don't like steep hills, I'm travelling with my parents."),
        Message(role="assistant", content="Noted: flat areas and easy transport matter most."),
    ]
    agent = Agent(llm=haiku, prompt=PROMPT, history=history)
    print(agent.run("So which neighbourhood should we stay in?").output)
    """),
    md("""
    ## 4 · From your own records

    Most apps store messages as rows. Turning them into `Message`s is one line.
    """),
    code("""
    rows = [  # e.g. SELECT role, body FROM chat_messages WHERE chat_id = ? ORDER BY created_at
        {"role": "user", "body": "Do I need a visa for Portugal? I have a Canadian passport."},
        {"role": "assistant", "body": "No visa for stays up to 90 days in the Schengen area."},
    ]
    history = [Message(role=r["role"], content=r["body"]) for r in rows]
    print(Agent(llm=haiku, prompt=PROMPT, history=history).run("And how long can I stay, again?").output)
    """),
    md("""
    ## 5 · Read history back

    `result.messages` is the conversation the model saw, including this turn. Keep the `user` and `assistant`
    text to store it.
    """),
    code("""
    result = Agent(llm=haiku, prompt=PROMPT, history=history).run("What's the best month to visit Porto?")
    turns = [{"role": m.role, "content": m.content} for m in result.messages if m.role in ("user", "assistant") and m.content]
    for t in turns:
        print(f"{t['role']:9} {t['content'][:80]}")
    (WORK / "chat.json").write_text(json.dumps(turns, indent=1))
    """),
    md("""
    ## 6 · Continue from the saved JSON

    The next request loads the file and carries on.
    """),
    code("""
    saved = json.loads((WORK / "chat.json").read_text())
    agent = Agent(llm=haiku, prompt=PROMPT, history=[Message(**t) for t in saved])
    print(agent.run("Remind me: which city did I ask about last, and when should I go?").output)
    """),
    md("""
    ## 7 · Chat sessions

    `chat_session()` keeps the history between `send()` calls and gives it back with `history()`.
    """),
    code("""
    chat = Agent(llm=haiku, prompt=PROMPT).chat_session(session_id="trip-planner")
    chat.send("I land in Lisbon on a Friday evening.")
    print(chat.send("What should I do on Saturday morning?").output)
    print("\\nhistory:", [(m.role, len(m.content or "")) for m in chat.history()])
    """),
    md("""
    ## 8 · History that survives a restart

    With a `session_store`, each turn is saved; a new agent with the same `session_id` continues the chat.
    """),
    code("""
    from shipit_agent import FileSessionStore

    store = FileSessionStore(WORK / "sessions")
    Agent(llm=haiku, prompt=PROMPT, session_store=store, session_id="chat-ada").run(
        "My name is Ada and I'm vegetarian. I'm visiting Lisbon.")

    after_restart = Agent(llm=haiku, prompt=PROMPT, session_store=store, session_id="chat-ada")
    print(after_restart.run("Suggest a dinner place for me tonight.").output)
    print("\\nstored messages:", len(store.load("chat-ada").messages))
    """),
    md("""
    ## 9 · One conversation per user

    Give each user their own `session_id`: histories never mix.
    """),
    code("""
    Agent(llm=haiku, prompt=PROMPT, session_store=store, session_id="chat-lin").run("I'm Lin, going to Porto for the wine.")
    for user in ("chat-ada", "chat-lin"):
        a = Agent(llm=haiku, prompt=PROMPT, session_store=store, session_id=user)
        print(f"{user}: {a.run('In five words: who am I and where am I going?').output}")
    """),
    md("""
    ## 10 · Long chats: keep the last turns

    Every turn is re-sent each request, so long chats grow expensive. The simplest cap is to pass only the last
    few turns.
    """),
    code("""
    long_history = []
    for day in range(1, 11):
        long_history += [Message(role="user", content=f"Day {day}: what should I do?"),
                         Message(role="assistant", content=f"Day {day}: visit spot number {day}.")]

    for keep in (len(long_history), 6):
        result = Agent(llm=haiku, prompt=PROMPT, history=long_history[-keep:]).run("What did you suggest for the last day?")
        print(f"last {keep:2} messages -> input tokens {result.metadata['usage']['prompt_tokens']:4} | {result.output[:70]}")
    """),
    md("""
    ## 11 · Long chats: summarise the older turns

    `ConversationMemory(strategy="summary")` keeps recent turns and folds older ones into a summary written by a
    model, so the agent keeps the gist at a fraction of the size.
    """),
    code("""
    from shipit_agent import ConversationMemory

    memory = ConversationMemory(strategy="summary", window_size=4, summary_llm=haiku)
    memory.add_many([
        Message(role="user", content="I'm Ada, vegetarian, travelling with my parents who dislike hills."),
        Message(role="assistant", content="Got it: vegetarian food, flat areas."),
        *long_history,
    ])
    compact = memory.get_messages()
    print(len(long_history) + 2, "messages ->", len(compact), "messages")
    print(compact[0].content[:400])
    print("\\n" + Agent(llm=haiku, prompt=PROMPT, history=compact).run("Any dietary needs I mentioned?").output)
    """),
    md("""
    ## 12 · Tool calls in history

    When a run used tools, `result.messages` also holds the tool calls and their results. Keep them to give the
    model the facts it found; drop them (keep only text) to store a smaller history.
    """),
    code("""
    from shipit_agent.tools import FunctionTool

    def weather(city: str) -> str:
        \"\"\"Forecast for a city.\"\"\"
        return {"Lisbon": "24°C, sunny", "Porto": "19°C, cloudy"}.get(city, "no forecast")

    result = Agent(llm=haiku, prompt=PROMPT, tools=[FunctionTool.from_callable(weather, read_only=True)]).run(
        "What's the weather in Lisbon tomorrow?")
    print([m.role for m in result.messages])
    full = [m for m in result.messages if m.role != "system"]
    text_only = [m for m in full if m.role in ("user", "assistant") and m.content]

    follow_up = "Should I pack a jacket for tomorrow?"
    print("with tool turns:", Agent(llm=haiku, prompt=PROMPT, history=full).run(follow_up).output[:160])
    """),
    md("""
    ## 13 · Switch models mid-conversation

    History is plain messages, so a conversation started on one model can continue on another. Here Haiku 5.5
    started it and Gemma 4 picks it up.
    """),
    code("""
    saved = [Message(**t) for t in json.loads((WORK / "chat.json").read_text())]
    print(Agent(llm=gemma, prompt=PROMPT, history=saved).run("Which city were we talking about, and what month did you suggest?").output)
    """),
    md("""
    ## 14 · Clean up
    """),
    code("""
    shutil.rmtree(WORK, ignore_errors=True)
    """),
    md("""
    ## 15 · Summary

    - An `Agent` object keeps its conversation; a new agent per request takes `history=[Message(...)]`.
    - `result.messages` gives the conversation back; store the user and assistant turns as JSON or rows.
    - `chat_session()` and `session_store` + `session_id` keep history between calls and restarts, per user.
    - Trim long chats to the last turns, or summarise older ones with `ConversationMemory(strategy="summary")`.
    - History is model-independent: switch models mid-conversation.
    """),
]
