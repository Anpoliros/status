/** @file page-identity.test.js @description Intranet HTTP must not require randomUUID. */
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import test from 'node:test';
import { createPageIdentity } from '../frontend/src/page-identity.js';

test('page identifiers work without secure-context randomUUID', () => {
  const provider = { getRandomValues: bytes => webcrypto.getRandomValues(bytes) };
  const first = createPageIdentity(provider);
  const second = createPageIdentity(provider);
  assert.match(first, /^[a-f0-9]{32}$/);
  assert.notEqual(first, second);
});
