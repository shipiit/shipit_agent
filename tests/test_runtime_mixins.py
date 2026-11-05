"""The runtime is assembled from mixins; no two of them may define the same name.

When two classes in the MRO define one attribute, the earlier silently wins
and the later is dead code that still looks live. Each name has one home.
"""

from __future__ import annotations

from collections import defaultdict

from shipit_agent.core.async_runtime import AsyncAgentRuntime
from shipit_agent.core.runtime import AgentRuntime

# AgentRuntime exists to replace these two with blocking versions.
_SYNC_OVERRIDES = {"run", "stream"}


def _homes(cls: type) -> dict[str, list[str]]:
    homes: dict[str, list[str]] = defaultdict(list)
    for klass in cls.__mro__:
        if klass is object:
            continue
        for name in vars(klass):
            if not (name.startswith("__") and name.endswith("__")):
                homes[name].append(klass.__name__)
    return homes


def test_every_runtime_attribute_has_one_home() -> None:
    clashes = {
        name: owners
        for name, owners in _homes(AsyncAgentRuntime).items()
        if len(owners) > 1
    }
    assert clashes == {}


def test_the_sync_runtime_overrides_only_run_and_stream() -> None:
    clashes = {
        name
        for name, owners in _homes(AgentRuntime).items()
        if len(owners) > 1 and "AgentRuntime" in owners
    }
    assert clashes == _SYNC_OVERRIDES


def test_mixins_are_assembled_into_both_runtimes() -> None:
    mixins = [k for k in AsyncAgentRuntime.__mro__ if k.__name__.endswith("Mixin")]
    assert len(mixins) >= 20
    assert all(issubclass(AgentRuntime, mixin) for mixin in mixins)
