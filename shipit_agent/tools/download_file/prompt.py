DOWNLOAD_FILE_PROMPT = """
Download a file from an http(s) URL to local disk — binary-safe (zips,
images, CSVs, PDFs, datasets, installers).

- `url` is required. `path` optionally names the destination (relative
  paths land in the downloads workspace); otherwise the filename comes
  from the URL / Content-Disposition header.
- Size-capped: downloads over the limit are aborted cleanly with the
  partial file removed.
- Use `read_file` / `pdf` / `run_code` afterwards to inspect what you
  downloaded; use `open_url` instead when you only need a page's TEXT.
""".strip()
