"""Skills the model can reach for mid-run, instead of ones chosen for it.

Selecting skills up front by matching trigger phrases against the first user
message has three costs. A request phrased differently from the authored
triggers activates nothing. A need that only becomes apparent at iteration four
— the file turns out to be a tracked-changes DOCX — can never be served, because
selection already happened. And injecting full skill bodies into the system
prompt makes each skill expensive enough that the count has to be capped low,
and moves the prompt prefix, which costs every subsequent cache hit.

Progressive disclosure fixes all three:

* the **catalog** — one line per skill, id plus a summary — sits in the stable
  prefix and costs roughly ten tokens per skill, so hundreds fit;
* the **body** is loaded only when the model calls ``load_skill``, at whatever
  iteration it decides it needs one, and arrives as a message in the volatile
  tail where it cannot disturb the cached prefix;
* loading a skill **widens the run's allowed tool set** to whatever that skill
  declares, so a skill can carry tools without every run paying for them.

Three trigger classes coexist, because each answers a different question:
``always_apply`` ("this agent is always this kind of agent"), ``manual``
("this phrasing means this skill", the fast path that needs no model turn), and
``model`` ("the model decided"). A skill naming a tool this deployment does not
have is loaded anyway with that tool dropped and a debug line — that is what
lets skills authored against another toolset import without breaking.
"""

from __future__ import annotations

from .entries import (
    LOAD_SKILL_TOOL_NAME,
    SKILL_MESSAGE_SOURCE,
    PrimedSkill,
    SkillCaps,
    SkillLike,
    build_catalog,
    logger,
)
from .load_tool import LoadSkillTool
from .session import SkillSession

__all__ = [
    "LOAD_SKILL_TOOL_NAME",
    "LoadSkillTool",
    "PrimedSkill",
    "SKILL_MESSAGE_SOURCE",
    "SkillCaps",
    "SkillLike",
    "SkillSession",
    "build_catalog",
    "logger",
]
