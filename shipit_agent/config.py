"""Moved to :mod:`shipit_agent.agent_setup.config`.

This path is kept so existing imports keep working; it is the same module
object, so attribute access and patching behave exactly as before.
"""
import sys

from shipit_agent.agent_setup import config as _moved

sys.modules[__name__] = _moved
