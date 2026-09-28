#!/usr/bin/env python3
"""Run transferred holdout images; requires Python 3.10+ and Docker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

IMAGES = {
    name: f"tollchat-holdout-{name}:1" for name in ("author", "evaluator", "proxy")
}
CORPUS = "tollchat-holdout-corpus"
OUTPUT = "tollchat-holdout-results"
AUTH = "tollchat-holdout-auth"
HARDEN = [
    "--read-only",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges",
    "--pids-limit=256",
    "--tmpfs=/tmp:rw,nosuid,nodev,size=512m,mode=1777",
    "--tmpfs=/home/author:rw,nosuid,nodev,size=128m,uid=1000,gid=1000,mode=0700",
]


def docker(
    *arguments: str, capture: bool = False, input_data: str | None = None
) -> str:
    result = subprocess.run(
        ["docker", *arguments],
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        input=input_data,
    )
    return result.stdout or ""


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_images(directory: Path, roles: list[str]) -> None:
    manifest = json.loads((directory / "transfer.json").read_text())
    for role in roles:
        expected = manifest["image_ids"][role]
        actual = docker(
            "image", "inspect", "--format", "{{.Id}}", IMAGES[role], capture=True
        ).strip()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected) or actual != expected:
            raise ValueError(f"{role} image changed; reload the reviewed transfer")
        # Docker runs the verified immutable ID even if a concurrent retag occurs.
        IMAGES[role] = expected


def load(directory: Path) -> None:
    manifest = json.loads((directory / "transfer.json").read_text())
    roles = manifest["images"]
    if (
        not roles
        or any(role not in IMAGES for role in roles)
        or not {f"{role}.tar" for role in roles} <= manifest["hashes"].keys()
    ):
        raise ValueError("transfer manifest does not cover every image")
    for name, expected in manifest["hashes"].items():
        if (
            Path(name).name != name
            or (directory / name).is_symlink()
            or checksum(directory / name) != expected
        ):
            raise ValueError("transfer checksum mismatch")
    for name in manifest["images"]:
        docker("image", "load", "--input", str(directory / f"{name}.tar"))
    verify_images(directory, manifest["images"])


def run(
    role: str,
    arguments: list[str],
    *,
    online: bool = False,
    private: bool = False,
    inputs: Path | None = None,
    interactive: bool = False,
    credentials: bool = False,
    capture: bool = False,
    input_data: str | None = None,
) -> str:
    token = uuid.uuid4().hex[:12]
    network, proxy = f"holdout-{token}", f"holdout-proxy-{token}"
    network_created = proxy_created = False
    options = [
        "run",
        "--rm",
        *HARDEN,
        "--platform",
        "linux/arm64" if role == "evaluator" else "linux/amd64",
    ]
    if interactive:
        options += ["--interactive", "--tty"]
    elif input_data is not None:
        options += ["--interactive"]
    if credentials:
        if role != "evaluator" or arguments[:2] not in (
            ["evaluate", "prepare"],
            ["evaluate", "run"],
        ):
            raise ValueError("API credentials are only for evaluator prepare/run")
        if not os.environ.get("OPENAI_API_KEY"):
            raise ValueError(
                "set OPENAI_API_KEY privately; it is never saved in the packet"
            )
        options += ["--env", "OPENAI_API_KEY"]
    if role == "author" and arguments and arguments[0] in {"login", "logout", "author"}:
        options += ["--mount", f"type=volume,source={AUTH},target=/auth"]
    if private:
        options += [
            "--mount",
            f"type=volume,source={CORPUS},target=/private"
            + (",readonly" if role == "evaluator" else ""),
        ]
    if role == "evaluator":
        options += ["--mount", f"type=volume,source={OUTPUT},target=/output"]
    if inputs is not None:
        if inputs.is_symlink() or "," in str(inputs):
            raise ValueError("use a real input directory without mount separators")
        inputs = inputs.resolve(strict=True)
        if not inputs.is_dir() or any(
            (inputs / name).is_symlink() or not (inputs / name).is_file()
            for name in ("release.zip", "context.json", "policy.json")
        ):
            raise ValueError("use a dedicated real input directory without symlinks")
        if set(path.name for path in inputs.iterdir()) != {
            "release.zip",
            "context.json",
            "policy.json",
        }:
            raise ValueError(
                "input directory must contain only release.zip, context.json and policy.json"
            )
        options += ["--mount", f"type=bind,source={inputs},target=/input,readonly"]
    try:
        if online:
            docker("network", "create", "--internal", network, capture=True)
            network_created = True
            docker(
                "create",
                "--name",
                proxy,
                *HARDEN,
                "--network",
                "bridge",
                IMAGES["proxy"],
                "-f",
                "/etc/squid/squid-author.conf"
                if role == "author"
                else "/etc/squid/squid.conf",
                capture=True,
            )
            proxy_created = True
            docker("network", "connect", "--alias", "model-proxy", network, proxy)
            docker("start", proxy, capture=True)
            options += [
                "--network",
                network,
                "--env",
                "HTTPS_PROXY=http://model-proxy:3128",
                "--env",
                "HTTP_PROXY=http://model-proxy:3128",
                "--env",
                "NO_PROXY=",
            ]
        else:
            options += ["--network", "none"]
        return docker(
            *options, IMAGES[role], *arguments, capture=capture, input_data=input_data
        )
    finally:
        if proxy_created:
            docker("rm", "--force", proxy, capture=True)
        if network_created:
            docker("network", "rm", network, capture=True)


def export_private(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    os.chmod(destination, 0o700)
    for volume, name in ((CORPUS, "authoring"), (OUTPUT, "evaluation")):
        container = "holdout-export-" + uuid.uuid4().hex[:12]
        try:
            docker(
                "create",
                "--name",
                container,
                "--network",
                "none",
                *HARDEN,
                "--mount",
                f"type=volume,source={volume},target=/private,readonly",
                IMAGES["author"],
                capture=True,
            )
            docker("cp", f"{container}:/private", str(destination / name))
        finally:
            docker("rm", container, capture=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, default=Path(__file__).parent)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("guide", help="start the private VS Code holdout workstation")
    loader = commands.add_parser(
        "load", help="verify checksums and load images from transfer folder"
    )
    loader.add_argument(
        "directory", type=Path, nargs="?", default=Path(__file__).parent
    )
    for command in ("check", "network-check", "preflight", "login", "logout"):
        commands.add_parser(command)
    author = commands.add_parser("author")
    author.add_argument("--model", required=True)
    author.add_argument("prompt", nargs="?", default="")
    validate = commands.add_parser("validate")
    validate.add_argument("--final", action="store_true")
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--inputs", type=Path)
    evaluate.add_argument("arguments", nargs=argparse.REMAINDER)
    backup = commands.add_parser(
        "export-private",
        help="private machine only; never import this backup into the repository",
    )
    backup.add_argument("destination", type=Path)
    review = commands.add_parser(
        "import-review",
        help="copy one human review JSON into the private results volume",
    )
    review.add_argument("file", type=Path)
    for command in ("export-report", "export-summary"):
        export = commands.add_parser(
            command,
            help="copy a private report or aggregate summary from one named run",
        )
        export.add_argument("--run", required=True)
        export.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "guide":
        if __package__:
            from .guide import main as guide_main
        else:
            from guide import main as guide_main

        guide_main(args.packet)
        return
    if args.command != "load":
        role = (
            "evaluator"
            if args.command
            in {
                "evaluate",
                "preflight",
                "import-review",
                "export-report",
                "export-summary",
            }
            else "author"
        )
        roles = [role]
        if args.command == "network-check":
            roles.append("evaluator")
        if args.command in {"login", "author", "network-check", "evaluate"}:
            roles.append("proxy")
        verify_images(args.packet, roles)
    if args.command == "load":
        load(args.directory)
    elif args.command == "check":
        run("author", ["selfcheck"])
    elif args.command == "network-check":
        for role in ("author", "evaluator"):
            run(role, ["network-check", role], online=True)
    elif args.command == "preflight":
        run("evaluator", ["preflight"])
    elif args.command in {"login", "logout"}:
        run(
            "author",
            [args.command],
            online=args.command == "login",
            interactive=args.command == "login",
        )
    elif args.command == "author":
        if not re.fullmatch(r"[a-zA-Z0-9_.:-]+", args.model):
            parser.error("invalid model name")
        run(
            "author",
            ["author", args.model, args.prompt],
            online=True,
            private=True,
            interactive=True,
        )
    elif args.command == "validate":
        run("author", ["validate", *(["--final"] if args.final else [])], private=True)
    elif args.command == "evaluate":
        arguments = (
            args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
        )
        if not arguments or arguments[0] not in {
            "prepare",
            "run",
            "render",
            "identity",
            "init-history",
        }:
            parser.error(
                "evaluate requires -- prepare|run|render|identity|init-history and evaluator arguments"
            )
        paid = arguments[0] in {"prepare", "run"}
        if paid and args.inputs is None:
            parser.error("prepare/run require --inputs")
        run(
            "evaluator",
            ["evaluate", *arguments],
            inputs=args.inputs,
            private=True,
            online=paid,
            credentials=paid,
        )
    elif args.command == "export-private":
        export_private(args.destination)
    elif args.command == "import-review":
        if args.file.stat().st_size > 16_384:
            parser.error("review exceeds 16 KiB")
        run(
            "evaluator",
            ["import-review", args.file.name],
            input_data=args.file.read_text(),
        )
    elif args.command in {"export-report", "export-summary"}:
        filename = (
            "summary.json"
            if args.command == "export-summary"
            else "private-report.json"
        )
        data = run("evaluator", ["export-file", args.run, filename], capture=True)
        os.umask(0o077)
        with args.destination.open("x") as stream:
            stream.write(data)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
