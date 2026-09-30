const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('../frontend/node_modules/typescript');
const compiled = ts.transpileModule(fs.readFileSync(require.resolve('../frontend/src/services/stream.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const loaded = { exports: {} };
new Function('exports', 'module', compiled)(loaded.exports, loaded);
const { consumeChatStream } = loaded.exports;
const encoder = new TextEncoder();

function streamOf(text, bytewise = false) {
  const bytes = encoder.encode(text);
  return new ReadableStream({ start(controller) {
    if (bytewise) for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
    else controller.enqueue(bytes);
    controller.close();
  } });
}

test('preserves Chinese UTF-8 and SSE frames split at every byte', async () => {
  const events = [];
  await consumeChatStream(streamOf('data: {"type":"answer","content":"你好，肇庆市一"}\r\n\r\ndata: {"type":"done"}\r\n\r\n', true), event => events.push(event));
  assert.equal(events[0].content, '你好，肇庆市一');
  assert.equal(events.at(-1).type, 'done');
});

test('rejects truncated connection even after partial answer', async () => {
  await assert.rejects(consumeChatStream(streamOf('data: {"type":"answer_chunk","content":"部分答案"}\n\n'), () => {}), /提前中断/);
});

test('rejects blank answer followed by done', async () => {
  await assert.rejects(consumeChatStream(streamOf('data: {"type":"answer","content":""}\n\ndata: {"type":"done"}\n\n'), () => {}), /有效答案/);
});

test('delivers server error and terminal event once', async () => {
  const events = [];
  await consumeChatStream(streamOf('data: {"type":"error","content":"检索失败"}\n\ndata: {"type":"done"}\n\ndata: {"type":"done"}\n\n'), event => events.push(event.type));
  assert.deepEqual(events, ['error', 'done']);
});

test('rejects malformed JSON instead of silently losing it', async () => {
  await assert.rejects(consumeChatStream(streamOf('data: {invalid}\n\n'), () => {}), SyntaxError);
});

test('times out and cancels an idle stream', async () => {
  let cancelled = false;
  const stream = new ReadableStream({ cancel() { cancelled = true; } });
  await assert.rejects(consumeChatStream(stream, () => {}, 10), /超时/);
  assert.equal(cancelled, true);
});
