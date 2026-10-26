'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  EVENTS,
  client: clientModule,
  loadText,
  jsonResponse,
  sseResponse,
} = require('./helpers.cjs');

const { HarnessClient, HarnessRequestError, SseDecoder } = clientModule;

const BASE = 'http://127.0.0.1:8765';
const TOKEN = 'app-token-not-in-url';

test('the app token is a header, never a URL or a provider key', async () => {
  const calls = [];
  const client = new HarnessClient({
    baseUrl: BASE,
    token: TOKEN,
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return jsonResponse({ items: [], last_event_seq: 0 });
    },
  });

  await client.events('task_demo0000000001', { afterSeq: 5 });

  assert.equal(calls.length, 1);
  const [{ url, init }] = calls;
  assert.ok(url.startsWith(`${BASE}/tasks/task_demo0000000001/events?`));
  assert.ok(url.includes('after_seq=5'));
  assert.ok(!url.includes(TOKEN), 'the token must not be in the URL');
  assert.equal(init.headers.Authorization, `Bearer ${TOKEN}`);
  assert.equal(init.headers['Content-Type'], undefined, 'a GET has no JSON body');
  assert.ok(!('api_key' in init.headers) && !('x-api-key' in init.headers));
  assert.equal(init.credentials, 'omit');
});

test('a secret query parameter is refused before a request is made', () => {
  const client = new HarnessClient({ baseUrl: BASE, token: TOKEN, fetchImpl: async () => jsonResponse({}) });

  assert.throws(
    () => client.safeUrl('/tasks?token=abc'),
    (error) => error instanceof HarnessRequestError && error.code === 'secret_in_url',
  );
  assert.throws(
    () => client.safeUrl('/tasks?api_key=abc'),
    (error) => error instanceof HarnessRequestError && error.code === 'secret_in_url',
  );
});

test('creating a task sends the prompt once with an idempotency header', async () => {
  const calls = [];
  const task = {
    id: 'task_demo0000000001',
    workspace_id: 'ws_1',
    status: 'queued',
    revision: 1,
    last_event_seq: 2,
  };
  const client = new HarnessClient({
    baseUrl: BASE,
    token: TOKEN,
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return jsonResponse({ task, run: null, last_event_seq: 2 }, { status: 202 });
    },
  });

  const result = await client.startTask({
    prompt: 'گزارش را بساز',
    idempotency_key: 'chat:1:msg_1',
  });

  assert.equal(result.task.id, task.id);
  const [{ url, init }] = calls;
  assert.equal(url, `${BASE}/tasks`);
  assert.equal(init.method, 'POST');
  assert.equal(init.headers['Idempotency-Key'], 'chat:1:msg_1');
  assert.deepEqual(JSON.parse(init.body), { prompt: 'گزارش را بساز', idempotency_key: 'chat:1:msg_1' });
  assert.equal(JSON.parse(init.body).api_key, undefined);
});

test('a 409 becomes a typed error with its current revision', async () => {
  const client = new HarnessClient({
    baseUrl: BASE,
    token: TOKEN,
    fetchImpl: async () =>
      jsonResponse(
        {
          code: 'workspace_busy',
          message: 'Another writer is active.',
          details: { lease_id: 'wslease_1' },
          retryable: true,
          current_revision: 7,
        },
        { status: 409 },
      ),
  });

  await assert.rejects(
    () => client.task('task_demo0000000001'),
    (error) =>
      error instanceof HarnessRequestError &&
      error.status === 409 &&
      error.code === 'workspace_busy' &&
      error.retryable === true &&
      error.currentRevision === 7 &&
      error.details.lease_id === 'wslease_1',
  );
});

test('Stop is an explicit request, never a side effect of reading', async () => {
  const calls = [];
  const client = new HarnessClient({
    baseUrl: BASE,
    token: TOKEN,
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return jsonResponse({ stopping: true });
    },
  });

  await client.stopTask('task_demo0000000001', 'stop:1');

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, `${BASE}/tasks/task_demo0000000001/stop`);
  assert.equal(calls[0].init.headers['Idempotency-Key'], 'stop:1');
});

test('the SSE decoder waits for a complete frame and ignores keepalive comments', () => {
  const decoder = new SseDecoder();

  assert.deepEqual(decoder.push(': keepalive\n\n'), []);
  assert.deepEqual(decoder.push('event: harness\nid: evt_1\ndata: {"a":'), [], 'a split frame is not dispatched early');
  const frames = decoder.push('1}\n\n');
  assert.deepEqual(frames, [{ event: 'harness', id: 'evt_1', data: '{"a":1}' }]);

  assert.deepEqual(decoder.push('data: one\ndata: two\n\n'), [{ event: 'message', data: 'one\ntwo' }]);
  assert.deepEqual(decoder.push('data: last'), []);
  assert.deepEqual(decoder.end(), [{ event: 'message', data: 'last' }]);
});

test('an SSE replay is parsed frame by frame across chunk boundaries', async () => {
  const client = new HarnessClient({
    baseUrl: BASE,
    token: TOKEN,
    fetchImpl: async () => sseResponse(loadText('sse.txt'), { splitAt: 17 }),
  });

  const seen = [];
  for await (const event of client.streamEvents('task_demo0000000001')) seen.push(event.sequence);

  assert.deepEqual(seen, [2, 3], '[DONE] ends the stream and comments are not events');
});

test('a malformed SSE event is refused instead of reaching the projector', async () => {
  const client = new HarnessClient({
    baseUrl: BASE,
    token: TOKEN,
    fetchImpl: async () => sseResponse('event: harness\ndata: {"not":"an event"}\n\n'),
  });

  await assert.rejects(
    async () => {
      for await (const _event of client.streamEvents('task_demo0000000001')) {
        // consume
      }
    },
    (error) => error instanceof HarnessRequestError && error.code === 'invalid_stream',
  );
});

test('JSON pages are followed from the last sequence to the end', async () => {
  const calls = [];
  const client = new HarnessClient({
    baseUrl: BASE,
    token: TOKEN,
    fetchImpl: async (url) => {
      const after = Number(new URL(url).searchParams.get('after_seq'));
      calls.push(after);
      if (after === 0) return jsonResponse({ items: EVENTS.slice(0, 2), last_event_seq: 20 });
      return jsonResponse({ items: [], last_event_seq: 20 });
    },
  });

  const seen = [];
  for await (const event of client.streamEvents('task_demo0000000001', { limit: 2 })) seen.push(event.sequence);

  assert.deepEqual(seen, [1, 2]);
  assert.deepEqual(calls, [0, 2], 'the next page starts after the last sequence already shown');
});

test('a connection failure is a typed network error, not a fake empty journal', async () => {
  const client = new HarnessClient({
    baseUrl: BASE,
    token: TOKEN,
    fetchImpl: async () => {
      throw new TypeError('fetch failed');
    },
  });

  await assert.rejects(
    () => client.events('task_demo0000000001'),
    (error) => error instanceof HarnessRequestError && error.code === 'network_error' && error.status === 0,
  );
});
