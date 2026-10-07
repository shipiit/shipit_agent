import { BRIDGE, extractPage, consumeEvents } from './core.mjs';

const $ = id => document.getElementById(id);
const extension = Boolean(globalThis.chrome?.storage?.session);
let token = '', sessionId = '', turns = [], page = null, controller = null;
const saved = extension ? await chrome.storage.session.get(['token', 'sessionId', 'turns']) : {};
token = saved.token || ''; sessionId = saved.sessionId || ''; turns = saved.turns || [];

function status(text, error = false) { $('status').textContent = text; $('status').classList.toggle('error', error); }
function connection() {
  $('connection').textContent = token ? 'Agent configured' : 'Connect your agent';
  $('dot').classList.toggle('connected', Boolean(token));
}
async function persist() {
  if (extension) await chrome.storage.session.set({ token, sessionId, turns });
}
async function api(path, body, signal) {
  const response = await fetch(BRIDGE + path, { method: 'POST', redirect: 'error',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body), signal });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || `Bridge returned ${response.status}`);
  }
  return response;
}
function message(turn) {
  const article = document.createElement('article'); article.className = `message ${turn.role}`;
  const label = document.createElement('div'); label.className = 'label'; label.textContent = turn.role === 'user' ? 'YOU' : 'SHIPIT';
  const body = document.createElement('div'); body.className = 'body'; body.textContent = turn.text;
  article.append(label, body);
  if (turn.source) { const note = document.createElement('div'); note.className = 'message-note'; note.textContent = `◫ ${turn.source}`; article.append(note); }
  if (turn.role === 'assistant') {
    const copy = document.createElement('button'); copy.className = 'copy'; copy.textContent = 'Copy response';
    copy.onclick = async () => { try { await navigator.clipboard.writeText(turn.text); copy.textContent = 'Copied'; } catch { status('Could not copy. Select the response text instead.', true); } };
    article.append(copy);
  }
  $('messages').append(article); $('welcome').hidden = true;
  return body;
}
function busy(value) {
  for (const id of ['send', 'attach', 'new', 'settings']) $(id).disabled = value;
  $('stop').hidden = !value; $('send').hidden = value;
}
function removePage() { page = null; $('page-card').hidden = true; }
$('remove-page').onclick = removePage;
$('attach').onclick = async () => {
  if (!extension) { status('Page capture is available when installed as a Chrome extension.', true); return; }
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !/^https?:/.test(tab.url || '')) throw new Error('Open a webpage and click the Shipit toolbar icon on that tab first.');
    const [snapshot] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: extractPage });
    if (!snapshot?.result?.text) throw new Error('No readable text found. Select or paste the document content instead.');
    page = snapshot.result;
    $('page-card').hidden = false; $('page-title').textContent = page.title;
    $('page-source').textContent = page.url;
    $('page-summary').textContent = `Review ${page.mode} · ${page.text.length.toLocaleString()} characters${page.truncated ? ' · truncated' : ''}`;
    $('page-limit').textContent = page.limitation; $('page-preview').textContent = page.text;
    status('Snapshot ready. Review it before sending. It will be attached to your next message only.');
  } catch (error) { status(`${error.message} If access was denied, click Shipit's toolbar icon on the page, then try again.`, true); }
};
$('settings').onclick = () => { $('token').value = token; $('config').showModal(); };
$('cancel-config').onclick = () => $('config').close();
$('config-form').onsubmit = async event => {
  event.preventDefault();
  const next = $('token').value.trim();
  if (next !== token) { sessionId = ''; turns = []; document.querySelectorAll('.message').forEach(el => el.remove()); $('welcome').hidden = false; }
  token = next; await persist(); connection(); $('config').close();
  status('Connection saved. Your next message will connect to the local agent.');
};
$('new').onclick = async () => {
  try {
    if (sessionId) await api('/sessions/delete', { session_id: sessionId });
  } catch (error) {
    if (!error.message.includes('expired')) { status(error.message, true); return; }
  }
  sessionId = ''; turns = []; removePage();
  document.querySelectorAll('.message').forEach(el => el.remove()); $('welcome').hidden = false;
  await persist(); status('New chat. Previous chat history cleared from this bridge.');
};
for (const button of document.querySelectorAll('[data-prompt]')) button.onclick = () => {
  $('prompt').value = button.dataset.prompt; $('prompt').focus();
  if (!page) status('Attach the current page, or paste the relevant context, before sending.');
};
$('stop').onclick = () => controller?.abort();
$('prompt').onkeydown = event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('composer').requestSubmit(); }
};
$('composer').onsubmit = async event => {
  event.preventDefault();
  if (controller) return;
  const prompt = $('prompt').value.trim();
  if (!prompt) return;
  if (!token) { $('settings').click(); return; }
  controller = new AbortController(); busy(true); status('Connecting to your agent…');
  let reply, output;
  try {
    if (!sessionId) { const response = await api('/sessions', {}, controller.signal); sessionId = (await response.json()).session_id; await persist(); }
    const response = await api('/chat', { session_id: sessionId, prompt, page: page && {
      title: page.title, url: page.url, text: page.text, mode: page.mode, truncated: page.truncated,
    } }, controller.signal);
    const user = { role: 'user', text: prompt, source: page?.title || '' };
    turns.push(user); message(user); $('prompt').value = ''; removePage();
    reply = { role: 'assistant', text: '' }; turns.push(reply); output = message(reply);
    status('Working…');
    await consumeEvents(response.body, event => {
      const p = event.payload || {};
      if (event.type === 'text_delta') reply.text += p.chunk || '';
      if (event.type === 'run_completed') { reply.text = p.output ?? reply.text; status('Complete'); }
      if (event.type.startsWith('tool_')) status(`${event.type.replaceAll('_', ' ')} · ${p.name || p.tool_name || 'tool'}`);
      if (event.type === 'context_compaction_started') status('Compacting conversation context…');
      if (event.type === 'error') throw new Error(p.message || 'Agent run failed');
      if (event.type === 'run_cancelled') throw new Error('Run cancelled');
      output.textContent = reply.text;
      const log = $('messages'); log.scrollTop = log.scrollHeight;
    });
  } catch (error) {
    const reason = error.name === 'AbortError'
      ? 'Stream stopped. An in-flight provider call may still finish on the backend.'
      : error.message;
    status(reason, true);
    if (reply) { reply.text += `\n\n[Incomplete: ${reason}]`; output.textContent = reply.text; }
  } finally { controller = null; busy(false); await persist().catch(() => status('Could not retain this transcript in browser session storage.', true)); }
};
for (const turn of turns) message(turn);
connection();
if (!extension) status('UI preview · Install the unpacked extension to connect and capture pages.');
