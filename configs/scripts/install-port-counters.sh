#!/bin/sh
# Install reviewed, root-owned helper files; keep web workers unprivileged.
set -eu
cd "$(dirname "$0")"
install -d -m 755 /usr/local/lib/status-ports
install -m 644 port-counters.py /usr/local/lib/status-ports/port-counters.py
install -m 644 ports.json /usr/local/lib/status-ports/ports.json
install -m 644 status-ports.service /etc/systemd/system/status-ports.service
systemctl daemon-reload
systemctl enable --now status-ports.service
systemctl restart status-ports.service
systemctl --no-pager status status-ports.service
