/** @file ServiceTelemetry.jsx @description Local origin traffic and TCP history. */
import React, { useState } from 'react';

function bytes(value) {
  if (value == null) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index++; }
  return `${value.toFixed(index ? 1 : 0)} ${units[index]}`;
}

function TrafficChart({ points }) {
  const maximum = Math.max(1, ...points.flatMap(p => [p.rx || 0, p.tx || 0]));
  // Keep absent intervals as gaps instead of drawing fabricated zero traffic.
  const paths = key => {
    const segments = [];
    let path = '';
    points.forEach((point, index) => {
      if (point[key] == null) { if (path) segments.push(path); path = ''; return; }
      const x = points.length > 1 ? index * 600 / (points.length - 1) : 300;
      const y = 94 - point[key] / maximum * 84;
      path += `${path ? ' L' : 'M'}${x},${y}`;
    });
    if (path) segments.push(path);
    return segments;
  };
  return <div className="trafficChart"><span>{bytes(maximum)}/s</span><svg viewBox="0 0 600 100" role="img" aria-label="Origin receive and send traffic"><path d="M0 95H600" className="trafficAxis" />{['rx', 'tx'].map(key => paths(key).map((d, index) => <path key={`${key}-${index}`} d={d} className={`trafficLine ${key}`} />))}</svg><small>↓ Receive · ↑ Send</small></div>;
}

export function ServiceTelemetry({ metrics }) {
  const [range, setRange] = useState('hour');
  const now = Date.now();
  const count = range === 'day' ? 24 : 60;
  const duration = range === 'day' ? 3600000 : 86400000;
  const resolution = range === 'day' ? 'hour' : 'day';
  const bins = new Map(metrics.history.filter(h => h.resolution === resolution).map(h => [h.bucket, h]));
  const historical = Array.from({ length: count }, (_, index) => {
    const key = new Date(now - (count - 1 - index) * duration).toISOString().slice(0, range === 'day' ? 13 : 10);
    const bin = bins.get(key);
    return { rx: bin?.seconds ? bin.incoming / bin.seconds : null, tx: bin?.seconds ? bin.outgoing / bin.seconds : null };
  });
  const recent = new Map(metrics.recent.map(p => [p.timestamp, p]));
  const points = range === 'hour' ? Array.from({ length: 60 }, (_, i) => recent.get(Math.floor(now / 60000) * 60 - (59 - i) * 60) || {}) : historical;
  const today = metrics.history.find(h => h.resolution === 'day' && h.bucket === new Date().toISOString().slice(0, 10));
  return <details className="serviceTelemetry"><summary><span>↓ {bytes(metrics.rx)}{metrics.rx == null ? '' : '/s'}</span><span>↑ {bytes(metrics.tx)}{metrics.tx == null ? '' : '/s'}</span><span>TCP {metrics.tcp ?? '—'}</span><span className="telemetryMore">Traffic history</span></summary>
    <div className="telemetryDetails"><div className="segmented">{[['hour', '1 hour'], ['day', '24 hours'], ['long', '60 days']].map(([key, label]) => <button key={key} className={range === key ? 'selected' : ''} onClick={() => setRange(key)}>{label}</button>)}</div>
      <TrafficChart points={points} />
      <div className="telemetryTotals"><span>Today (UTC) ↓ {today?.seconds ? bytes(today.incoming) : '—'} ↑ {today?.seconds ? bytes(today.outgoing) : '—'}</span><span>TCP peak {today?.tcp_max ?? '—'}</span></div>
      <small>Origin port {metrics.port} · includes local calls and TCP overhead · excludes Cloudflare cache hits</small>
      <small>{metrics.timestamp ? `Collected ${new Date(metrics.timestamp * 1000).toLocaleString()}` : 'Waiting for collection'}{metrics.rx == null ? ' · Traffic counters unavailable or warming up' : ''}</small>
    </div></details>;
}
