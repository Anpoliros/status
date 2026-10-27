/** Regression coverage for load color boundaries and mixed service history. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { gaugeLevel, serviceHistoryLevel } from '../frontend/src/status-utils.js';

test('gauges change color at 60 and 80 percent and preserve missing data', () => {
  assert.equal(gaugeLevel(null), 'missing');
  assert.equal(gaugeLevel(0), 'healthy');
  assert.equal(gaugeLevel(59.9), 'healthy');
  assert.equal(gaugeLevel(60), 'warning');
  assert.equal(gaugeLevel(79.9), 'warning');
  assert.equal(gaugeLevel(80), 'critical');
});

test('service buckets distinguish partial outage from complete outage', () => {
  assert.equal(serviceHistoryLevel([]), 'missing');
  assert.equal(serviceHistoryLevel([{ status: 'up' }]), 'healthy');
  assert.equal(serviceHistoryLevel([{ status: 'down' }]), 'critical');
  assert.equal(serviceHistoryLevel([{ status: 'down' }, { status: 'up' }]), 'warning');
  assert.equal(serviceHistoryLevel([{ status: 'up' }, { status: 'down' }]), 'warning');
});
