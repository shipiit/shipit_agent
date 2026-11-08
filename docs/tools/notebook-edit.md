---
title: notebook_edit
description: Let an agent read and change Jupyter notebooks cell by cell, instead of rewriting the JSON.
---

# `notebook_edit`

A notebook is JSON, and rewriting it as text is how cells get lost. `notebook_edit` edits `.ipynb` files structurally: list the cells, read one, replace its source, add or delete a cell, or clear every output.

## Actions

| Action | Arguments | What it does |
| --- | --- | --- |
| `list` | `path` | Every cell with its index, type and first line |
| `read` | `path`, `index` | One cell's source |
| `edit` | `path`, `index`, `source` | Replace a cell's source |
| `add` | `path`, `index`, `source`, `cell_type` | Insert a `code` (default) or `markdown` cell |
| `delete` | `path`, `index` | Remove a cell |
| `clear_outputs` | `path` | Remove every saved output |

## Use it

```python
from shipit_agent import Agent, NotebookEditTool
from shipit_agent.llms import build_llm_from_env

agent = Agent(llm=build_llm_from_env(), tools=[NotebookEditTool(root_dir="notebooks")])
agent.run("In analysis.ipynb, add a markdown cell before the chart explaining what it shows.")
```

`root_dir` is the folder whose notebooks it may touch; paths outside it are refused. `Agent.with_builtins()` includes the tool for the project root.

## See also

- [Read file](read-file.md) and [Edit file](edit-file.md) for other files
