"""Dead-code detection — fails if vulture finds unreferenced code."""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_no_dead_code():
    result = subprocess.run(
        [
            sys.executable, "-m", "vulture",
            "osr2_broker", "vulture_whitelist.py",
            "--min-confidence", "60",
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, f"Vulture found dead code:\n{result.stdout}"
