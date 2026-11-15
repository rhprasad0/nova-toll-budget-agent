"""TollChat factory dispatcher: the sandbox, and the inbox's poller, runner and dashboard.

Usage:
  dispatcher.py preflight
      prove the proxy blocks and allows as it should
  dispatcher.py verify [JOB] [--profile P] [--branch B]
      run .github/scripts/verify.sh on branch B (default main)
  dispatcher.py poll
      record new GitHub issue events in the inbox, then exit (the systemd timer)
  dispatcher.py run
      take events from the inbox one at a time (refuses to start until Stage 6)
  dispatcher.py dashboard
      serve the read-only dashboard on 127.0.0.1:6007

Trust split (see v2/plans/FACTORY-SPEC.md): this host process holds the GitHub
login and never runs git in a repository the sandbox could write to. Code goes in
as a git bundle. verify.sh comes from this checkout of main, never from the code
under test.

Network layout per work order: the candidate PostGIS container owns a network
namespace on factory-internal, and the retained PostGIS and the sandbox join it.
So the databases are on localhost at 5432 and 5433, as in CI, and the proxy is
the only way out.
"""

import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

if not __package__:  # run as a script, python3 factory/host/dispatcher.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from factory.host import dashboard, inbox

REPO_URL = "https://github.com/rhprasad0/nova-toll-budget-agent.git"
FACTORY = Path(__file__).resolve().parent.parent
CHECKOUT = FACTORY.parent  # the dispatcher's own checkout of main
STATE = Path(os.environ.get("FACTORY_STATE", Path.home() / ".local/state/factory"))
INBOX = STATE / "inbox.db"
ORIGIN = STATE / "origin.git"  # host-only bare clone; the sandbox never touches it
IMAGE = os.environ.get("FACTORY_IMAGE", "factory-agent:dev")
POSTGIS = "postgis/postgis:17-3.5"
NETWORK = "factory-internal"
DOCKER_SOCKET = Path("/var/run/docker.sock")
TIMEOUT_SECONDS = 30 * 60
LABEL = "factory.work_order"
PHOENIX_READY = "http://127.0.0.1:6006/readyz"
MODEL = os.environ.get("FACTORY_MODEL", "claude-opus-5-5")
MAX_TURNS = "60"
SETUP_TIMEOUT_SECONDS = 20 * 60
PLACEHOLDER_TOKEN = "placeholder-the-proxy-sets-the-real-token"
CACHED_SETTINGS = "rm -f ~/.claude/remote-settings.json* ~/.claude/policy-limits.json*"
ENV_FILE = Path.home() / ".config/factory/factory.env"


def run(
    *args: str | Path, check: bool = True, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(a) for a in args],
        check=check,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def refresh_origin(branch: str = "main") -> str:
    """Fetch main and BRANCH into the host-only clone; return BRANCH's commit."""
    if not ORIGIN.exists():
        run("git", "clone", "--quiet", "--bare", REPO_URL, ORIGIN)
    refs = {f"+refs/heads/{b}:refs/heads/{b}" for b in ("main", branch)}
    run("git", "-C", ORIGIN, "fetch", "--quiet", "origin", *sorted(refs))
    return run("git", "-C", ORIGIN, "rev-parse", branch).stdout.strip()


def database_args(work_order: str) -> list[str]:
    """The candidate PostGIS, which owns the work order's network namespace.

    Nothing is published: Docker publishes no ports on an internal network, so
    tests that would read `docker port` follow DISPOSABLE_DOCKER_NETWORK instead.
    """
    return [
        "--detach", "--name", f"{work_order}-db", "--label", f"{LABEL}={work_order}",
        "--network", NETWORK,
        "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
        POSTGIS,
    ]  # fmt: skip


def retained_database_args(work_order: str) -> list[str]:
    # PGPORT sets the server's port and the default for `docker exec ... psql`.
    return [
        "--detach", "--name", f"{work_order}-db-retained", "--label", f"{LABEL}={work_order}",
        "--network", f"container:{work_order}-db",
        "--env", "POSTGRES_HOST_AUTH_METHOD=trust", "--env", "PGPORT=5433",
        POSTGIS,
    ]  # fmt: skip


