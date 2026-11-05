# `shipit_agent.sessions`

Conversation state across runs.

| Module | What it does |
|---|---|
| `chat_history.py` | The collapsed chat-history shape, and the conversions to/from the wire |
| `lock.py` | Cross-runtime serialization for one durable conversation |
| `manager.py` | Creating, loading and listing conversation sessions over a session store |

Old import paths at the package root (for example `shipit_agent.runtime`) still work; they are aliases of the modules here.
