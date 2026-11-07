# Shipit Workspace companion

A docked Chrome sidebar backed by an ordinary Shipit `Agent` and its streaming
chat session. The browser controls the panel height. The composer stays at the
bottom while the conversation scrolls.

## Run locally

From the repository root:

```sh
python -m pip install -e '.[browser,bedrock]'
export SHIPIT_BROWSER_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m shipit_agent.browser_bridge
```

Use your existing AWS profile or environment credentials and region. The default
model menu offers Gemma 4 31B and Gemma 4 26B-A4B through Bedrock Mantle, both with
image input. AWS credentials stay in the backend. The bridge listens only on
`127.0.0.1:8400`; it is a single-user development service, not a hosted API.

Open `chrome://extensions`, enable Developer mode, choose **Load unpacked**, and
select this `extensions/chrome` directory. Open Shipit from Chrome's extension
toolbar on the page you want to use. In Connection settings, paste the value of
`SHIPIT_BROWSER_TOKEN` from your terminal. Keep that value private: it authorizes
calls to the local agent. Reload the extension after changing its source files.

## Use the composer

- **+** attaches files. PNG, JPEG and WebP go to the vision model. PDF, DOCX,
  XLSX, PPTX and supported text files contribute extracted text.
- **Page** attaches readable text or the selected text from the current tab.
  Review the snapshot before sending. Chrome restricts capture on internal pages
  such as `chrome://extensions`; use a normal website.
- **Camera** attaches a screenshot of the visible tab.
- The model selector switches models while preserving the backend conversation.
- Enter sends; Shift+Enter adds a line. Stop disconnects the stream; an already
  running provider request may still finish on the backend.

Page capture requires Chrome's temporary `activeTab` permission. If capture is
denied after navigating to another site, click Shipit's toolbar icon on that site
and retry. Page and file contents are attached only when you send the message.
The extension does not automatically click, type into, or crawl arbitrary sites.

## Connect Google Docs, Sheets and Slides

Create a Google Cloud OAuth **Desktop app** client and enable the Drive, Docs,
Sheets and Slides APIs for that project. Keep the downloaded client JSON outside
this repository. Authorize the intended Google account locally:

```sh
python -m shipit_agent.browser_bridge --google-login --google-client /absolute/path/client.json
```

Restart the bridge after login. The account token is stored with owner-only
permissions at `~/.shipit_browser/google_token.json`; `--google-token` can select
another location. The sidebar's **Google configured** label indicates that a
token file exists, not that every document is accessible or every scope is valid.
The API verifies access when a tool is used.

Open a Google document, attach its page, and ask Shipit to read or prepare a
change. Google editors often render on canvas, so their page snapshot alone may
contain only interface text. The Workspace tool reads the document through the
Google API. File IDs come from the attached page URL or Drive search.

Changes are proposals until you review the exact request and click **Apply**.
Docs and Slides updates use Google's revision check. Sheets checks the current
content before applying; this is best effort and does not prevent a simultaneous
edit between that check and the write. Ambiguous network failures are not
automatically replayed. Check the document before submitting another proposal.

Excel and PowerPoint uploads are read as extracted text. Editing is available
for native Google Sheets and Slides through the Workspace API; the extension
does not edit a locally uploaded Office file in place. Gmail is not yet a tool.

## Limits and session behavior

Up to eight attachments, 4 MB each and 12 MB combined. Document excerpts share
a 60,000-character limit and page snapshots have a 24,000-character limit;
truncation is disclosed. Scanned PDFs need page images for vision. Office text
extraction omits formatting, embedded images and objects.

Backend chats are kept in memory (up to 32) and expire when the bridge restarts.
The sidebar transcript and bridge token use Chrome session storage. New chat
clears the current chat from the bridge. This version does not provide durable
conversation recovery, cross-user hosting or a browser-wide automation agent.

## Verification

```sh
python -m pytest -q tests/test_browser_bridge.py tests/test_browser_workspace.py tests/test_browser_attachments.py tests/test_chat_session_and_packets.py
node --test extensions/chrome/core.test.mjs
python scripts/smoke_browser_live.py
```

The last command makes real, billable Bedrock calls using synthetic page text,
tests five turns and a model switch through HTTP/SSE, and prints provider usage.
It does not verify native Chrome permissions or live Google edits. Workspace
unit tests use a fake API; they verify proposal and conflict handling without
modifying an account. `scripts/browser_sidebar_fixture.py` is a separate offline
UI fixture and must not be confused with the real bridge. Its explicit `--live`
mode uses Bedrock and requires `SHIPIT_BROWSER_TOKEN`; it also serves a synthetic
page at `http://127.0.0.1:8400/test-page` for extension capture verification.
Stop an existing bridge before running this test server on the same port.

`scripts/browser_extension_smoke.js` is a Playwright function accepting a browser
page and `{ extensionPath, executablePath, token, screenshotPath? }`. It loads the
extension in a temporary Chrome profile and checks real chat, model switching,
reload, failed connection recovery and viewport fit. See [verification results](VERIFICATION.md)
for the actual tested scope and remaining gaps.
