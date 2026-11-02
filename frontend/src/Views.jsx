/** @file Views.jsx @description Machine, service and pre-aggregated history presentation. */
import React from 'react';
import { CheckCircle2, LayoutGrid, List, WifiOff } from 'lucide-react';
import { MachineCard } from './MachineCard.jsx';

export function EmptyState({ label }) { return <div className="empty">{label}</div>; }

export function MachinesView({ servers, preferences, setPreferences }) {
  const clusters = [...new Set(servers.map(server => server.cluster || 'Default'))];
  return <>{clusters.map(cluster => {
    const items = servers.filter(server => (server.cluster || 'Default') === cluster);
    return <div className="clusterBlock" key={cluster}>
      <div className="clusterHeader"><div><h2>{cluster}</h2><span>{items.length} machines</span></div>
        <div className="segmented iconSegments">{[['list', List], ['grid', LayoutGrid]].map(([value, Icon]) => <button key={value} className={preferences.layout === value ? 'selected' : ''} onClick={() => setPreferences(previous => ({ ...previous, layout: value }))} aria-label={`${value} view`}><Icon size={16} /></button>)}</div>
      </div>
      <div className={`machineList ${preferences.layout}`}>{items.map(server => <MachineCard key={server.id} server={server} layout={preferences.layout} />)}</div>
    </div>;
  })}{!servers.length && <EmptyState label="No machines match the current filters" />}</>;
}

export function ServicesView({ services }) {
  return <section className="contentCard"><div className="serviceList">{services.map(service => {
    const level = service.status === 'up' ? 'healthy' : service.status === 'down' ? 'critical' : 'missing';
    return <article className="serviceCard" key={service.id}><div className="serviceIdentity"><span className={`statusDot ${level}`} /><div><h3>{service.name}</h3><p>{service.url}</p></div></div><div className="serviceMetric">{level === 'healthy' ? <CheckCircle2 size={15} /> : <WifiOff size={15} />}<span>{service.latency_ms == null ? service.status === 'down' ? 'Down' : 'No measurement' : `${service.latency_ms} ms`}</span></div></article>;
  })}{!services.length && <EmptyState label="No services configured" />}</div></section>;
}

export function HistoryView({ history, range, setRange, resourceView, preferences }) {
  const items = (history?.items || []).filter(item => resourceView === 'services' || (!preferences.hiddenClusters.includes(item.cluster || 'Default') && !preferences.hiddenMachines.includes(item.id)));
  return <section className="contentCard"><div className="historyControls"><div className="segmented"><button className={range === '60d' ? 'selected' : ''} onClick={() => setRange('60d')}>60 days</button><button className={range === '48h' ? 'selected' : ''} onClick={() => setRange('48h')}>48 hours</button></div></div>
    <div className="historySection"><h2>{resourceView === 'services' ? 'Services' : 'Machines'}</h2><div className="historyList">{items.map(item => <HistoryRow key={item.id} item={item} range={range} />)}{!items.length && <EmptyState label="No history available" />}</div></div>
  </section>;
}

function HistoryRow({ item, range }) {
  const hourly = range === '48h';
  const count = hourly ? 48 : 60;
  const buckets = new Map(item.buckets.map(bucket => [bucket.key, bucket]));
  const segments = Array.from({ length: count }, (_, index) => {
    const date = new Date(Date.now() - (count - 1 - index) * (hourly ? 3600000 : 86400000));
    const key = date.toISOString().slice(0, hourly ? 13 : 10);
    return { key, level: buckets.get(key)?.level || 'missing' };
  });
  const measured = segments.filter(segment => segment.level !== 'missing');
  const uptime = measured.length ? `${Math.round(100 * measured.filter(segment => segment.level === 'healthy').length / measured.length)}% uptime` : 'No measurements';
  return <div className="historyRow"><div className="historyIdentity"><strong>{item.name}</strong><span className={`statusDot ${segments.at(-1)?.level || 'missing'}`} /></div><div className="uptimeBar" style={{ '--segments': count }}>{segments.map(segment => <span key={segment.key} className={segment.level} title={`${segment.key}: ${segment.level}`} />)}</div><div className="historyLabels"><span>{hourly ? '48 hours ago' : '60 days ago'}</span><strong>{uptime}</strong><span>Today</span></div></div>;
}
