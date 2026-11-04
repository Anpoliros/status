"""Preview, validate and manage per-instance systemd user SSH tunnels."""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from .config import load_config, repository_path
from .ssh_transport import collection_url, render_unit


def unit_prefix(config_path: Path) -> str:
    instance = hashlib.sha256(str(config_path.resolve()).encode()).hexdigest()[:12]
    return f'status-ssh-{instance}-'


def planned_units(config_path: Path, servers) -> dict[str, tuple[str, object]]:
    prefix = unit_prefix(config_path)
    return {f'{prefix}{hashlib.sha256(server.id.encode()).hexdigest()[:16]}.service':
            (render_unit(server.target, server.transport), server)
            for server in servers if server.transport}


def systemctl(*arguments):
    subprocess.run(['systemctl', '--user', *arguments], check=True, timeout=30)


def validate_units(units):
    # Parse SSH configuration without opening connections or prompting for keys.
    with tempfile.TemporaryDirectory(prefix='status-ssh-') as directory:
        paths = []
        for name, (content, server) in units.items():
            subprocess.run(['/usr/bin/ssh', '-G', '-o', 'BatchMode=yes', server.transport.host],
                           check=True, stdout=subprocess.DEVNULL, timeout=10)
            path = Path(directory) / name
            path.write_text(content)
            paths.append(str(path))
        if paths:
            subprocess.run(['systemd-analyze', '--user', 'verify', *paths], check=True, timeout=30)


def apply_units(config_path: Path, units, remove: bool = False):
    directory = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'systemd/user'
    directory.mkdir(parents=True, exist_ok=True)
    # Only this config path's generated units are managed; other instances stay intact.
    wanted = {} if remove else units
    for path in directory.glob(f'{unit_prefix(config_path)}*.service'):
        if path.name not in wanted:
            systemctl('disable', '--now', path.name)
            path.unlink()
    for name, (content, _) in wanted.items():
        with tempfile.NamedTemporaryFile(mode='w', dir=directory, delete=False) as temporary:
            temporary.write(content)
            staged = Path(temporary.name)
        staged.chmod(0o644)
        staged.replace(directory / name)
    systemctl('daemon-reload')
    for name in wanted:
        systemctl('enable', name)
        systemctl('restart', name)
    # Check real metrics, not only the SSH process: forwarding can be alive while
    # the remote exporter is unreachable. Disable HTTP proxies for loopback traffic.
    opener = build_opener(ProxyHandler({}))
    for name, (_, server) in wanted.items():
        systemctl('is-active', name)
        failure = None
        for _ in range(10):
            try:
                with opener.open(collection_url(server.target, server.transport), timeout=3) as response:
                    if response.status != 200 or b'node_exporter_build_info' not in response.read():
                        raise ValueError('Endpoint does not return Node Exporter metrics')
                failure = None
                break
            except (OSError, ValueError) as error:
                failure = error
                time.sleep(1)
        if failure:
            raise RuntimeError(f'Exporter probe failed for {server.id}; inspect journalctl --user -u {name}') from failure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='configs/general.json')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--check', action='store_true', help='Validate locally without starting tunnels (default)')
    action.add_argument('--apply', action='store_true', help='Install/reconcile user units and probe metrics')
    action.add_argument('--remove', action='store_true', help='Stop and remove this instance’s generated tunnels')
    args = parser.parse_args()
    path = repository_path(args.config)
    config = load_config(path)
    units = planned_units(path, config.servers)
    if not args.remove:
        validate_units(units)
    for name, (content, server) in units.items():
        print(f'# {server.id}: {collection_url(server.target, server.transport)}\n# {name}\n{content}')
    if args.apply or args.remove:
        apply_units(path, units, remove=args.remove)
    else:
        print(f'Validated {len(units)} SSH tunnel(s); no services changed.')


if __name__ == '__main__':
    main()
