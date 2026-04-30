from __future__ import annotations

import argparse
import asyncio
import signal

from .collector import run_server_collection, run_service_checks
from .config import AppConfig, load_config
from .db import connect, init_db, sync_config
from .status import write_status_json


async def run_worker(config: AppConfig, once: bool = False) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    with connect(config.database) as conn:
        init_db(conn)
        sync_config(conn, config)
        await run_server_collection(conn, config)
        await run_service_checks(conn, config)
        write_status_json(conn, config)

        if once:
            return

        next_server = loop.time() + config.server_interval_seconds
        next_service = loop.time() + config.service_interval_seconds

        while not stop.is_set():
            sleep_for = max(1.0, min(next_server, next_service) - loop.time())
            try:
                await asyncio.wait_for(stop.wait(), timeout=sleep_for)
                break
            except TimeoutError:
                pass

            now = loop.time()
            if now >= next_server:
                await run_server_collection(conn, config)
                next_server = now + config.server_interval_seconds
            if now >= next_service:
                await run_service_checks(conn, config)
                next_service = now + config.service_interval_seconds
            write_status_json(conn, config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the status monitor worker.")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--once", action="store_true", help="Collect once, write status.json, then exit.")
    args = parser.parse_args()
    asyncio.run(run_worker(load_config(args.config), once=args.once))


if __name__ == "__main__":
    main()
