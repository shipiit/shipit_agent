# Verification — 8 October 2026

## Automated checks

- 37 Python tests passed: bridge authorization, session isolation, invalid model
  recovery, busy-chat rejection, Workspace proposals and conflict checks,
  invalid approvals, bounded attachment extraction, and chat-session packets.
- 5 Node tests passed: fragmented UTF-8/SSE, incomplete streams, invalid JSON,
  consumer failures, and Google document URL identification.

## Real provider checks

The HTTP/SSE smoke test used AWS credentials and Gemma 4 31B, switching to
26B-A4B for one follow-up. All five turns completed with streamed deltas and
correct retention of the test project's owner, budget and revised deadline.
That measured session reported **10,085 input + 98 output tokens**. Cache-read
counters were zero; no caching savings are claimed.

An installed-extension test in an isolated, headless Chrome for Testing profile
connected to the real bridge, uploaded a text document, asked a follow-up, and
switched from 31B to 26B-A4B. Its first measured three-turn session reported
**5,910 input + 66 output tokens**, with 27, 14 and 22 text deltas respectively.
These counts describe those particular sessions, not every subsequent test run.

Further browser checks confirmed:

- Reload retained all three answers and the selected model.
- A failed token change displayed its error inside the dialog and preserved chat.
- At 320×500, 410×900 and 1100×740, there was no horizontal or document overflow
  and the composer bottom matched the viewport bottom.
- No JavaScript page errors were observed in the completed browser smoke run.
- The actual Page control captured a synthetic open page served by the test
  bridge. The snapshot contained the heading, owner and deadline, and excluded
  hidden text, form contents, editable text and script contents. Real Gemma
  answered the question correctly from that attached snapshot.
- Real 31B vision identified Shipit and a suggested action in a UI screenshot.
  Real 26B vision, through the installed extension's image upload, read the new
  canvas-rendered code **PINE-742** correctly.

## Not yet verified live

- Google Docs, Sheets and Slides API reads/writes require a Google OAuth client
  and account authorization. No Workspace token was configured. Workspace tests
  used a fake API; no live document edits were made or claimed.
- The native toolbar-to-side-panel opening and activeTab permission grant on
  arbitrary external sites were not completed through native automation. The
  successful automated capture used the already-permitted loopback test origin.
- The extension screenshot button's native activeTab grant still needs a manual
  check on an external page. Vision was verified with uploaded images.
- This is focused functional verification, not an exhaustive long-session,
  cross-provider, Google account or Chrome version certification.

The native Chrome control connection was unreliable during testing. The installed
extension checks above used an isolated automated Chrome profile instead. During
test development, one attempt to read an already-consumed SSE response through
Chrome's network debugger failed; the browser smoke runner now asserts the
visible completed answer and HTTP status rather than depending on debugger body
retention. The bridge smoke test separately verifies SSE events and usage.
