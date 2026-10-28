'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { loadModule } = require('./helpers.cjs');

const flow = loadModule('setup-flow');

test('an interrupted setup resumes at the step whose prerequisite is still true', () => {
  assert.equal(flow.resumeStep(4, { workspaceOpen: false, modelConfigured: true, modelHasKey: true }), 1);
  assert.equal(flow.resumeStep(4, { workspaceOpen: true, modelConfigured: false, modelHasKey: false }), 2);
  assert.equal(flow.resumeStep(4, { workspaceOpen: true, modelConfigured: true, modelHasKey: false }), 2);

  // Steps 1–2 are done, so a stored "1" resumes at the environment step.
  assert.equal(flow.resumeStep(1, { workspaceOpen: true, modelConfigured: true, modelHasKey: true }), 3);
  assert.equal(flow.resumeStep(3, { workspaceOpen: true, modelConfigured: true, modelHasKey: true }), 3);
  assert.equal(flow.resumeStep(4, { workspaceOpen: true, modelConfigured: true, modelHasKey: true }), 4);
  assert.equal(flow.resumeStep(99, { workspaceOpen: true, modelConfigured: true, modelHasKey: true }), 4);
});

test('completion needs a workspace, a model and a key in the backend order', () => {
  assert.deepEqual(flow.missingForCompletion({ workspaceOpen: false, modelConfigured: false, modelHasKey: false }), ['workspace', 'model']);
  assert.deepEqual(flow.missingForCompletion({ workspaceOpen: true, modelConfigured: true, modelHasKey: false }), ['provider_key']);
  assert.deepEqual(flow.missingForCompletion({ workspaceOpen: true, modelConfigured: true, modelHasKey: true }), []);
  assert.equal(flow.canComplete({ workspaceOpen: true, modelConfigured: true, modelHasKey: true }), true);
});

test('the demo model is visibly a demo and counts as a usable model', () => {
  const view = flow.capabilityOf({ base_url: 'demo://', has_key: false });
  assert.equal(view.tone, 'success');
  assert.equal(view.label, 'مدل نمایشی');
  assert.equal(view.canWrite, true);
});

test('a model without a key or a probe cannot be claimed as able to write', () => {
  const noKey = flow.capabilityOf({ base_url: 'https://api.example.com/v1', has_key: false });
  assert.equal(noKey.canWrite, false);
  assert.equal(noKey.label, 'کلید ندارد');

  const unproven = flow.capabilityOf({
    base_url: 'https://api.example.com/v1',
    has_key: true,
    capabilities: { tools: null, error_code: null },
  });
  assert.equal(unproven.canWrite, false);
  assert.equal(unproven.label, 'بررسی نشده');

  const missing = flow.capabilityOf({ base_url: 'https://api.example.com/v1', has_key: true });
  assert.equal(missing.canWrite, false);
  assert.equal(missing.label, 'بررسی نشده');
});

test('only a probe that observed a tool call permits writes', () => {
  const proven = flow.capabilityOf({
    base_url: 'https://api.example.com/v1',
    has_key: true,
    capabilities: { tools: true, error_code: null, checked_at: 42 },
  });
  assert.equal(proven.canWrite, true);
  assert.equal(proven.label, 'ابزارها تأیید شد');

  const unsupported = flow.capabilityOf({
    base_url: 'https://api.example.com/v1',
    has_key: true,
    capabilities: { tools: false, error_code: 'tools_not_observed' },
  });
  assert.equal(unsupported.canWrite, false);
  assert.equal(unsupported.tone, 'danger');
  assert.equal(unsupported.label, 'ابزار فراخوانی نشد');
});

test('provider failures stay distinct so the setup screen can say what to fix', () => {
  const labels = ['provider_auth', 'provider_unreachable', 'model_not_found', 'tools_unsupported', 'provider_error'].map(
    (code) => flow.providerFailure(code).label,
  );
  assert.equal(new Set(labels).size, labels.length);
  assert.match(flow.providerFailure('provider_unreachable').hint, /آدرس مدل/);
  assert.match(flow.providerFailure('provider_auth').hint, /کلید/);
  assert.equal(flow.providerFailure('something_new').label, 'بررسی ممکن نشد');
});

test('saved commands are preselected only while the preflight still suggests them', () => {
  const suggested = ['npm test', 'npm run typecheck', 'npm run build'];
  assert.deepEqual(flow.initialCommandSelection(suggested), suggested);
  assert.deepEqual(flow.initialCommandSelection(suggested, []), suggested);
  assert.deepEqual(flow.initialCommandSelection(suggested, ['npm test', 'rm -rf .']), ['npm test']);
});

test('all four disclosures exist with user-visible text and no hidden extra permission', () => {
  assert.deepEqual([...flow.DISCLOSURE_KEYS], ['model_api', 'sandbox_network', 'demo_state', 'read_only']);
  for (const key of flow.DISCLOSURE_KEYS) {
    assert.ok(flow.disclosureText[key].title.length > 0);
    assert.ok(flow.disclosureText[key].body.length > 0);
  }
  assert.match(flow.disclosureText.sandbox_network.body, /دسترسی حساب ویندوز/);
  assert.match(flow.disclosureText.sandbox_network.body, /sandbox سیستم‌عامل نیست/);
});
