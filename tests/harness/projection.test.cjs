'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  EVENTS,
  PARTIAL_SNAPSHOT,
  projection,
  projector,
  applyRange,
  chunkTypes,
  textDeltas,
  dataParts,
} = require('./helpers.cjs');

const { HarnessEventProjector, EventGapError, ProjectionError } = projection;

test('a text segment projects to start/text/deltas/end/finish in order', () => {
  const state = projector();
  const chunks = applyRange(state, 1, 6);

  assert.deepEqual(
    chunkTypes(chunks).filter((type) => type !== 'data-harness'),
    ['start', 'text-start', 'text-delta', 'text-delta', 'text-delta', 'text-end', 'finish'],
  );

  const start = chunks.find((chunk) => chunk.type === 'start');
  assert.equal(start.messageId, 'msg_1');

  const [message] = state.messages();
  assert.equal(message.role, 'assistant');
  assert.equal(message.parts[0].text, 'سلام دنیا 🎉');
  assert.equal(message.parts[0].state, 'done');

  const finish = chunks.find((chunk) => chunk.type === 'finish');
  assert.equal(finish.messageMetadata.last_event_seq, 6);
  assert.equal(finish.messageMetadata.task_state, 'executing');
  assert.equal(finish.messageMetadata.segment_finished, true);
  assert.equal(finish.messageMetadata.task_closed, false, 'a finished message does not close the task');
});

test('duplicate and out-of-order events are no-ops; a gap is an error', () => {
  const state = projector();
  state.apply(EVENTS[0]);

  assert.deepEqual(state.apply(EVENTS[0]), [], 'the same sequence must not be applied twice');
  assert.throws(() => state.apply(EVENTS[2]), (error) => error instanceof EventGapError && error.expected === 2);

  const retry = projector();
  retry.apply(EVENTS[0]);
  retry.apply(EVENTS[1]);
  assert.deepEqual(retry.apply(EVENTS[0]), [], 'an older cursor is a replay, not new text');
  assert.equal(retry.lastEventSeq, 2);

  const duplicateId = { ...EVENTS[1], sequence: 3 };
  assert.throws(
    () => retry.apply(duplicateId),
    (error) => error instanceof ProjectionError && error.code === 'duplicate_event_id',
  );
});

test('text offsets make a reconnect idempotent and refuse to guess', () => {
  const state = projector();
  state.apply(EVENTS[0]); // seq 1: task is executing
  state.apply(EVENTS[1]); // seq 2: message_started
  const delta = EVENTS[2].payload; // seq 3: offset 0

  assert.equal(textDeltas(state.apply(EVENTS[2])), 'سلام');
  assert.deepEqual(
    state.apply({ ...EVENTS[2], sequence: 4, event_id: 'evt_replay_delta' }),
    [],
    'the same delta at offset 0 is already shown',
  );

  assert.throws(
    () =>
      state.apply({
        ...EVENTS[3],
        sequence: 5,
        event_id: 'evt_conflict',
        payload: { ...delta, offset: 2, delta: 'X' },
      }),
    (error) => error instanceof ProjectionError && error.code === 'text_conflict',
  );
  assert.throws(
    () =>
      state.apply({
        ...EVENTS[3],
        sequence: 5,
        event_id: 'evt_gap',
        payload: { ...delta, offset: 20, delta: 'x' },
      }),
    (error) => error instanceof ProjectionError && error.code === 'offset_gap',
  );
  assert.deepEqual(
    state.apply({
      ...EVENTS[3],
      sequence: 5,
      event_id: 'evt_overlap',
      payload: { ...delta, offset: 1, delta: 'لا' },
    }),
    [],
    'a matching overlap is a replay, not an append',
  );
});

test('offsets are Unicode code points, so an emoji is one character', () => {
  const state = projector();
  state.apply(EVENTS[0]); // seq 1: task is executing
  state.apply(EVENTS[1]);
  state.apply(EVENTS[2]); // 4 code points
  state.apply(EVENTS[3]); // 9 code points
  state.apply(EVENTS[4]); // 11 code points: space + emoji

  const text = state.messages()[0].parts[0].text;
  assert.equal(text, 'سلام دنیا 🎉');
  assert.equal(Array.from(text).length, 11);
  assert.ok(text.length > Array.from(text).length, 'UTF-16 would count the emoji as two');

  assert.throws(
    () =>
      state.apply({
        ...EVENTS[4],
        sequence: 6,
        event_id: 'evt_after_emoji',
        payload: { message_id: 'msg_1', part_id: 'part_1', offset: text.length, delta: '!' },
      }),
    (error) => error instanceof ProjectionError && error.code === 'offset_gap',
  );
  const appended = state.apply({
    ...EVENTS[4],
    sequence: 6,
    event_id: 'evt_after_emoji',
    payload: { message_id: 'msg_1', part_id: 'part_1', offset: 11, delta: '!' },
  });
  assert.equal(textDeltas(appended), '!');
});

