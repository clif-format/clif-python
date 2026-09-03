from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
SPEC_EXAMPLES = WORKSPACE_ROOT / "clif" / "spec" / "examples" / "clif-1.0.0"
CLIF_TEST_FIXTURES = WORKSPACE_ROOT / "clif-test" / "tests" / "fixtures"


def require_sibling(directory: Path, name: str) -> list[Path]:
    """Collect .clif files from a sibling repository checkout.

    The specification and the conformance suite live in sibling repositories.
    When they are absent the dependent tests skip, but setting
    CLIF_REQUIRE_SIBLINGS=1 (as CI does) turns the absence into a failure so a
    misconfigured pipeline cannot silently collect zero cases.
    """
    if directory.is_dir():
        return sorted(directory.rglob("*.clif"))
    message = f"sibling checkout {name} not found at {directory}"
    if os.environ.get("CLIF_REQUIRE_SIBLINGS") == "1":
        pytest.fail(message)
    return []


def skip_if_missing(paths: list[Path], name: str) -> None:
    if not paths:
        pytest.skip(f"sibling checkout {name} is not available")
