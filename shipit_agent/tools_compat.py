"""Moved to :mod:`shipit_agent.core.tools_compat`.

This path is kept so existing imports keep working; it is the same module
object, so attribute access and patching behave exactly as before.
"""
import sys

from shipit_agent.core import tools_compat as _moved

sys.modules[__name__] = _moved
