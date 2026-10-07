"""Environment for subprocesses that run model-written commands.

Tools like ``bash`` and ``run_code`` execute whatever the model asks for, so
whatever is in the host process environment (API keys loaded by dotenv, DB
passwords, ``SECRET_KEY``) is one ``printenv`` away from the model. Those tools
build their child environment here: a short list of non-secret basics, plus
only what the caller explicitly opts in to.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

#: Non-secret variables a shell or interpreter needs to behave normally.
#: Deliberately excludes ``SSH_AUTH_SOCK`` (an agent socket is a credential)
#: and anything provider/cloud specific.
SAFE_ENV_NAMES: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LANGUAGE",
        "TERM",
        "TZ",
        "TMPDIR",
        "TMP",
        "TEMP",
        "PYTHONIOENCODING",
        # Windows: Python and most CLIs fail to start without these.
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
    }
)
SAFE_ENV_PREFIXES: tuple[str, ...] = ("LC_",)


def build_tool_env(
    *,
    allowlist: Iterable[str] = (),
    extra_env: Mapping[str, str] | None = None,
    inherit: bool = False,
    parent: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return the environment for a model-controlled subprocess.

    Precedence, lowest to highest: the safe basics (or the whole parent
    environment when ``inherit`` is true), then parent variables named in
    ``allowlist``, then ``extra_env`` verbatim.
    """
    source = os.environ if parent is None else parent
    if inherit:
        env = dict(source)
    else:
        env = {
            name: value
            for name, value in source.items()
            if name in SAFE_ENV_NAMES or name.startswith(SAFE_ENV_PREFIXES)
        }
    env.setdefault("PATH", os.defpath)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    for name in allowlist:
        if name in source:
            env[name] = source[name]
    if extra_env:
        env.update(extra_env)
    return env
