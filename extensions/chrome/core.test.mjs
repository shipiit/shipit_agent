import { test } from 'node:test';
import assert from 'node:assert/strict';
import { consumeEvents } from './core.mjs';

function stream(text, width = 1) {
  const bytes = new TextEncoder().encode(text);
  return new ReadableStream({ start(controller) {
    for (let i = 0; i < bytes.length; i += width) controller.enqueue(bytes.slice(i, i + width));
    controller.close();
  } });
}
test('SSE handles fragmented UTF-8, CRLF, and final completion', async () => {
  const events = [];
  await consumeEvents(stream('data: {"type":"text_delta","payload":{"chunk":"你好"}}\r\n\r\ndata: {"type":"done"}\n\n'), e => events.push(e));
  assert.equal(events[0].payload.chunk, '你好'); assert.equal(events[1].type, 'done');
});
test('truncated stream cannot become a success', async () => {
  await assert.rejects(consumeEvents(stream('data: {"type":"text_delta"}\n\n'), () => {}), /before completion/);
});
test('malformed JSON is explicit', async () => {
  await assert.rejects(consumeEvents(stream('data: broken\n\n'), () => {}), SyntaxError);
});
test('consumer errors propagate and release stream', async () => {
  const source = stream('data: {"type":"error"}\n\n');
  await assert.rejects(consumeEvents(source, () => { throw new Error('model failed'); }), /model failed/);
  assert.equal(source.locked, false);
});
