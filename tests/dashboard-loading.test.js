/** @file dashboard-loading.test.js @description In-flight history reads survive collection preset changes. */
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import test from 'node:test';
import React from 'react';
import { act, create } from 'react-test-renderer';
import { useDashboard } from '../frontend/src/useDashboard.js';

test('changing collection interval during first history read starts a usable replacement', async t => {
  const original = { window: globalThis.window, document: globalThis.document, fetch: globalThis.fetch };
  const noop = () => {};
  globalThis.window = { crypto: webcrypto, AbortController: globalThis.AbortController, setInterval: () => 1, clearInterval: noop, addEventListener: noop, removeEventListener: noop };
  globalThis.document = { hidden: false, addEventListener: noop, removeEventListener: noop };
  const reads = [];
  globalThis.fetch = (path, options) => new Promise((resolve, reject) => {
    options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    reads.push({ path, resolve: payload => resolve({ ok: true, json: async () => payload }) });
  });
  let root, dashboard;
  t.after(async () => {
    if (root) await act(async () => root.unmount());
    Object.assign(globalThis, original);
  });
  function Dashboard({ seconds }) {
    dashboard = useDashboard({ resourceView: 'machines', mode: 'status', range: '60d', seconds, automatic: true });
    return null;
  }
  await act(async () => { root = create(React.createElement(Dashboard, { seconds: 60 })); });
  assert.equal(reads[0].path, '/api/session');
  await act(async () => reads[0].resolve({ full_access: false, refresh: { presets: [60, 120, 300] } }));
  assert.equal(reads.length, 2);
  assert.equal(reads[1].path, '/history/services?range=60d');
  await act(async () => root.update(React.createElement(Dashboard, { seconds: 300 })));
  assert.equal(reads.length, 3, 'restart must not be blocked by the invalidated in-flight read');
  const payload = { items: [], instance: { name: 'x250' } };
  await act(async () => reads[2].resolve(payload));
  assert.equal(dashboard.loading, false);
  assert.deepEqual(dashboard.history, payload);
  assert.equal(dashboard.error, '');
});