def sandbox_args(work_order: str, socket_group: int) -> list[str]:
    """The sandbox container. The socket makes it a convention, not a boundary (spec, Sandbox)."""
    return [
        "--name", work_order, "--label", f"{LABEL}={work_order}",
        "--network", f"container:{work_order}-db",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", "4096",
        "--memory", "8g",
        "--cpus", "4",
        "--volume", f"{DOCKER_SOCKET}:{DOCKER_SOCKET}",
        "--group-add", str(socket_group),
        "--env", f"POSTGRES_CONTAINER_ID={work_order}-db",
        "--env", f"RETAINED_POSTGRES_CONTAINER_ID={work_order}-db-retained",
        "--env", f"DISPOSABLE_DOCKER_NETWORK=container:{work_order}-db",
        "--env", "PGHOST=localhost",
        "--env", "PGPORT=5432",
        "--env", "PGUSER=postgres",
    ]  # fmt: skip


def wait_ready(container: str, port: int) -> None:
    for _ in range(60):
        if (
            run(
                "docker",
                "exec",
                container,
                "pg_isready",
                "-h",  # TCP, so the image's temporary first-start server does not count
                "127.0.0.1",
                "-U",
                "postgres",
                "-p",
                str(port),
                check=False,
            ).returncode
            == 0
        ):
            return
        time.sleep(1)
    raise RuntimeError(f"{container} did not become ready")


def cleanup(work_order: str) -> None:
    # shortcut: containers the tests start through the socket carry no label and rely on
    # --rm; a killed run can leave one behind, so sweep by hand if `docker ps` shows strays.
    label = f"label={LABEL}={work_order}"
    ids = run("docker", "ps", "--all", "--quiet", "--filter", label).stdout.split()
    if ids:
        run("docker", "rm", "--force", "--volumes", *ids, check=False)
    volumes = run("docker", "volume", "ls", "--quiet", "--filter", label).stdout.split()
    if volumes:
        run("docker", "volume", "rm", "--force", *volumes, check=False)


