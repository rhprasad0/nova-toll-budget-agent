"""Build a portable kit and clean, allowlisted application source handoffs."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import subprocess
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

HERE = Path(__file__).resolve().parent
CONTRACT = json.loads((HERE / "contract.json").read_text())
APPLICATION = (
    "agent/__init__.py",
    "agent/toll_agent.py",
    "agent-sops/nova-toll-pricing-assistant.sop.md",
    "agent_tools/currency.py",
    "agent_tools/current_price_domain.py",
    "agent_tools/get_current_toll_price.py",
    "agent_tools/get_annual_toll_ballpark.py",
    "agent_tools/validate_toll_route.py",
    "pyproject.toml",
    "uv.lock",
)
DATABASE_REFERENCES = (
    "db/schema.sql",
    "db/analysis.sql",
    "db/oracle/schema.sql",
    "db/oracle/CONTRACT.md",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value: object) -> str:
    return sha(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    )


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(
            json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        )


def snapshot(source: Path, output: Path) -> dict[str, Any]:
    """Never ship repository history, eval inputs, credentials, or untracked files."""
    source = source.resolve()
    if git(source, "status", "--porcelain", "--untracked-files=all").strip():
        raise ValueError("candidate source must be clean and committed")
    commit = git(source, "rev-parse", "HEAD").decode().strip()
    blobs = {name: git(source, "show", f"{commit}:v2/{name}") for name in APPLICATION}
    for name in APPLICATION:
        mode = git(source, "ls-tree", commit, f"v2/{name}").split()[0]
        if mode != b"100644":
            raise ValueError("candidate handoff accepts regular source files only")
    identity = {
        "commit": commit,
        "files": {name: sha(data) for name, data in blobs.items()},
    }
    identity["source_sha256"] = digest(identity)
    blobs["snapshot.json"] = json.dumps(identity, sort_keys=True).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "x", ZIP_DEFLATED) as archive:
        for name, data in sorted(blobs.items()):
            entry = ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            entry.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(entry, data)
    return identity


def read_snapshot(path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if (
            len(entries) != len(APPLICATION) + 1
            or {e.filename for e in entries} != {*APPLICATION, "snapshot.json"}
            or any(
                e.file_size > 10_000_000 or stat.S_ISLNK(e.external_attr >> 16)
                for e in entries
            )
        ):
            raise ValueError(
                "invalid snapshot allowlist, duplicates, size, or file type"
            )
        identity = json.loads(archive.read("snapshot.json"))
        files = {name: archive.read(name) for name in APPLICATION}
    if (
        set(identity) != {"commit", "files", "source_sha256"}
        or identity["files"] != {name: sha(data) for name, data in files.items()}
        or identity["source_sha256"]
        != digest({k: v for k, v in identity.items() if k != "source_sha256"})
        or len(identity["commit"]) != 40
        or any(c not in "0123456789abcdef" for c in identity["commit"])
    ):
        raise ValueError("snapshot hash or commit mismatch")
    return identity, files


def evaluator_identity() -> dict[str, Any]:
    """Pin existing evaluator bytes and the factory, including the dependency lock."""
    v2 = HERE.parents[1]
    pins = json.loads((HERE / "pins.json").read_text())
    hashes = {name: sha((v2 / name).read_bytes()) for name in pins["files"]}
    if hashes != pins["files"]:
        raise ValueError("pinned evaluator sources changed; rebuild and recalibrate")
    hashes.update(
        {
            "eval/factory/" + p.name: sha(p.read_bytes())
            for p in sorted(HERE.glob("*.py"))
        }
    )
    hashes["eval/factory/contract.json"] = sha((HERE / "contract.json").read_bytes())
    return {"source_commit": pins["commit"], "files": hashes, "sha256": digest(hashes)}


def build(output: Path) -> None:
    repo = HERE.parents[2]
    pins = json.loads((HERE / "pins.json").read_text())
    output.mkdir(parents=True, exist_ok=False)
    for name, expected in pins["files"].items():
        blob = git(repo, "show", f"{pins['commit']}:v2/{name}")
        if sha(blob) != expected:
            raise ValueError("pinned source hash mismatch")
        target = output / "runtime/v2" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    # Explicit public allowlist. Never recurse into private work or copy a repo.
    public = [
        *HERE.glob("*.py"),
        HERE / "pins.json",
        HERE / "contract.json",
        HERE / "AGENTS.md",
        HERE / "README.md",
        HERE / "DATABASE.md",
        HERE / "start-tailscale.sh",
        *HERE.glob("examples/*.json"),
        *HERE.glob("examples/*.jsonl"),
    ]
    for path in public:
        target = output / "runtime/v2/eval/factory" / path.relative_to(HERE)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    reference_commit = git(repo, "rev-parse", "HEAD").decode().strip()
    reference_hashes: dict[str, str] = {}
    for name in DATABASE_REFERENCES:
        blob = git(repo, "show", f"{reference_commit}:v2/{name}")
        target = output / "runtime/v2/eval/factory/database" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
        reference_hashes[name] = sha(blob)
    write(
        output / "runtime/v2/eval/factory/database/manifest.json",
        {"source_commit": reference_commit, "files": reference_hashes},
    )
    for name in (
        "Dockerfile",
        ".devcontainer/devcontainer.json",
        ".devcontainer/seccomp.json",
        "README.md",
        "DATABASE.md",
    ):
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((HERE / name).read_bytes())
    (output / "LICENSE").write_bytes((repo / "LICENSE").read_bytes())
    write(
        output / "kit-manifest.json",
        {
            "evaluator": evaluator_identity(),
            "files": {
                str(p.relative_to(output)): sha(p.read_bytes())
                for p in sorted(output.rglob("*"))
                if p.is_file()
            },
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("build")
    pack.add_argument("--output", type=Path, required=True)
    handoff = commands.add_parser("snapshot")
    handoff.add_argument("--source", type=Path, required=True)
    handoff.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args.output)
    else:
        print(json.dumps(snapshot(args.source, args.output), indent=2))


if __name__ == "__main__":
    main()