test('a reloaded partial message continues at its offset without duplication', () => {
  const state = HarnessEventProjector.fromSnapshot(PARTIAL_SNAPSHOT);
  assert.equal(state.lastEventSeq, 3);
  assert.equal(state.messages()[0].parts[0].text, 'سلام');

  const chunks = [];
  for (const event of EVENTS) {
    if (event.sequence > 3 && event.sequence <= 6) chunks.push(...state.apply(event));
  }

  assert.equal(textDeltas(chunks), ' دنیا 🎉');
  assert.equal(state.messages()[0].parts[0].text, 'سلام دنیا 🎉');
  assert.equal(
    chunks.filter((chunk) => chunk.type === 'start').length,
    0,
    'a hydrated message is not started a second time',
  );
});

test('domain events become typed data parts, with a stable operation id', () => {
  const state = projector();
  const chunks = applyRange(state, 1, 20);
  const parts = dataParts(chunks);
  const byKind = Object.fromEntries(parts.map((part) => [part.kind, part]));

  assert.equal(byKind['task-state'].task.state, 'closed', 'the last task state wins');
  assert.equal(byKind.plan.plan.revision, 2);
  assert.equal(byKind.plan.plan.steps[0].title, 'بررسی فایل‌ها');
  assert.deepEqual(byKind.plan.plan.scope, ['docs/report.md']);
  assert.equal(byKind.approval.approval.approval_id, 'ap_1');
  assert.equal(byKind.approval.approval.state, 'required');
  assert.equal(byKind.action.action.operation_id, 'op_1');
  assert.equal(byKind.action.action.state, 'succeeded');
  assert.deepEqual(byKind.action.action.receipt, { operation_id: 'op_1' });
  assert.equal(byKind.budget.budget.revision, 3);
  assert.equal(byKind.lease.lease.fencing_token, 4);
  assert.equal(byKind.quality.quality.quality_status, 'not_verified');
  assert.equal(byKind.file.file.path, 'docs/report.md');
  assert.equal(byKind.verification.verification.outcome, 'passed');
  assert.equal(byKind.repair.repair.repair_index, 1);
  assert.equal(byKind['apply-file'].file.state, 'applied');
  assert.equal(byKind.recovery.recovery.reconcile_required, true);

  assert.equal(state.taskClosed, true);
  assert.equal(state.snapshot().domain.actions.op_1.operation_id, 'op_1');
  assert.equal(state.snapshot().domain.approvals.ap_1.tool, 'write_file');
});

test('an action without an operation id is invalid, never hash-derived', () => {
  const state = projector(9);
  const event = {
    ...EVENTS[9],
    payload: { ...EVENTS[9].payload, operation_id: undefined },
  };
  assert.throws(
    () => state.apply(event),
    (error) => error instanceof ProjectionError && error.code === 'invalid_payload',
  );
});

test('terminal receipt survives replay and preserves the canonical tool identity', () => {
  const state=projector();
  const base=EVENTS[0];
  const receipt={operation_id:'op_terminal',exit_code:0,output:'fixture effect stored',cwd:'/workspace',truncated:false};
  const events=[{...base,event_id:'terminal-start',sequence:1,type:'action_started',payload:{operation_id:'op_terminal',state:'running',tool:'execute',summary:'printf fixture'}},{...base,event_id:'terminal-end',sequence:2,type:'action_finished',payload:{operation_id:'op_terminal',state:'succeeded',receipt}}];
  for(const event of events)state.apply(event);
  const action=state.snapshot().domain.actions.op_terminal;
  assert.equal(action.tool,'execute');
  assert.equal(action.summary,'printf fixture');
  assert.deepEqual(action.receipt,receipt);
  const restored=projector();
  for(const event of events)restored.apply(event);
  assert.deepEqual(restored.snapshot().domain.actions.op_terminal.receipt,receipt);
});

test('a task waiting for a decision stays open after the stream ends', () => {
  const state = projector();
  const chunks = applyRange(state, 1, 7);
  const end = state.endSegment();
  const finish = [...chunks, ...end].filter((chunk) => chunk.type === 'finish').at(-1);

  assert.equal(finish.messageMetadata.task_state, 'awaiting_decision');
  assert.equal(finish.messageMetadata.segment_finished, true);
  assert.equal(finish.messageMetadata.task_closed, false);
  assert.equal(state.taskClosed, false);
  assert.deepEqual(state.endSegment(), [], 'ending the same segment twice emits nothing');
});

test('a segment without message_finished still ends with text-end and finish', () => {
  const state = projector();
  state.apply(EVENTS[0]);
  state.apply(EVENTS[1]);
  state.apply(EVENTS[2]);

  const chunks = state.endSegment();
  assert.deepEqual(chunkTypes(chunks), ['text-end', 'finish']);
  assert.equal(chunks[1].messageMetadata.segment_finished, true);
  assert.equal(chunks[1].messageMetadata.task_closed, false);
});

test('an event for another task or an unknown type is refused', () => {
  const state = projector();
  assert.throws(
    () => state.apply({ ...EVENTS[0], task_id: 'task_other' }),
    (error) => error instanceof ProjectionError && error.code === 'task_mismatch',
  );
  assert.throws(
    () => state.apply({ ...EVENTS[0], type: 'made_up' }),
    (error) => error instanceof ProjectionError && error.code === 'invalid_payload',
  );
});
