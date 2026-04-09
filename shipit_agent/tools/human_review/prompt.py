from __future__ import annotations

HUMAN_REVIEW_PROMPT = """

## request_human_review
Pause execution and ask the human to explicitly review an important action before proceeding.

**Use it for:**
- Create, update, delete, publish, or other consequential actions
- Cases where the user should review a proposed payload, summary, or diff before execution
- Situations where "approve / edit / reject" is the right interaction, not a normal clarification

**Rules:**
- Include a short `title`, clear `summary`, and concrete `proposed_action`
- Include `preview` when the user should review content, code, config, or a structured payload
- Use `editable_fields` when the human may want to request specific changes before approval
- Prefer this over `ask_user_question` for approval-style gates
- If the user approves (yes, y, approve, approved, confirm, proceed), treat that as final authorization and execute the pending reviewed tool directly; do not re-preview or request human review again for the same action unless the user explicitly asks to change something
""".strip()
