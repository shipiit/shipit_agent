---
title: download_file
description: Download files (zip, csv, images, PDFs) over http(s) into a workspace folder, with a size cap and private networks blocked.
---

# `download_file`

`download_file` saves a file from an `http` or `https` URL to disk, binary-safe, so an agent can fetch a dataset, an image or a PDF and then work on it with other tools.

It is careful by default: files land in a downloads workspace, there is a size cap, and addresses on private networks (`localhost`, `10.x`, `192.168.x` and so on) are refused, so a URL in a document can't make the agent reach into your network.

## Use it

```python
from shipit_agent import Agent, DownloadFileTool
from shipit_agent.llms import build_llm_from_env

downloads = DownloadFileTool(workspace_root=".shipit_workspace/downloads", max_bytes=50 * 1024 * 1024)
agent = Agent(llm=build_llm_from_env(), tools=[downloads])
agent.run("Download the CSV at https://example.com/sales.csv and tell me how many rows it has.")
```

| Argument | Default | What it does |
| --- | --- | --- |
| `workspace_root` | `".shipit_workspace/downloads"` | Where files are saved |
| `max_bytes` | 100 MB | Larger downloads are refused |
| `timeout_seconds` | `60` | Longest a download may take |
| `allow_private_hosts` | `False` | Allow `localhost` and private network addresses |

The model calls it with a `url`, an optional destination `path`, and `overwrite` (default `False`).

## See also

- [PDF](pdf.md) and [SQL](sql.md) to work on what you downloaded
