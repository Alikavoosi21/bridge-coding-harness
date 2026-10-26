'use strict';

// Shared helpers for the harness contract tests. The renderer modules are
// compiled to CommonJS by scripts/test-harness.cjs before these tests run.

const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.join(__dirname, '..', '..');
const BUILD = path.join(ROOT, 'node_modules', '.cache', 'onboard-harness-tests');
const FIXTURES = path.join(ROOT, 'tests', 'contracts', 'harness-stream');

function loadModule(name) {
  return require(path.join(BUILD, `${name}.js`));
}

function loadJson(name) {
  return JSON.parse(fs.readFileSync(path.join(FIXTURES, name), 'utf8'));
}

function loadText(name) {
  return fs.readFileSync(path.join(FIXTURES, name), 'utf8');
}

const projection = loadModule('projection');
const client = loadModule('client');
const transport = loadModule('transport');

const EVENTS = loadJson('events.json');
const PARTIAL_SNAPSHOT = loadJson('partial-snapshot.json');

function projector(cursor = 0, status = null) {
  return new projection.HarnessEventProjector({
    taskId: 'task_demo0000000001',
    cursor,
    status,
  });
}

function applyRange(target, from, to) {
  const chunks = [];
  for (const event of EVENTS) {
    if (event.sequence >= from && event.sequence <= to) chunks.push(...target.apply(event));
  }
  return chunks;
}

function chunkTypes(chunks) {
  return chunks.map((chunk) => chunk.type);
}

function textDeltas(chunks) {
  return chunks.filter((chunk) => chunk.type === 'text-delta').map((chunk) => chunk.delta).join('');
}

function dataParts(chunks) {
  return chunks.filter((chunk) => chunk.type === 'data-harness').map((chunk) => chunk.data);
}

function jsonResponse(body, options = {}) {
  return new Response(JSON.stringify(body), {
    status: options.status ?? 200,
    headers: {
      'Content-Type': options.contentType ?? 'application/json',
      ...(options.headers ?? {}),
    },
  });
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function abortError() {
  const error = new Error('aborted');
  error.name = 'AbortError';
  return error;
}

function sseResponse(text, options = {}) {
  const bytes = new TextEncoder().encode(text);
  const splitAt = options.splitAt ?? bytes.length;
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(bytes.slice(0, splitAt));
      controller.enqueue(bytes.slice(splitAt));
      controller.close();
    },
  });
  return new Response(body, {
    status: options.status ?? 200,
    headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
  });
}

async function collect(stream) {
  const reader = stream.getReader();
  const chunks = [];
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  return chunks;
}

function userMessage(id, text) {
  return { id, role: 'user', parts: [{ type: 'text', text }] };
}

class FakeClient {
  constructor(options = {}) {
    this.taskSnapshot = options.taskSnapshot ?? {
      id: 'task_demo0000000001',
      workspace_id: 'ws_1',
      status: 'executing',
      revision: 1,
      last_event_seq: 0,
    };
    this.events = options.events ?? EVENTS;
    this.startResult = options.startResult ?? {
      task: { ...this.taskSnapshot, id: 'task_new0000000001', status: 'queued' },
      run: null,
      last_event_seq: 0,
    };
    this.calls = [];
    this.afterCancel = options.afterCancel;
  }

  async startTask(input) {
    this.calls.push({ kind: 'startTask', input });
    return this.startResult;
  }

  async sendMessage(taskId, input) {
    this.calls.push({ kind: 'sendMessage', taskId, input });
    return { task: this.taskSnapshot, message: { id: 'msg_steering', task_id: taskId, role: 'user', parts: [{id:'msg_steering:text',text:input.text,state:'done'}], references: input.references ?? [], delivered_at: null } };
  }

  async proposePlan(taskId, input) {
    this.calls.push({ kind: 'proposePlan', taskId, input });
    return { task: this.taskSnapshot, plan: null, message: input.instruction ? { id: 'msg_correction', task_id: taskId, role: 'user', parts: [{id:'msg_correction:text',text:input.instruction,state:'done'}], references: input.references ?? [], delivered_at: null } : null };
  }

  async continueTask(taskId, input) {
    this.calls.push({ kind: 'continueTask', taskId, input });
    return { task: this.taskSnapshot, plan: null, run: null };
  }

  async task(taskId) {
    this.calls.push({ kind: 'task', taskId });
    return this.taskSnapshot;
  }

  async stopTask(taskId) {
    this.calls.push({ kind: 'stopTask', taskId });
    return { stopping: true };
  }

  async *streamEvents(taskId, options) {
    this.calls.push({ kind: 'streamEvents', taskId, afterSeq: options.afterSeq });
    const pending = this.events.filter((event) => event.sequence > options.afterSeq);
    for (const event of pending) {
      if (options.signal?.aborted) throw abortError();
      yield event;
      if (this.afterCancel) await this.afterCancel(options.signal);
    }
  }
}

module.exports = {
  ROOT,
  BUILD,
  FIXTURES,
  loadModule,
  loadJson,
  loadText,
  EVENTS,
  PARTIAL_SNAPSHOT,
  projection,
  client,
  transport,
  projector,
  applyRange,
  chunkTypes,
  textDeltas,
  dataParts,
  jsonResponse,
  sseResponse,
  deferred,
  abortError,
  collect,
  userMessage,
  FakeClient,
};
