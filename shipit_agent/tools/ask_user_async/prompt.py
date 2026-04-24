ASK_USER_ASYNC_PROMPT = """Use `ask_user_async` when you need a clarification
from the user DURING an Autopilot run — but the run is long (minutes or
hours) and you can't wait for a synchronous reply.

What happens when you call it:

  1. The question you pass is written to a side channel (file).
  2. Autopilot checkpoints the run and halts cleanly with
     status="awaiting_user".
  3. The user sees the question via their UI / shell — they reply
     with `shipit answer <run_id> "..."` at their own pace.
  4. Autopilot resume() — either manual or via the scheduler daemon —
     picks up the answer and passes it to you as tool output.

Use when:
  - You discovered an ambiguity the code can't resolve on its own.
  - A decision needs human judgment (product call, priority, style).
  - You'd otherwise loop forever without a choice being made.

Do NOT use when:
  - You can look it up in the codebase (read_file / grep_search first).
  - The ask is "should I proceed?" — pick a default, note it, proceed.
  - You only need an approval for a destructive action — the harness
    already asks for that separately.

Format your question concretely. "Which SSO provider should I wire up?
Options: Okta, Auth0, Google Workspace, Microsoft Entra." beats a vague
"what auth should we use?".
"""
