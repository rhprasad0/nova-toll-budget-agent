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


def retained(path: str, baseline: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{baseline}:{path}"], cwd=ROOT)


def load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "baseline", [REVIEW["baseline"], REVIEW["development_baseline"]]
)
def test_mixed_loader_publisher_timed_and_cost_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, baseline: str
) -> None:
    monkeypatch.setattr(sys, "path", [str(ROOT / "v2/lambdas/loader"), *sys.path])
    modules: dict[str, list[Any]] = {}
    for name in ("loader", "publisher", "timed_checks"):
        path = f"v2/lambdas/{name}/handler.py"
        old = tmp_path / (name + ".py")
        old.write_bytes(retained(path, baseline))
        modules[name] = [
            load(old, "retained_" + name),
            load(ROOT / path, "candidate_" + name),
        ]
    # Costs is independently scheduled, has no loader or database coupling, and
    # its executable source is unchanged in this reviewed transition.
    costs = "v2/lambdas/publisher/costs.py"
    assert retained(costs, baseline) == (ROOT / costs).read_bytes()
    for name, digest in REVIEW["schemas"].items():
        previous = retained("v2/db/" + name, baseline)
        current = (ROOT / "v2/db" / name).read_bytes()
        if name == "oracle/schema.sql":
            # The reviewed 1.15.1 label migration changes only these schema markers.
            for marker in (
                b"-- oracle schema version: 1.15.0\n",
                b"INSERT INTO oracle.schema_version (version) VALUES ('1.15.0');",
            ):
                assert previous.count(marker) == 1
                previous = previous.replace(
                    marker, marker.replace(b"1.15.0", b"1.15.1")
                )
        assert previous == current
        assert hashlib.sha256(current).hexdigest() == digest
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


@pytest.mark.parametrize("environment", ["development", "production"])
def test_compatibility_gate_binds_the_serving_baseline_and_built_packages(
    tmp_path: Path,
    environment: str,
) -> None:
    baseline = REVIEW[
        "development_baseline" if environment == "development" else "baseline"
    ]
    expected = shared_packages.evidence(
        environment,
        shared_packages.ACCOUNTS[environment],
        "a" * 40,
        REVIEW["packages"],
    )
    for name in REVIEW["schemas"]:
        path = tmp_path / "v2/db" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / "v2/db" / name).read_bytes())
    assert (
        shared_packages.compatibility(tmp_path, expected, baseline)["status"]
        == "reviewed"
    )
    with pytest.raises(ValueError, match="shared_compatibility"):
        shared_packages.compatibility(tmp_path, expected, "b" * 40)
    assert (
        shared_packages.compatibility(tmp_path, expected, "b" * 40, changing=False)[
            "status"
        ]
        == "unchanged"
    )
    (tmp_path / "v2/db/schema.sql").write_text("wrong schema")
    with pytest.raises(ValueError, match="shared_compatibility"):
        shared_packages.compatibility(tmp_path, expected, baseline)
    (tmp_path / "v2/db/schema.sql").write_bytes(
        (ROOT / "v2/db/schema.sql").read_bytes()
    )
    expected["packages"]["loader.zip"]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="shared_compatibility"):
        shared_packages.compatibility(tmp_path, expected, baseline)


def test_committed_shared_packages_match_compatibility_review() -> None:
    manifest = json.loads(
        (ROOT / "infra/development-release-manifest.json").read_text()
    )
    assert REVIEW["packages"] == {
        name: manifest["packages"][name] for name in shared_packages.PACKAGES
    }
