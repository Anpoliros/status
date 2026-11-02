/** @file useDashboard.js @description Session-aware snapshot polling and expiring page leases. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { post, request } from './api.js';

export function useDashboard({ resourceView, mode, range, seconds, automatic }) {
  const [session, setSession] = useState(null);
  const [status, setStatus] = useState(null);
  const [history, setHistory] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [control, setControl] = useState(null);
  const page = useRef(window.crypto.randomUUID());
  const requestId = useRef(0);
  const pendingUntil = useRef(0);
  const pendingVersion = useRef(0);
  const pendingScope = useRef('servers');
  const reading = useRef('');
  const retryUntil = useRef(0);
  const loadSession = useCallback(async () => {
    try {
      const next = await request('/api/session');
      setSession(next);
      setError('');
      if (!next.full_access) setStatus(null);
    } catch (failure) {
      setError(failure.message);
      setSession({ full_access: false, refresh: { minimum_seconds: 10, presets: [10, 20, 60] } });
    }
  }, []);

  useEffect(() => { loadSession(); }, [loadSession]);
  const full = Boolean(session?.full_access);
  useEffect(() => {
    if (!full) return;
    let disposed = false;
    request('/status').then(payload => { if (!disposed) setStatus(payload); }).catch(() => {});
    return () => { disposed = true; };
  }, [full]);
  const effectiveResource = full ? resourceView : 'services';
  const effectiveMode = full ? mode : 'history';
  const path = effectiveMode === 'history'
    ? `/history/${effectiveResource === 'machines' ? 'servers' : 'services'}?range=${range}` : '/status';
  const latestPath = useRef(path);
  latestPath.current = path;

  const load = useCallback(async () => {
    if (Date.now() < retryUntil.current) return;
    if (reading.current === path) return;
    reading.current = path;
    const id = ++requestId.current;
    const currentPath = path;
    try {
      const payload = await request(currentPath);
      if (id !== requestId.current || currentPath !== latestPath.current) return;
      if (currentPath.startsWith('/history/')) setHistory(payload);
      else setStatus(payload);
      setError('');
      if (pendingUntil.current && ((payload.collection_versions?.[pendingScope.current] ?? 0) > pendingVersion.current || Date.now() >= pendingUntil.current)) {
        pendingUntil.current = 0;
        setUpdating(false);
      }
    } catch (failure) {
      if (id !== requestId.current || currentPath !== latestPath.current) return;
      retryUntil.current = Date.now() + Math.max(failure.retryAfter * 1000, 3000);
      setError(failure.message);
      if (failure.status === 401) { setStatus(null); setHistory(null); loadSession(); }
    } finally {
      if (reading.current === currentPath) reading.current = '';
      if (id === requestId.current && currentPath === latestPath.current) setLoading(false);
    }
  }, [path, loadSession]);

  useEffect(() => {
    if (!session) return;
    setLoading(true);
    setHistory(null);
    pendingUntil.current = 0;
    setUpdating(false);
    load();
    const interval = effectiveMode === 'history' ? 60000 : effectiveResource === 'services' ? 600000 : seconds * 1000;
    let nextRead = Date.now() + interval;
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      const now = Date.now();
      if (pendingUntil.current || (automatic && now >= nextRead)) {
        load();
        nextRead = now + interval;
      }
    }, 1000);
    const visible = () => { if (!document.hidden) load(); };
    document.addEventListener('visibilitychange', visible);
    return () => { window.clearInterval(timer); document.removeEventListener('visibilitychange', visible); requestId.current += 1; };
  }, [session, load, effectiveMode, effectiveResource, seconds, automatic]);

  // Heartbeat lifetime is independent of the requested collection interval.
  useEffect(() => {
    if (!full || !automatic) return;
    let disposed = false;
    const send = async (action) => {
      try {
        const result = await post('/api/control', { page: page.current, action, seconds });
        if (!disposed) setControl(result);
      } catch (failure) { if (!disposed) setError(failure.message); }
    };
    send(document.hidden ? 'release' : 'connect');
    const timer = window.setInterval(() => { if (!document.hidden) send('heartbeat'); }, 20000);
    const visible = () => send(document.hidden ? 'release' : 'connect');
    document.addEventListener('visibilitychange', visible);
    const leave = () => send('release');
    window.addEventListener('pagehide', leave);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', visible);
      window.removeEventListener('pagehide', leave);
      post('/api/control', { page: page.current, action: 'release', seconds }).catch(() => {});
    };
  }, [full, automatic, seconds]);

  async function refresh() {
    if (updating) return;
    setUpdating(true);
    try {
      if (full) {
        const result = await post('/api/control', { page: page.current, action: 'refresh', scope: effectiveResource === 'services' ? 'services' : 'servers', seconds });
        setControl(result);
        pendingScope.current = effectiveResource === 'services' ? 'services' : 'servers';
        pendingVersion.current = result.version;
        pendingUntil.current = Date.now() + (result.wait_seconds + 120) * 1000;
      } else setUpdating(false);
      await load();
    } catch (failure) { setError(failure.message); setUpdating(false); }
  }

  return { session, status, history, error, loading, updating, control, refresh, loadSession,
    resourceView: effectiveResource, mode: effectiveMode };
}
