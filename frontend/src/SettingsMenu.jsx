/** @file SettingsMenu.jsx @description Status-native Filter, Display, Account and Control panels. */
import React, { useEffect, useRef, useState } from 'react';
import { ResourceFilter } from './ResourceFilter.jsx';
import { post } from './api.js';

const TABS = ['Filter', 'Display', 'Account', 'Control'];

export function SettingsMenu({ open, onClose, filterItems, filters, setFilters, setClusterOrder, filterScope, preferences, setPreferences, session, reloadSession, presets, setPresets, seconds, automatic, setAutomatic, control, generatedAt }) {
  const [tab, setTab] = useState('Filter');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const panel = useRef(null);
  const change = (key, value) => setPreferences(previous => ({ ...previous, [key]: value }));

  useEffect(() => {
    if (!open) return;
    const key = event => { if (event.key === 'Escape') onClose(); };
    const outside = event => { if (!panel.current?.contains(event.target) && !event.target.closest('[data-menu-trigger]')) onClose(); };
    document.addEventListener('keydown', key);
    document.addEventListener('pointerdown', outside);
    return () => { document.removeEventListener('keydown', key); document.removeEventListener('pointerdown', outside); };
  }, [open, onClose]);

  async function login(event) {
    event.preventDefault();
    setBusy(true); setError('');
    const form = event.currentTarget;
    try {
      await post('/auth/local', { username: form.elements.username.value, password: form.elements.password.value });
      form.reset(); await reloadSession();
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }

  if (!open) return null;
  return <aside ref={panel} className="settingsMenu" aria-label="Settings">
    <div className="segmented menuTabs" role="tablist" aria-label="Settings sections">
      {TABS.map((name, index) => <button key={name} id={`tab-${name}`} role="tab" aria-selected={tab === name} aria-controls="settings-content" tabIndex={tab === name ? 0 : -1} className={tab === name ? 'selected' : ''} onClick={() => setTab(name)} onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? TABS.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + TABS.length) % TABS.length;
        setTab(TABS[next]); document.getElementById(`tab-${TABS[next]}`).focus();
      }}>{name}</button>)}
    </div>
    <div id="settings-content" className="settingsContent" role="tabpanel" aria-labelledby={`tab-${tab}`}>
      {tab === 'Filter' && <ResourceFilter key={filterScope} items={filterItems} filters={filters} setFilters={setFilters} setClusterOrder={setClusterOrder} scope={filterScope} />}
      {tab === 'Display' && <>
        <label className="settingRow">Sort by<select value={preferences.sort} onChange={event => change('sort', event.target.value)}><option value="config">Configured order</option><option value="name">Name</option><option value="status">Status</option><option value="cpu_usage">CPU</option><option value="memory_usage">Memory</option><option value="disk_usage">Disk</option></select></label>
        <label className="settingRow">Layout<select value={preferences.layout} onChange={event => change('layout', event.target.value)}><option value="list">List</option><option value="grid">Grid</option></select></label>
        <label className="settingRow">Content width<select value={preferences.width} onChange={event => change('width', event.target.value)}><option value="960">Compact</option><option value="1220">Standard</option><option value="1600">Wide</option><option value="100%">Adaptive</option></select></label>
        <label className="settingRow">Maximum cards per row<input type="number" min="1" max="6" value={preferences.columns} onChange={event => { const value = Number(event.target.value); if (value >= 1 && value <= 6) change('columns', value); }} /></label>
      </>}
      {tab === 'Account' && <>
        {session?.user ? <><p>Signed in as <strong>{session.user.name}</strong></p><button className="menuButton" onClick={async () => { try { await post('/auth/logout', {}); await reloadSession(); } catch (failure) { setError(failure.message); } }}>Sign out</button></> : <>
          {session?.shizunet && <a className="menuButton" href="/auth/start">Sign in with Shizunet</a>}
          {session?.pseudo_user && <form onSubmit={login} className="loginForm"><strong>Local account</strong><label>Username<input name="username" autoComplete="username" required maxLength="128" /></label><label>Password<input type="password" name="password" autoComplete="current-password" required maxLength="1024" /></label><button className="menuButton" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button></form>}
          {!session?.shizunet && !session?.pseudo_user && <p className="muted">Authentication is disabled for this instance.</p>}
        </>}
        {error && <p role="alert" className="muted">{error}</p>}
      </>}
      {tab === 'Control' && <>
        <label className="checkRow"><span>Automatic refresh</span><input type="checkbox" checked={automatic} onChange={event => setAutomatic(event.target.checked)} /></label>
        <p className="muted">Edit the three intervals shown in the top bar.</p>
        {presets.map((value, index) => <label className="settingRow" key={index}>Button {index + 1} (seconds)<input type="number" min="1" max="86400" value={value} onChange={event => { const next = Number(event.target.value); if (Number.isInteger(next) && next >= 1 && next <= 86400) setPresets(previous => previous.map((item, i) => i === index ? next : item)); }} /></label>)}
        <p className="muted">Server minimum: {session?.refresh?.minimum_seconds ?? 10}s. Idle collection: {session?.refresh?.idle_seconds ?? 300}s.</p>
        {seconds < (session?.refresh?.minimum_seconds ?? 10) && <p className="controlWarning" role="status">Requested {seconds}s; the server uses at least {session.refresh.minimum_seconds}s.</p>}
        <p className="muted">Last data update: {generatedAt ? new Date(generatedAt).toLocaleString() : 'Waiting for data'}</p>
      </>}
    </div>
  </aside>;
}
