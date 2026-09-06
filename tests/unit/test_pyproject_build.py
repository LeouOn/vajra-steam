"""Wave 1 Task 7 — RED test for pyproject.toml build-backend.

Asserts that ``python -m build --wheel`` exits 0 against the project's
PEP 517 build-backend declared in ``pyproject.toml``. Prior to the fix,
the declared backend ``setuptools.backends._legacy:_Backend`` does not
exist, so this test fails with ``BackendUnavailable``. After switching
to ``setuptools.build_meta`` it should pass.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_build_wheel_succeeds() -> None:
    """``python -m build --wheel`` must exit 0 against the project's build backend.

    This gates all editable installs (``pip install -e .``) and any
    wheel/sdist distribution. The PEP 517 build-backend declared in
    ``pyproject.toml`` must be importable by setuptools.
    """
    result = subprocess.run(
        [sys.executable, "-P", "-m", "build", "--wheel"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        result.returncode == 0
    ), f"python -m build --wheel failed.\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}\n"
