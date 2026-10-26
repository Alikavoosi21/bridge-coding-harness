'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const {
  EVENTS,
  PARTIAL_SNAPSHOT,
  ROOT,
  transport: transportModule,
  collect,
  textDeltas,
  userMessage,
  FakeClient,
  deferred,
  abortError,
} = require('./helpers.cjs');

const { HarnessChatTransport, HarnessTransportError } = transportModule;

test('durable receipt survives stream failure and retry does not send twice', async () => {
  const fake = new FakeClient({ events: [] });
  fake.streamEvents = async function* () { throw new Error('connection lost after POST'); };
  const receipts = [];
  const chat = new HarnessChatTransport({ client: fake, snapshot: {task_id: 'task_demo0000000001', last_event_seq: 0, status: 'executing'}, onMessageAccepted: id => receipts.push(id) });
  const input = {trigger: 'submit-message', chatId: 'chat_1', messages: [userMessage('stable-user', 'hello')], abortSignal: undefined};
  const stream = await chat.sendMessages(input);
  assert.deepEqual(receipts, ['stable-user'], 'acknowledged before the stream finishes');
  await assert.rejects(() => collect(stream), /connection lost/);
  const retry = await chat.sendMessages(input);
  await assert.rejects(() => collect(retry), /connection lost/);
  assert.equal(fake.calls.filter(c => c.kind === 'sendMessage').length, 1);
});

test('rejected POST has no receipt; retry reuses its key until accepted', async () => {
  const fake = new FakeClient({events: []});
  const keys = [];
  let reject = true;
  fake.sendMessage = async (_task, input) => {
    keys.push(input.idempotency_key);
    if (reject) throw new Error('message refused');
    return {message: {id: 'stored'}};
  };
  const receipts = [];
  const chat = new HarnessChatTransport({client: fake, snapshot: {task_id: 'task_demo0000000001', last_event_seq: 0, status: 'executing'}, onMessageAccepted: id=>receipts.push(id)});
  const input = {trigger: 'submit-message', chatId: 'chat_1', messages: [userMessage('stable-retry', 'hello')], abortSignal: undefined};
  await assert.rejects(() => chat.sendMessages(input), /refused/);
  assert.deepEqual(receipts, []);
  reject = false;
  await collect(await chat.sendMessages(input));
  assert.deepEqual(receipts, ['stable-retry']);
  assert.equal(keys[0], keys[1]);
});

const TASK = 'task_demo0000000001';

test('a fresh AI SDK reader resumes partial text from the snapshot without missing text-start', async () => {
  const {readUIMessageStream} = await import('ai');
  const fake = new FakeClient({events: EVENTS});
  const chat = new HarnessChatTransport({client: fake, snapshot: PARTIAL_SNAPSHOT});
  const stream = await chat.reconnectToStream({chatId:'task:'+TASK});
  let last;
  for await (const message of readUIMessageStream({stream, terminateOnError:true})) last = message;
  assert.equal(last.parts.filter(p=>p.type==='text').map(p=>p.text).join(''), 'سلام دنیا 🎉');
  assert.equal(chat.resumeStreamIsReplay, true);
  assert.equal(fake.calls.filter(c=>c.kind==='sendMessage'||c.kind==='startTask').length, 0);
});

function event(sequence, type, payload, eventId = `evt_custom_${sequence}`) {
  return {
    schema_version: 1,
    task_id: TASK,
    run_id: 'run_1',
    sequence,
    event_id: eventId,
    type,
    occurred_at: sequence,
    payload,
  };
}

function fakeClient(overrides = {}) {
  const fake = new FakeClient(overrides);
  fake.startResult = {
    task: {
      id: TASK,
      workspace_id: 'ws_1',
      status: 'queued',
      revision: 1,
      last_event_seq: 0,
    },
    run: null,
    last_event_seq: 0,
  };
  return fake;
}

function kinds(fake) {
  return fake.calls.map((call) => call.kind);
}

