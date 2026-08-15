"""Connector catalog — one module per category, each registering connectors.

The registry's ``load_catalog()`` imports every module in this package once, so
adding an integration is a matter of dropping a manifest into the right module
(or a new module) — no central list to edit.
"""
