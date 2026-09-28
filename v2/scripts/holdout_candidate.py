"""Export one verified development artifact for the private holdout workstation."""

from __future__ import annotations

import argparse
import ctypes
import os
import tempfile
from pathlib import Path

from eval import private_holdout as private
from scripts import check_production_release as release
from scripts import golden_gate as gate
from scripts import golden_release

PRIVATE = gate.ROOT / "v2/eval/private"
EXCHANGE = Path.home() / "Documents/private-holdout/exchange/candidate"


def output_path(path: Path) -> Path:
    path = path.expanduser().absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("candidate output cannot follow symlinks")
    path = path.resolve()
    if not (path.is_relative_to(PRIVATE.resolve()) and path != PRIVATE.resolve()) and (
        path != EXCHANGE.resolve()
    ):
        raise ValueError(
            "use ignored eval/private output or the fixed exchange/candidate"
        )
    if path.exists():
        raise FileExistsError("candidate output already exists; retain the original")
    return path


def publish(source: Path, destination: Path) -> None:
    """Linux atomic directory publication, including no overwrite during a race."""
    rename = ctypes.CDLL(None, use_errno=True).renameat2
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def export(development_run: int, output: Path, policy: Path = gate.POLICY) -> Path:
    if type(development_run) is not int or development_run <= 0:
        raise ValueError("development run must be a positive integer")
    output = output_path(output)
    policy_bytes = policy.read_bytes()
    context = golden_release.resolve(development_run)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(
        prefix=".holdout-candidate-", dir=output.parent
    ) as temporary:
        staging = Path(temporary)
        packet = staging / "candidate"
        packet.mkdir(mode=0o700)
        gate.write(packet / "context.json", context)
        context = private.context_identity(packet / "context.json")
        (packet / "policy.json").write_bytes(policy_bytes)
        private.policy_limits(packet / "policy.json")
        release.download(context["bundle_id"], packet / "release.zip")
        private.extract_agent(
            packet / "release.zip", context, staging / "verified-agent"
        )
        if golden_release.resolve(development_run) != context:
            raise ValueError("development delivery changed during export")
        # The exact downloaded ZIP is published; extraction is verification only.
        publish(packet, output_path(output))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development-run", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=gate.POLICY)
    args = parser.parse_args()
    try:
        result = export(args.development_run, args.output, args.policy)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, f"Candidate export blocked: {error}\n")
    print(f"Verified candidate packet: {result}")


if __name__ == "__main__":
    main()
