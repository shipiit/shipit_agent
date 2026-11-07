"""Moved to :mod:`shipit_agent.agents.delegation`.

This path is kept so existing imports keep working; it is the same module
object, so attribute access and patching behave exactly as before.
"""
import sys

from shipit_agent.agents import delegation as _moved

sys.modules[__name__] = _moved
