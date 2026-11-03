#!/usr/bin/env python3
"""Repository entry point for validated Prometheus inventory deployment."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from backend.status_monitor.deploy_prometheus import main

if __name__=='__main__':
    main()
