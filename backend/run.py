"""PM2 entry point that preserves the repository's explicit Python interpreter."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

# PM2 resolves executable symlinks used as scripts. An ordinary Python entry file
# keeps .venv/bin/python in the interpreter field, so virtualenv discovery works.
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

if __name__ == '__main__':
    if len(sys.argv)<2 or sys.argv[1] not in ('api','worker'):
        raise SystemExit('Usage: backend/run.py {api|worker} [options]')
    component = sys.argv.pop(1)
    importlib.import_module(f'backend.status_monitor.{component}').main()
