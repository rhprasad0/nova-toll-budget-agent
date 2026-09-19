"""Focused contracts for the reviewed shared-package transition and mixed versions."""

import hashlib
import importlib.util
import itertools
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from scripts import shared_packages

ROOT = Path(__file__).resolve().parents[2]
REVIEW = json.loads((ROOT / "v2/scripts/shared-package-compatibility.json").read_text())


def retained(path: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"{REVIEW['baseline']}:{path}"], cwd=ROOT
    )


def load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_mixed_loader_publisher_timed_and_cost_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "path", [str(ROOT / "v2/lambdas/loader"), *sys.path])
    modules: dict[str, list[Any]] = {}
    for name in ("loader", "publisher", "timed_checks"):
        path = f"v2/lambdas/{name}/handler.py"
        old = tmp_path / (name + ".py")
        old.write_bytes(retained(path))
        modules[name] = [
            load(old, "retained_" + name),
            load(ROOT / path, "candidate_" + name),
        ]
    # Costs is independently scheduled, has no loader or database coupling, and
    # its executable source is unchanged in this reviewed transition.
    costs = "v2/lambdas/publisher/costs.py"
    assert retained(costs) == (ROOT / costs).read_bytes()
    for name, digest in REVIEW["schemas"].items():
        assert hashlib.sha256(retained("v2/db/" + name)).hexdigest() == digest
        assert (
            hashlib.sha256((ROOT / "v2/db" / name).read_bytes()).hexdigest() == digest
        )
    for environment in shared_packages.ACCOUNTS:
        monkeypatch.setenv("TOLLCHAT_ENVIRONMENT", environment)
        for loader, publisher, timed in itertools.product(*modules.values()):
            detail = loader._i95_success_detail(
                watermark="2026-09-19T12:00:00Z",
                s3_key="raw/feed=i95/date=2026-09-19/1200Z.csv",
                row_count=1,
            )
            event = {
                "source": "tollchat.pricing-loader",
                "detail-type": "I95 Pricing Load Committed",
                "detail": detail,
            }
            assert publisher._expected_watermark(event) == datetime(
                2026, 9, 19, 12, tzinfo=UTC
            )
            assert loader.UPSERT_I95_SQL == modules["loader"][0].UPSERT_I95_SQL
            assert loader.UPSERT_I66_SQL == modules["loader"][0].UPSERT_I66_SQL
            assert publisher.REPORT_SQL == modules["publisher"][0].REPORT_SQL
            assert publisher.PUBLICATION_FORMAT_VERSION == "3.0.0"
            for schedule, window in timed.SCHEDULE_WINDOW_PAIRS:
                assert timed._validate_event(
                    {"window_id": window, "schedule": schedule}
                ) == (window, schedule)


def test_compatibility_gate_binds_the_serving_baseline_and_built_packages(
    tmp_path: Path,
) -> None:
    expected = shared_packages.evidence(
        "development",
        shared_packages.ACCOUNTS["development"],
        "a" * 40,
        REVIEW["packages"],
    )
    for name in REVIEW["schemas"]:
        path = tmp_path / "v2/db" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / "v2/db" / name).read_bytes())
    assert (
        shared_packages.compatibility(tmp_path, expected, REVIEW["baseline"])["status"]
        == "reviewed"
    )
    with pytest.raises(ValueError, match="shared_compatibility"):
        shared_packages.compatibility(tmp_path, expected, "b" * 40)
    expected["packages"]["loader.zip"]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="shared_compatibility"):
        shared_packages.compatibility(tmp_path, expected, REVIEW["baseline"])
