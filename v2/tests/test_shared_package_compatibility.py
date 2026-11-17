"""Focused contracts for the reviewed shared-package transition and mixed versions."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from scripts import shared_packages

ROOT = Path(__file__).resolve().parents[2]
REVIEW = json.loads((ROOT / "v2/scripts/shared-package-compatibility.json").read_text())


def retained(path: str, baseline: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{baseline}:{path}"], cwd=ROOT)


RETIRED_REPORT_AND_EVALUATION_OBJECTS: dict[
    str, tuple[tuple[bytes, bytes, int], ...]
] = {
    "schema.sql": ((b"1.4.0", b"1.5.0", 2),),
    "oracle/schema.sql": (
        (b"1.15.2", b"1.16.0", 2),
        (
            b"DO $$\nBEGIN\n    CREATE ROLE report_publisher LOGIN;\nEXCEPTION\n"
            b"    WHEN duplicate_object THEN NULL;\nEND $$;\n\n",
            b"",
            1,
        ),
        (
            b"WHERE rolname IN ('tollchat_agent', 'pricing_caller', 'report_publisher')",
            b"WHERE rolname IN ('tollchat_agent', 'pricing_caller')",
            1,
        ),
        (
            b"WHERE member_role.rolname IN (\n"
            b"            'tollchat_agent', 'pricing_caller', 'report_publisher'\n        )",
            b"WHERE member_role.rolname IN ('tollchat_agent', 'pricing_caller')",
            1,
        ),
        (
            b"to_regrole('pricing_caller'),\n              to_regrole('report_publisher')",
            b"to_regrole('pricing_caller')",
            1,
        ),
        (
            b"to_regrole('pricing_caller'),\n            to_regrole('report_publisher')",
            b"to_regrole('pricing_caller')",
            3,
        ),
        (b"pricing_caller, report_publisher;", b"pricing_caller;", 2),
        (
            b"GRANT EXECUTE ON FUNCTION oracle.get_i95_i495_report_inputs()\n"
            b"TO report_publisher;\n",
            b"",
            1,
        ),
        (
            b"ALTER FUNCTION oracle.get_i95_i495_report_inputs() OWNER TO oracle_owner;\n"
            b"ALTER FUNCTION oracle.get_agent_report_routes() OWNER TO oracle_owner;\n",
            b"",
            1,
        ),
        (
            b"SET LOCAL ROLE oracle_owner;\n"
            b"GRANT EXECUTE ON FUNCTION oracle.get_agent_report_routes()\n"
            b"TO report_publisher;\n",
            b"",
            1,
        ),
    ),
}
RETIRED_SPANS = {
    "schema.sql": (
        b"CREATE TABLE pricing.evaluation_runs (",
        b"CREATE TABLE pricing.trip_pricing_i95 (",
    ),
    "oracle/schema.sql": (
        b"CREATE FUNCTION oracle.get_i95_i495_report_inputs()",
        b"REVOKE ALL ON ALL TABLES IN SCHEMA oracle FROM PUBLIC;",
    ),
}


def without_retired_objects(name: str, previous: bytes) -> bytes:
    start, end = RETIRED_SPANS[name]
    assert previous.count(start) == previous.count(end) == 1
    previous = previous[: previous.index(start)] + previous[previous.index(end) :]
    for old, new, count in RETIRED_REPORT_AND_EVALUATION_OBJECTS[name]:
        assert previous.count(old) == count
        previous = previous.replace(old, new)
    return previous


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
def test_mixed_loader_and_cost_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, baseline: str
) -> None:
    monkeypatch.setattr(sys, "path", [str(ROOT / "v2/lambdas/loader"), *sys.path])
    path = "v2/lambdas/loader/handler.py"
    old = tmp_path / "loader.py"
    old.write_bytes(retained(path, baseline))
    loaders: list[Any] = [
        load(old, "retained_loader"),
        load(ROOT / path, "candidate_loader"),
    ]
    for name, digest in REVIEW["schemas"].items():
        previous = retained("v2/db/" + name, baseline)
        if name in RETIRED_SPANS:
            previous = without_retired_objects(name, previous)
        current = (ROOT / "v2/db" / name).read_bytes()
        review = (
            f"v2/db/{name} differs from reviewed baseline {baseline}. Extending "
            "v2/scripts/shared-package-compatibility.json needs a human review "
            "(v2/runbooks/blue-green-deployments.md); do not edit it to pass"
        )
        assert previous == current, review
        assert hashlib.sha256(current).hexdigest() == digest, review
    for environment in shared_packages.ACCOUNTS:
        monkeypatch.setenv("TOLLCHAT_ENVIRONMENT", environment)
        for loader in loaders:
            assert loader.UPSERT_I95_SQL == loaders[0].UPSERT_I95_SQL
            assert loader.UPSERT_I66_SQL == loaders[0].UPSERT_I66_SQL


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
    for unreviewed in ("b" * 40, "4f6334a8e0cba0b6ccda8bc45fee82a9a5cdfafe"):
        with pytest.raises(ValueError, match="shared_compatibility"):
            shared_packages.compatibility(tmp_path, expected, unreviewed)
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
