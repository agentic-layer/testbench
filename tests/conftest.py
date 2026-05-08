"""Shared test configuration — adds testbench/ to sys.path for all tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "testbench"))
