/** Shared display rules for resource gauges and service history buckets. */
export function gaugeLevel(value) {
  if (value == null) return 'missing';
  if (value >= 80) return 'critical';
  if (value >= 60) return 'warning';
  return 'healthy';
}

export function serviceHistoryLevel(checks) {
  const up = checks.some((item) => item.status === 'up');
  const down = checks.some((item) => item.status === 'down');
  if (up && down) return 'warning';
  if (down) return 'critical';
  return up ? 'healthy' : 'missing';
}
