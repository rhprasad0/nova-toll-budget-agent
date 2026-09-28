"""Exercise the host boundary without mounting real private Docker volumes."""

import json
import os
import socket
import subprocess
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from eval.holdout_container import guide


def workstation(tmp_path: Path) -> guide.Guide:
    instance = guide.Guide(tmp_path / "packet", tmp_path / "private")
    for path in (instance.state, instance.exchange, instance.control):
        path.mkdir(parents=True, exist_ok=True)
    return instance


def test_socket_rejects_unknown_duplicate_and_oversized_requests(
    tmp_path: Path,
) -> None:
    instance = workstation(tmp_path)
    with guide.Server(instance) as server, patch.object(instance, "docker") as docker:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            for data in (
                b'{"action":"shell","command":"pwd"}',
                b'{"action":"status","action":"freeze"}',
                b'{"action":"status","path":"/auth/auth.json"}',
                b'{"action":"freeze","digest":"bad","note":"approved"}',
                json.dumps(
                    {"action": "freeze", "digest": "a" * 64, "note": []}
                ).encode(),
                b'{"action":"status","data":"' + b"x" * guide.LIMIT + b'"}',
            ):
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.connect(str(instance.control / "guide.sock"))
                    client.sendall(data + b"\n")
                    client.shutdown(socket.SHUT_WR)
                    response = client.makefile("rb").read()
                assert "error" in json.loads(response)
            docker.assert_not_called()
        finally:
            server.shutdown()
            thread.join()


def test_freeze_quiesces_editor_before_hashing_and_restarts_readonly(
    tmp_path: Path,
) -> None:
    instance = workstation(tmp_path)
    calls: list[str] = []

    def helper(request: dict[str, object], **_: object) -> dict[str, object]:
        calls.append(str(request["action"]))
        return {"frozen": True, "ready": True}

    with (
        patch.object(instance, "idle"),
        patch.object(
            instance, "stop_workspace", side_effect=lambda: calls.append("stop")
        ),
        patch.object(instance, "helper", side_effect=helper),
        patch.object(instance, "start_workspace") as start,
    ):
        instance.handle(
            {
                "action": "freeze",
                "digest": "a" * 64,
                "note": "I reviewed these saved cases.",
            }
        )
    assert calls == ["stop", "freeze", "status"]
    start.assert_called_once_with(frozen=True, ready=True)


def test_workspace_has_no_output_before_freeze_and_readonly_corpus_after(
    tmp_path: Path,
) -> None:
    instance = workstation(tmp_path)
    for frozen, ready in ((False, False), (True, False), (True, True)):
        with (
            patch.object(instance, "stop_workspace"),
            patch.object(instance, "network", return_value=("internal", "proxy")),
            patch.object(instance, "docker") as docker,
        ):
            instance.start_workspace(frozen=frozen, ready=ready)
        command = docker.call_args_list[0].args
        corpus = f"type=volume,source={guide.VOLUMES['corpus']},target=/private"
        assert corpus + (",readonly" if frozen else "") in command
        assert any("target=/output" in value for value in command) == (frozen and ready)
        assert "OPENAI_API_KEY" not in repr(command)
        assert "docker.sock" not in repr(command)
        assert "HOME=/home/author" in command
        assert "DISPLAY=disabled" in command
        assert "target=/control,readonly" in repr(command)
        assert "target=/guide,readonly" in repr(command)


@pytest.mark.parametrize("frozen", [False, True])
def test_unapproved_status_and_import_never_expose_candidate(
    tmp_path: Path, frozen: bool
) -> None:
    instance = workstation(tmp_path)
    state = {"frozen": frozen, "ready": False}
    with (
        patch.object(instance, "helper", return_value=state),
        patch.object(instance, "selected") as selected,
        patch.object(instance, "evaluation", return_value=None) as evaluation,
    ):
        assert instance.handle({"action": "status"}) == state
        evaluation.assert_not_called()
        with pytest.raises(ValueError, match="freeze"):
            instance.handle({"action": "import_candidate"})
    selected.assert_not_called()


def test_active_evaluation_prevents_render_and_paid_repeat(tmp_path: Path) -> None:
    instance = workstation(tmp_path)
    with (
        patch.object(instance, "evaluation", return_value={"running": True}),
        patch.object(instance, "helper") as helper,
    ):
        for request in (
            {"action": "prepare", "note": "approved"},
            {"action": "review_result", "kind": "candidate", "run": "run-001"},
        ):
            with pytest.raises(ValueError, match="still running"):
                instance.handle(request)
        helper.assert_not_called()


