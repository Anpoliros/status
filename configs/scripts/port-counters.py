#!/usr/bin/env python3
"""Root helper: count loopback service traffic without changing packet verdicts.

Install this file and ports.json root-owned under /usr/local/lib/status-ports.
The status web application never runs privileged commands.
"""
import json
import os
from pathlib import Path
import subprocess
import time
import uuid


def nft(*args, input=None):
    return subprocess.run(['/usr/sbin/nft', *args], input=input, text=True,
                          capture_output=True, check=True, timeout=5).stdout


def main():
    ports = json.loads(Path('/usr/local/lib/status-ports/ports.json').read_text())
    if not isinstance(ports, list) or not ports or any(type(p) is not int or not 1 <= p <= 65535 for p in ports):
        raise ValueError('Expected a nonempty array of TCP ports')
    ports = sorted(set(ports))
    # Replace only our dedicated table in one atomic nft transaction.
    exists = subprocess.run(['/usr/sbin/nft', 'list', 'table', 'inet', 'status_ports'],
                            capture_output=True, timeout=5).returncode == 0
    rules = ['delete table inet status_ports'] if exists else []
    rules += ['add table inet status_ports',
              'add chain inet status_ports output { type filter hook output priority 10; policy accept; }']
    for port in ports:
        for direction, field in [('rx', 'dport'), ('tx', 'sport')]:
            name = f'{direction}_{port}'
            rules += [f'add counter inet status_ports {name}',
                      f'add rule inet status_ports output oifname "lo" tcp {field} {port} counter name {name}']
    nft('-f', '-', input='\n'.join(rules) + '\n')
    generation = str(uuid.uuid4())
    directory = Path('/run/status-ports')
    directory.mkdir(mode=0o755, exist_ok=True)
    while True:
        counters = {}
        for item in json.loads(nft('-j', 'list', 'table', 'inet', 'status_ports'))['nftables']:
            counter = item.get('counter', {})
            if 'name' in counter:
                counters[counter['name']] = counter['bytes']
        payload = {'generation': generation, 'timestamp': time.time(),
                   'ports': {str(p): [counters[f'rx_{p}'], counters[f'tx_{p}']] for p in ports}}
        temporary = directory / 'counters.tmp'
        temporary.write_text(json.dumps(payload))
        temporary.chmod(0o644)
        os.replace(temporary, directory / 'counters.json')
        time.sleep(5)


if __name__ == '__main__':
    main()
