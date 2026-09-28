"""Private host supervisor. Only fixed operations cross the container boundary."""

from __future__ import annotations

import fcntl
import getpass
import hashlib
import json
import os
import re
import shutil
import socketserver
import stat
import subprocess
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

if __package__:
    from . import holdout
else:
    import holdout

LIMIT = 16_384
WORKSPACE = "tollchat-holdout-workspace"
VOLUMES = {
    "corpus": holdout.CORPUS,
    "output": holdout.OUTPUT,
    "auth": holdout.AUTH,
    "guide": "tollchat-holdout-guide",
    "notes": "tollchat-holdout-notes",
    "editor": "tollchat-holdout-editor",
}
# Values are request fields, not a generic command/argument passthrough.
ACTIONS: dict[str, set[str]] = {
    "status": set(),
    "validate": set(),
    "review_cases": set(),
    "approve_cases": {"batch", "digest", "note"},
    "freeze": {"digest", "note"},
    "review_result": {"kind", "run"},
    "approve_result": {"kind", "run", "digest", "note"},
    "init_history": {"prior_cost_usd", "prior_unknown_usage"},
    "prepare": {"note"},
    "run": {"note", "replacement_reason"},
    "import_candidate": set(),
    "import_policy": set(),
    "export_identities": set(),
    "export_summary": {"run"},
}


def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON field")
        value[key] = item
    return value


def decode(data: bytes, maximum: int = LIMIT) -> dict[str, Any]:
    if len(data) > maximum:
        raise ValueError("JSON exceeds the guide size limit")
    value: Any = json.loads(data, object_pairs_hook=object_pairs)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return cast(dict[str, Any], value)


