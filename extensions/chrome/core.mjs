export const BRIDGE = 'http://127.0.0.1:8400';

// Called in Chrome's isolated world. No cookies, form values, hidden DOM, or scripts.
export function extractPage() {
  const limit = 24000;
  const active = document.activeElement;
  const privateFocus = active?.matches('input, textarea, [contenteditable="true"]');
  const selection = privateFocus ? '' : String(window.getSelection() || '').trim();
  const root = document.querySelector('main, [role="main"], article') || document.body;
  const parts = [];
  let size = 0;
  if (!selection && root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node;
    let visited = 0;
    while ((node = walker.nextNode()) && size <= limit && visited++ < 50000) {
      const el = node.parentElement;
      if (!el || el.closest('script,style,noscript,textarea,input,select,[contenteditable="true"],[hidden],[aria-hidden="true"]')) continue;
      const style = getComputedStyle(el);
      if (style.visibility === 'hidden' || style.display === 'none' || !el.getClientRects().length) continue;
      const text = node.textContent.trim();
      if (text) { parts.push(text); size += text.length + 1; }
    }
  }
  const text = selection || parts.join('\n');
  const url = new URL(location.href);
  // Query strings and fragments can contain private tokens or search queries.
  url.search = ''; url.hash = '';
  return { title: document.title.slice(0, 500), url: url.href.slice(0, 2000),
    text: text.slice(0, limit), mode: selection ? 'selection' : 'page',
    truncated: text.length > limit,
    limitation: location.hostname === 'docs.google.com'
      ? 'Docs / Sheets may use canvas rendering. This snapshot may contain only interface text. Select or paste the relevant content.'
      : 'Readable text only. Hidden content, embedded frames, images and form fields are excluded.' };
}

export async function consumeEvents(stream, onEvent) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = ''; let done = false;
  try {
    while (true) {
      const item = await reader.read();
      buffer += decoder.decode(item.value, { stream: !item.done });
      let match;
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        const data = frame.split(/\r?\n/).filter(x => x.startsWith('data:')).map(x => x.slice(5).trimStart()).join('\n');
        if (!data) continue;
        const event = JSON.parse(data);
        onEvent(event);
        if (event.type === 'done') done = true;
      }
      if (buffer.length > 2000000) throw new Error('Stream frame exceeded the safety limit');
      if (item.done) break;
    }
    if (!done) throw new Error('Connection ended before completion. The reply may be incomplete.');
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
