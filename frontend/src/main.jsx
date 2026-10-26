/**
 * @file frontend/src/main.jsx
 * @description Status dashboard with independent machine, service, and history views.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, CheckCircle2, ChevronDown, ChevronRight, CircleAlert, Filter, LayoutGrid, List, Moon, RefreshCcw, Server, Settings2, Sun, WifiOff } from 'lucide-react';
import './styles.css';

const API_BASE = import.meta.env.VITE_STATUS_API || '';
const MACHINE_REFRESH = [10, 20, 60];
const THEME_ORDER = ['system', 'light', 'dark'];

function App() {
  const [resourceView, setResourceView] = useState('machines');
  const [mode, setMode] = useState('status');
  const [status, setStatus] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshSeconds, setRefreshSeconds] = useState(60);
  const [layout, setLayout] = useState('list');
  const [historyRange, setHistoryRange] = useState('60d');
  const [theme, setTheme] = useState(() => localStorage.getItem('status-theme') || 'system');
  const [filterOpen, setFilterOpen] = useState(false);
  const [selectedClusters, setSelectedClusters] = useState(null);
  const scope = mode === 'status' ? (resourceView === 'services' ? 'services' : 'servers') : '';

  async function loadStatus({ probe = scope } = {}) {
    try {
      const query = probe ? `?probe=${probe}` : '';
      const response = await fetch(`${API_BASE}/status${query}`, { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setStatus(await response.json());
      setError('');
    } catch (apiError) {
      try {
        const response = await fetch('/status.json', { cache: 'no-store' });
        if (!response.ok) throw apiError;
        setStatus(await response.json());
        setError('API unavailable, showing generated status.json');
      } catch {
        setError(apiError.message || 'Unable to load status');
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    loadStatus();
    const interval = mode === 'history' ? 60000 : resourceView === 'services' ? 600000 : refreshSeconds * 1000;
    const timer = window.setInterval(() => loadStatus(), interval);
    return () => window.clearInterval(timer);
  }, [mode, resourceView, refreshSeconds]);

  useEffect(() => {
    const applyTheme = () => {
      const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      document.documentElement.dataset.theme = theme === 'system' ? (dark ? 'dark' : 'light') : theme;
    };
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    applyTheme();
    localStorage.setItem('status-theme', theme);
    media.addEventListener('change', applyTheme);
    return () => media.removeEventListener('change', applyTheme);
  }, [theme]);

  const clusters = useMemo(() => unique((status?.servers || []).map((server) => server.cluster || 'Default')), [status]);
  const visibleServers = (status?.servers || []).filter((server) => !selectedClusters || selectedClusters.has(server.cluster || 'Default'));

  return (
    <main className="page">
      <header className="topbar"><nav className="navigation" aria-label="Primary navigation"><button className="navIcon" aria-label="Filter machines" onClick={() => setFilterOpen((open) => !open)}><Filter size={18} /></button><div className="segmented"><button className={resourceView === 'machines' ? 'selected' : ''} onClick={() => setResourceView('machines')}>Machines</button><button className={resourceView === 'services' ? 'selected' : ''} onClick={() => setResourceView('services')}>Services</button></div><div className="segmented"><button className={mode === 'status' ? 'selected' : ''} onClick={() => setMode('status')}>Status</button><button className={mode === 'history' ? 'selected' : ''} onClick={() => setMode('history')}>History</button></div></nav><div className="topActions">{mode === 'status' && resourceView === 'machines' && <div className="segmented">{MACHINE_REFRESH.map((seconds) => <button key={seconds} className={refreshSeconds === seconds ? 'selected' : ''} onClick={() => setRefreshSeconds(seconds)}>{seconds}s</button>)}</div>}<button className="iconButton" onClick={() => loadStatus()} aria-label="Refresh status" title="Refresh status"><RefreshCcw size={18} /></button><button className="iconButton" onClick={() => setTheme(nextTheme(theme))} aria-label={`Theme: ${theme}`} title={`Theme: ${theme}`}>{themeIcon(theme)}</button></div></header>
      {error && <div className="notice">{error}</div>}{loading && <div className="notice">Loading current status...</div>}
      {mode === 'status' && resourceView === 'machines' && <MachinesView servers={visibleServers} clusters={clusters} selectedClusters={selectedClusters} setSelectedClusters={setSelectedClusters} filterOpen={filterOpen} setFilterOpen={setFilterOpen} layout={layout} setLayout={setLayout} />}
      {mode === 'status' && resourceView === 'services' && <ServicesView services={status?.services || []} />}
      {mode === 'history' && <HistoryView history={status?.history} range={historyRange} setRange={setHistoryRange} resourceView={resourceView} />}
    </main>
  );
}

function MachinesView({ servers, clusters, selectedClusters, setSelectedClusters, filterOpen, setFilterOpen, layout, setLayout }) {
  return <>{filterOpen && <FilterPanel clusters={clusters} selectedClusters={selectedClusters} setSelectedClusters={setSelectedClusters} />}{clusters.map((cluster) => { const items = servers.filter((server) => (server.cluster || 'Default') === cluster); if (!items.length) return null; return <div className="clusterBlock" key={cluster}><div className="clusterHeader"><div><h2>{cluster}</h2><span>{items.length} machines</span></div><div className="segmented"><button className={layout === 'list' ? 'selected' : ''} onClick={() => setLayout('list')} aria-label="List view"><List size={16} /></button><button className={layout === 'grid' ? 'selected' : ''} onClick={() => setLayout('grid')} aria-label="Grid view"><LayoutGrid size={16} /></button></div></div><div className={`machineList ${layout}`}>{items.map((server) => <MachineCard key={server.id || server.ip} server={server} />)}</div></div>; })}{!servers.length && <EmptyState label="No machines selected" />}</>;
}

function ServicesView({ services }) { return <section className="contentCard"><div className="serviceList">{services.map((service) => <ServiceCard key={service.id || service.url} service={service} />)}{!services.length && <EmptyState label="No services configured" />}</div></section>; }
function HistoryView({ history, range, setRange, resourceView }) { const services = unique((history?.services || []).map((item) => item.url)); const servers = unique((history?.servers || []).map((item) => item.ip)); const hours = range === '60d' ? 60 * 24 : 48; const rows = resourceView === 'services' ? services.map((url) => <HistoryRow key={url} url={url} items={(history?.services || []).filter((item) => item.url === url)} kind="service" hours={hours} />) : servers.map((ip) => { const item = (history?.servers || []).find((entry) => entry.ip === ip); return <HistoryRow key={ip} url={item?.name || ip} items={(history?.servers || []).filter((entry) => entry.ip === ip)} kind="server" hours={hours} />; }); return <section className="contentCard"><div className="historyControls"><div className="segmented"><button className={range === '60d' ? 'selected' : ''} onClick={() => setRange('60d')}>60 days</button><button className={range === '48h' ? 'selected' : ''} onClick={() => setRange('48h')}>48 hours</button></div></div><div className="historySection"><h2>{resourceView === 'services' ? 'Services' : 'Machines'}</h2><div className="historyList">{rows}{!rows.length && <EmptyState label={`No ${resourceView === 'services' ? 'service' : 'machine'} history yet`} />}</div></div></section>; }
function FilterPanel({ clusters, selectedClusters, setSelectedClusters }) { const active = selectedClusters || new Set(clusters); const toggle = (cluster) => { const next = new Set(active); if (next.has(cluster)) next.delete(cluster); else next.add(cluster); setSelectedClusters(next.size === clusters.length ? null : next); }; return <aside className="filterPanel"><div className="filterHeader"><strong>Display</strong><Settings2 size={16} /></div>{clusters.map((cluster) => <label className="checkRow" key={cluster}><span>{cluster}</span><input type="checkbox" checked={active.has(cluster)} onChange={() => toggle(cluster)} /></label>)}</aside>; }
function MachineCard({ server }) { const [collapsed, setCollapsed] = useState(true); const level = server.status || 'critical'; return <article className={`machineCard ${collapsed ? 'collapsed' : ''}`}><button className="machineHeader" onClick={() => setCollapsed((value) => !value)} aria-expanded={!collapsed}><h3>{server.name}</h3><span className={`statusDot ${level}`} /><span className="machineToggle">{collapsed ? <ChevronRight size={17} /> : <ChevronDown size={17} />}</span></button>{collapsed ? <div className="machineNetwork">NET <span>IN {formatRate(server.network_in)}</span><span>OUT {formatRate(server.network_out)}</span></div> : <div className="metricGrid"><MetricRing label="CPU" value={server.cpu_usage} /><MetricRing label="RAM" value={server.memory_usage} /><MetricRing label="DISK" value={server.disk_usage} /><div className="networkMetric"><strong>NET</strong><span>IN {formatRate(server.network_in)}</span><span>OUT {formatRate(server.network_out)}</span></div></div>}</article>; }
function ServiceCard({ service }) { const level = service.status === 'up' ? 'healthy' : 'critical'; return <article className="serviceCard"><div className="serviceIdentity"><span className={`statusDot ${level}`} /><div><h3>{service.name}</h3><p>{service.url}</p></div></div><div className="serviceMetric">{level === 'healthy' ? <CheckCircle2 size={15} /> : <WifiOff size={15} />}<span>{service.latency_ms == null ? 'Down' : `${service.latency_ms} ms`}</span></div></article>; }
function MetricRing({ label, value }) { const percent = value == null ? 0 : Math.max(0, Math.min(100, value)); return <div className="metricRing"><div className="ring" style={{ '--percent': `${percent * 3.6}deg` }}><span>{value == null ? '-' : `${value.toFixed(1)}%`}</span></div><strong>{label}</strong></div>; }
function HistoryRow({ url, items, kind, hours }) { const isHours = hours === 48; const count = isHours ? 48 : 60; const days = Array.from({ length: count }, (_, index) => { const date = new Date(Date.now() - (count - 1 - index) * (isHours ? 60 * 60 * 1000 : 24 * 60 * 60 * 1000)); const key = isHours ? date.toISOString().slice(0, 13) : date.toISOString().slice(0, 10); const checks = items.filter((item) => (isHours ? item.timestamp?.slice(0, 13) : item.timestamp?.slice(0, 10)) === key); if (!checks.length) return { key, level: 'missing' }; if (kind === 'service') return { key, level: checks.some((item) => item.status === 'down') ? 'critical' : 'healthy' }; const worst = checks.reduce((level, item) => levelRank(metricLevel(item)) > levelRank(level) ? metricLevel(item) : level, 'healthy'); return { key, level: worst }; }); const uptime = Math.round((days.filter((item) => item.level === 'healthy').length / Math.max(1, days.filter((item) => item.level !== 'missing').length)) * 100); return <div className="historyRow"><div className="historyIdentity"><strong>{url.replace(/^https?:\/\//, '')}</strong><span className={`statusDot ${days.at(-1)?.level || 'missing'}`} /></div><div className="uptimeBar" style={{ '--segments': count }}>{days.map((item) => <span key={item.key} className={item.level} title={`${item.key}: ${item.level}`} />)}</div><div className="historyLabels"><span>{isHours ? '48 hours ago' : '60 days ago'}</span><strong>{uptime}% uptime</strong><span>Today</span></div></div>; }
function metricLevel(item) { const values = [item.cpu_usage, item.memory_usage, item.disk_usage].filter((value) => value != null); if (!values.length) return 'critical'; if (values.some((value) => value >= 95)) return 'critical'; if (values.some((value) => value >= 80)) return 'warning'; return 'healthy'; }
function levelRank(level) { return { healthy: 0, warning: 1, critical: 2 }[level] ?? 3; }
function EmptyState({ label }) { return <div className="empty">{label}</div>; }
function unique(values) { return [...new Set(values)]; }
function formatDate(value) { return value ? new Date(value).toLocaleString() : 'No data yet'; }
function formatRate(value) { return value == null ? '-' : `${formatBytes(value)}/s`; }
function formatBytes(value) { if (value == null) return '-'; const units = ['B', 'KB', 'MB', 'GB', 'TB']; let size = value; let unit = 0; while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; } return `${size.toFixed(unit ? 1 : 0)} ${units[unit]}`; }
function nextTheme(theme) { return THEME_ORDER[(THEME_ORDER.indexOf(theme) + 1) % THEME_ORDER.length]; }
function themeIcon(theme) { return theme === 'light' ? <Sun size={18} /> : theme === 'dark' ? <Moon size={18} /> : <Settings2 size={18} />; }
function summaryFor(status) { return status === 'healthy' ? 'All monitored systems are healthy.' : status === 'warning' ? 'Some machines are under heavy load.' : status === 'critical' ? 'One or more systems need immediate attention.' : 'Waiting for the first monitoring cycle.'; }
function StatusIcon({ status }) { return status === 'healthy' ? <CheckCircle2 size={24} /> : status === 'warning' ? <CircleAlert size={24} /> : status === 'critical' ? <WifiOff size={24} /> : <Server size={24} />; }

createRoot(document.getElementById('root')).render(<App />);
