"""Moved to :mod:`shipit_agent.scheduling.schedule`.

This path is kept so existing imports keep working; it is the same module
object, so attribute access and patching behave exactly as before.
"""
import sys

from shipit_agent.scheduling import schedule as _moved

sys.modules[__name__] = _moved
