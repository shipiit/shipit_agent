# `shipit_agent.context`

What goes into each model request: compaction, prefix assembly, token counting and tool discovery.

| Module | What it does |
|---|---|
| `compaction.py` | Checkpoint compaction — keep a long run inside the context window |
| `discovery.py` | Making a hundred available tools cost the tokens of a dozen |
| `fit.py` | Provider-safe final fitting of the exact request sent to an LLM |
| `prefix.py` | Assembling the prompt so its prefix is byte-stable across a conversation |
| `prefix_rules.py` | Rendering rules into the stable prefix, scoped to what is actually active |
| `session_facts.py` | Typed, provenance-carrying facts explicitly declared by tool results |
| `token_calibration.py` | Learn the error in our token estimate and correct it, per model |
| `token_counting.py` | Real, per-model token counts — with a safe fall-back to the estimate |
| `tracker.py` | Tracking how full the context window is during a run |

Old import paths at the package root (for example `shipit_agent.runtime`) still work; they are aliases of the modules here.