def verify(
    job: str, profile: str | None, branch: str = "main", source: Path | None = None
) -> int:
    """Run verify.sh on BRANCH in a fresh sandbox; return its exit code."""
    work_order = (
        f"factory-verify-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    )
    job_dir = STATE / "jobs" / work_order
    (job_dir / "in").mkdir(parents=True)
    if source is None:
        sha, repo = refresh_origin(branch), ORIGIN
    else:
        sha, repo = run("git", "-C", source, "rev-parse", branch).stdout.strip(), source
    heads = sorted({"refs/heads/main", f"refs/heads/{branch}"})
    run("git", "-C", repo, "bundle", "create", job_dir / "in/base.bundle", *heads)
    shutil.copy(CHECKOUT / ".github/scripts/verify.sh", job_dir / "in/verify.sh")
    env = ["--env", f"FACTORY_BRANCH={branch}"]
    env += ["--env", f"DATABASE_PROFILE={profile}"] if profile else []
    print(f"{work_order}: verify {job} on {branch} {sha[:8]}, log in {job_dir}")
    try:
        run("docker", "run", *database_args(work_order))
        run("docker", "run", *retained_database_args(work_order))
        wait_ready(f"{work_order}-db", 5432)
        wait_ready(f"{work_order}-db-retained", 5433)
        run("docker", "create", *sandbox_args(work_order, DOCKER_SOCKET.stat().st_gid), *env,
            IMAGE, "run-verify.sh", job)  # fmt: skip
        run("docker", "cp", job_dir / "in", f"{work_order}:/work/in")
        started = time.monotonic()
        (STATE / "current-job").write_text(work_order)  # the proxy tags flows with it
        with (job_dir / "verify.log").open("w") as log:
            try:
                code = subprocess.run(["docker", "start", "--attach", work_order], stdout=log,
                                      stderr=subprocess.STDOUT, timeout=TIMEOUT_SECONDS).returncode  # fmt: skip
            except subprocess.TimeoutExpired:
                code = 124
        print(
            f"{work_order}: exit {code} after {time.monotonic() - started:.0f} s",
            flush=True,
        )
        return code
    finally:
        (STATE / "current-job").write_text("none")
        cleanup(work_order)


def factory_version() -> str:
    return run(
        "git", "-C", CHECKOUT, "log", "-1", "--format=%H", "--", "factory"
    ).stdout.strip()


def worker_env(work_order: str) -> list[str]:
    env = {
        "CLAUDE_CODE_OAUTH_TOKEN": PLACEHOLDER_TOKEN,
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "OTEL_TRACES_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://proxy:4318",
        "OTEL_LOG_USER_PROMPTS": "1",
        "OTEL_LOG_TOOL_DETAILS": "1",
        "OTEL_LOG_TOOL_CONTENT": "1",
        "OTEL_RESOURCE_ATTRIBUTES": f"factory.version={factory_version()},factory.work_order={work_order}",
    }
    return [arg for key, value in env.items() for arg in ("--env", f"{key}={value}")]


def start_sandbox(work_order: str, branch: str) -> tuple[Path, str]:
    job_dir = STATE / "jobs" / work_order
    (job_dir / "in").mkdir(parents=True)
    base = refresh_origin()
    run(
        "git",
        "-C",
        ORIGIN,
        "bundle",
        "create",
        job_dir / "in/base.bundle",
        "refs/heads/main",
    )
    try:
        run(
            "docker",
            "volume",
            "create",
            "--label",
            f"{LABEL}={work_order}",
            f"{work_order}-work",
        )
        run("docker", "run", *database_args(work_order))
        run("docker", "run", *retained_database_args(work_order))
        wait_ready(f"{work_order}-db", 5432)
        wait_ready(f"{work_order}-db-retained", 5433)
        run("docker", "run", "--detach", *sandbox_args(work_order, DOCKER_SOCKET.stat().st_gid),
            "--volume", f"{work_order}-work:/work", *worker_env(work_order),
            IMAGE, "sleep", "infinity")  # fmt: skip
        run("docker", "cp", job_dir / "in", f"{work_order}:/work/in")
        (STATE / "current-job").write_text(work_order)
        with (job_dir / "setup.log").open("w") as log:
            subprocess.run(["docker", "exec", work_order, "prepare-work.sh", branch], stdout=log,
                           stderr=subprocess.STDOUT, timeout=SETUP_TIMEOUT_SECONDS, check=True)  # fmt: skip
    except BaseException:
        cleanup(work_order)
        raise
    finally:
        (STATE / "current-job").write_text("none")
    return job_dir, base


def run_round(
    work_order: str,
    transcript: Path,
    prompt: str,
    traceparent: str,
    resume: str | None = None,
    stop: Callable[[], bool] = lambda: False,
) -> tuple[dict[str, Any], str]:
    if resume:
        run("docker", "exec", work_order, "sh", "-c", CACHED_SETTINGS)
    command = [
        "docker", "exec", "-i", "--env", f"TRACEPARENT={traceparent}", "--workdir", "/work/repo",
        work_order, "claude", "-p", "--input-format", "stream-json",
        "--output-format", "stream-json", "--verbose", "--model", MODEL,
        "--max-turns", MAX_TURNS, "--dangerously-skip-permissions",
        "--disallowedTools", "WebSearch,WebFetch", *(["--resume", resume] if resume else []),
    ]  # fmt: skip
    message = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": prompt}]},
    }
    ended = "done"
    (STATE / "current-job").write_text(work_order)
    try:
        with (
            transcript.open("w") as out,
            transcript.with_suffix(".err").open("w") as err,
        ):
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=out,
                                       stderr=err, text=True)  # fmt: skip
            assert process.stdin is not None
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.close()
            deadline = time.monotonic() + TIMEOUT_SECONDS
            while True:
                try:
                    process.wait(timeout=60)
                    break
                except subprocess.TimeoutExpired:
                    if stop() or time.monotonic() > deadline:
                        ended = "cancelled" if stop() else "timeout"
                        run(
                            "docker",
                            "exec",
                            work_order,
                            "bash",
                            "-c",
                            "kill -TERM -1; sleep 5; kill -KILL -1",
                            check=False,
                        )
                        process.kill()
                        process.wait()
                        break
            if ended == "done" and process.returncode:
                ended = "failed"
    finally:
        (STATE / "current-job").write_text("none")
    return final_result(transcript), ended


def final_result(transcript: Path) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for line in transcript.read_text().splitlines():
        with contextlib.suppress(json.JSONDecodeError):
            event: Any = json.loads(line)
            if (
                isinstance(event, dict)
                and cast(dict[str, Any], event).get("type") == "result"
            ):
                results.append(cast(dict[str, Any], event))
    return results[-1] if results else {}


def import_bundle(bundle: Path, branch: str, clean: Path) -> Path:
    shutil.rmtree(clean, ignore_errors=True)
    run("git", "clone", "--quiet", "--no-checkout", ORIGIN, clean)
    run("git", "-C", clean, "bundle", "verify", "--quiet", bundle)
    run(
        "git",
        "-C",
        clean,
        "fetch",
        "--quiet",
        bundle,
        f"refs/heads/{branch}:refs/heads/{branch}",
    )
    return clean


