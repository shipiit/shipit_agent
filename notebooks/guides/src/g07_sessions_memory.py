"""Guide 07: sessions that survive a restart, and memory the agent or your code keeps."""

from cells import code, md

TITLE = "Sessions and memory"

CELLS = [
    md("""
    # Guide 07 · Sessions and memory

    A **session** is one conversation that continues: each run sees what came before, even from a new
    process. **Memory** is what lasts beyond a conversation: facts about a user or a project. shipit has both,
    and a way for the model to keep memory itself.

    **What you'll learn**

    1. Save a session to disk and continue it from a fresh agent
    2. List, fork, resume and archive sessions
    3. Cap how many tokens a session may use
    4. Let the model remember facts with the `memory` tool
    5. Keep memory in your own code with `AgentMemory`: history, searchable facts and entities
    6. Combine the two on Haiku 5.5 (Anthropic) and Gemma 4 31B (Bedrock)

    Every output below is real.
    """),
    md("""
    ## 1 · Models
    """),
    code("""
    import os
    import shutil
    from pathlib import Path

    from shipit_agent import Agent
    from shipit_agent.llms import build_llm_from_env
    from shipit_agent.llms.factory import build_llm_from_settings

    os.environ["SHIPIT_ANTHROPIC_MODEL"] = "claude-haiku-5-5"
    haiku = build_llm_from_env("anthropic")
    gemma = build_llm_from_settings({"model": "google.gemma-4-31b"}, provider="bedrock")
    WORK = Path("memory_demo")
    shutil.rmtree(WORK, ignore_errors=True)
    """),
    md("""
    ## 2 · A session on disk

    Give an agent a `session_store` and a `session_id`. The history is saved after every turn.
    """),
    code("""
    from shipit_agent import FileSessionStore

    store = FileSessionStore(WORK / "sessions")
    agent = Agent(llm=haiku, prompt="You are a concise support agent.", session_store=store, session_id="ticket-812")
    print(agent.run("Customer Ada says the nightly CSV export times out after 30 seconds. Note it.").output)
    print("files:", sorted(p.name for p in (WORK / "sessions").iterdir()))
    """),
    md("""
    ## 3 · Continue it from a new agent

    A brand-new `Agent` object (as after a restart) with the same store and id picks up the conversation.
    """),
    code("""
    later = Agent(llm=haiku, prompt="You are a concise support agent.", session_store=store, session_id="ticket-812")
    print(later.run("Who reported it, and what was the symptom?").output)
    """),
    md("""
    ## 4 · What's stored

    A session record holds the messages and metadata.
    """),
    code("""
    record = store.load("ticket-812")
    print("ticket-812 |", len(record.messages), "messages")
    for m in record.messages:
        print(f"  {m.role:9} {m.content[:70]!r}")
    """),
    md("""
    ## 5 · Managing sessions

    `SessionManager` lists, forks, resumes and archives sessions in a store. A fork starts with the original's
    history and goes its own way; the original is untouched. `fork` and `resume` return a chat session (`send()`).
    """),
    code("""
    from shipit_agent import SessionManager

    manager = SessionManager(store)
    Agent(llm=haiku, session_store=store, session_id="ticket-813").run("Customer Lin can't reset a password. Note it.")
    print("sessions in the store:", len(manager.list_sessions()))

    trial = manager.fork(later, "ticket-812")
    is_new = trial.session_id != "ticket-812"
    print("the fork is a new session:", is_new)
    print(trial.send("Try a different angle: suggest one likely cause in one line.").output)
    print("original still has", len(store.load("ticket-812").messages), "messages")
    """),
    code("""
    manager.archive("ticket-813")   # marks it archived; the history is kept
    for name in ("ticket-812", "ticket-813"):
        print(f"{name}: archived={store.load(name).metadata.get('archived', False)}")
    """),
    md("""
    ## 6 · A token cap per session

    `max_session_tokens` stops a session once its runs together reach a limit: a guard for long-lived chats.
    A run past the limit doesn't raise; it returns a short message saying it stopped.
    """),
    code("""
    capped = Agent(llm=haiku, max_session_tokens=1500)
    for i in range(1, 5):
        result = capped.run(f"Message {i}: reply with the single word 'ok'.")
        print(f"run {i}: {result.output[:70]!r:74} session tokens {capped.session_token_usage}")
    """),
    md("""
    ## 7 · The model keeps memory: the `memory` tool

    Give the agent the `memory` tool and a `memory_store`, and it decides itself what to save and when to look.
    (`Agent.with_builtins()` includes the tool already.) Memory outlives sessions: a new conversation still
    finds it.
    """),
    code("""
    from shipit_agent import FileMemoryStore
    from shipit_agent.tools import MemoryTool

    memory_store = FileMemoryStore(WORK / "memory.json")
    agent = Agent(llm=haiku, memory_store=memory_store, tools=[MemoryTool()],
                  prompt="Save durable facts about the user to memory.")
    print("tools:", [t.name for t in agent.tools])
    agent.run("For future reference: I'm Ada, I deploy from the eu-west-1 region, and I prefer answers as bullet lists.")

    fresh = Agent(llm=haiku, memory_store=memory_store, tools=[MemoryTool()],
                  prompt="Check memory before answering questions about the user. Search it one keyword at a time.")
    result = fresh.run("Which region do I deploy from, and how do I like answers?")
    print(result.output)
    print("calls:", [r.name for r in result.tool_results])
    """),
    md("""
    `FileMemoryStore` matches the search text as a phrase, so one-word searches ("region") find facts that
    longer ones ("deploy region") miss; hence the hint in the prompt. What it saved:
    """),
    code("""
    print((WORK / "memory.json").read_text()[:500])
    print("search 'region':       ", [m.content for m in memory_store.search("region")])
    print("search 'deploy region':", [m.content for m in memory_store.search("deploy region")])
    """),
    md("""
    ## 8 · Your code keeps memory: `AgentMemory`

    When your application decides what to remember, `AgentMemory` bundles three stores: the conversation,
    searchable facts, and entities. Facts need an embedding function; here, Amazon Titan on Bedrock.
    """),
    code("""
    import json

    import boto3

    from shipit_agent import AgentMemory

    bedrock = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION_NAME", "us-east-1"))

    def embed(text: str) -> list[float]:
        body = json.dumps({"inputText": text, "dimensions": 256})
        return json.loads(bedrock.invoke_model(modelId="amazon.titan-embed-text-v2:0", body=body)["body"].read())["embedding"]

    memory = AgentMemory.default(llm=haiku, embedding_fn=embed)
    for fact in [
        "Ada's team ships on Tuesdays and Thursdays.",
        "The billing service is written in Go and owned by the payments team.",
        "Customer exports are capped at 100,000 rows per file.",
        "The staging database is refreshed from production every Sunday night.",
    ]:
        memory.add_fact(fact)
    for hit in memory.search_knowledge("how big can an export be?", top_k=2):
        print(f"{hit.score:.3f}  {hit.text}")
    """),
    md("""
    ## 9 · Entities

    Entities are structured records about people, projects or systems, found by name or search.
    """),
    code("""
    from shipit_agent import Entity

    memory.add_entity(Entity(name="Ada", entity_type="person", context="Lead engineer on exports; prefers bullet lists."))
    memory.add_entity(Entity(name="exports", entity_type="service", context="Nightly CSV export job; times out on large accounts."))
    print(memory.get_entity("Ada"))
    print([e.name for e in memory.search_entities("export")])
    """),
    md("""
    ## 10 · Hand memory to an agent

    Your code chooses what goes into the prompt: here, the facts that match the question.
    """),
    code("""
    def answer(llm, question: str) -> str:
        facts = "\\n".join(f"- {h.text}" for h in memory.search_knowledge(question, top_k=3))
        person = memory.get_entity("Ada")
        prompt = f"You help Ada's team. Known facts:\\n{facts}\\nAbout the user: {person.context}"
        return Agent(llm=llm, prompt=prompt, history=memory.get_conversation_messages()).run(question).output

    print(answer(haiku, "A customer wants a 250,000-row export in one file. Can we do that?"))
    """),
    md("""
    ## 11 · Conversation memory

    `memory.add_message` records turns; with `llm=` set, older turns are summarised so the history stays short.
    """),
    code("""
    from shipit_agent.models import Message

    memory.add_message(Message(role="user", content="Ada here. We're moving the export job to run at 02:00 UTC."))
    memory.add_message(Message(role="assistant", content="Noted: the export job moves to 02:00 UTC."))
    print(answer(haiku, "From now on, what time does the export job run?"))
    """),
    md("""
    ## 12 · The same memory on Gemma 4
    """),
    code("""
    print(answer(gemma, "Who owns the billing service, and when does staging get refreshed?"))
    """),
    md("""
    ## 13 · Clean up
    """),
    code("""
    shutil.rmtree(WORK, ignore_errors=True)
    """),
    md("""
    ## 14 · Summary

    - `session_store` + `session_id` persist a conversation; a new agent with the same id continues it.
    - `SessionManager` lists, forks, resumes and archives; `max_session_tokens` caps a session.
    - `MemoryTool()` with a `memory_store` lets the model decide what to keep across conversations.
    - `AgentMemory` keeps history, searchable facts and entities under your code's control.

    **Next:** Guide 08 — structured output.
    """),
]
