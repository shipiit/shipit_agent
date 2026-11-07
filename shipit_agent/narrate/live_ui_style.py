"""The style sheet of the live chat panel shown in notebooks."""

# Same palette as ``share.py`` — warm orange on off-white, dark mode by query.
# Kept as its own sheet rather than imported because every rule here is
# prefixed, and the two surfaces have different layouts (a page vs. a card).
_STYLE = """
.sa-live {
  --sa-bg: #fff; --sa-line: #e8e6e3; --sa-text: #1c1b1a;
  --sa-muted: #6f6b66; --sa-faint: #9a958f;
  --sa-accent: #e8590c; --sa-accent-soft: #fdf0e8;
  --sa-danger: #c92a2a; --sa-ok: #2f9e44; --sa-chip: #f4f2f0;
  --sa-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  --sa-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, system-ui, sans-serif;
  background: var(--sa-bg); color: var(--sa-text);
  font: 14.5px/1.62 var(--sa-sans);
  border: 1px solid var(--sa-line); border-radius: 14px;
  max-width: 780px; overflow: hidden;
  box-shadow: 0 1px 2px rgba(0,0,0,.04), 0 8px 24px rgba(0,0,0,.05);
}
@media (prefers-color-scheme: dark) {
  .sa-live {
    --sa-bg: #201e1d; --sa-line: #34312e; --sa-text: #eceae7;
    --sa-muted: #a9a39c; --sa-faint: #726c66;
    --sa-accent: #ff8040; --sa-accent-soft: #2e1f16;
    --sa-danger: #ff8787; --sa-ok: #69db7c; --sa-chip: #2a2725;
  }
}
.sa-live * { box-sizing: border-box; }
.sa-live .sa-head {
  display: flex; align-items: center; gap: 10px;
  padding: 13px 18px; border-bottom: 1px solid var(--sa-line);
}
.sa-live .sa-title { font-weight: 600; font-size: 14px; letter-spacing: -.01em; }
.sa-live .sa-badge {
  font: 11px/1 var(--sa-mono); color: var(--sa-ok);
  background: var(--sa-chip); border-radius: 999px; padding: 5px 9px;
  display: inline-flex; align-items: center; gap: 6px;
}
.sa-live .sa-badge.done { color: var(--sa-muted); }
.sa-live .sa-dot {
  width: 6px; height: 6px; border-radius: 50%; background: currentColor;
  animation: sa-pulse 1.4s ease-in-out infinite;
}
.sa-live .sa-badge.done .sa-dot { animation: none; }
@keyframes sa-pulse { 0%,100% { opacity: 1 } 50% { opacity: .25 } }
.sa-live .sa-body { padding: 18px 18px 6px; }
.sa-live .sa-ask {
  background: var(--sa-chip); border-radius: 14px;
  padding: 11px 15px; margin: 0 0 18px auto; max-width: 76%; width: fit-content;
}
.sa-live .sa-prose { margin: 14px 0; white-space: pre-wrap; }
.sa-live .sa-row {
  display: flex; gap: 11px; align-items: flex-start;
  margin: 12px 0; color: var(--sa-muted);
}
.sa-live .sa-glyph {
  font: 13px/1.5 var(--sa-mono); color: var(--sa-faint);
  width: 16px; flex: 0 0 16px; text-align: center; padding-top: 1px;
}
.sa-live .sa-label { flex: 1; min-width: 0; }
.sa-live .sa-label b { font-weight: 500; color: var(--sa-text); }
.sa-live .sa-targets {
  font: 12.5px/1.6 var(--sa-mono); color: var(--sa-faint);
  overflow-wrap: anywhere;
}
.sa-live .sa-count {
  font: 12px/1.6 var(--sa-mono); color: var(--sa-faint);
  white-space: nowrap; padding-top: 1px;
}
.sa-live .sa-run { color: var(--sa-accent); }
.sa-live .sa-err b { color: var(--sa-danger); }
.sa-live details.sa-call { margin: 6px 0 0; }
.sa-live details.sa-call > summary {
  cursor: pointer; list-style: none; font: 12px/1.6 var(--sa-mono);
  color: var(--sa-faint);
}
.sa-live details.sa-call > summary::-webkit-details-marker { display: none; }
.sa-live details.sa-call > summary:hover { color: var(--sa-accent); }
.sa-live pre.sa-out {
  font: 12px/1.55 var(--sa-mono); background: var(--sa-chip);
  border-radius: 8px; padding: 10px 12px; margin: 7px 0 0;
  max-height: 260px; overflow: auto; white-space: pre-wrap;
  overflow-wrap: anywhere; color: var(--sa-muted);
}
.sa-live .sa-approval {
  border: 1px solid var(--sa-line); border-radius: 12px;
  padding: 13px 15px; margin: 16px 0;
}
.sa-live .sa-approval .sa-bullet { color: var(--sa-accent); margin-right: 7px; }
.sa-live .sa-approval .sa-what { font-weight: 500; margin-bottom: 8px; }
.sa-live .sa-approval .sa-meta {
  font: 12px/1.6 var(--sa-mono); color: var(--sa-faint);
}
.sa-live .sa-choices {
  display: flex; gap: 16px; justify-content: flex-end;
  margin-top: 11px; font-size: 13px; color: var(--sa-muted);
}
.sa-live .sa-choices .sa-primary { color: var(--sa-text); font-weight: 600; }
.sa-live .sa-decision {
  border-left: 2px solid var(--sa-accent); padding: 2px 0 2px 12px;
  margin: 14px 0; color: var(--sa-muted);
}
.sa-live .sa-decision .sa-step {
  display: block; font: 11px/1.6 var(--sa-mono);
  text-transform: uppercase; letter-spacing: .06em; color: var(--sa-accent);
}
.sa-live a.sa-artifact {
  display: flex; align-items: center; gap: 13px;
  border: 1px solid var(--sa-line); border-radius: 12px;
  padding: 12px 15px; margin: 14px 0; text-decoration: none;
  color: inherit; transition: border-color .15s;
}
.sa-live a.sa-artifact:hover { border-color: var(--sa-accent); }
.sa-live .sa-file {
  width: 34px; height: 34px; border-radius: 9px; background: var(--sa-chip);
  display: flex; align-items: center; justify-content: center;
  font-size: 15px; color: var(--sa-muted); flex: 0 0 34px;
}
.sa-live .sa-art-body { flex: 1; min-width: 0; }
.sa-live .sa-art-body b { display: block; font-weight: 600; }
.sa-live .sa-art-meta { font-size: 12.5px; color: var(--sa-faint); }
.sa-live .sa-open { color: var(--sa-faint); }
.sa-live .sa-connect {
  border: 1px solid var(--sa-line); border-radius: 12px;
  padding: 13px 15px; margin: 16px 0; background: var(--sa-accent-soft);
}
.sa-live .sa-connect .sa-what { font-weight: 600; margin-bottom: 4px; }
.sa-live .sa-connect .sa-plug { color: var(--sa-accent); margin-right: 8px; }
.sa-live .sa-connect .sa-reason { margin-bottom: 6px; }
.sa-live .sa-connect .sa-meta {
  font: 12px/1.6 var(--sa-mono); color: var(--sa-faint);
}
.sa-live .sa-sub {
  border-left: 2px solid var(--sa-accent-soft);
  padding-left: 13px; margin: 14px 0;
}
.sa-live .sa-notice {
  font-size: 13px; color: var(--sa-muted);
  background: var(--sa-accent-soft); border-radius: 8px; padding: 9px 12px;
  margin: 14px 0;
}
.sa-live .sa-caret {
  display: inline-block; width: 7px; height: 1.05em; margin-left: 1px;
  background: var(--sa-accent); vertical-align: text-bottom;
  animation: sa-blink 1s steps(2) infinite;
}
@keyframes sa-blink { 50% { opacity: 0 } }
.sa-live pre.sa-tree {
  font: 12.5px/1.7 var(--sa-mono); margin: 4px 0 12px;
  white-space: pre; overflow-x: auto; color: var(--sa-text);
}
.sa-live .sa-foot {
  border-top: 1px solid var(--sa-line); padding: 11px 18px;
  font: 12px/1.5 var(--sa-mono); color: var(--sa-faint); text-align: right;
}
"""
