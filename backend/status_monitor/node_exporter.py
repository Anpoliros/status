from __future__ import annotations

import re
from collections import defaultdict


MetricKey = tuple[str, tuple[tuple[str, str], ...]]

LINE_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([-+eE0-9.]+)")
LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="([^"]*)"')


def parse_prometheus(text: str) -> dict[MetricKey, float]:
    metrics: dict[MetricKey, float] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = LINE_RE.match(line)
        if not match:
            continue
        name, labels_raw, value_raw = match.groups()
        labels = tuple(sorted(LABEL_RE.findall(labels_raw or "")))
        try:
            metrics[(name, labels)] = float(value_raw)
        except ValueError:
            continue
    return metrics


def _labels_to_dict(labels: tuple[tuple[str, str], ...]) -> dict[str, str]:
    return dict(labels)


def extract_node_metrics(text: str) -> dict[str, float | None]:
    metrics = parse_prometheus(text)
    cpu_by_cpu: dict[str, dict[str, float]] = defaultdict(dict)
    memory_total = None
    memory_available = None
    filesystem_total = 0.0
    filesystem_available = 0.0
    network_in = 0.0
    network_out = 0.0

    for (name, labels_tuple), value in metrics.items():
        labels = _labels_to_dict(labels_tuple)
        if name == "node_cpu_seconds_total":
            cpu = labels.get("cpu")
            mode = labels.get("mode")
            if cpu is not None and mode is not None:
                cpu_by_cpu[cpu][mode] = value
        elif name == "node_memory_MemTotal_bytes":
            memory_total = value
        elif name == "node_memory_MemAvailable_bytes":
            memory_available = value
        elif name == "node_filesystem_size_bytes" and _is_real_filesystem(labels):
            filesystem_total += value
        elif name == "node_filesystem_avail_bytes" and _is_real_filesystem(labels):
            filesystem_available += value
        elif name == "node_network_receive_bytes_total" and _is_real_network(labels):
            network_in += value
        elif name == "node_network_transmit_bytes_total" and _is_real_network(labels):
            network_out += value

    cpu_usage = None
    if cpu_by_cpu:
        cpu_usages = []
        for by_mode in cpu_by_cpu.values():
            total = sum(by_mode.values())
            idle = by_mode.get("idle", 0.0) + by_mode.get("iowait", 0.0)
            if total > 0:
                cpu_usages.append(max(0.0, min(100.0, (1.0 - idle / total) * 100.0)))
        if cpu_usages:
            cpu_usage = sum(cpu_usages) / len(cpu_usages)

    memory_usage = None
    if memory_total and memory_available is not None and memory_total > 0:
        memory_usage = max(0.0, min(100.0, (1.0 - memory_available / memory_total) * 100.0))

    disk_usage = None
    if filesystem_total > 0:
        disk_usage = max(0.0, min(100.0, (1.0 - filesystem_available / filesystem_total) * 100.0))

    return {
        "cpu_usage": cpu_usage,
        "memory_usage": memory_usage,
        "disk_usage": disk_usage,
        "network_in": network_in,
        "network_out": network_out,
    }


def _is_real_filesystem(labels: dict[str, str]) -> bool:
    fstype = labels.get("fstype", "")
    mountpoint = labels.get("mountpoint", "")
    ignored_types = {"tmpfs", "devtmpfs", "overlay", "squashfs", "proc", "sysfs", "cgroup2"}
    return fstype not in ignored_types and not mountpoint.startswith(("/run", "/var/lib/docker"))


def _is_real_network(labels: dict[str, str]) -> bool:
    device = labels.get("device", "")
    return bool(device) and device != "lo" and not device.startswith(("veth", "docker", "br-", "tailscale"))
