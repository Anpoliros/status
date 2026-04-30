import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, CheckCircle2, ChevronDown, ChevronRight, Clock3, Cpu, HardDrive, Monitor, Moon, RefreshCcw, Server, Sun, WifiOff } from 'lucide-react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import './styles.css';

const API_BASE = import.meta.env.VITE_STATUS_API || '';
const THEME_ORDER = ['system', 'light', 'dark'];

function App() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [theme, setTheme] = useState(() => window.localStorage.getItem('status-theme') || 'system');

  async function loadStatus() {
    try {
      const response = await fetch(`${API_BASE}/status`, { cache: 'no-store' });
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
    loadStatus();
    const timer = window.setInterval(loadStatus, 30000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const applyTheme = () => {
      const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      const resolved = theme === 'system' ? (systemDark ? 'dark' : 'light') : theme;
      document.documentElement.dataset.theme = resolved;
      document.documentElement.dataset.themePreference = theme;
    };
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    applyTheme();
    window.localStorage.setItem('status-theme', theme);
    media.addEventListener('change', applyTheme);
    return () => media.removeEventListener('change', applyTheme);
  }, [theme]);

  const serviceChart = useMemo(() => buildServiceChart(status?.history?.services || []), [status]);
  const serverChart = useMemo(() => buildServerChart(status?.history?.servers || []), [status]);
  const generatedAt = status?.generated_at ? new Date(status.generated_at).toLocaleString() : 'No data yet';

  return (
    <main className="page">
      <header className="topbar">
        <div>
          <p className="eyebrow">Internal Status</p>
          <h1>{titleFor(status?.overall_status)}</h1>
        </div>
        <div className="topActions">
          <button className="iconButton" onClick={() => setTheme(nextTheme(theme))} aria-label={`Theme: ${theme}`} title={`Theme: ${theme}`}>
            {themeIcon(theme)}
          </button>
          <button className="iconButton" onClick={loadStatus} aria-label="Refresh status" title="Refresh status">
            <RefreshCcw size={18} />
          </button>
        </div>
      </header>

      <section className={`banner ${status?.overall_status || 'unknown'}`}>
        <div className="bannerIcon">{bannerIcon(status?.overall_status)}</div>
        <div>
          <strong>{summaryFor(status?.overall_status)}</strong>
          <span>Updated {generatedAt}</span>
        </div>
      </section>

      {error && <div className="notice">{error}</div>}
      {loading && <div className="notice">Loading current status...</div>}

      <section className="grid two">
        <Panel title="Services" icon={<Activity size={18} />}>
          <div className="list">
            {(status?.services || []).map((service) => (
              <ServiceRow key={service.id || service.url} service={service} />
            ))}
            {!status?.services?.length && <EmptyState label="No services configured" />}
          </div>
        </Panel>

        <Panel title="Servers" icon={<Server size={18} />}>
          <div className="list">
            {(status?.servers || []).map((server) => (
              <ServerRow key={server.id || server.ip} server={server} />
            ))}
            {!status?.servers?.length && <EmptyState label="No servers configured" />}
          </div>
        </Panel>
      </section>

      <section className="grid two charts">
        <Panel title="Service Latency, 24h" icon={<Clock3 size={18} />}>
          <ChartFrame>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={serviceChart}>
                <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 3" />
                <XAxis dataKey="time" minTickGap={28} stroke="var(--muted)" />
                <YAxis stroke="var(--muted)" width={42} />
                <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid var(--border)', background: 'var(--panel)', color: 'var(--text)' }} />
                <Line type="monotone" dataKey="latency" name="Latency ms" stroke="var(--accent)" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </ChartFrame>
        </Panel>

        <Panel title="Server Load, 24h" icon={<Cpu size={18} />}>
          <ChartFrame>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={serverChart}>
                <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="3 3" />
                <XAxis dataKey="time" minTickGap={28} stroke="var(--muted)" />
                <YAxis stroke="var(--muted)" width={42} domain={[0, 100]} />
                <Tooltip contentStyle={{ borderRadius: 8, border: '1px solid var(--border)', background: 'var(--panel)', color: 'var(--text)' }} />
                <Area type="monotone" dataKey="cpu" name="CPU %" stroke="var(--text)" fill="var(--chart-cpu-fill)" strokeWidth={2} dot={false} isAnimationActive={false} />
                <Area type="monotone" dataKey="memory" name="Memory %" stroke="var(--accent)" fill="var(--chart-memory-fill)" strokeWidth={2} dot={false} isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </ChartFrame>
        </Panel>
      </section>
    </main>
  );
}

function Panel({ title, icon, children }) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <div className="panelTitle">{icon}<h2>{title}</h2></div>
      </div>
      {children}
    </section>
  );
}

function ServiceRow({ service }) {
  const up = service.status === 'up';
  return (
    <article className="row">
      <div className="rowMain">
        <span className={`statusDot ${up ? 'up' : 'down'}`} />
        <div>
          <h3>{service.name}</h3>
          <p>{service.url}</p>
        </div>
      </div>
      <div className="metricPill">
        {up ? <CheckCircle2 size={16} /> : <WifiOff size={16} />}
        <span>{up ? 'Up' : 'Down'}</span>
        <strong>{service.latency_ms == null ? '-' : `${service.latency_ms} ms`}</strong>
      </div>
    </article>
  );
}

