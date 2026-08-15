"""Bundled plugin catalog — one <name>/ directory per plugin.

A plugin is a plugin.yaml manifest + a plugin.py with register(reg). The
registry scans this directory; nothing is imported from here.
"""
