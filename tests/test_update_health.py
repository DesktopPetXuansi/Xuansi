"""The trial probe must exercise Qt without starting the desktop pet or writing user data."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_health_trial_is_read_only(tmp_path):
    root = Path(__file__).resolve().parents[1]
    nonce = "0123456789abcdef0123456789abcdef"
    env = os.environ | {
        "QT_QPA_PLATFORM": "offscreen",
        "XUANSI_WRITABLE_ROOT": str(tmp_path),
        "XUANSI_UPDATE_TRIAL_NONCE": nonce,
    }
    result = subprocess.run(
        [sys.executable, "-m", "pet", "--update-health-check"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert json.loads(result.stdout.strip()) == {
        "nonce": nonce,
        "version": (root / "VERSION").read_text(encoding="utf-8").strip(),
    }
    assert list(tmp_path.iterdir()) == []
