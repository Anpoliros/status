"""Single-owner adaptive collection worker with persistent private snapshots."""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import signal

from .collector import run_server_collection, run_service_checks
from .config import AppConfig, load_config
from .db import connect, init_db, sync_config
from .scheduler import claim_due, finish_collection, init_control
from .status import write_status_json


async def run_worker(config: AppConfig, once: bool = False) -> None:
    config.database.parent.mkdir(parents=True,exist_ok=True)
    lock = config.database.with_suffix('.worker.lock').open('w')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Another worker already owns this instance')
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):
        loop.add_signal_handler(sig,stop.set)
    init_control(config)
    with connect(config.database) as conn:
        init_db(conn)
        sync_config(conn,config)
        # Publish persisted data immediately; collection can proceed afterwards.
        write_status_json(conn,config)
        while not stop.is_set():
            changed = False
            for scope,collect in [('servers',run_server_collection),('services',run_service_checks)]:
                if claim_due(config,scope):
                    try:
                        await collect(conn,config)
                        print(f'Collected {scope}',flush=True)
                    except Exception as error:
                        conn.rollback()
                        print(f'Collection failed ({scope}): {type(error).__name__}',flush=True)
                    finally:
                        finish_collection(config,scope)
                    changed = True
            if changed:
                write_status_json(conn,config)
            if once:
                break
            try:
                await asyncio.wait_for(stop.wait(),timeout=0.5)
            except TimeoutError:
                pass
    lock.close()


def main():
    parser = argparse.ArgumentParser(description='Run adaptive status collection.')
    parser.add_argument('--config',default='configs/general.json')
    parser.add_argument('--once',action='store_true')
    args = parser.parse_args()
    asyncio.run(run_worker(load_config(args.config),once=args.once))


if __name__=='__main__':
    main()
