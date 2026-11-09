---
title: Sessions
description: Keep a conversation across turns and restarts, list and fork sessions, and resume them from the SDK API.
---

# Sessions

A session is a conversation that continues: each run sees what came before. Give the agent a session store and a session id, and the history is saved after every turn and loaded before the next, even by a new process.

```python
from shipit_agent import Agent, FileSessionStore
from shipit_agent.llms import build_llm_from_env

store = FileSessionStore(".shipit/sessions")
agent = Agent.with_builtins(llm=build_llm_from_env(), session_store=store, session_id="ticket-812")

agent.run("The nightly export fails with a timeout. Find out why.")
agent.run("Now fix it and add a test.")  # sees the first turn
```

A new `Agent` built tomorrow with the same store and `session_id="ticket-812"` carries on from there.

## Stores

| Store | Keeps sessions |
| :- | :- |
| `InMemorySessionStore()` | In memory, for one process. The default when you pass nothing. |
| `FileSessionStore(root_dir)` | As JSON files in a folder, one per session. |

A store has three methods, `load(session_id)`, `save(record)` and `list_all()`. Implement them over your database to keep sessions in Postgres, Redis or anywhere else.

## A chat

`chat_session()` holds a conversation open and adds conveniences for chat interfaces: callbacks for every event and packet streaming for the web.

```python
chat = agent.chat_session(session_id="support-42")
chat.send("The export button does nothing on Safari.")
reply = chat.send("It started after Tuesday's release.")
print(reply.output)

for event in chat.stream("Which commit changed the export code?"):
    print(event.type, event.message)
```

## Managing sessions

`SessionManager` lists, resumes, forks and archives sessions in a store.

```python
from shipit_agent import SessionManager

manager = SessionManager(store)
for record in manager.list_sessions():
    print(record.session_id)

trial = manager.fork(agent, "ticket-812")  # a copy to try another approach
manager.archive("ticket-811")
```

A fork starts with the original's history and goes its own way; the original is untouched. `from_message=` forks from an earlier point.

## With the SDK API

The SDK's session options and functions work on any store:

```python
from shipit_agent.sdk import AgentOptions, fork_session, list_sessions, query

options = AgentOptions(session_store=store, resume="ticket-812")          # continue a session
options = AgentOptions(session_store=store, continue_conversation=True)  # continue the latest
options = AgentOptions(session_store=store, resume="ticket-812", fork_session=True)  # a copy

for info in list_sessions(store, limit=10):
    print(info.session_id, info.summary)

copy_id = fork_session(store, "ticket-812", title="try the retry fix")
```

`get_session_messages`, `get_session_info`, `rename_session` and `tag_session` read and label sessions.

## What a session keeps

The conversation: every message, tool call and result. Long sessions are compacted as they grow, so a session can run for days without outgrowing the model's window. [Context management](../guides/context-management.md).

A session is one conversation. To remember facts across conversations, such as a user's preferences or a project's conventions, use [memory](memory.md).
