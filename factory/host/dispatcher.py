"""TollChat factory dispatcher. Stage 3: run the required checks in the sandbox.

Usage:
  dispatcher.py preflight
      prove the proxy blocks and allows as it should
  dispatcher.py verify [JOB] [--profile P] [--branch B]
      run .github/scripts/verify.sh on branch B (default main)

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
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO_URL = "https://github.com/rhprasad0/nova-toll-budget-agent.git"
FACTORY = Path(__file__).resolve().parent.parent
CHECKOUT = FACTORY.parent  # the dispatcher's own checkout of main
STATE = Path(os.environ.get("FACTORY_STATE", Path.home() / ".local/state/factory"))
ORIGIN = STATE / "origin.git"  # host-only bare clone; the sandbox never touches it
IMAGE = os.environ.get("FACTORY_IMAGE", "factory-agent:dev")
POSTGIS = "postgis/postgis:17-3.5"
NETWORK = "factory-internal"
DOCKER_SOCKET = Path("/var/run/docker.sock")
TIMEOUT_SECONDS = 30 * 60
LABEL = "factory.work_order"


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

    The published ports are never used from the host: the tests read them with
    `docker port` and connect to 127.0.0.1 inside the shared namespace.
    """
    return [
        "--detach", "--name", f"{work_order}-db", "--label", f"{LABEL}={work_order}",
        "--network", NETWORK,
        "--publish", "127.0.0.1:5432:5432", "--publish", "127.0.0.1:5433:5433",
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
    ids = run(
        "docker", "ps", "--all", "--quiet", "--filter", f"label={LABEL}={work_order}"
    ).stdout.split()
    if ids:
        run("docker", "rm", "--force", "--volumes", *ids, check=False)


def verify(job: str, profile: str | None, branch: str = "main") -> int:
    """Run verify.sh on BRANCH in a fresh sandbox; return its exit code."""
    work_order = (
        f"factory-verify-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    )
    job_dir = STATE / "jobs" / work_order
    (job_dir / "in").mkdir(parents=True)
    sha = refresh_origin(branch)
    # main rides along so verify.sh can find the merge base.
    heads = sorted({"refs/heads/main", f"refs/heads/{branch}"})
    run("git", "-C", ORIGIN, "bundle", "create", job_dir / "in/base.bundle", *heads)
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
        cleanup(work_order)


def preflight() -> None:
    """Prove the proxy blocks an unlisted host and passes a listed one.

    mitmproxy keeps serving if its addon unloads, and then it is an open proxy.
    """
    probe = (
        "code() { curl -s -o /dev/null -w '%{http_code}' -m 10 \"$1\"; }; "
        'echo "$(code https://example.com) $(code https://pypi.org/simple/)"'
    )
    out = run("docker", "run", "--rm", "--network", NETWORK, "--cap-drop", "ALL",
              IMAGE, "bash", "-c", probe, check=False).stdout.split()  # fmt: skip
    blocked, allowed = [*out, "?", "?"][:2]
    if blocked not in {"000", "403"} or allowed != "200":
        raise SystemExit(
            f"proxy preflight failed (example.com -> {blocked}, pypi.org -> {allowed})"
        )
    print("proxy preflight passed")


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
    args = parser.parse_args()
    if args.command == "preflight":
        preflight()
    else:
        preflight()
        sys.exit(verify(args.job, args.profile, args.branch))


if __name__ == "__main__":
    main()