def test_snapshot_is_independent_and_rejects_symlinks(tmp_path: Path) -> None:
    instance = workstation(tmp_path)
    source = instance.exchange / "candidate"
    source.mkdir()
    for name in ("release.zip", "context.json", "policy.json"):
        (source / name).write_text(name)
    with (
        patch.object(instance, "idle"),
        patch.object(
            instance,
            "helper",
            side_effect=[{"frozen": True, "ready": True}, {"candidate": "verified"}],
        ),
    ):
        instance.snapshot(policy_only=False)
    selected = instance.selected()
    assert selected is not None
    (source / "policy.json").write_text("changed")
    assert (selected / "policy.json").read_text() == "policy.json"
    (source / "policy.json").unlink()
    (source / "policy.json").symlink_to(tmp_path / "secret")
    with (
        patch.object(instance, "idle"),
        patch.object(instance, "helper", return_value={"frozen": True, "ready": True}),
        pytest.raises(OSError),
    ):
        instance.snapshot(policy_only=False)


def test_export_uses_validated_helper_value_only(tmp_path: Path) -> None:
    instance = workstation(tmp_path)
    summary = {"schema_version": 1, "synthetic": True}
    with (
        patch.object(instance, "idle"),
        patch.object(instance, "helper", return_value=summary) as helper,
    ):
        instance.handle({"action": "export_summary", "run": "run-001"})
    helper.assert_called_once_with({"action": "summary", "run": "run-001"}, inputs=None)
    assert json.loads((instance.exchange / "summary.json").read_text()) == summary
    assert list(instance.exchange.iterdir()) == [instance.exchange / "summary.json"]


def test_private_helper_keeps_actionable_errors_and_hides_docker_details(
    tmp_path: Path,
) -> None:
    instance = workstation(tmp_path)
    for stdout, message in (
        ('{"error":"case content changed; review it again"}', "case content changed"),
        ("", "private container operation failed"),
    ):
        result = subprocess.CompletedProcess(
            [], 1, stdout, "sensitive Docker diagnostic"
        )
        with (
            patch.object(guide.subprocess, "run", return_value=result),
            patch.object(instance, "inspect", return_value=None),
            pytest.raises(ValueError, match=message) as error,
        ):
            instance.helper({"action": "validate"})
        assert "sensitive" not in str(error.value)


def test_helpers_exclude_evaluator_and_results_until_approved(tmp_path: Path) -> None:
    instance = workstation(tmp_path)
    for approved in (False, True):
        with (
            patch.object(instance, "inspect", return_value=None),
            patch.object(
                instance,
                "docker",
                side_effect=[json.dumps({"needs_evaluator": approved}), "{}"],
            ) as docker,
        ):
            instance.helper({"action": "status"})
        probe, operation = docker.call_args_list
        assert guide.holdout.IMAGES["author"] in probe.args
        assert not any("target=/output" in value for value in probe.args)
        assert (
            guide.holdout.IMAGES["evaluator" if approved else "author"]
            in operation.args
        )
        assert any("target=/output" in value for value in operation.args) == approved
        assert "target=/auth" not in repr(docker.call_args_list)
        assert "target=/input" not in repr(docker.call_args_list)
    with (
        patch.object(instance, "inspect", return_value=None),
        patch.object(
            instance, "docker", return_value='{"needs_evaluator":false}'
        ) as docker,
        pytest.raises(ValueError, match="freeze"),
    ):
        instance.helper({"action": "evaluation_plan"})
    assert docker.call_count == 1
    assert guide.holdout.IMAGES["author"] in docker.call_args.args


def test_helper_timeout_stops_container(tmp_path: Path) -> None:
    instance = workstation(tmp_path)
    with (
        patch.object(instance, "inspect", return_value=None),
        patch.object(
            instance,
            "docker",
            side_effect=[subprocess.TimeoutExpired("docker", 90), ""],
        ) as docker,
        pytest.raises(ValueError, match="timed out and was stopped"),
    ):
        instance.helper({"action": "validate"})
    assert docker.call_args.args == ("rm", "--force", instance.workspace + "-helper")


