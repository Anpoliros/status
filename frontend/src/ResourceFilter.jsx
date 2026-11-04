/** @file ResourceFilter.jsx @description Collapsible resource filters with held-pointer cluster ordering. */
import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, GripVertical } from 'lucide-react';

export const resourceKey = item => String(item.resource_id ?? item.id);
export const orderedClusters = (items, order = []) => {
  const clusters = [...new Set(items.map(item => item.cluster || 'Default'))];
  return [...order.filter(cluster => clusters.includes(cluster)), ...clusters.filter(cluster => !order.includes(cluster))];
};

export function ResourceFilter({ items, filters, setFilters, setClusterOrder, scope }) {
  const [dragging, setDragging] = useState(null);
  const gesture = useRef(null);
  const clusters = orderedClusters(items, filters.clusterOrder);
  const toggle = (key, value) => setFilters(previous => ({ ...previous,
    [key]: previous[key].includes(value) ? previous[key].filter(item => item !== value) : [...previous[key], value],
  }));
  const cancel = () => {
    window.clearTimeout(gesture.current?.timer);
    window.clearInterval(gesture.current?.scrollTimer);
    gesture.current = null;
    setDragging(null);
  };
  useEffect(() => () => {
    window.clearTimeout(gesture.current?.timer);
    window.clearInterval(gesture.current?.scrollTimer);
  }, [scope]);
  const moveCluster = (from, to) => {
    if (from === to || !clusters.includes(to)) return;
    const order = clusters.filter(cluster => cluster !== from);
    order.splice(clusters.indexOf(to), 0, from);
    setClusterOrder(order);
  };

  // Keep the DOM stationary during a drag; commit only when the pointer is released.
  const updateDrop = () => {
    const current = gesture.current;
    if (!current?.held) return;
    const bounds = current.scroller.getBoundingClientRect();
    if (current.y < bounds.top + 36) current.scroller.scrollTop -= 12;
    else if (current.y > bounds.bottom - 36) current.scroller.scrollTop += 12;
    const target = document.elementFromPoint(current.x, Math.max(bounds.top + 1, Math.min(bounds.bottom - 1, current.y)))?.closest('[data-filter-cluster]');
    if (!target || target.dataset.filterCluster === current.cluster) {
      current.drop = null;
    } else {
      const box = target.getBoundingClientRect();
      current.drop = { cluster: target.dataset.filterCluster, after: current.y > box.top + box.height / 2 };
    }
    setDragging({ cluster: current.cluster, drop: current.drop });
  };
  const start = (event, cluster, immediate) => {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    cancel();
    const current = { cluster, x: event.clientX, y: event.clientY, held: false,
      scroller: event.currentTarget.closest('.settingsContent') };
    gesture.current = current;
    const activate = () => {
      current.held = true;
      setDragging({ cluster, drop: null });
      current.scrollTimer = window.setInterval(updateDrop, 40);
    };
    if (immediate) activate();
    else current.timer = window.setTimeout(activate, 350);
  };
  const move = event => {
    if (!gesture.current) return;
    gesture.current.x = event.clientX;
    gesture.current.y = event.clientY;
    updateDrop();
  };
  const finish = () => {
    const current = gesture.current;
    if (current?.held && current.drop) {
      const order = clusters.filter(cluster => cluster !== current.cluster);
      order.splice(order.indexOf(current.drop.cluster) + Number(current.drop.after), 0, current.cluster);
      setClusterOrder(order);
    } else if (current && !current.held) toggle('collapsedClusters', current.cluster);
    cancel();
  };

  return <>
    <div className="settingsHeading"><strong>Clusters</strong><button onClick={() => setFilters(previous => ({ ...previous, hiddenClusters: [], hiddenMachines: [] }))}>Show all</button></div>
    <p className="muted">Click to expand. Hold a title or drag its handle to reorder.</p>
    {clusters.map(cluster => {
      const collapsed = filters.collapsedClusters.includes(cluster);
      return <div key={cluster} data-filter-cluster={cluster} className={`filterCluster${dragging?.cluster === cluster ? ' dragging' : ''}${dragging?.drop?.cluster === cluster ? dragging.drop.after ? ' dropAfter' : ' dropBefore' : ''}`}>
        <div className="checkRow">
          <button className="filterClusterTitle" aria-expanded={!collapsed} aria-label={`${cluster}: expand or collapse; Alt + arrow keys to reorder`} onClick={event => {
            if (event.detail === 0) toggle('collapsedClusters', cluster);
          }} onKeyDown={event => {
            if (!event.altKey || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
            event.preventDefault();
            moveCluster(cluster, clusters[clusters.indexOf(cluster) + (event.key === 'ArrowUp' ? -1 : 1)]);
          }} onPointerDown={event => start(event, cluster, Boolean(event.target.closest('[data-drag-handle]')))} onPointerMove={move} onPointerUp={finish} onPointerCancel={cancel}>
            {collapsed ? <ChevronRight size={15} /> : <ChevronDown size={15} />}<strong>{cluster}</strong><span data-drag-handle title="Drag to reorder" className="clusterDragHandle"><GripVertical size={16} /></span>
          </button>
          <input aria-label={`Show ${cluster}`} type="checkbox" checked={!filters.hiddenClusters.includes(cluster)} onChange={() => toggle('hiddenClusters', cluster)} />
        </div>
        {!collapsed && items.filter(item => (item.cluster || 'Default') === cluster).map(item => <label className="checkRow machineFilter" key={resourceKey(item)}><span>{item.name}</span><input type="checkbox" disabled={filters.hiddenClusters.includes(cluster)} checked={!filters.hiddenMachines.includes(resourceKey(item))} onChange={() => toggle('hiddenMachines', resourceKey(item))} /></label>)}
      </div>;
    })}
    {!items.length && <p className="muted">No resources available.</p>}
  </>;
}
