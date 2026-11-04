/** @file ResourceFilter.jsx @description Collapsible resource filters with held-pointer cluster ordering. */
import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, GripVertical } from 'lucide-react';

export const resourceKey = item => String(item.resource_id ?? item.id);
export const orderedClusters = (items, order = []) => {
  const clusters = [...new Set(items.map(item => item.cluster || 'Default'))];
  return [...order.filter(cluster => clusters.includes(cluster)), ...clusters.filter(cluster => !order.includes(cluster))];
};

export function ResourceFilter({ items, filters, setFilters, scope }) {
  const [dragging, setDragging] = useState(null);
  const gesture = useRef(null);
  const clusters = orderedClusters(items, filters.clusterOrder);
  const toggle = (key, value) => setFilters(previous => ({ ...previous,
    [key]: previous[key].includes(value) ? previous[key].filter(item => item !== value) : [...previous[key], value],
  }));
  const cancel = () => {
    window.clearTimeout(gesture.current?.timer);
    gesture.current = null;
    setDragging(null);
  };
  useEffect(() => () => window.clearTimeout(gesture.current?.timer), [scope]);
  const moveCluster = (from, to) => {
    if (from === to || !clusters.includes(to)) return;
    const order = clusters.filter(cluster => cluster !== from);
    order.splice(clusters.indexOf(to), 0, from);
    setFilters(previous => ({ ...previous, clusterOrder: order }));
  };

  return <>
    <div className="settingsHeading"><strong>Clusters</strong><button onClick={() => setFilters(previous => ({ ...previous, hiddenClusters: [], hiddenMachines: [] }))}>Show all</button></div>
    <p className="muted">Click a cluster to expand. Hold and drag its title to reorder.</p>
    {clusters.map(cluster => {
      const collapsed = filters.collapsedClusters.includes(cluster);
      return <div key={cluster} data-filter-cluster={cluster} className={dragging === cluster ? 'filterCluster dragging' : 'filterCluster'}>
        <div className="checkRow">
          <button className="filterClusterTitle" aria-expanded={!collapsed} aria-label={`${cluster}: expand or collapse; Alt + arrow keys to reorder`} onClick={event => {
            if (event.detail === 0) toggle('collapsedClusters', cluster);
          }} onKeyDown={event => {
            if (!event.altKey || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
            event.preventDefault();
            moveCluster(cluster, clusters[clusters.indexOf(cluster) + (event.key === 'ArrowUp' ? -1 : 1)]);
          }} onPointerDown={event => {
            if (event.button !== 0) return;
            event.currentTarget.setPointerCapture(event.pointerId);
            gesture.current = { x: event.clientX, y: event.clientY, held: false,
              timer: window.setTimeout(() => { if (gesture.current) { gesture.current.held = true; setDragging(cluster); } }, 350) };
          }} onPointerMove={event => {
            const current = gesture.current;
            if (!current) return;
            if (!current.held) {
              if (Math.hypot(event.clientX - current.x, event.clientY - current.y) > 8) { window.clearTimeout(current.timer); current.moved = true; }
              return;
            }
            const target = document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-filter-cluster]');
            if (target) moveCluster(cluster, target.dataset.filterCluster);
          }} onPointerUp={() => {
            if (gesture.current && !gesture.current.held && !gesture.current.moved) toggle('collapsedClusters', cluster);
            cancel();
          }} onPointerCancel={cancel}>
            {collapsed ? <ChevronRight size={15} /> : <ChevronDown size={15} />}<strong>{cluster}</strong><GripVertical size={14} className="muted" />
          </button>
          <input aria-label={`Show ${cluster}`} type="checkbox" checked={!filters.hiddenClusters.includes(cluster)} onChange={() => toggle('hiddenClusters', cluster)} />
        </div>
        {!collapsed && items.filter(item => (item.cluster || 'Default') === cluster).map(item => <label className="checkRow machineFilter" key={resourceKey(item)}><span>{item.name}</span><input type="checkbox" disabled={filters.hiddenClusters.includes(cluster)} checked={!filters.hiddenMachines.includes(resourceKey(item))} onChange={() => toggle('hiddenMachines', resourceKey(item))} /></label>)}
      </div>;
    })}
    {!items.length && <p className="muted">No resources available.</p>}
  </>;
}
