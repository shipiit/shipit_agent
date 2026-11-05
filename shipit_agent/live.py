"""Moved to :mod:`shipit_agent.observability.live`.

This path is kept so existing imports keep working; it is the same module
object, so attribute access and patching behave exactly as before.
"""
import sys

from shipit_agent.observability import live as _moved

sys.modules[__name__] = _moved