def request_action(request: dict[str, Any]) -> str:
    action = request.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        raise ValueError("unknown guide action")
    allowed = ACTIONS[action]
    required = allowed - ({"replacement_reason"} if action == "run" else set())
    if not required <= request.keys() or set(request) - {"action"} - allowed:
        raise ValueError("incorrect action fields")
    if "note" in request and (
        not isinstance(request["note"], str)
        or not request["note"].strip()
        or len(request["note"]) > 4000
    ):
        raise ValueError(
            "record the human's explicit decision in a note (1-4000 characters)"
        )
    if "digest" in request and (
        not isinstance(request["digest"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", request["digest"])
    ):
        raise ValueError("invalid evidence digest")
    return action


def private_directory(path: Path) -> None:
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError("private directories cannot use symlinks")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir() or path.stat().st_uid != os.getuid():
        raise ValueError("private directory must belong to this operator")
    path.chmod(0o700)


def write_json(path: Path, value: object) -> None:
    if path.is_symlink():
        raise ValueError("refusing a symlink")
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class Guide:
    def __init__(self, packet: Path, root: Path) -> None:
        self.packet = packet
        self.root = root
        self.state = root / ".guide"
        self.exchange = root / "exchange"
        self.control = self.state / "control"
        self.lock = threading.Lock()
        self.api_key = ""
        self.workspace = WORKSPACE
        self.volumes = VOLUMES.copy()

    def docker(
        self,
        *args: str,
        input_data: str | None = None,
        helper_result: bool = False,
        timeout: int = 30,
    ) -> str:
        result = subprocess.run(
            ["docker", *args],
            input=input_data,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if result.returncode:
            if helper_result:
                try:
                    error = decode(result.stdout.encode())
                except ValueError:
                    error = {}
                if set(error) == {"error"} and isinstance(error["error"], str):
                    raise ValueError(error["error"])
            # Never send Docker's resolved mounts/environment or logs to the host terminal.
            raise ValueError(
                "private container operation failed; inspect workstation readiness"
            )
        return result.stdout

    def inspect(self, name: str) -> dict[str, Any] | None:
        result = subprocess.run(
            ["docker", "container", "inspect", name],
            text=True,
            capture_output=True,
            timeout=30,
        )
        if result.returncode:
            if "No such" in result.stderr:
                return None
            raise ValueError("cannot inspect private container state")
        value: Any = json.loads(result.stdout)
        return cast(dict[str, Any], value[0])

    def mount(self, volume: str, target: str, *, writable: bool = False) -> list[str]:
        return [
            "--mount",
            f"type=volume,source={self.volumes[volume]},target={target}"
            + ("" if writable else ",readonly"),
        ]

    def selected(self) -> Path | None:
        record = self.state / "selected.json"
        if not record.exists():
            return None
        value = decode(record.read_bytes())
        key = value.get("snapshot")
        if (
            set(value) != {"snapshot"}
            or not isinstance(key, str)
            or not re.fullmatch(r"[0-9a-f]{64}", key)
        ):
            raise ValueError("invalid private candidate selection")
        path = self.state / "inputs" / key
        if path.is_symlink() or not path.is_dir():
            raise ValueError("private candidate snapshot is missing")
        return path

    def helper(
        self, request: dict[str, Any], *, inputs: Path | None = None
    ) -> dict[str, Any]:
        action = request["action"]
        role = "author"
        if action not in {
            "phase",
            "validate",
            "review_cases",
            "approve_cases",
            "freeze",
        }:
            phase = self._helper({"action": "phase"}, role="author")
            if phase.get("needs_evaluator") is True:
                role = "evaluator"
            elif action != "status":
                raise ValueError(
                    "freeze and review the independent corpus before evaluator operations"
                )
        return self._helper(request, role=role, inputs=inputs)

    def _helper(
        self,
        request: dict[str, Any],
        *,
        role: str,
        inputs: Path | None = None,
    ) -> dict[str, Any]:
        action = request["action"]
        name = self.workspace + "-helper"
        previous = self.inspect(name)
        if previous is not None:
            labels = cast(dict[str, Any], previous["Config"].get("Labels") or {})
            if labels.get("tollchat.holdout") != "helper":
                raise ValueError("helper name is occupied by another container")
            self.docker("rm", "--force", name)
        command = [
            "run",
            "--rm",
            "--interactive",
            "--name",
            name,
            "--label",
            "tollchat.holdout=helper",
            *holdout.HARDEN,
            "--network",
            "none",
            "--platform",
            "linux/arm64" if role == "evaluator" else "linux/amd64",
            *self.mount("corpus", "/private", writable=action == "freeze"),
            *self.mount("guide", "/guide", writable=True),
        ]
        if role == "evaluator":
            command += self.mount("output", "/output", writable=True)
        if inputs is not None:
            if role != "evaluator":
                raise ValueError("author helpers cannot receive candidate inputs")
            command += ["--mount", f"type=bind,source={inputs},target=/input,readonly"]
        command += [holdout.IMAGES[role], "guide-data"]
        try:
            response = self.docker(
                *command,
                input_data=json.dumps(request, allow_nan=False),
                helper_result=True,
                timeout=90,
            )
        except subprocess.TimeoutExpired:
            # Killing the Docker client does not stop its container.
            self.docker("rm", "--force", name)
            raise ValueError(
                "offline helper timed out and was stopped; repair the input and retry"
            ) from None
        value = decode(response.encode(), maximum=1_048_576)
        if "error" in value:
            raise ValueError(str(value["error"]))
        return value

    def evaluation(self) -> dict[str, Any] | None:
        record = self.inspect(self.workspace + "-evaluation")
        if record is None:
            return None
        labels: dict[str, Any] = record["Config"].get("Labels") or {}
        if labels.get("tollchat.holdout") != "evaluation":
            raise ValueError(
                "evaluation container name is occupied by another container"
            )
        return {
            "running": record["State"]["Running"],
            "exit_code": record["State"]["ExitCode"],
            "run": labels.get("tollchat.run"),
            "mode": labels.get("tollchat.mode"),
        }

    def idle(self) -> None:
        state = self.evaluation()
        if state and state["running"]:
            raise ValueError("evaluation is still running; inspect status and wait")

    def network(self, suffix: str, policy: str) -> tuple[str, str]:
        network, proxy = (
            self.workspace + suffix + "-network",
            self.workspace + suffix + "-proxy",
        )
        # These names belong exclusively to this workstation's supervised processes.
        self.docker("network", "create", "--internal", network)
        try:
            self.docker(
                "create",
                "--name",
                proxy,
                *holdout.HARDEN,
                "--network",
                "bridge",
                "--label",
                "tollchat.holdout=proxy",
                holdout.IMAGES["proxy"],
                "-f",
                "/etc/squid/squid-author.conf"
                if policy == "author"
                else "/etc/squid/squid.conf",
            )
            self.docker("network", "connect", "--alias", "model-proxy", network, proxy)
            self.docker("start", proxy)
        except Exception:
            self.cleanup_network(suffix)
            raise
        return network, proxy

    def cleanup_network(self, suffix: str) -> None:
        proxy = self.workspace + suffix + "-proxy"
        record = self.inspect(proxy)
        if record is not None:
            if (
                cast(dict[str, Any], record["Config"].get("Labels") or {}).get(
                    "tollchat.holdout"
                )
                != "proxy"
            ):
                raise ValueError("proxy name is occupied by another container")
            self.docker("rm", "--force", proxy)
        subprocess.run(
            ["docker", "network", "rm", self.workspace + suffix + "-network"],
            capture_output=True,
        )

    def stop_workspace(self) -> None:
        record = self.inspect(self.workspace)
        if record is not None:
            if (
                cast(dict[str, Any], record["Config"].get("Labels") or {}).get(
                    "tollchat.holdout"
                )
                != "workspace"
            ):
                raise ValueError("workspace name is occupied by another container")
            if record["State"]["Running"]:
                self.docker("stop", "--time", "20", self.workspace)
            self.docker("rm", self.workspace)
        self.cleanup_network("")

    @staticmethod
    def proxy_env() -> list[str]:
        return [
            "--env",
            "HTTPS_PROXY=http://model-proxy:3128",
            "--env",
            "HTTP_PROXY=http://model-proxy:3128",
            "--env",
            "NO_PROXY=localhost,127.0.0.1,::1",
        ]

    def start_workspace(self, *, frozen: bool, ready: bool = False) -> None:
        self.stop_workspace()
        network, _ = self.network("", "author")
        command = [
            "create",
            "--name",
            self.workspace,
            "--label",
            "tollchat.holdout=workspace",
            *holdout.HARDEN,
            "--platform",
            "linux/amd64",
            "--network",
            network,
            *self.proxy_env(),
            "--env",
            "HOME=/home/author",
            "--env",
            "CODEX_HOME=/home/author/.codex",
            "--env",
            "DISPLAY=disabled",
            *self.mount("corpus", "/private", writable=not frozen),
            *self.mount("guide", "/guide"),
            *self.mount("notes", "/notes", writable=True),
            *self.mount("auth", "/auth", writable=True),
            *self.mount("editor", "/home/author/.vscode-server", writable=True),
            "--mount",
            f"type=bind,source={self.control},target=/control,readonly",
        ]
        if frozen and ready:
            command += self.mount("output", "/output")
        command += [holdout.IMAGES["author"], "workspace"]
        try:
            self.docker(*command)
            self.docker("start", self.workspace)
        except Exception:
            self.stop_workspace()
            raise

    def snapshot(self, *, policy_only: bool) -> dict[str, Any]:
        self.idle()
        if not self.helper({"action": "status"}).get("ready"):
            raise ValueError(
                "review and freeze the corpus before introducing a candidate"
            )
        previous = self.selected()
        if policy_only and previous is None:
            raise ValueError("import a candidate before its approved policy")
        source = previous if policy_only else self.exchange / "candidate"
        assert source is not None
        if source.is_symlink() or set(p.name for p in source.iterdir()) != {
            "release.zip",
            "context.json",
            "policy.json",
        }:
            raise ValueError(
                "candidate directory must contain exactly the three handoff files"
            )
        snapshots = self.state / "inputs"
        snapshots.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=snapshots) as directory:
            stage = Path(directory) / "candidate"
            stage.mkdir()
            for name in ("release.zip", "context.json", "policy.json"):
                path = (
                    self.exchange / "policy.json"
                    if policy_only and name == "policy.json"
                    else source / name
                )
                maximum = 2_000_000_000 if name == "release.zip" else LIMIT
                with os.fdopen(
                    os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb"
                ) as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                        raise ValueError("invalid or oversized handoff file")
                    with (stage / name).open("xb") as target:
                        shutil.copyfileobj(stream, target, length=1024 * 1024)
                if (stage / name).stat().st_size > maximum:
                    raise ValueError("handoff changed while copying")
                (stage / name).chmod(0o644)
            # Host ancestors remain 0700; the read-only bind must also work with
            # rootless Docker's remapped non-root evaluator UID.
            stage.chmod(0o755)
            result = self.helper({"action": "validate_input"}, inputs=stage)
            key = hashlib.sha256(
                b"".join(
                    holdout.checksum(stage / name).encode()
                    for name in ("release.zip", "context.json", "policy.json")
                )
            ).hexdigest()
            destination = snapshots / key
            if not destination.exists():
                stage.rename(destination)
            write_json(self.state / "selected.json", {"snapshot": key})
        return {"imported": "policy" if policy_only else "candidate", **result}

    def start_evaluation(self, request: dict[str, Any]) -> dict[str, Any]:
        self.idle()
        selected = self.selected()
        if selected is None:
            raise ValueError("import the verified candidate first")
        if not self.api_key:
            raise ValueError(
                "API key is not unlocked; enter it in the private host launcher, never in chat"
            )
        mode = request["action"]
        plan = self.helper(
            {**request, "action": "evaluation_plan", "mode": mode}, inputs=selected
        )
        arguments, run = plan.get("arguments"), plan.get("run")
        if (
            not isinstance(arguments, list)
            or not all(isinstance(v, str) for v in cast(list[Any], arguments))
            or not isinstance(run, str)
        ):
            raise ValueError("invalid evaluator plan")
        previous = self.inspect(self.workspace + "-evaluation")
        if previous is not None:
            self.docker("rm", self.workspace + "-evaluation")
        self.cleanup_network("-evaluation")
        network, _ = self.network("-evaluation", "evaluator")
        command = [
            "docker",
            "create",
            "--name",
            self.workspace + "-evaluation",
            "--label",
            "tollchat.holdout=evaluation",
            "--label",
            "tollchat.run=" + run,
            "--label",
            "tollchat.mode=" + mode,
            *holdout.HARDEN,
            "--platform",
            "linux/arm64",
            "--network",
            network,
            *self.proxy_env(),
            "--env",
            "OPENAI_API_KEY",
            *self.mount("corpus", "/private"),
            *self.mount("output", "/output", writable=True),
            "--mount",
            f"type=bind,source={selected},target=/input,readonly",
            holdout.IMAGES["evaluator"],
            *cast(list[str], arguments),
        ]
        environment = os.environ.copy()
        environment["OPENAI_API_KEY"] = self.api_key
        result = subprocess.run(
            command, env=environment, capture_output=True, text=True
        )
        if result.returncode:
            self.cleanup_network("-evaluation")
            raise ValueError("could not create evaluator; no evaluation was started")
        self.docker("start", self.workspace + "-evaluation")
        return {
            "started": run,
            "mode": mode,
            "next": "Use status to follow this execution; do not start another.",
        }

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        action = request_action(request)
        # ponytail: serialize one workstation; independent workstations need distinct volumes.
        with self.lock:
            if action == "status":
                result = self.helper(request)
                if result.get("ready"):
                    result["evaluation"] = self.evaluation()
                    selected = self.selected()
                    if selected:
                        result["candidate"] = decode(
                            (selected / "context.json").read_bytes()
                        )
                    result["api_key_ready"] = bool(self.api_key)
                return result
            self.idle()
            if action == "import_candidate" or action == "import_policy":
                return self.snapshot(policy_only=action == "import_policy")
            if action in {"prepare", "run"}:
                return self.start_evaluation(request)
            if action in {"export_identities", "export_summary"}:
                operation = "identities" if action == "export_identities" else "summary"
                value = self.helper(
                    {**request, "action": operation},
                    inputs=self.selected() if operation == "summary" else None,
                )
                name = (
                    "identities.json" if operation == "identities" else "summary.json"
                )
                write_json(self.exchange / name, value)
                return {
                    "exported": name,
                    "next": "Ask repository Codex to continue the holdout release from the exchange folder.",
                }
            if action == "freeze":
                self.stop_workspace()
                try:
                    result = self.helper(request)
                finally:
                    state = self.helper({"action": "status"})
                    self.start_workspace(
                        frozen=bool(state.get("frozen")), ready=bool(state.get("ready"))
                    )
                return {
                    **result,
                    "next": "Reconnect VS Code, then use Start/Resume Holdout.",
                }
            return self.helper(
                request, inputs=self.selected() if action == "approve_result" else None
            )

    def vscode(self) -> None:
        executable = shutil.which("code")
        if executable is None or Path(executable).resolve().name == "snap":
            raise ValueError(
                "Ask repository Codex to prepare native Linux VS Code 1.138+ and put its code command on PATH."
            )
        profile = self.root / ".vscode-private"
        private_directory(profile)
        user = profile / "User"
        user.mkdir(exist_ok=True)
        settings: dict[str, Any] = {
            "telemetry.telemetryLevel": "off",
            "extensions.autoUpdate": False,
            "extensions.autoCheckUpdates": False,
            "extensions.allowed": {
                "*": False,
                "ms-vscode-remote.remote-containers": True,
            },
            "dev.containers.copyGitConfig": False,
            "dev.containers.gitCredentialHelperConfigLocation": "none",
            "dev.containers.dockerCredentialHelper": False,
            "dev.containers.githubCLILoginWithToken": False,
            "dev.containers.mountWaylandSocket": False,
            "dev.containers.defaultExtensions": [],
            "remote.autoForwardPorts": False,
            "workbench.browser.enableRemoteProxy": True,
            "workbench.browser.dataStorage": "ephemeral",
            "workbench.browser.enableChatTools": False,
            "workbench.browser.searchEngine": "none",
            "workbench.browser.maxHistoryEntries": 0,
            "workbench.browser.openLocalhostLinks": True,
            "workbench.externalBrowser": "/bin/true",
        }
        write_json(user / "settings.json", settings)
        # Native attached-container configuration: no repository bind or container lifecycle hooks.
        storage = user / "globalStorage/ms-vscode-remote.remote-containers/nameConfigs"
        storage.mkdir(parents=True, exist_ok=True)
        write_json(
            storage / (self.workspace + ".json"),
            {
                "workspaceFolder": "/workspace",
                "remoteUser": "author",
                "userEnvProbe": "none",
                "settings": settings,
                "extensions": [],
            },
        )
        extensions = profile / "extensions"
        isolated_home = profile / "host-home"
        for directory in (
            isolated_home,
            isolated_home / ".docker",
            isolated_home / ".config",
            isolated_home / ".gnupg",
        ):
            private_directory(directory)
        # Dev Containers exposes credential RPC even when helper installation is
        # disabled. Isolate its host credential sources and disable keychain fallback.
        write_json(
            isolated_home / ".docker/config.json",
            {"credsStore": "holdout-disabled"},
        )
        endpoint = (
            os.environ.get("DOCKER_HOST")
            or self.docker(
                "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"
            ).strip()
        )
        if not endpoint.startswith("unix://"):
            raise ValueError("the private workstation requires a local Docker socket")
        environment = {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "PATH",
                "LANG",
                "LC_ALL",
                "LC_CTYPE",
                "TZ",
                "TERM",
                "USER",
                "LOGNAME",
                "DISPLAY",
                "WAYLAND_DISPLAY",
                "XAUTHORITY",
                "XDG_RUNTIME_DIR",
                "DBUS_SESSION_BUS_ADDRESS",
                "XDG_SESSION_TYPE",
                "XDG_CURRENT_DESKTOP",
            }
        }
        environment.update(
            HOME=str(isolated_home),
            XDG_CONFIG_HOME=str(isolated_home / ".config"),
            XDG_CACHE_HOME=str(isolated_home / ".cache"),
            XDG_DATA_HOME=str(isolated_home / ".local/share"),
            GNUPGHOME=str(isolated_home / ".gnupg"),
            GIT_CONFIG_GLOBAL="/dev/null",
            GIT_CONFIG_SYSTEM="/dev/null",
            GIT_CONFIG_NOSYSTEM="1",
            DOCKER_HOST=endpoint,
            VSCODE_CLI="1",
        )
        base = [
            "code",
            "--force-disable-user-env",
            "--user-data-dir",
            str(profile),
            "--extensions-dir",
            str(extensions),
        ]
        subprocess.run(
            [
                *base,
                "--install-extension",
                "ms-vscode-remote.remote-containers@0.469.0",
            ],
            env=environment,
            cwd=profile,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.Popen(
            [*base, "--sync", "off", "--new-window"],
            env=environment,
            cwd=profile,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


class Server(socketserver.UnixStreamServer):
    def __init__(self, guide: Guide) -> None:
        self.guide = guide
        super().__init__(str(guide.control / "guide.sock"), Handler)


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.connection.settimeout(30)
        try:
            request = decode(self.rfile.readline(LIMIT + 2).strip())
            result = cast(Server, self.server).guide.handle(request)
        except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
            result = {"error": str(error)}
        payload = json.dumps(result, allow_nan=False).encode() + b"\n"
        if len(payload) > 1_048_576:
            payload = b'{"error":"response exceeds guide limit"}\n'
        # Freeze intentionally disconnects the old workspace.
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(payload)


def main(packet: Path) -> None:
    os.umask(0o077)
    packet = packet.resolve(strict=True)
    root = Path.home() / "Documents/private-holdout"
    private_directory(root)
    guide = Guide(packet, root)
    for path in (guide.state, guide.exchange, guide.control):
        private_directory(path)
    # Rootless Docker maps container UID 1000 differently. Only this private
    # bind directory exposes the socket; its host ancestor stays mode 0700.
    guide.control.chmod(0o711)
    with (guide.state / "supervisor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(
                "private guide already running; reconnect in VS Code"
            ) from None
        holdout.load(packet)
        for role, command in (("author", "selfcheck"), ("evaluator", "preflight")):
            holdout.run(role, [command])
        for role in ("author", "evaluator"):
            holdout.run(role, ["network-check", role], online=True)
        socket_path = guide.control / "guide.sock"
        socket_path.unlink(missing_ok=True)
        with Server(guide) as server:
            socket_path.chmod(0o666)
            state = guide.helper({"action": "status"})
            guide.start_workspace(
                frozen=bool(state.get("frozen")), ready=bool(state.get("ready"))
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                guide.vscode()
                print(
                    "In private VS Code: Attach to Running Container → tollchat-holdout-workspace."
                )
                print(
                    "Open /workspace, then Run Task → Start/Resume Holdout. Keep this launcher open."
                )
                print(
                    "Enter 'key' here to unlock paid evaluation, or 'quit' to close the workstation."
                )
                while True:
                    choice = input("Private launcher [key/quit]: ").strip().lower()
                    if choice == "quit":
                        break
                    if choice == "key":
                        guide.api_key = getpass.getpass(
                            "Private evaluator API key (never sent to Codex): "
                        ).strip()
                        print(
                            "Evaluator key ready."
                            if guide.api_key
                            else "Evaluator key cleared."
                        )
            except (EOFError, KeyboardInterrupt):
                pass
            finally:
                server.shutdown()
                thread.join()
                guide.stop_workspace()
                guide.api_key = ""
                socket_path.unlink(missing_ok=True)
                print(
                    "Workstation closed. Private files remain; any running evaluation continues."
                )
