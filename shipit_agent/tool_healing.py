"""Moved to :mod:`shipit_agent.safety.tool_healing`.

This path is kept so existing imports keep working; it is the same module
object, so attribute access and patching behave exactly as before.
"""
import sys

from shipit_agent.safety import tool_healing as _moved

sys.modules[__name__] = _moved
