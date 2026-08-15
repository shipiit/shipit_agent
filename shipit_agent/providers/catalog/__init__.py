"""Provider catalog — one ``<name>/profile.yaml`` per model provider.

A profile is data; an imperative provider adds a sibling ``provider.py`` with a
``build()``. The registry scans this directory; nothing is imported from here.
"""
