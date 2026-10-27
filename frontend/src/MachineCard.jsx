/**
 * @file frontend/src/MachineCard.jsx
 * @description Compact list gauges and grid bars stay visible; expansion adds collection details.
 */
import React, { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { gaugeLevel } from './status-utils.js';

const METRICS = [
  ['CPU', 'cpu_usage'],
  ['RAM', 'memory_usage'],
  ['DISK', 'disk_usage'],
];

export function MachineCard({ server, layout }) {
  const [expanded, setExpanded] = useState(false);
  const detailsId = `machine-details-${server.id}`;
  return (
    <article className={`machineCard ${expanded ? 'expanded' : 'collapsed'}`}>
      <div className="machineOverview">
        <button className="machineHeader" onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded} aria-controls={detailsId}>
          <h3>{server.name}</h3>
          <span className={`statusDot ${server.status || 'critical'}`} />
          <span className="machineToggle">{expanded ? <ChevronDown size={17} /> : <ChevronRight size={17} />}</span>
        </button>
        <div className="metricGrid">
          {METRICS.map(([label, field]) => (
            <Gauge key={field} label={label} value={server[field]} bars={layout === 'grid'} />
          ))}
          <div className="networkMetric">
            <strong>NET</strong>
            <span>IN {formatRate(server.network_in)}</span>
            <span>OUT {formatRate(server.network_out)}</span>
          </div>
        </div>
      </div>
      {expanded && <dl className="machineDetails" id={detailsId}>
        <div><dt>Endpoint</dt><dd>{server.ip}</dd></div>
        <div><dt>Cluster</dt><dd>{server.cluster || 'Default'}</dd></div>
        <div><dt>Last collected</dt><dd>{server.timestamp ? new Date(server.timestamp).toLocaleString() : 'No data'}</dd></div>
        <div><dt>Status</dt><dd>{server.status || 'No data'}</dd></div>
      </dl>}
    </article>
  );
}

function Gauge({ label, value, bars }) {
  const percent = value == null ? 0 : Math.max(0, Math.min(100, value));
  const text = value == null ? '—' : `${value.toFixed(1)}%`;
  const style = { '--percent': `${percent * 3.6}deg`, '--fill': `${percent}%` };
  return <div className={`${bars ? 'metricBar' : 'metricRing'} gauge-${gaugeLevel(value)}`} style={style}>
    <strong>{label}</strong>
    {bars ? <><div className="metricTrack"><span /></div><span>{text}</span></> : <div className="ring"><span>{text}</span></div>}
  </div>;
}

// Stored network deltas are normalized to bytes/minute; display them as bytes/second.
function formatRate(value) {
  if (value == null) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value / 60;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size.toFixed(unit ? 1 : 0)} ${units[unit]}/s`;
}
