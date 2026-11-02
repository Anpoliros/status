/**
 * @file frontend/src/main.jsx
 * @description Status dashboard navigation, local display settings and authenticated views.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Moon, Monitor, RefreshCcw, Settings2, Sun } from 'lucide-react';
import { readPreference } from './api.js';
import { SettingsMenu } from './SettingsMenu.jsx';
import { EmptyState, HistoryView, MachinesView, ServicesView } from './Views.jsx';
import { useDashboard } from './useDashboard.js';
import './styles.css';

const DEFAULT_DISPLAY = { hiddenClusters: [], hiddenMachines: [], sort: 'config', layout: 'list', width: '1220', columns: 3 };

function App() {
  const [resourceView, setResourceView] = useState('machines');
  const [mode, setMode] = useState('status');
  const [range, setRange] = useState('60d');
  const [menuOpen, setMenuOpen] = useState(false);
  const [preferences, setPreferences] = useState(() => ({ ...DEFAULT_DISPLAY, ...readPreference('display', {}) }));
  const [presets, setPresets] = useState(() => readPreference('refresh-presets', [10, 20, 60]));
  const [selectedPreset, setSelectedPreset] = useState(() => readPreference('refresh-selected', 2));
  const [automatic, setAutomatic] = useState(() => readPreference('automatic', true));
  const [theme, setTheme] = useState(() => localStorage.getItem('status-theme') || 'system');
  const seconds = presets[selectedPreset] || 60;
  const dashboard = useDashboard({ resourceView, mode, range, seconds, automatic });
  const { session, status, history, loading, updating, error } = dashboard;
  const full = Boolean(session?.full_access);
  const closeMenu = useCallback(() => setMenuOpen(false), []);

  useEffect(() => {
    if (session && !localStorage.getItem('status-refresh-presets')) setPresets(session.refresh.presets);
  }, [session]);
  useEffect(() => {
    localStorage.setItem('status-display', JSON.stringify(preferences));
    localStorage.setItem('status-refresh-selected', JSON.stringify(selectedPreset));
    localStorage.setItem('status-automatic', JSON.stringify(automatic));
  }, [preferences, selectedPreset, automatic]);
  const updatePresets = update => setPresets(previous => {
    const next = typeof update === 'function' ? update(previous) : update;
    localStorage.setItem('status-refresh-presets', JSON.stringify(next));
    return next;
  });

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const apply = () => { document.documentElement.dataset.theme = theme === 'system' ? (media.matches ? 'dark' : 'light') : theme; };
    apply(); localStorage.setItem('status-theme', theme);
    media.addEventListener('change', apply);
    return () => media.removeEventListener('change', apply);
  }, [theme]);

  const machines = useMemo(() => {
    const visible = (status?.servers || []).filter(server => !preferences.hiddenClusters.includes(server.cluster || 'Default') && !preferences.hiddenMachines.includes(server.id));
    const priority = { critical: 0, warning: 1, unknown: 2, healthy: 3 };
    if (preferences.sort === 'name') visible.sort((a, b) => a.name.localeCompare(b.name));
    else if (preferences.sort === 'status') visible.sort((a, b) => (priority[a.status] ?? 2) - (priority[b.status] ?? 2));
    else if (preferences.sort !== 'config') visible.sort((a, b) => (b[preferences.sort] ?? -1) - (a[preferences.sort] ?? -1));
    return visible;
  }, [status, preferences]);
  const currentData = dashboard.mode === 'history' ? history : status;
  const loginError = new URLSearchParams(window.location.search).has('login_error');

  return <main className="page" style={{ '--page-width': preferences.width === '100%' ? '100%' : `${preferences.width}px`, '--max-columns': preferences.columns }}>
    <header className="topbar">
      <nav className="navigation" aria-label="Primary navigation">
        <div className="segmented iconSegments"><button data-menu-trigger className={menuOpen ? 'selected' : ''} aria-label="Settings" aria-expanded={menuOpen} onClick={() => setMenuOpen(value => !value)}><Settings2 size={18} /></button></div>
        <div className="segmented"><button disabled={!full} className={dashboard.resourceView === 'machines' ? 'selected' : ''} onClick={() => setResourceView('machines')}>Machines</button><button className={dashboard.resourceView === 'services' ? 'selected' : ''} onClick={() => setResourceView('services')}>Services</button></div>
        <div className="segmented"><button disabled={!full} className={dashboard.mode === 'status' ? 'selected' : ''} onClick={() => setMode('status')}>Status</button><button className={dashboard.mode === 'history' ? 'selected' : ''} onClick={() => setMode('history')}>History</button></div>
      </nav>
      <div className="topActions">
        {dashboard.mode === 'status' && dashboard.resourceView === 'machines' && <div className="segmented">{presets.map((value, index) => <button key={index} className={selectedPreset === index ? 'selected' : ''} onClick={() => setSelectedPreset(index)}>{value}s</button>)}</div>}
        <div className="segmented iconSegments"><button onClick={dashboard.refresh} disabled={updating || !session} aria-label="Refresh status" title="Refresh status"><RefreshCcw size={18} className={updating ? 'refreshing' : ''} /></button></div>
        <ThemeSwitch theme={theme} setTheme={setTheme} />
      </div>
    </header>
    <SettingsMenu open={menuOpen} onClose={closeMenu} machines={status?.servers || []} preferences={preferences} setPreferences={setPreferences} session={session} reloadSession={dashboard.loadSession} presets={presets} setPresets={updatePresets} seconds={seconds} automatic={automatic} setAutomatic={setAutomatic} control={dashboard.control} generatedAt={currentData?.generated_at} />
    {loginError && !session?.user && <div className="notice">Shizunet login could not be completed. You can retry or use the local account in Account.</div>}
    {error && <div className="notice" role="alert">{error}{currentData && ' — showing the last available data.'}</div>}
    {dashboard.control?.clamped && <div className="notice" role="status">Requested {seconds}s; the server minimum is {dashboard.control.minimum_seconds}s.</div>}
    {updating && <div className="notice" role="status">Updating data… Existing measurements remain visible.</div>}
    {(loading && !currentData) ? <div className="loadingState" role="status"><span className="loadingPulse" />Loading {dashboard.mode === 'history' ? 'history' : 'current status'}…</div> : !currentData ? <EmptyState label={error ? 'Unable to load data. Use Refresh to retry.' : 'Waiting for the first collection'} /> : <>
      {dashboard.mode === 'status' && dashboard.resourceView === 'machines' && <MachinesView servers={machines} preferences={preferences} setPreferences={setPreferences} />}
      {dashboard.mode === 'status' && dashboard.resourceView === 'services' && <ServicesView services={status.services} />}
      {dashboard.mode === 'history' && <HistoryView history={history} range={range} setRange={setRange} resourceView={dashboard.resourceView} preferences={preferences} />}
    </>}
  </main>;
}

function ThemeSwitch({ theme, setTheme }) {
  return <div className="segmented iconSegments" role="group" aria-label="Theme">{[['light', Sun, 'Light'], ['dark', Moon, 'Dark'], ['system', Monitor, 'Automatic']].map(([value, Icon, label]) => <button key={value} className={theme === value ? 'selected' : ''} aria-label={label} aria-pressed={theme === value} onClick={() => setTheme(value)}><Icon size={18} /></button>)}</div>;
}

createRoot(document.getElementById('root')).render(<App />);