def export_branch(
    work_order: str, job_dir: Path, branch: str, base: str
) -> Path | None:
    run("docker", "stop", "--time", "5", work_order)
    try:
        made = run("docker", "run", "--rm", "--network", "none", "--cap-drop", "ALL",
                   "--volume", f"{work_order}-work:/work", IMAGE,
                   "git", "-C", "/work/repo", "bundle", "create", "/work/out.bundle",
                   f"refs/heads/{branch}", f"^{base}", check=False)  # fmt: skip
        if made.returncode:
            if "empty bundle" in made.stderr:
                return None
            raise RuntimeError(
                f"exporting {branch} failed: {made.stderr.strip()[-500:]}"
            )
        run("docker", "cp", f"{work_order}:/work/out.bundle", job_dir / "work.bundle")
    finally:
        run("docker", "start", work_order)
    return import_bundle(job_dir / "work.bundle", branch, job_dir / "clean")


def env_file() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    pairs = (
        line.split("=", 1) for line in ENV_FILE.read_text().splitlines() if "=" in line
    )
    return {key.strip(): value.strip().strip("'\"") for key, value in pairs}


def archive(path: Path, key: str) -> bool:
    bucket = env_file().get("FACTORY_TRACES_BUCKET")
    if not bucket:
        return False
    try:
        copied = run("aws", "s3", "cp", "--quiet", "--profile", "factory", path,
                     f"s3://{bucket}/factory-traces/{key}", check=False)  # fmt: skip
    except OSError:
        return False
    return copied.returncode == 0


def preflight() -> None:
    """Prove the proxy blocks an unlisted host and passes a listed one.

    mitmproxy keeps serving if its addon unloads, and then it is an open proxy.
    """
    probe = (
        "code() { curl -s --head -o /dev/null -w '%{http_code}' -m 10 \"$1\"; }; "
        'echo "$(code https://example.com) $(code https://pypi.org/simple/)"; '
        "curl -s -m 10 https://api.anthropic.com/ | grep -q 'blocked by factory proxy' "
        "&& echo no-token || echo token"
    )
    out = run("docker", "run", "--rm", "--network", NETWORK, "--cap-drop", "ALL",
              IMAGE, "bash", "-c", probe, check=False).stdout.split()  # fmt: skip
    blocked, allowed, token = [*out, "?", "?", "?"][:3]
    if blocked not in {"000", "403"} or allowed != "200" or token != "token":
        raise SystemExit(
            f"proxy preflight failed (example.com -> {blocked}, pypi.org -> {allowed}, "
            f"Anthropic -> {token})"
        )
    print("proxy preflight passed")


def admission_preflight() -> str | None:
    try:
        with urllib.request.urlopen(PHOENIX_READY, timeout=10) as response:
            if response.status != 200:
                return f"Phoenix is not ready: {response.status}"
    except OSError as error:
        return f"Phoenix is not ready at {PHOENIX_READY}: {error}"
    try:
        tailscale = run("tailscale", "status", "--json", check=False, timeout=10)
        state = json.loads(tailscale.stdout).get("BackendState")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        return f"Tailscale status failed: {error}"
    if state != "Running":
        return f"Tailscale is not running (state {state})"
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            preflight()
    except SystemExit as failure:
        return str(failure)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight")
    v = sub.add_parser("verify")
    v.add_argument(
        "job",
        nargs="?",
        default="all",
        choices=["all", "loader", "terraform", "database"],
    )
    v.add_argument("--profile", help="DATABASE_PROFILE for verify.sh, e.g. full")
    v.add_argument("--branch", default="main", help="branch to verify (default main)")
    sub.add_parser("poll")
    sub.add_parser("run")
    sub.add_parser("dashboard")
    args = parser.parse_args()
    if args.command == "preflight":
        preflight()
    elif args.command == "poll":
        print(f"poll: {inbox.poll(inbox.connect(INBOX), inbox.GhCli())} events read")
    elif args.command == "run":
        inbox.run_forever(INBOX, inbox.GhCli(), admission_preflight, cleanup)
    elif args.command == "dashboard":
        dashboard.server(INBOX).serve_forever()
    else:
        preflight()
        sys.exit(verify(args.job, args.profile, args.branch))


if __name__ == "__main__":
    main()