test('a new task sends one product command and projects the journal once', async () => {
  const fake = fakeClient({ events: EVENTS.filter((item) => item.sequence <= 6) });
  const chat = new HarnessChatTransport({ client: fake });
  const message = userMessage('um_1', 'گزارش را بساز');

  const stream = await chat.sendMessages({
    trigger: 'submit-message',
    chatId: 'chat_1',
    messageId: undefined,
    messages: [message],
    abortSignal: undefined,
  });
  const chunks = await collect(stream);

  assert.equal(kinds(fake).filter((kind) => kind === 'startTask').length, 1);
  assert.equal(kinds(fake).includes('sendMessage'), false, 'a new task is not also steered');
  assert.equal(kinds(fake).includes('stopTask'), false);
  assert.equal(fake.calls.find((call) => call.kind === 'startTask').input.prompt, 'گزارش را بساز');
  assert.equal(textDeltas(chunks), 'سلام دنیا 🎉');
  assert.equal(chunks.filter((chunk) => chunk.type === 'finish').length, 1);
  assert.equal(chat.currentTaskId, TASK);
  assert.equal(chat.lastEventSeq, 6);
});

test('an existing task is steered, and only new text is projected', async () => {
  const fake = fakeClient({
    events: EVENTS,
    taskSnapshot: { id: TASK, workspace_id: 'ws_1', status: 'executing', revision: 2, last_event_seq: 6 },
  });
  const chat = new HarnessChatTransport({ client: fake, snapshot: PARTIAL_SNAPSHOT });

  const stream = await chat.sendMessages({
    trigger: 'submit-message',
    chatId: 'chat_existing',
    messageId: undefined,
    messages: [userMessage('um_1', 'اول'), userMessage('um_2', 'ادامه بده')],
    abortSignal: undefined,
  });
  const chunks = await collect(stream);

  assert.equal(kinds(fake).includes('startTask'), false);
  const sent = fake.calls.find((call) => call.kind === 'sendMessage');
  assert.equal(sent.taskId, TASK);
  assert.equal(sent.input.text, 'ادامه بده');
  assert.equal(textDeltas(chunks), 'سلام دنیا 🎉', 'the new SDK reader rebuilds the open response');
});

test('an existing task without a caller cursor reads the snapshot before sending', async () => {
  const fake = fakeClient({
    events: EVENTS,
    taskSnapshot: {
      id: TASK,
      workspace_id: 'ws_1',
      status: 'executing',
      revision: 2,
      last_event_seq: 3,
      messages: PARTIAL_SNAPSHOT.messages,
    },
  });
  const chat = new HarnessChatTransport({ client: fake, taskId: TASK });

  const stream = await chat.sendMessages({
    trigger: 'submit-message',
    chatId: 'chat_existing',
    messageId: undefined,
    messages: [userMessage('um_2', 'ادامه بده')],
    abortSignal: undefined,
  });
  const chunks = await collect(stream);

  assert.deepEqual(kinds(fake).slice(0, 2), ['task', 'sendMessage'], 'a baseline is read before the command');
  assert.equal(textDeltas(chunks), 'سلام دنیا 🎉');
  assert.equal(fake.calls.find((call) => call.kind === 'startTask'), undefined);
});

test('reconnect reads from the cursor and never sends a command', async () => {
  const snapshot = {
    task_id: TASK,
    last_event_seq: 6,
    status: 'executing',
    messages: [
      { id: 'msg_1', role: 'assistant', parts: [{ id: 'part_1', text: 'سلام دنیا 🎉', state: 'done' }] },
    ],
  };
  const fake = fakeClient({
    events: EVENTS,
    taskSnapshot: { id: TASK, workspace_id: 'ws_1', status: 'awaiting_decision', revision: 3, last_event_seq: 7 },
  });
  const chat = new HarnessChatTransport({ client: fake, snapshot });

  const stream = await chat.reconnectToStream({ chatId: 'chat_1' });
  assert.ok(stream, 'there is a new event to replay');

  const chunks = await collect(stream);
  assert.equal(kinds(fake).includes('startTask'), false);
  assert.equal(kinds(fake).includes('sendMessage'), false);
  assert.equal(kinds(fake).includes('stopTask'), false);
  assert.equal(textDeltas(chunks), '', 'a finished message is not reopened');
  assert.equal(chunks.some((chunk) => chunk.type === 'data-harness' && chunk.data.kind === 'task-state'), true);

  assert.equal(await chat.reconnectToStream({ chatId: 'chat_1' }), null, 'at the end, there is no active stream');
  assert.equal(kinds(fake).filter((kind) => kind === 'streamEvents').length, 1);
});