function ServerRow({ server }) {
  const [collapsed, setCollapsed] = useState(true);
  const healthy = serverHealthy(server);

  return (
    <article className={`serverRow ${collapsed ? 'collapsed' : ''}`}>
      <button
        className="serverTitle serverToggle"
        onClick={() => setCollapsed((value) => !value)}
        aria-expanded={!collapsed}
        title={collapsed ? 'Expand server details' : 'Collapse server details'}
      >
        <div className="rowMain">
          <span className={`statusDot ${healthy ? 'up' : 'down'}`} />
          <div>
            <h3>{server.name}</h3>
          </div>
        </div>
        <div className="serverSummary">
          <span className={`healthPill ${healthy ? 'up' : 'down'}`}>
            {healthy ? <CheckCircle2 size={15} /> : <WifiOff size={15} />}
            {healthy ? 'Healthy' : 'No data'}
          </span>
          {collapsed ? <ChevronRight size={18} /> : <ChevronDown size={18} />}
        </div>
      </button>

      {collapsed ? (
        <div className="collapsedSummary">
          <span>Network {formatBytesPerMinute(server.network_in)} in / {formatBytesPerMinute(server.network_out)} out</span>
        </div>
      ) : (
        <>
          <MetricBar label="CPU" value={server.cpu_usage} icon={<Cpu size={15} />} />
          <MetricBar label="Memory" value={server.memory_usage} icon={<Activity size={15} />} />
          <MetricBar label="Disk" value={server.disk_usage} icon={<HardDrive size={15} />} />
          <div className="network">
            <span>Network, last minute</span>
            <strong>{formatBytesPerMinute(server.network_in)} in / {formatBytesPerMinute(server.network_out)} out</strong>
          </div>
        </>
      )}
    </article>
  );
}

function MetricBar({ label, value, icon }) {
  const normalized = value == null ? 0 : Math.max(0, Math.min(100, value));
  return (
    <div className="barRow">
      <div className="barLabel">{icon}<span>{label}</span><strong>{value == null ? '-' : `${value.toFixed(1)}%`}</strong></div>
      <div className="barTrack"><span style={{ width: `${normalized}%` }} /></div>
    </div>
  );
}

function ChartFrame({ children }) {
  return <div className="chartFrame">{children}</div>;
}

function EmptyState({ label }) {
  return <div className="empty">{label}</div>;
}

function buildServiceChart(items) {
  return items.slice(-180).map((item) => ({
    time: formatTime(item.timestamp),
    latency: item.latency_ms,
  }));
}

function buildServerChart(items) {
  const grouped = new Map();
  for (const item of items) {
    if (!item.timestamp) continue;
    const bucket = item.timestamp.slice(0, 16);
    const row = grouped.get(bucket) || { timestamp: item.timestamp, cpuTotal: 0, cpuCount: 0, memoryTotal: 0, memoryCount: 0 };
    if (item.cpu_usage != null) {
      row.cpuTotal += item.cpu_usage;
      row.cpuCount += 1;
    }
    if (item.memory_usage != null) {
      row.memoryTotal += item.memory_usage;
      row.memoryCount += 1;
    }
    grouped.set(bucket, row);
  }

  return Array.from(grouped.values()).slice(-240).map((item) => ({
    time: formatTime(item.timestamp),
    cpu: item.cpuCount ? rounded(item.cpuTotal / item.cpuCount) : null,
    memory: item.memoryCount ? rounded(item.memoryTotal / item.memoryCount) : null,
  }));
}

function rounded(value) {
  return value == null ? null : Number(value.toFixed(1));
}

function formatTime(value) {
  if (!value) return '';
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatBytes(value) {
  if (value == null) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatBytesPerMinute(value) {
  if (value == null) return '-';
  return `${formatBytes(value)}/min`;
}

function serverHealthy(server) {
  return [server.cpu_usage, server.memory_usage, server.disk_usage].some((value) => value != null);
}

function nextTheme(theme) {
  const index = THEME_ORDER.indexOf(theme);
  return THEME_ORDER[(index + 1) % THEME_ORDER.length];
}

function themeIcon(theme) {
  if (theme === 'light') return <Sun size={18} />;
  if (theme === 'dark') return <Moon size={18} />;
  return <Monitor size={18} />;
}

function titleFor(status) {
  if (status === 'operational') return 'All systems operational';
  if (status === 'degraded') return 'Some systems need attention';
  return 'Status is initializing';
}

function summaryFor(status) {
  if (status === 'operational') return 'All monitored services are healthy.';
  if (status === 'degraded') return 'At least one monitored service is currently down.';
  return 'Waiting for the first monitoring cycle.';
}

function bannerIcon(status) {
  if (status === 'operational') return <CheckCircle2 size={24} />;
  if (status === 'degraded') return <WifiOff size={24} />;
  return <Clock3 size={24} />;
}

createRoot(document.getElementById('root')).render(<App />);
