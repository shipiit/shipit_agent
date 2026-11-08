"""Bash guidance for a rename across many files: one perl call, scratch files in temp.

Gemma renamed a function across 13 files with a read, an edit and a todo
update per file, and ran out of turns; another run's `sed -i` failed on
macOS and its helper script was left in the project.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from shipit_agent.tools.bash.prompt import BASH_PROMPT


def test_guidance_names_one_portable_command_and_temp_scripts() -> None:
    assert "perl -pi -e" in BASH_PROMPT and "grep_files" in BASH_PROMPT
    assert "mktemp -d" in BASH_PROMPT


def test_the_suggested_command_renames_whole_words_in_place(tmp_path: Path) -> None:
    command = re.search(r"`(perl -pi -e '[^`]+') <files>`", BASH_PROMPT).group(1)
    command = command.replace("old", "to_cents_amount").replace("new", "to_cents")
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text("from m import to_cents_amount\nto_cents_amounts = 1\n")
    subprocess.run(f"{command} a.py b.py", shell=True, cwd=tmp_path, check=True)
    for name in ("a.py", "b.py"):
        assert (tmp_path / name).read_text() == "from m import to_cents\nto_cents_amounts = 1\n"
