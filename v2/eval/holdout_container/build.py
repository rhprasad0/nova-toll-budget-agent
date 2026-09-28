"""Build from explicit public allowlists, then export images and checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

from eval.holdout_authoring import export_kit
from eval.holdout_container.holdout import IMAGES, checksum, docker
from eval.private_holdout import SOURCES

SOURCE = Path(__file__).parent
V2 = SOURCE.parents[1]
EVALUATOR_FILES = SOURCES
AUTHOR_TOOLS = {
    **{
        f"opt/{name}": name
        for name in (
            "runtime.py",
            "guide_data.py",
            "guide_client.py",
            "PRIVATE_GUIDE.md",
        )
    },
    **{
        f"workspace/.vscode/{name}": f"workspace/.vscode/{name}"
        for name in ("tasks.json", "settings.json")
    },
}


def copy_files(names: tuple[str, ...], source: Path, target: Path) -> None:
    for name in names:
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, destination)


def audit_author(image: Path, kit: Path) -> None:
    """Check every saved layer, including files hidden by a later layer."""
    with zipfile.ZipFile(kit) as source:
        expected = set(source.namelist())
    seen: set[str] = set()
    seen_tools: set[str] = set()
    with tarfile.open(image) as archive:
        manifest = archive.extractfile("manifest.json")
        assert manifest is not None
        for item in json.load(manifest):
            for name in item["Layers"]:
                stream = archive.extractfile(name)
                assert stream is not None
                with tarfile.open(fileobj=stream) as layer:
                    for entry in layer:
                        path = Path(entry.name)
                        if (
                            ".git" in path.parts
                            or "agent-sops" in path.parts
                            or path.name
                            in {"toll_agent.py", "EXPERIMENT_JOURNAL.md", "release.zip"}
                        ):
                            raise ValueError(
                                "author image contains candidate or repository material"
                            )
                        if entry.isfile() and entry.name.startswith("opt/kit/"):
                            seen.add(entry.name.removeprefix("opt/kit/"))
                        if entry.isfile() and entry.name in AUTHOR_TOOLS:
                            tool = layer.extractfile(entry)
                            assert tool is not None
                            if hashlib.sha256(tool.read()).hexdigest() != checksum(
                                SOURCE / AUTHOR_TOOLS[entry.name]
                            ):
                                raise ValueError(
                                    "author image tool differs from its allowlisted source"
                                )
                            seen_tools.add(entry.name)
                        if (
                            entry.isfile()
                            and entry.name.startswith("opt/")
                            and not (
                                entry.name.startswith(
                                    ("opt/kit/", "opt/site/", "opt/codex/")
                                )
                                or entry.name in AUTHOR_TOOLS
                            )
                        ):
                            raise ValueError(
                                "author image contains a non-allowlisted tool"
                            )
                        if (
                            path.name == "cases.jsonl"
                            and entry.name != "opt/kit/teaching/cases.jsonl"
                        ):
                            raise ValueError("author image contains evaluation cases")
    if seen != expected:
        raise ValueError("author image kit differs from the allowlisted export")
    if seen_tools != set(AUTHOR_TOOLS):
        raise ValueError("author image is missing an allowlisted guide tool")


def build(destination: Path, roles: list[str]) -> None:
    # Exports are always ignored local artifacts, never tracked packet copies.
    destination = destination.resolve()
    private = (V2 / "eval/private").resolve()
    if not destination.is_relative_to(private):
        raise ValueError("build output must be under ignored v2/eval/private/")
    destination.mkdir(parents=True, exist_ok=False)
    archive = destination / "authoring-kit.zip"
    export_kit(archive)
    for role in roles:
        with tempfile.TemporaryDirectory(prefix=f"holdout-{role}-") as temporary:
            context = Path(temporary)
            shutil.copyfile(SOURCE / f"Dockerfile.{role}", context / "Dockerfile")
            if role == "proxy":
                copy_files(("squid.conf", "squid-author.conf"), SOURCE, context)
            else:
                requirements = context / "requirements.txt"
                subprocess.run(
                    [
                        "uv",
                        "export",
                        "--directory",
                        str(V2),
                        "--frozen",
                        "--no-emit-project",
                        "--no-header",
                        "--no-annotate",
                        *(["--no-dev"] if role == "author" else ["--all-groups"]),
                        "--output-file",
                        str(requirements),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
                subprocess.run(
                    [
                        "uv",
                        "pip",
                        "install",
                        "--python-platform",
                        "x86_64-manylinux_2_28"
                        if role == "author"
                        else "aarch64-manylinux_2_28",
                        "--python-version",
                        "3.13",
                        "--only-binary",
                        ":all:",
                        "--require-hashes",
                        "--target",
                        str(context / "site"),
                        "-r",
                        str(requirements),
                    ],
                    check=True,
                )
                if role == "author":
                    copy_files(("runtime.py", "guide_data.py"), SOURCE, context)
                    with zipfile.ZipFile(archive) as kit:
                        kit.extractall(context / "kit")
                    copy_files(("config.toml", "requirements.toml"), SOURCE, context)
                    copy_files(
                        (
                            "guide_client.py",
                            "PRIVATE_GUIDE.md",
                            "workspace/.vscode/tasks.json",
                            "workspace/.vscode/settings.json",
                        ),
                        SOURCE,
                        context,
                    )
                else:
                    (context / "empty").mkdir()
                    copy_files(EVALUATOR_FILES, V2, context / "evaluator")
            docker(
                "build",
                "--platform",
                "linux/arm64" if role == "evaluator" else "linux/amd64",
                "--tag",
                IMAGES[role],
                str(context),
            )
        docker("save", "--output", str(destination / f"{role}.tar"), IMAGES[role])
        if role == "author":
            audit_author(destination / "author.tar", archive)
    shutil.copyfile(SOURCE / "holdout.py", destination / "holdout.py")
    shutil.copyfile(SOURCE / "guide.py", destination / "guide.py")
    operator = V2 / "eval/HOLDOUT_SETUP.md"
    if operator.exists():
        shutil.copyfile(operator, destination / "HOLDOUT_SETUP.md")
    manifest = {
        "version": 1,
        "images": roles,
        "image_ids": {
            role: docker(
                "image", "inspect", "--format", "{{.Id}}", IMAGES[role], capture=True
            ).strip()
            for role in roles
        },
        "hashes": {
            path.name: checksum(path)
            for path in sorted(destination.iterdir())
            if path.is_file()
        },
    }
    (destination / "transfer.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Transfer export: {destination}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--images", choices=["all", *IMAGES], default="all")
    args = parser.parse_args()
    try:
        build(args.output, list(IMAGES) if args.images == "all" else [args.images])
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