test('cancelling the consumer does not stop the runtime', async () => {
  const fake = fakeClient({
    events: [EVENTS[0]],
    taskSnapshot: { id: TASK, workspace_id: 'ws_1', status: 'executing', revision: 1, last_event_seq: 1 },
  });
  let released;
  const blocked = new Promise((resolve) => {
    released = resolve;
  });
  fake.afterCancel = async (signal) => {
    await blocked;
    if (signal.aborted) throw abortError();
  };
  const chat = new HarnessChatTransport({ client: fake, snapshot: { task_id: TASK, last_event_seq: 0, status: 'executing' } });

  const stream = await chat.reconnectToStream({ chatId: 'chat_1' });
  const reader = stream.getReader();
  const first = await reader.read();
  assert.equal(first.done, false);

  await reader.cancel();
  released();

  assert.equal(kinds(fake).includes('stopTask'), false, 'clicking away is not the Stop button');
  assert.equal(kinds(fake).includes('startTask'), false);
  assert.equal(kinds(fake).includes('sendMessage'), false);
});

test('regeneration is a replay, not a second command or a second model call', async () => {
  const snapshot = {
    task_id: TASK,
    last_event_seq: 20,
    status: 'closed',
    messages: [{ id: 'msg_1', role: 'assistant', parts: [{ id: 'part_1', text: 'done', state: 'done' }] }],
  };
  const fake = fakeClient({
    events: EVENTS,
    taskSnapshot: { id: TASK, workspace_id: 'ws_1', status: 'closed', revision: 4, last_event_seq: 20 },
  });
  const chat = new HarnessChatTransport({ client: fake, snapshot });

  const stream = await chat.sendMessages({
    trigger: 'regenerate-message',
    chatId: 'chat_1',
    messageId: 'msg_1',
    messages: [userMessage('um_1', 'دوباره')],
    abortSignal: undefined,
  });
  const chunks = await collect(stream);

  assert.equal(kinds(fake).includes('startTask'), false);
  assert.equal(kinds(fake).includes('sendMessage'), false, 'regenerate does not repeat the command');
  assert.equal(kinds(fake).includes('stopTask'), false);
  assert.equal(chunks.length, 0, 'nothing after the cursor means no duplicate text');
});

test('a finish chunk while a decision is pending does not mark the task completed', async () => {
  const events = [
    event(1, 'message_started', { message_id: 'msg_1', part_id: 'part_1' }),
    event(2, 'text_delta', { message_id: 'msg_1', part_id: 'part_1', offset: 0, delta: 'پیش‌نویس' }),
    event(3, 'task_state_changed', { state: 'awaiting_decision', reason: 'plan' }),
    event(4, 'message_finished', { message_id: 'msg_1', part_id: 'part_1', finish_reason: 'stop' }),
  ];
  const fake = fakeClient({ events });
  const chat = new HarnessChatTransport({ client: fake });

  const stream = await chat.sendMessages({
    trigger: 'submit-message',
    chatId: 'chat_1',
    messageId: undefined,
    messages: [userMessage('um_1', 'برنامه را بده')],
    abortSignal: undefined,
  });
  const chunks = await collect(stream);
  const finish = chunks.find((chunk) => chunk.type === 'finish');

  assert.equal(finish.messageMetadata.task_state, 'awaiting_decision');
  assert.equal(finish.messageMetadata.task_closed, false);
  assert.equal(finish.messageMetadata.segment_finished, true);
});

test('a journal gap fails the stream instead of showing partial text', async () => {
  const fake = fakeClient({ events: [EVENTS[1]] }); // sequence 2 with no sequence 1
  const chat = new HarnessChatTransport({ client: fake });

  const stream = await chat.sendMessages({
    trigger: 'submit-message',
    chatId: 'chat_1',
    messageId: undefined,
    messages: [userMessage('um_1', 'سلام')],
    abortSignal: undefined,
  });

  await assert.rejects(() => collect(stream), (error) => error.name === 'EventGapError');
  assert.equal(kinds(fake).filter((kind) => kind === 'startTask').length, 1, 'the command is not silently repeated');
  assert.equal(kinds(fake).includes('stopTask'), false);
});

