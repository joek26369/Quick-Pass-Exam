#!/usr/bin/env python3
"""WorkBuddy entrypoint for the local Quick-Pass-Exam study library."""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / "study_server.py"), run_name="__main__")