@pytest.mark.parametrize(
    "name,policy_only",
    [
        ("release.zip", False),
        ("context.json", False),
        ("policy.json", False),
        ("policy.json", True),
    ],
)
def test_import_rejects_fifo_without_waiting_for_a_writer(
    tmp_path: Path, name: str, policy_only: bool
) -> None:
    instance = workstation(tmp_path)
    source = instance.exchange / "candidate"
    source.mkdir(exist_ok=True)
    for item in ("release.zip", "context.json", "policy.json"):
        (source / item).write_text("synthetic")
    fifo = (instance.exchange if policy_only else source) / name
    fifo.unlink(missing_ok=True)
    os.mkfifo(fifo)
    failures: list[Exception] = []

    def import_fifo() -> None:
        try:
            instance.snapshot(policy_only=policy_only)
        except Exception as error:
            failures.append(error)

    with (
        patch.object(instance, "idle"),
        patch.object(
            instance, "selected", return_value=source if policy_only else None
        ),
        patch.object(instance, "helper", return_value={"frozen": True, "ready": True}),
    ):
        thread = threading.Thread(target=import_fifo, daemon=True)
        thread.start()
        thread.join(timeout=2)
        blocked = thread.is_alive()
        if blocked:
            # Unblock the old implementation so a failed regression cannot hang pytest.
            os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
            thread.join(timeout=2)
    assert not blocked
    assert len(failures) == 1 and isinstance(failures[0], ValueError)
    assert str(failures[0]) == "invalid or oversized handoff file"


def test_editor_isolates_host_credential_rpc_and_gui_forwarding(tmp_path: Path) -> None:
    instance = workstation(tmp_path)
    with (
        patch.object(guide.shutil, "which", return_value="/usr/local/bin/code"),
        patch.dict(
            guide.os.environ,
            {
                "PATH": "/usr/bin",
                "DISPLAY": ":1",
                "SSH_AUTH_SOCK": "/secret/ssh",
                "GH_TOKEN": "synthetic",
                "AWS_SECRET_ACCESS_KEY": "synthetic",
                "GIT_CONFIG_PARAMETERS": "secret",
                "OPENAI_API_KEY": "synthetic",
                "VSCODE_IPC_HOOK_CLI": "/host/code.sock",
            },
            clear=True,
        ),
        patch.object(
            instance, "docker", return_value="unix:///run/user/1000/docker.sock\n"
        ) as docker,
        patch.object(guide.subprocess, "run") as install,
        patch.object(guide.subprocess, "Popen") as launch,
    ):
        instance.vscode()
    docker.assert_called_once_with(
        "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"
    )
    environment = launch.call_args.kwargs["env"]
    profile = instance.root / ".vscode-private"
    assert environment["HOME"] == str(profile / "host-home")
    assert environment["DOCKER_HOST"] == "unix:///run/user/1000/docker.sock"
    assert environment["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert environment["GIT_CONFIG_SYSTEM"] == "/dev/null"
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["VSCODE_CLI"] == "1"
    assert (
        environment["DISPLAY"] == ":1"
    )  # Host GUI needs it; container gets a dummy value.
    assert (
        not {
            "GH_TOKEN",
            "AWS_SECRET_ACCESS_KEY",
            "GIT_CONFIG_PARAMETERS",
            "SSH_AUTH_SOCK",
            "OPENAI_API_KEY",
            "VSCODE_IPC_HOOK_CLI",
        }
        & environment.keys()
    )
    assert install.call_args.kwargs["env"] == environment
    assert "--force-disable-user-env" in install.call_args.args[0]
    assert "--force-disable-user-env" in launch.call_args.args[0]
    assert launch.call_args.kwargs["cwd"] == profile
    assert json.loads((profile / "host-home/.docker/config.json").read_text()) == {
        "credsStore": "holdout-disabled"
    }
    settings = json.loads((profile / "User/settings.json").read_text())
    assert settings["dev.containers.dockerCredentialHelper"] is False
    assert settings["dev.containers.githubCLILoginWithToken"] is False
    assert settings["dev.containers.mountWaylandSocket"] is False
    assert settings["extensions.allowed"] == {
        "*": False,
        "ms-vscode-remote.remote-containers": True,
    }
    assert settings["workbench.externalBrowser"] == "/bin/true"