test('the same user message retries with the same idempotency key', async () => {
  const first = fakeClient({ events: [] });
  const second = fakeClient({ events: [] });
  const one = new HarnessChatTransport({ client: first });
  const two = new HarnessChatTransport({ client: second });
  const message = userMessage('um_stable', 'همان پیام');

  await collect(
    await one.sendMessages({
      trigger: 'submit-message',
      chatId: 'chat_1',
      messageId: undefined,
      messages: [message],
      abortSignal: undefined,
    }),
  );
  await collect(
    await two.sendMessages({
      trigger: 'submit-message',
      chatId: 'chat_1',
      messageId: undefined,
      messages: [message],
      abortSignal: undefined,
    }),
  );

  const keyOf = (fake) => fake.calls.find((call) => call.kind === 'startTask').input.idempotency_key;
  assert.equal(keyOf(first), keyOf(second));
  assert.equal(keyOf(first), 'chat:chat_1:um_stable');
});

test('closing the transport releases readers and never stops the task', async () => {
  const fake = fakeClient();
  const chat = new HarnessChatTransport({ client: fake, snapshot: { task_id: TASK, last_event_seq: 0 } });

  chat.close();

  assert.equal(await chat.reconnectToStream({ chatId: 'chat_1' }), null);
  await assert.rejects(
    () =>
      chat.sendMessages({
        trigger: 'submit-message',
        chatId: 'chat_1',
        messageId: undefined,
        messages: [userMessage('um_1', 'x')],
        abortSignal: undefined,
      }),
    (error) => error instanceof HarnessTransportError && error.code === 'closed',
  );
  assert.deepEqual(fake.calls, []);
});

test('an interrupted finish is reported as interrupt, not completion', async () => {
  const events = [
    event(1, 'task_state_changed', { state: 'executing' }),
    event(2, 'message_started', { message_id: 'msg_1', part_id: 'part_1' }),
    event(3, 'text_delta', { message_id: 'msg_1', part_id: 'part_1', offset: 0, delta: 'نیمه‌کاره' }),
    event(4, 'message_finished', { message_id: 'msg_1', part_id: 'part_1', finish_reason: 'interrupted' }),
    event(5, 'task_state_changed', { state: 'paused', reason: 'stopped' }),
  ];
  const fake = fakeClient({ events });
  const chat = new HarnessChatTransport({ client: fake });

  const stream = await chat.sendMessages({
    trigger: 'submit-message',
    chatId: 'chat_1',
    messageId: undefined,
    messages: [userMessage('um_1', 'متوقف کن')],
    abortSignal: undefined,
  });
  const chunks = await collect(stream);
  const finishes = chunks.filter((chunk) => chunk.type === 'finish');

  assert.equal(finishes[0].finishReason, 'interrupted');
  assert.equal(finishes.at(-1).messageMetadata.task_state, 'paused');
  assert.equal(finishes.at(-1).messageMetadata.task_closed, false);
  assert.equal(textDeltas(chunks), 'نیمه‌کاره');
});

test('the harness modules contain no provider key or server-side model runner', () => {
  const files = ['client.ts', 'projection.ts', 'transport.ts'];
  const source = files
    .map((name) => fs.readFileSync(path.join(ROOT, 'src', 'lib', 'harness', name), 'utf8'))
    .join('\n');

  const forbidden = [
    ['streamText', /streamText/],
    ['ToolLoopAgent', /ToolLoopAgent/],
    ['apiKey', /apiKey/],
    ['api_key', /api_key/],
    ['OPENAI_API_KEY', /OPENAI_API_KEY/],
    ['ANTHROPIC_API_KEY', /ANTHROPIC_API_KEY/],
    ['a sk- provider key', /\bsk-[A-Za-z0-9]/],
    ['process.env', /process\.env/],
  ];
  for (const [label, pattern] of forbidden) {
    assert.equal(pattern.test(source), false, `${label} must stay out of the renderer transport`);
  }
});
