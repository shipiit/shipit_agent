from __future__ import annotations

ASK_USER_PROMPT = """

## ask_user_question
Pause execution and ask the human a clarifying question only when ambiguity would materially change the work.

**Use it for:**
- Choosing between valid approaches, formats, scopes, or priorities
- Collecting missing user preferences before proceeding
- Narrowing ambiguous search or execution intent

**Do not use it for:**
- Routine approvals for create/update/delete actions when a separate HITL or review flow exists
- Asking unnecessary follow-up questions when a reasonable assumption is safe
- Breaking one decision into many small questions

**Preferred structure:**
- Ask one compact question set whenever possible
- Keep it to 1-4 questions normally; up to 6 is allowed when a creation or setup workflow truly needs it
- Prefer `single_choice` or `multi_choice` over free text
- Use `text` only for names, URLs, identifiers, or truly custom input
- When one option is best, put it first and suffix the label with `(Recommended)`
- Use option `preview` for concrete comparisons, code/config snippets, or short examples

After answers arrive, continue directly without re-asking the same thing.
""".strip()
