/**
 * @file frontend/src/main.jsx
 * @description Status dashboard with independent machine, service, and history views.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, CalendarDays, CheckCircle2, ChevronDown, ChevronRight, CircleAlert, Filter, LayoutGrid, List, Moon, RefreshCcw, Server, Settings2, Sun, WifiOff } from 'lucide-react';
import './styles.css';

const API_BASE = import.meta.env.VITE_STATUS_API || '';
const MACHINE_REFRESH = [10, 20, 60];
const THEME_ORDER = ['system', 'light', 'dark'];

function App() {
  const [page, setPage] = useState('machines');
  const [status, setStatus] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshSeconds, setRefreshSeconds] = useState(60);
  const [layout, setLayout] = useState('list');
  const [theme, setTheme] = useState(() => localStorage.getItem('status-theme') || 'system');
  const [filterOpen, setFilterOpen] = useState(false);
  const [selectedClusters, setSelectedClusters] = useState(null);
  const scope = page === 'services' ? 'services' : page === 'machines' ? 'servers' : '';

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
    const interval = page === 'history' ? 60000 : page === 'services' ? 600000 : refreshSeconds * 1000;
    const timer = window.setInterval(() => loadStatus(), interval);
    return () => window.clearInterval(timer);
  }, [page, refreshSeconds]);

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
      <header className="topbar"><div><p className="eyebrow">Internal Status</p><h1>{page === 'history' ? 'History' : page === 'services' ? 'Services' : 'Machines'}</h1></div><div className="topActions"><button className="iconButton" onClick={() => setTheme(nextTheme(theme))} aria-label={`Theme: ${theme}`} title={`Theme: ${theme}`}>{themeIcon(theme)}</button><button className="iconButton" onClick={() => loadStatus()} aria-label="Refresh status" title="Refresh status"><RefreshCcw size={18} /></button></div></header>
      <nav className="navigation" aria-label="Primary navigation"><button className="navIcon" aria-label="Dashboard"><Activity size={18} /></button><div className="segmented"><button className={page === 'machines' ? 'selected' : ''} onClick={() => setPage('machines')}>Machines</button><button className={page === 'services' ? 'selected' : ''} onClick={() => setPage('services')}>Services</button></div><div className="segmented"><button className={page !== 'history' ? 'selected' : ''} onClick={() => setPage('machines')}>Status</button><button className={page === 'history' ? 'selected' : ''} onClick={() => setPage('history')}>History</button></div></nav>
      <section className={`banner ${status?.overall_status || 'unknown'}`}><StatusIcon status={status?.overall_status} /><div><strong>{summaryFor(status?.overall_status)}</strong><span>Updated {formatDate(status?.generated_at)}</span></div></section>
      {error && <div className="notice">{error}</div>}{loading && <div className="notice">Loading current status...</div>}
      {page === 'machines' && <MachinesView servers={visibleServers} clusters={clusters} selectedClusters={selectedClusters} setSelectedClusters={setSelectedClusters} filterOpen={filterOpen} setFilterOpen={setFilterOpen} refreshSeconds={refreshSeconds} setRefreshSeconds={setRefreshSeconds} layout={layout} setLayout={setLayout} />}
      {page === 'services' && <ServicesView services={status?.services || []} />}
      {page === 'history' && <HistoryView history={status?.history} />}
    </main>
  );
}

function MachinesView({ servers, clusters, selectedClusters, setSelectedClusters, filterOpen, setFilterOpen, refreshSeconds, setRefreshSeconds, layout, setLayout }) {
  return <><ViewToolbar><div className="toolbarGroup"><span className="toolbarLabel">Refresh</span><div className="segmented">{MACHINE_REFRESH.map((seconds) => <button key={seconds} className={refreshSeconds === seconds ? 'selected' : ''} onClick={() => setRefreshSeconds(seconds)}>{seconds}s</button>)}</div></div><div className="toolbarGroup"><button className="iconButton small" onClick={() => setFilterOpen((open) => !open)} aria-expanded={filterOpen} title="Filter machines"><Filter size={16} /></button><div className="segmented"><button className={layout === 'list' ? 'selected' : ''} onClick={() => setLayout('list')} aria-label="List view"><List size={16} /></button><button className={layout === 'grid' ? 'selected' : ''} onClick={() => setLayout('grid')} aria-label="Grid view"><LayoutGrid size={16} /></button></div></div></ViewToolbar>{filterOpen && <FilterPanel clusters={clusters} selectedClusters={selectedClusters} setSelectedClusters={setSelectedClusters} />}{clusters.map((cluster) => { const items = servers.filter((server) => (server.cluster || 'Default') === cluster); if (!items.length) return null; return <section className="cluster" key={cluster}><div className="clusterHeader"><h2>{cluster}</h2><span>{items.length} machines</span></div><div className={`machineList ${layout}`}>{items.map((server) => <MachineCard key={server.id || server.ip} server={server} />)}</div></section>; })}{!servers.length && <EmptyState label="No machines selected" />}</>;
}

function ServicesView({ services }) { return <><ViewToolbar><span className="toolbarLabel">Automatic refresh every 10 minutes</span></ViewToolbar><section className="contentCard"><div className="serviceList">{services.map((service) => <ServiceCard key={service.id || service.url} service={service} />)}{!services.length && <EmptyState label="No services configured" />}</div></section></>; }
function HistoryView({ history }) { const services = unique((history?.services || []).map((item) => item.url)); return <><ViewToolbar><span className="toolbarLabel"><CalendarDays size={16} /> Last 60 days</span></ViewToolbar><section className="contentCard"><div className="historyList">{services.map((url) => <HistoryRow key={url} url={url} items={(history?.services || []).filter((item) => item.url === url)} />)}{!services.length && <EmptyState label="No history yet" />}</div></section></>; }
function ViewToolbar({ children }) { return <div className="viewToolbar">{children}</div>; }
function FilterPanel({ clusters, selectedClusters, setSelectedClusters }) { const active = selectedClusters || new Set(clusters); const toggle = (cluster) => { const next = new Set(active); if (next.has(cluster)) next.delete(cluster); else next.add(cluster); setSelectedClusters(next.size === clusters.length ? null : next); }; return <aside className="filterPanel"><div className="filterHeader"><strong>Display</strong><Settings2 size={16} /></div>{clusters.map((cluster) => <label className="checkRow" key={cluster}><span>{cluster}</span><input type="checkbox" checked={active.has(cluster)} onChange={() => toggle(cluster)} /></label>)}</aside>; }
function MachineCard({ server }) { const [collapsed, setCollapsed] = useState(true); const level = server.status || 'critical'; return <article className={`machineCard ${collapsed ? 'collapsed' : ''}`}><button className="machineHeader" onClick={() => setCollapsed((value) => !value)} aria-expanded={!collapsed}><h3>{server.name}</h3><span className={`statusDot ${level}`} /><span className="machineToggle">{collapsed ? <ChevronRight size={17} /> : <ChevronDown size={17} />}</span></button>{collapsed ? <div className="machineNetwork">NET <span>IN {formatRate(server.network_in)}</span><span>OUT {formatRate(server.network_out)}</span></div> : <div className="metricGrid"><MetricRing label="CPU" value={server.cpu_usage} /><MetricRing label="RAM" value={server.memory_usage} /><MetricRing label="DISK" value={server.disk_usage} /><div className="networkMetric"><strong>NET</strong><span>IN {formatRate(server.network_in)}</span><span>OUT {formatRate(server.network_out)}</span></div></div>}</article>; }
function ServiceCard({ service }) { const level = service.status === 'up' ? 'healthy' : 'critical'; return <article className="serviceCard"><div className="serviceIdentity"><span className={`statusDot ${level}`} /><div><h3>{service.name}</h3><p>{service.url}</p></div></div><div className="serviceMetric">{level === 'healthy' ? <CheckCircle2 size={15} /> : <WifiOff size={15} />}<span>{service.latency_ms == null ? 'Down' : `${service.latency_ms} ms`}</span></div></article>; }
function MetricRing({ label, value }) { const percent = value == null ? 0 : Math.max(0, Math.min(100, value)); return <div className="metricRing"><div className="ring" style={{ '--percent': `${percent * 3.6}deg` }}><span>{value == null ? '-' : `${value.toFixed(1)}%`}</span></div><strong>{label}</strong></div>; }
function HistoryRow({ url, items }) { const days = Array.from({ length: 60 }, (_, index) => { const date = new Date(); date.setHours(0, 0, 0, 0); date.setDate(date.getDate() - (59 - index)); const day = date.toISOString().slice(0, 10); const checks = items.filter((item) => item.timestamp?.slice(0, 10) === day); if (!checks.length) return { day, level: 'missing' }; return { day, level: checks.some((item) => item.status === 'down') ? 'critical' : 'healthy' }; }); const uptime = Math.round((days.filter((item) => item.level === 'healthy').length / Math.max(1, days.filter((item) => item.level !== 'missing').length)) * 100); return <div className="historyRow"><div className="historyIdentity"><strong>{url.replace(/^https?:\/\//, '')}</strong><span className="statusDot healthy" /></div><div className="uptimeBar">{days.map((item) => <span key={item.day} className={item.level} title={`${item.day}: ${item.level}`} />)}</div><div className="historyLabels"><span>60 days ago</span><strong>{uptime}% uptime</strong><span>Today</span></div></div>; }
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
