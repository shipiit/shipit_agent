# The v2 tool-layer rewrite (core_tools / Workspace, one-tool-per-package) forks
# the working `tools/` layer the runtime depends on; they cannot both live at
# `shipit_agent/tools/`. These two modules exercise the v2 tool layer and so
# only import once that fork is resolved. Ignored here (not deleted) so the
# decision is a checklist item, not a lost file.
collect_ignore = ["test_core_tools.py", "test_tools_and_connections.py"]
