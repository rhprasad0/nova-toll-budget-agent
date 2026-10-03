"""Synthetic factory regressions: privacy, binding, denominators, and history."""

from __future__ import annotations

import io
import json
import os
import pty
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zipfile import ZipFile

import pytest

from eval import golden
from eval import golden_run as run
from eval.factory import factory as f
from eval.factory import kit, smoke
from eval.factory.source_agent import SourceAgent


def test_kit_retains_default_seccomp_and_packages_namespace_exceptions(
    tmp_path: Path,
) -> None:
    profile = json.loads((kit.HERE / ".devcontainer/seccomp.json").read_text())
    mount_rule, namespace_rule = profile["syscalls"][-2:]
    assert mount_rule["names"] == ["mount", "pivot_root", "umount2"]
    assert mount_rule["action"] == "SCMP_ACT_ALLOW"
    assert namespace_rule["names"] == ["clone", "unshare"]
    assert namespace_rule["action"] == "SCMP_ACT_ALLOW"
    assert namespace_rule["args"] == [
        {
            "index": 0,
            "value": 268435456,
            "valueTwo": 268435456,
            "op": "SCMP_CMP_MASKED_EQ",
        }
    ]
    # All upstream Docker restrictions remain exactly as pinned at 2ceae35.
    profile["syscalls"] = profile["syscalls"][:-2]
    assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
    assert (
        kit.digest(profile)
        == "a894b5730caa168d88da7fffe8ace974ad05fb84547e1766fa879d75d3ac6ba2"
    )
    output = tmp_path / "kit"
    kit.build(output)
    runtime = output / "runtime/v2"
    subprocess.run(
        [
            sys.executable,
            "-B",
            "-I",
            "-c",
            "import socket, sys; "
            "socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network forbidden')); "
            "sys.path.insert(0, sys.argv[1]); "
            "from eval.factory import factory; "
            "from eval.factory.kit import evaluator_identity; "
            "assert factory.__file__.startswith(sys.argv[1]); "
            "evaluator_identity()",
            str(runtime),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    manifest = json.loads((output / "kit-manifest.json").read_text())
    assert (output / "LICENSE").read_bytes() == (
        kit.HERE.parents[2] / "LICENSE"
    ).read_bytes()
    assert manifest["files"][".devcontainer/seccomp.json"] == kit.sha(
        (kit.HERE / ".devcontainer/seccomp.json").read_bytes()
    )
    settings = json.loads((output / ".devcontainer/devcontainer.json").read_text())
    assert "--network=host" not in settings["runArgs"]
    assert (
        settings["postStartCommand"]
        == "sh /opt/factory/v2/eval/factory/start-tailscale.sh"
    )
    assert settings["waitFor"] == "postStartCommand"
    assert (output / "runtime/v2/eval/factory/start-tailscale.sh").read_bytes() == (
        kit.HERE / "start-tailscale.sh"
    ).read_bytes()
    assert "--cap-drop=ALL" in settings["runArgs"]
    assert "--security-opt=no-new-privileges" in settings["runArgs"]
    assert (
        "--security-opt=seccomp=${localWorkspaceFolder}/.devcontainer/seccomp.json"
        in settings["runArgs"]
    )
    references = output / "runtime/v2/eval/factory/database"
    provenance = json.loads((references / "manifest.json").read_text())
    assert set(provenance["files"]) == set(kit.DATABASE_REFERENCES)
    assert all(
        provenance["files"][name] == kit.sha((references / name).read_bytes())
        for name in kit.DATABASE_REFERENCES
    )
    assert (output / "DATABASE.md").is_file()
    for name in ("AUTHORING.md", "runtime/v2/eval/factory/AUTHORING.md"):
        assert (output / name).read_bytes() == (kit.HERE / "AUTHORING.md").read_bytes()
        assert manifest["files"][name] == kit.sha((output / name).read_bytes())
    recipe = (
        (output / "DATABASE.md")
        .read_text()
        .split("bash <<'SH'\n", 1)[1]
        .split("\nSH\n", 1)[0]
    )
    subprocess.run(["bash", "-n"], input=recipe, text=True, check=True)


def test_tailscale_startup_survives_terminal_hangup(tmp_path: Path) -> None:
    state = tmp_path / "state"
    tools = tmp_path / "bin"
    tools.mkdir()
    cli = tools / "tailscale"
    cli.write_text(f'#!/bin/sh\ntest -s "{state}/ready"\n')
    daemon = tools / "tailscaled"
    daemon.write_text(
        f"#!{f.sys.executable}\n"
        "import json, os, signal, time\nfrom pathlib import Path\n"
        f"state = Path({str(state)!r})\n"
        "(state / 'heartbeat').write_text('.')\n"
        "(state / 'ready').write_text(json.dumps({'pid': os.getpid(), "
        "'hangup_ignored': signal.getsignal(signal.SIGHUP) == signal.SIG_IGN}))\n"
        "while True:\n"
        "    with (state / 'heartbeat').open('a') as stream: stream.write('.')\n"
        "    time.sleep(0.02)\n"
    )
    cli.chmod(0o755)
    daemon.chmod(0o755)
    startup = tmp_path / "start.sh"
    startup.write_text(
        (kit.HERE / "start-tailscale.sh")
        .read_text()
        .replace("/private/agent-state/tailscale", str(state))
    )
    environment = {**os.environ, "PATH": f"{tools}:{os.environ['PATH']}"}
    child, terminal = pty.fork()
    if child == 0:
        os.execve("/bin/sh", ["sh", str(startup)], environment)
    try:
        _, status = os.waitpid(child, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        ready = json.loads((state / "ready").read_text())
        daemon_pid = ready["pid"]
        try:
            assert ready["hangup_ignored"]
            os.close(terminal)
            terminal = -1
            os.kill(daemon_pid, signal.SIGHUP)
            heartbeat = state / "heartbeat"
            before = heartbeat.stat().st_size
            deadline = time.monotonic() + 2
            while heartbeat.stat().st_size == before and time.monotonic() < deadline:
                time.sleep(0.02)
            assert heartbeat.stat().st_size > before
            subprocess.run(["sh", str(startup)], env=environment, check=True)
            assert json.loads((state / "ready").read_text())["pid"] == daemon_pid
        finally:
            os.kill(daemon_pid, signal.SIGTERM)
    finally:
        if terminal >= 0:
            os.close(terminal)


@pytest.mark.parametrize(
    ("state", "online", "route", "address", "allowed"),
    [
        ("Running", True, "fd7a:115c:a1e0:b1a:0:1:ac1f:0/112", "172.31.1.2", True),
        ("NeedsLogin", True, "fd7a:115c:a1e0:b1a:0:1:ac1f:0/112", "172.31.1.2", False),
        ("Running", False, "fd7a:115c:a1e0:b1a:0:1:ac1f:0/112", "172.31.1.2", False),
        ("Running", True, "10.0.0.0/16", "172.31.1.2", False),
        ("Running", True, "fd7a:115c:a1e0:b1a:0:2:ac1f:0/112", "172.31.1.2", False),
        ("Running", True, "fd7a:115c:a1e0:b1a:0:1:ac1f:0/112", "10.0.1.2", False),
        ("Running", True, "fd7a:115c:a1e0:b1a:0:1:ac1f:0/112", "8.8.8.8", False),
    ],
)
def test_database_recipe_requires_connected_development_route(
    state: str,
    online: bool,
    route: str,
    address: str,
    allowed: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    program = (
        (kit.HERE / "DATABASE.md")
        .read_text()
        .split("<<'PY'\n", 1)[1]
        .split("\nPY\n", 1)[0]
    )
    status = {
        "BackendState": state,
        "Peer": {"router": {"Online": online, "PrimaryRoutes": [route]}},
    }
    with (
        patch.object(
            f.sys, "argv", ["recipe", "synthetic.invalid", json.dumps(status)]
        ),
        patch.object(
            socket, "getaddrinfo", return_value=[(0, 0, 0, "", (address, 5432))]
        ),
    ):
        if allowed:
            exec(compile(program, "DATABASE.md", "exec"), {})
            assert capsys.readouterr().out.strip() == "fd7a:115c:a1e0:b1a:0:1:ac1f:102"
        else:
            with pytest.raises(SystemExit, match="1"):
                exec(compile(program, "DATABASE.md", "exec"), {})
            assert capsys.readouterr().out == ""


def test_private_api_key_entry_rotation_and_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "work"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with (
        patch.object(f.sys.stdin, "isatty", return_value=True),
        patch.object(
            f.getpass, "getpass", side_effect=[" synthetic-first ", "synthetic-next"]
        ) as prompt,
    ):
        f.set_api_key(root)
        assert f.load_api_key(root) == "synthetic-first"
        f.set_api_key(root)
        assert prompt.call_count == 2
    key_path = f.api_key_path(root)
    assert f.load_api_key(root) == "synthetic-next"
    assert key_path.stat().st_mode & 0o777 == 0o600
    assert key_path.parent.stat().st_mode & 0o777 == 0o700
    assert list(key_path.parent.iterdir()) == [key_path]
    assert not root.exists()
    assert "OPENAI_API_KEY" not in os.environ
    assert "synthetic" not in capsys.readouterr().out
    monkeypatch.setenv("OPENAI_API_KEY", " synthetic-override ")
    assert f.load_api_key(root) == "synthetic-override"


def test_api_key_rejects_noninteractive_and_empty_entry(tmp_path: Path) -> None:
    root = tmp_path / "work"
    with (
        patch.object(f.sys.stdin, "isatty", return_value=False),
        pytest.raises(ValueError, match="interactive terminal"),
    ):
        f.set_api_key(root)
    with (
        patch.object(f.sys.stdin, "isatty", return_value=True),
        patch.object(f.getpass, "getpass", return_value="  "),
        pytest.raises(ValueError, match="empty"),
    ):
        f.set_api_key(root)
    with (
        patch.object(f.sys.stdin, "isatty", return_value=True),
        patch.object(f.getpass, "getpass", side_effect=f.getpass.GetPassWarning()),
        pytest.raises(ValueError, match="hidden API key entry"),
    ):
        f.set_api_key(root)
    assert not f.api_key_path(root).exists()


@pytest.mark.parametrize("invalid", ["empty", "permissions", "symlink", "fifo"])
def test_api_key_rejects_unsafe_or_empty_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path = f.api_key_path(tmp_path / "work")
    path.parent.mkdir()
    if invalid == "symlink":
        target = tmp_path / "other"
        target.write_text("synthetic-key")
        path.symlink_to(target)
    elif invalid == "fifo":
        os.mkfifo(path, mode=0o600)
    else:
        path.write_text("" if invalid == "empty" else "synthetic-key")
        path.chmod(0o600 if invalid == "empty" else 0o644)
    with pytest.raises(ValueError, match="API key"):
        f.load_api_key(tmp_path / "work")


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    with patch.object(
        socket.socket, "connect", side_effect=AssertionError("network forbidden")
    ):
        return smoke.prepared(tmp_path_factory.mktemp("factory-template"))


@pytest.fixture
def factory(prepared: tuple[Path, str], tmp_path: Path) -> tuple[Path, str]:
    root, source_id = prepared
    work = tmp_path / "work"
    shutil.copytree(root, work)
    return work, source_id


def application(
    factory: tuple[Path, str], role: str = "candidate"
) -> tuple[Path, str, dict[str, Any]]:
    root, source_id = factory
    run_id = f.evaluate(root, "4.0.0", source_id, role, mock=True)
    return root, run_id, f.application(root, run_id)[1]


@pytest.mark.parametrize("command", ["calibrate", "evaluate"])
def test_missing_api_key_stops_before_paid_attempt(
    factory: tuple[Path, str], monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    root, source_id = factory
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    before = (root / "ledger.jsonl").read_bytes()
    existing_runs = list((root / "runs").iterdir())
    # The fixture is synthetic; bypass only that guard to exercise real key loading.
    with (
        patch.object(f, "paid_guard"),
        patch.object(
            socket.socket, "connect", side_effect=AssertionError("network forbidden")
        ),
        pytest.raises(ValueError, match="run factory set-api-key"),
    ):
        if command == "calibrate":
            f.calibrate(root, "4.0.0", budget=1, authorization="Test")
        else:
            f.evaluate(
                root, "4.0.0", source_id, "candidate", budget=1, authorization="Test"
            )
    assert (root / "ledger.jsonl").read_bytes() == before
    assert list((root / "runs").iterdir()) == existing_runs


def test_validate_cli_does_not_freeze_or_change_history(
    factory: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, _ = factory
    before = {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }
    monkeypatch.setattr(
        f.sys,
        "argv",
        ["factory", "--root", str(root), "validate", "--inputs", str(root / "drafts")],
    )
    with patch.object(
        socket.socket, "connect", side_effect=AssertionError("network forbidden")
    ):
        f.main()
    assert json.loads(capsys.readouterr().out) == {
        "valid": True,
        "cases": {"training": 100, "holdout": 50, "shadow": 10},
    }
    assert {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    } == before


def replace_report(root: Path, run_id: str, report: dict[str, Any]) -> None:
    report["evidence_sha256"] = kit.digest(
        {k: v for k, v in report.items() if k != "evidence_sha256"}
    )
    (root / "runs" / run_id / "report.json").write_text(json.dumps(report))


def assessment(blind: dict[str, Any]) -> dict[str, Any]:
    return {
        "audit_sha256": blind["audit_sha256"],
        "reviewer": "Test",
        "evidence": "Offline synthetic review",
        "items": [
            {
                "token": i["token"],
                **dict.fromkeys(f.DIMENSIONS, True),
                "actor_validity": "valid",
                "evidence": "Synthetic assessment",
            }
            for i in blind["items"]
        ],
    }


def test_allocations_settings_and_one_full_calibration(
    factory: tuple[Path, str],
) -> None:
    root, _ = factory
    directory, manifest = f.suite(root, "4.0.0")
    assert [manifest["splits"][s]["count"] for s in f.SPLITS] == [100, 50, 10]
    calibration = f.checked_report(directory / "calibration/report.json")
    assert len(calibration["rows"]) == 180 and len(calibration["actor_check"]) == 160
    assert f.CONTRACT["settings"]["actor_params"] == run.EVAL_MODEL_PARAMS
    assert f.CONTRACT["settings"]["judge_params"] == run.JUDGE_MODEL_PARAMS
    with pytest.raises(FileExistsError):
        f.calibrate(root, "4.0.0", mock=True)


@pytest.mark.parametrize(
    "change", ["allocation", "group", "duplicate", "actor", "time", "reference"]
)
def test_input_validation(factory: tuple[Path, str], change: str) -> None:
    root, _ = factory
    path = root / "drafts/holdout/cases.jsonl"
    cases = [json.loads(line) for line in path.read_text().splitlines()]
    if change == "allocation":
        cases[0]["kind"] = "annual"
    elif change == "group":
        cases[0]["split_group"] = "smoke-training-001"
    elif change == "duplicate":
        cases[0]["prompt"] = cases[1]["prompt"]
    elif change == "actor":
        cases[0]["actor"]["facts"] += " Use get_current_toll_price."
    elif change == "time":
        cases[0]["frozen_time"] = "2026-10-01T08:00:00"
    else:
        examples_path = root / "drafts/holdout/examples.json"
        examples_path.write_text(json.dumps(json.loads(examples_path.read_text())[1:]))
    path.write_text("".join(json.dumps(c) + "\n" for c in cases))
    with pytest.raises(ValueError):
        f.validate_splits(root / "drafts")


@pytest.mark.parametrize("budget", [1, 2, 3, 4, 5])
def test_factory_requires_five_turns_including_opening(
    factory: tuple[Path, str], budget: int
) -> None:
    root, _ = factory
    path = root / "drafts/holdout/cases.jsonl"
    cases = [json.loads(line) for line in path.read_text().splitlines()]
    cases[0]["actor"]["max_turns"] = budget
    # A one-turn reference and minimum do not justify reducing the actor budget.
    assert cases[0]["minimum_user_turns"] == 1
    path.write_text("".join(json.dumps(c) + "\n" for c in cases))
    if budget == 5:
        assert set(f.validate_splits(root / "drafts")) == set(f.SPLITS)
    else:
        with pytest.raises(ValueError, match="five turns including the opening"):
            f.validate_splits(root / "drafts")


@pytest.mark.parametrize(
    ("point", "canonical"),
    [
        ("greenway:7:entry:EB", "greenway:7"),
        ("greenway:7:exit:WB", "greenway:7"),
        ("dtr:1819:exit:WB", "dtr:1819"),
        ("i495:1819ND", "i495:181"),
        ("i495:180SO", "i495:181"),
        ("i495:182SD", "i495:182"),
        ("i495:184SD", "i495:183"),
        ("i95:211NO", "i95:211ND"),
        ("i95:211SD", "i95:211ND"),
        ("i95:219NO", "i95:219NO"),
        ("i95:220SD", "i95:219NO"),
        ("i95:226SD", "i95:2229ND"),
        ("i95:235SD", "i95:234NO"),
        ("i95:22329ND", "i95:22329ND"),
        ("airport_iad", "airport_iad"),
    ],
)
def test_canonical_catalog_access(point: str, canonical: str) -> None:
    assert f.canonical_access(point) == canonical


def add_route_case(
    drafts: Path,
    split: str,
    legs: list[tuple[str, str]],
    *,
    kind: str = "current",
    number: int | None = None,
) -> None:
    """Independently authored receipts in an allocated synthetic smoke case."""
    directory = drafts / split
    cases_path = directory / "cases.jsonl"
    cases = [json.loads(line) for line in cases_path.read_text().splitlines()]
    case = next(
        c
        for c in cases
        if c["kind"] == kind
        and (split != "training" or c["number"] > 20)
        and (number is None or c["number"] == number)
    )
    case["max_tool_calls"] = 1
    name = case["id"] + ".json"
    case["steps"] = [{"fixture": name, "min_turn": 1, "required_user_patterns": []}]
    time = (
        "2026-10-01T08:00:00-04:00"
        if split == "training"
        else "2026-10-02T08:00:00-04:00"
    )
    case["frozen_time"] = time
    labels = {
        p.point_id: p.label
        for p in f.parse_prompt_points(
            json.loads((directory / "prompt-points.json").read_text())
        )
    }
    origin, destination = legs[0]
    case["prompt"] = (
        f"Please check {labels[origin]} to {labels[destination]} for my synthetic {split} trip {case['number']}."
    )
    case["actor"]["facts"] = (
        "You drive a two-axle passenger car with E-ZPass in toll mode. The supplied endpoints are intentional."
    )
    case["actor"]["goal"] = (
        "Get the requested estimate, or learn why pricing is unavailable."
    )
    provenance = {
        "kind": "synthetic",
        "source": "route guard regression",
        "note": "No packet or benchmark case used.",
    }
    arguments: dict[str, Any]
    if kind == "annual":
        case["prompt"] += (
            f" Return from {labels[legs[1][0]]} to {labels[legs[1][1]]}; Mondays, leaving at 7 AM and returning at 5 PM, 40 annual days, gross salary $90,000."
        )
        arguments = {
            role: {
                "origin_point_id": origin,
                "destination_point_id": destination,
                "departure_time": departure,
            }
            for role, (origin, destination), departure in zip(
                ("outbound", "return"), legs, ("07:00:00", "17:00:00"), strict=True
            )
        }
        arguments.update(
            weekdays=["monday"],
            planned_annual_commute_days=40,
            gross_annual_income_usd="90000.00",
        )
        tool = "get_annual_toll_ballpark"
        error_text = (
            f"Unable to calculate the annual toll ballpark. Reference: {case['id']}."
        )
    else:
        origin, destination = legs[0]
        arguments = {
            "origin_point_id": origin,
            "destination_point_id": destination,
            "pricing_profile": {
                "vehicle_class": "two_axle_passenger",
                "payment_method": "e_zpass",
                "transponder_mode": "toll",
            },
        }
        tool = "get_current_toll_price"
        error_text = f"Unable to get the current toll price. Reference: {case['id']}."
    fixture: dict[str, Any] = {
        "tool": tool,
        "input": arguments,
        "result": {
            "toolUseId": case["id"],
            "status": "error",
            "content": [{"text": error_text}],
        },
        "is_error": True,
        "provenance": provenance,
    }
    response = "Pricing failed, so I cannot give an estimate."
    if kind == "current" and legs[0][0].startswith("i66:"):
        price = "3.00" if split == "training" else "4.00"
        fixture["is_error"] = False
        fixture["result"] = {
            **arguments,
            "method": "latest_complete_current_facility_prices",
            "evaluated_at": time,
            "maximum_observation_age_minutes": 30,
            "source_kind": "observed",
            "total_usd": price,
            "components": [
                {
                    "route_step_id": "step-1",
                    "price_usd": price,
                    "source_kind": "observed",
                    "pricing_method": "source_observation",
                    "facility": "i66",
                    "component_evaluated_at": time,
                    "bin_minutes": 6,
                    "bin_start": time,
                    "bin_end": time.replace("08:00:00", "08:06:00"),
                    "interval_end_at": time,
                    "observed_at": time,
                }
            ],
        }
        response = f"The current toll is ${price}, using a recent I-66 observation."
    (directory / "fixtures" / name).write_text(json.dumps(fixture))
    case["terminal_objective"] = "unavailable" if fixture["is_error"] else "answer"
    case["expected_assertion"] = response
    cases_path.write_text("".join(json.dumps(c) + "\n" for c in cases))
    examples_path = directory / "examples.json"
    examples = json.loads(examples_path.read_text())
    example = next(e for e in examples if e["case_id"] == case["id"])
    example["turns"] = [
        {
            "user": case["prompt"],
            "response": response,
            "calls": [
                {
                    "name": tool,
                    **{k: fixture[k] for k in ("input", "result", "is_error")},
                }
            ],
        }
    ]
    examples_path.write_text(json.dumps(examples))


@pytest.mark.parametrize("split", ["holdout", "shadow"])
@pytest.mark.parametrize(
    ("kind", "training", "holdout"),
    [
        (
            "current",
            [("greenway:7:entry:EB", "greenway:28:exit:EB")],
            [("greenway:7:entry:EB", "greenway:28:exit:EB")],
        ),
        (
            "current",
            [("greenway:7:entry:EB", "greenway:28:exit:EB")],
            [("greenway:28:entry:WB", "greenway:7:exit:WB")],
        ),
        ("current", [("i495:182NO", "i495:181ND")], [("i495:180SO", "i495:182SD")]),
        ("current", [("i495:182NO", "i495:181ND")], [("i495:182NO", "i495:1819ND")]),
        ("current", [("i495:183NO", "i495:181ND")], [("i495:180SO", "i495:184SD")]),
        ("current", [("i95:219NO", "i495:181ND")], [("i495:180SO", "i95:220SD")]),
        ("current", [("i95:222NO", "i495:181ND")], [("i495:180SO", "i95:226SD")]),
        ("current", [("i95:234NO", "i495:181ND")], [("i495:180SO", "i95:235SD")]),
        ("current", [("i95:211NO", "i495:182ND")], [("i495:182SO", "i95:211SD")]),
        (
            "current",
            [("i66:4:entry:EB", "i66:12:exit:EB")],
            [("i66:12:entry:WB", "i66:4:exit:WB")],
        ),
        (
            "annual",
            [("greenway:7:entry:EB", "greenway:28:exit:EB")],
            [
                ("greenway:7:entry:EB", "greenway:28:exit:EB"),
                ("dtr:17:entry:WB", "dtr:12:exit:WB"),
            ],
        ),
        (
            "annual",
            [("greenway:7:entry:EB", "greenway:28:exit:EB")],
            [
                ("dtr:12:entry:EB", "dtr:17:exit:EB"),
                ("greenway:28:entry:WB", "greenway:7:exit:WB"),
            ],
        ),
    ],
)
def test_route_reuse_across_splits_ignores_evidence_and_groups(
    factory: tuple[Path, str],
    split: str,
    kind: str,
    training: list[tuple[str, str]],
    holdout: list[tuple[str, str]],
) -> None:
    root, _ = factory
    drafts = root / "drafts"
    add_route_case(drafts, "training", training)
    add_route_case(drafts, split, holdout, kind=kind)
    # Each split passes the full offline receipt/reference checks independently.
    for selected in ("training", split):
        golden.validate_payload(
            golden.load_cases(drafts / selected),
            drafts / selected,
            {
                p.point_id
                for p in f.parse_prompt_points(
                    json.loads((drafts / selected / "prompt-points.json").read_text())
                )
            },
            complete=False,
        )
    with pytest.raises(ValueError, match="canonical route pair crosses splits"):
        f.validate_splits(drafts)


@pytest.mark.parametrize("split", ["holdout", "shadow"])
@pytest.mark.parametrize(
    "distinct",
    [
        [("greenway:6:entry:EB", "greenway:28:exit:EB")],
        [("dtr:12:entry:EB", "dtr:17:exit:EB")],
    ],
)
def test_distinct_routes_and_within_split_reuse_are_valid(
    factory: tuple[Path, str],
    split: str,
    distinct: list[tuple[str, str]],
) -> None:
    root, _ = factory
    drafts = root / "drafts"
    route = [("greenway:7:entry:EB", "greenway:28:exit:EB")]
    add_route_case(drafts, "training", route, number=21)
    add_route_case(drafts, "training", route, number=22)
    add_route_case(drafts, split, distinct)
    assert set(f.validate_splits(drafts)) == set(f.SPLITS)


@pytest.mark.parametrize(
    ("north", "south"),
    [("209NO", "209SO"), ("217NO", "217SD"), ("218NO", "218SD"), ("216SD", "236SO")],
)
def test_distinct_i95_accesses_with_shared_stems_or_labels_remain_valid(
    factory: tuple[Path, str],
    north: str,
    south: str,
) -> None:
    root, _ = factory
    drafts = root / "drafts"
    add_route_case(drafts, "training", [(f"i95:{north}", "i95:222ND")])
    add_route_case(drafts, "holdout", [(f"i95:{south}", "i95:2229ND")])
    assert f.canonical_access(f"i95:{north}") != f.canonical_access(f"i95:{south}")
    assert set(f.validate_splits(drafts)) == set(f.SPLITS)


def test_frozen_file_and_calibration_review_bindings(factory: tuple[Path, str]) -> None:
    root, _ = factory
    review_path = root / "suites/4.0.0/calibration/review.json"
    review = f.read(review_path)
    review["evidence_sha256"] = "f" * 64
    review_path.write_text(json.dumps(review))
    with pytest.raises(ValueError, match="calibration"):
        f.measurement(root, "4.0.0")
    (root / "suites/4.0.0/holdout/cases.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="frozen inputs"):
        f.suite(root, "4.0.0")


def test_deterministic_coverage_audit_selection(factory: tuple[Path, str]) -> None:
    _, _, report = application(factory)
    selected = f.audit_selection(report)
    shuffled = deepcopy(report)
    shuffled["attempts"].reverse()
    assert f.audit_selection(shuffled) == selected
    keys = [(r["case_id"], r["trial"]) for r in selected]
    assert keys == sorted(set(keys))
    assert ("smoke-holdout-001", 3) in keys
    cases = {c["id"]: c for c in report["manifest"]["identity"]["cases"]}
    for family in f.CONTRACT["splits"]["holdout"]["coverage"]:
        for success in (True, False):
            eligible = sorted(
                (r["case_id"], r["trial"])
                for r in report["attempts"]
                if r["status"] == "scored"
                and r["overall_success"] == success
                and cases[r["case_id"]]["coverage_family"] == family
            )
            if eligible:
                assert eligible[0] in keys


def test_blinding_review_binding_and_immutable_assessments(
    factory: tuple[Path, str],
) -> None:
    root, run_id, report = application(factory)
    blind = f.audit(root, run_id)
    rendered = json.dumps(blind)
    for forbidden in (
        '"verdicts":',
        "overall_success",
        "measurement_complete",
        "source_sha256",
        report["source"]["commit"],
        run_id,
    ):
        assert forbidden not in rendered
    assert {"turns", "tool_contract", "requested_tools", "actor_replies"} <= blind[
        "items"
    ][0].keys()
    review = assessment(blind)
    stale = {**review, "audit_sha256": "a" * 64}
    with pytest.raises(ValueError, match="binding"):
        f.assessments(root, run_id, stale)
    missing = {**review, "items": review["items"][1:]}
    with pytest.raises(ValueError, match="all selected"):
        f.assessments(root, run_id, missing)
    reveal = f.assessments(root, run_id, review)
    assert reveal["application"] == report["source"]
    assert any(i["disagreements"] for i in reveal["items"])
    with pytest.raises(FileExistsError):
        f.assessments(root, run_id, review)
    assert f.application(root, run_id)[1] == report


def test_material_grading_defect_blocks_without_rewriting_scores(
    factory: tuple[Path, str], tmp_path: Path
) -> None:
    root, run_id, original = application(factory)
    blind = f.audit(root, run_id)
    reveal = f.assessments(root, run_id, assessment(blind))
    review = {
        "reveal_sha256": reveal["reveal_sha256"],
        "reviewer": "Test",
        "evidence": "Known grading defect",
        "dispositions": [
            {
                "id": i["id"],
                "dimension": key,
                "material": True,
                "disposition": "grading_defect",
                "evidence": "Repair in new calibration",
            }
            for i in reveal["items"]
            for key in i["disagreements"]
        ],
    }
    with pytest.raises(ValueError, match="every disagreement"):
        f.finish_audit(root, run_id, {**review, "dispositions": []})
    f.finish_audit(root, run_id, review)
    assert f.audit_status(root, run_id) == "blocked"
    exported = f.export_report(
        root, run_id, tmp_path / "aggregate.json", "Test", "Review"
    )
    assert (
        not exported["release_ready_evidence"] and exported["audit_status"] == "blocked"
    )
    assert f.application(root, run_id)[1] == original


def test_audit_approval_detects_changed_assessments(factory: tuple[Path, str]) -> None:
    root, run_id, _ = application(factory)
    smoke.audited(root, run_id)
    path = root / "runs" / run_id / "audit-assessments.json"
    review = f.read(path)
    review["items"][0]["outcome"] = False
    path.write_text(json.dumps(review))
    with pytest.raises(ValueError, match="stale"):
        f.audit_status(root, run_id)


@pytest.mark.parametrize("change", ["assessments", "binding"])
def test_disposition_rejects_rehashed_audit_edits(
    factory: tuple[Path, str], change: str
) -> None:
    root, run_id, _ = application(factory)
    blind = f.audit(root, run_id)
    reveal = f.assessments(root, run_id, assessment(blind))
    output = root / "runs" / run_id
    if change == "assessments":
        path = output / "audit-assessments.json"
        assessed = f.read(path)
        assessed["evidence"] = "Rewritten after seeing judge scores"
        for item, original in zip(assessed["items"], reveal["items"], strict=True):
            row = original["original"]
            item["actor_validity"] = row["actor_validity"]["status"]
            for key in f.DIMENSIONS:
                item[key] = row["verdicts"].get(key, {}).get("passed")
            original["assessment"] = item
            original["disagreements"] = []
        path.write_text(json.dumps(assessed))
        reveal["assessments_sha256"] = kit.digest(assessed)
        reveal["reveal_sha256"] = kit.digest(
            {k: v for k, v in reveal.items() if k != "reveal_sha256"}
        )
        (output / "audit-reveal.json").write_text(json.dumps(reveal))
    else:
        path = output / "audit-binding.json"
        binding = f.read(path)
        binding["mapping"][blind["items"][0]["token"]] = "changed"
        path.write_text(json.dumps(binding))
    with pytest.raises(ValueError, match="stale"):
        f.finish_audit(
            root,
            run_id,
            {
                "reveal_sha256": reveal["reveal_sha256"],
                "reviewer": "Test",
                "evidence": "Attempt to approve changed initial review",
                "dispositions": [],
            },
        )
    assert not (output / "audit-review.json").exists()


def test_disclosures_are_exact_and_reuse_approvals_go_stale(
    factory: tuple[Path, str], tmp_path: Path
) -> None:
    root, run_id, report = application(factory)
    source_id = factory[1]
    f.approve_reuse(root, "4.0.0", source_id, "Test", "Next source approval")
    destination = tmp_path / "aggregate.json"
    f.export_report(root, run_id, destination, "Recipient", "Aggregate feedback")
    event = f.ledger(root)[-1]
    assert event["payload_sha256"] == kit.sha(destination.read_bytes())
    assert (
        event["recipient"] == "Recipient"
        and event["purpose"] == "Aggregate feedback"
        and event["timestamp"]
    )
    with pytest.raises(ValueError, match="fresh approval"):
        f.evaluate(root, "4.0.0", source_id, "candidate", mock=True)
    f.disclose(root, run_id, "2" * 64, "Recipient", "Manual feedback", manual=True)
    assert f.ledger(root)[-1]["manual"]
    assert (
        f.reuse_status(root, report["measurement"]["holdout_sha256"])["disclosures"]
        == 2
    )
    f.approve_reuse(root, "4.0.0", source_id, "Test", "Fresh approval")
    f.evaluate(root, "4.0.0", source_id, "candidate", mock=True)
    with pytest.raises(ValueError, match="fresh approval"):
        f.evaluate(root, "4.0.0", source_id, "candidate", mock=True)


def test_holdout_history_survives_training_revision(factory: tuple[Path, str]) -> None:
    root, source_id = factory
    _, _, report = application(factory)
    path = root / "drafts/training/cases.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["expected_assertion"] += " Preserve route identity."
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    changed = f.freeze(
        root,
        root / "drafts",
        "4.0.1",
        {"training": "4.0.1", "holdout": "4.0.0", "shadow": "4.0.0"},
        smoke=True,
    )
    assert (
        changed["splits"]["holdout"]["sha256"]
        == report["measurement"]["holdout_sha256"]
    )
    assert f.reuse_status(root, changed["splits"]["holdout"]["sha256"])["attempts"] == 1
    calibration = f.calibrate(root, "4.0.1", mock=True)
    f.review_calibration(
        root,
        "4.0.1",
        {
            "evidence_sha256": calibration["evidence_sha256"],
            "reviewer": "Test",
            "evidence": "Synthetic",
            "dispositions": [],
        },
    )
    with pytest.raises(ValueError, match="fresh approval"):
        f.evaluate(root, "4.0.1", source_id, "candidate", mock=True)


def test_missing_slots_fixed_denominator_and_invalid_scores(
    factory: tuple[Path, str],
) -> None:
    root, run_id, report = application(factory)
    assert (
        report["overall"]["expected_trials"] == 150
        and report["overall"]["expected_cases"] == 50
    )
    assert report["overall"]["inconclusive_trials"] == 1
    missing = deepcopy(report)
    missing["attempts"].pop()
    summary = f.summarize(missing["manifest"]["identity"]["cases"], missing["attempts"])
    assert (
        summary["expected_trials"] == 150
        and summary["missing_trials"] == 1
        and not summary["complete"]
    )
    with pytest.raises(ValueError, match="duplicate"):
        f.summarize(
            report["manifest"]["identity"]["cases"],
            report["attempts"] + [report["attempts"][0]],
        )
    report["attempts"][0]["overall_success"] = not report["attempts"][0][
        "overall_success"
    ]
    replace_report(root, run_id, report)
    with pytest.raises(ValueError, match="success"):
        f.application(root, run_id)


def paired(factory: tuple[Path, str]) -> tuple[Path, str, str]:
    root, source_id = factory
    incumbent = f.evaluate(root, "4.0.0", source_id, "incumbent", mock=True)
    smoke.audited(root, incumbent)
    f.approve_reuse(root, "4.0.0", source_id, "Test", "Candidate reuse")
    candidate = f.evaluate(root, "4.0.0", source_id, "candidate", mock=True)
    smoke.audited(root, candidate)
    return root, incumbent, candidate


def test_incumbent_reuse_grouped_uncertainty_and_export_privacy(
    factory: tuple[Path, str], tmp_path: Path
) -> None:
    root, incumbent, candidate = paired(factory)
    private = f.comparison(root, candidate, incumbent)
    assert len(private["private_case_differences"]) == 50
    aggregate = private["aggregate"]
    assert aggregate["scenario_groups"] == 50
    assert aggregate["baseline"]["slots"] == aggregate["final"]["slots"] == 150
    assert aggregate["mean_paired_case_delta"] == pytest.approx(
        aggregate["successful_trial_delta"] / 150
    )
    assert len(aggregate["intervals_percent"]["delta"]) == 2
    assert sum(aggregate["final"]["case_success_histogram"]) == 50
    exported = f.export_report(
        root, candidate, tmp_path / "aggregate.json", "Test", "Comparison", incumbent
    )
    rendered = json.dumps(exported)
    assert all(
        name not in rendered
        for name in (
            "smoke-holdout",
            "Testtown",
            "private_case_differences",
            "turns",
            "dispositions",
        )
    )
    assert exported["comparison"] == aggregate
    f.approve_reuse(root, "4.0.0", factory[1], "Test", "Later candidate")
    later = f.evaluate(root, "4.0.0", factory[1], "candidate", mock=True)
    smoke.audited(root, later)
    assert f.comparison(root, later, incumbent)["aggregate"] == aggregate
    with pytest.raises(ValueError, match="incumbent already"):
        f.evaluate(root, "4.0.0", factory[1], "incumbent", mock=True)


@pytest.mark.parametrize("change", ["identity", "missing", "duplicate", "usage"])
def test_reject_incompatible_or_incomplete_comparison(
    factory: tuple[Path, str], change: str
) -> None:
    root, incumbent, candidate = paired(factory)
    path, report = f.application(root, candidate)
    if change == "identity":
        report["measurement"]["calibration_sha256"] = "f" * 64
    elif change == "missing":
        report["attempts"].pop()
        report["overall"] = f.summarize(
            report["manifest"]["identity"]["cases"], report["attempts"]
        )
    elif change == "duplicate":
        report["attempts"].append(report["attempts"][0])
    else:
        attempt = run.Attempt.model_validate(
            {
                k: v
                for k, v in report["attempts"][0].items()
                if k in run.Attempt.model_fields
            }
        )
        attempt.measurements[0].complete = False
        report["attempts"][0] = f.application_row(attempt)
        report["overall"] = f.summarize(
            report["manifest"]["identity"]["cases"], report["attempts"]
        )
    replace_report(root, candidate, report)
    with pytest.raises(ValueError):
        f.comparison(root, candidate, incumbent)
    assert path.is_dir()


def test_public_suite_export_excludes_holdout_evidence(
    factory: tuple[Path, str], tmp_path: Path
) -> None:
    root, _ = factory
    output = tmp_path / "public.zip"
    f.export_suite(root, "4.0.0", output)
    with ZipFile(output) as archive:
        assert any(name.startswith("training/") for name in archive.namelist())
        assert any(name.startswith("shadow/") for name in archive.namelist())
        assert not any(name.startswith("holdout/") for name in archive.namelist())
        assert all(
            b"smoke-holdout" not in archive.read(name) for name in archive.namelist()
        )


@pytest.mark.parametrize("tampering", ["changed", "extra", "bytecode", "symlink"])
def test_clean_allowlisted_handoff_and_snapshot_tampering(
    factory: tuple[Path, str], tmp_path: Path, tampering: str
) -> None:
    root, source_id = factory
    directory, _ = f.source(root, source_id)
    assert {
        str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()
    } == {*kit.APPLICATION, "snapshot.json"}
    if tampering == "changed":
        (directory / "agent/toll_agent.py").write_text("tampered")
    elif tampering == "extra":
        (directory / "strands.py").write_text("raise RuntimeError('unreviewed module')")
    elif tampering == "bytecode":
        (directory / "strands.pyc").write_bytes(b"unreviewed bytecode")
    else:
        (directory / "unreviewed_package").symlink_to(
            tmp_path, target_is_directory=True
        )
    with pytest.raises(ValueError, match="snapshot changed"):
        f.source(root, source_id)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    (repo / "untracked").touch()
    with pytest.raises(ValueError, match="clean and committed"):
        kit.snapshot(repo, tmp_path / "dirty.zip")


def test_backup_restore_excludes_agent_auth_and_rejects_traversal(
    factory: tuple[Path, str], tmp_path: Path
) -> None:
    root, _ = factory
    auth = root.parent / "agent-state"
    auth.mkdir()
    (auth / "auth.json").write_text("synthetic authentication sentinel")
    (auth / "openai-api-key").write_text("synthetic evaluation key sentinel")
    for name in (
        "aws/config",
        "home/.aws/sso/cache/login.json",
        "tailscale/tailscaled.state",
    ):
        path = auth / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic database authentication sentinel")
    archive = tmp_path / "backup.tar.gz"
    f.backup(root, archive)
    with tarfile.open(archive) as packed:
        assert all(
            "agent-state" not in member.name and "auth.json" not in member.name
            for member in packed
        )
        contents = b"".join(
            stream.read()
            for member in packed
            if member.isfile()
            if (stream := packed.extractfile(member)) is not None
        )
        assert b"synthetic evaluation key sentinel" not in contents
        assert b"synthetic database authentication sentinel" not in contents
    restored = tmp_path / "restored"
    restored.mkdir()
    f.restore(restored, archive)
    assert f.ledger(restored) == f.ledger(root)
    assert f.suite(restored, "4.0.0")[1] == f.suite(root, "4.0.0")[1]
    with pytest.raises(ValueError, match="fresh empty"):
        f.restore(restored, archive)
    malicious = tmp_path / "malicious.tar.gz"
    with tarfile.open(malicious, "w:gz") as packed:
        member = tarfile.TarInfo("../escape")
        member.size = 1
        packed.addfile(member, io.BytesIO(b"x"))
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    with pytest.raises(ValueError, match="unsafe"):
        f.restore(fresh, malicious)


@pytest.mark.parametrize("change", ["rewrite", "rechain", "truncate", "delete"])
def test_ledger_detects_changed_committed_history(
    factory: tuple[Path, str], change: str
) -> None:
    root, source_id = factory
    path = root / "ledger.jsonl"
    prefix = path.read_bytes()
    f.evaluate(root, "4.0.0", source_id, "candidate", mock=True)
    events = f.ledger(root)
    if change == "truncate":
        path.write_bytes(prefix)
    elif change == "delete":
        path.unlink()
    else:
        events[0]["timestamp"] = "changed"
        if change == "rechain":
            previous = "0" * 64
            for event in events:
                event["previous"] = previous
                event["sha256"] = kit.digest(
                    {k: v for k, v in event.items() if k != "sha256"}
                )
                previous = event["sha256"]
        path.write_text("".join(json.dumps(e) + "\n" for e in events))
    with pytest.raises(ValueError, match="history changed"):
        f.ledger(root)
    with pytest.raises(ValueError, match="history changed"):
        f.evaluate(root, "4.0.0", source_id, "candidate", mock=True)


def test_no_paid_or_mock_work_without_correct_authorization(
    factory: tuple[Path, str],
) -> None:
    root, _ = factory
    _, manifest = f.suite(root, "4.0.0")
    with pytest.raises(ValueError, match="paid work requires"):
        f.paid_guard(manifest, False, 25, "")
    manifest["synthetic_smoke"] = False
    with pytest.raises(ValueError, match="mock measurements"):
        f.paid_guard(manifest, True, None, "")
    for invalid in (None, -1, float("inf"), float("nan")):
        with pytest.raises(ValueError, match="authorized finite budget"):
            f.paid_guard(manifest, False, invalid, "Test authorization")


@pytest.mark.parametrize(
    "model_change",
    [
        None,
        ('model_id="gpt-6-luna"', 'model_id="gpt-6-astra"'),
        ('"max_output_tokens": 2048', '"max_output_tokens": 8192'),
        ('"effort": "low"', '"effort": "medium"'),
    ],
)
def test_source_worker_real_protocol_with_canned_provider(
    factory: tuple[Path, str], tmp_path: Path, model_change: tuple[str, str] | None
) -> None:
    root, source_id = factory
    original, _ = f.source(root, source_id)
    bundle = tmp_path / "canned-source"
    shutil.copytree(original, bundle)
    # Exercise the actual Strands application, SDK, subprocess protocol and replay.
    fixture = json.loads((kit.HERE / "examples/fixtures.json").read_text())
    case = golden.GoldenCase.model_validate_json(
        (kit.HERE / "examples/cases.jsonl").read_text().splitlines()[0]
    )
    corpus = tmp_path / "corpus"
    (corpus / "fixtures").mkdir(parents=True)
    shutil.copyfile(
        kit.HERE / "examples/prompt-points.json", corpus / "prompt-points.json"
    )
    for name, value in fixture.items():
        (corpus / "fixtures" / name).write_text(json.dumps(value))
    first = fixture[case.steps[0].fixture]
    module = bundle / "agent/toll_agent.py"
    if model_change:
        source_text = module.read_text()
        assert source_text.count(model_change[0]) == 1
        module.write_text(source_text.replace(*model_change))
    with module.open("a") as stream:
        stream.write(
            "\nimport socket as _smoke_socket\n_smoke_socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network forbidden'))\n"
        )
        stream.write("_original_smoke_model = _build_model\n")
        stream.write(f"_smoke_fixture = {first!r}\n")
        stream.write("""
def _build_model():
    model = _original_smoke_model()
    calls = 0
    async def scripted(*args, **kwargs):
        nonlocal calls
        calls += 1
        yield {"messageStart": {"role": "assistant"}}
        if calls == 1:
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "frozen", "name": _smoke_fixture["tool"]}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": __import__("json").dumps(_smoke_fixture["input"])}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": "Supported frozen quote."}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {"metadata": {"usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120}, "metrics": {"latencyMs": 1}}}
    model.stream = scripted
    return model
""")
    attempt = run.Attempt(
        id="protocol",
        case_id=case.id,
        trial=1,
        turns=[golden.Turn(user=case.prompt, response="pending", calls=[])],
    )
    messages = [case.prompt]
    journal = run.Journal(tmp_path / "protocol-run", 1)
    with patch.object(golden, "ROOT", corpus):
        if model_change:
            with pytest.raises(run.StopRun, match="source_model_config"):
                SourceAgent(
                    bundle, "synthetic-secret", case, attempt, journal, messages
                )
            assert journal.spent == 0 and not attempt.measurements
            return
        worker = SourceAgent(
            bundle, "synthetic-secret", case, attempt, journal, messages
        )
        try:
            answer = worker(case.prompt)
            assert str(answer).strip() == "Supported frozen quote."
            assert len(attempt.turns[0].calls) == 1
            assert len(attempt.measurements) == 2 and all(
                m.complete for m in attempt.measurements
            )
            assert (
                "synthetic-secret"
                not in (journal.directory / "events.jsonl").read_text()
            )
        finally:
            worker.close()
        assert not list(bundle.rglob("*.pyc"))
