#!/usr/bin/env python3
"""Repository entry point for optional exporter SSH tunnel deployment."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.status_monitor.deploy_ssh import main

if __name__ == '__main__':
    main()
