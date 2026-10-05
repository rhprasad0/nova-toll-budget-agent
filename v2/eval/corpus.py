"""Local corpus validation and versioned identities; no model calls or credentials."""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import re
import subprocess
import sys
import traceback
from collections import Counter
from collections.abc import Generator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from importlib.metadata import distributions
from pathlib import Path
from typing import Any, TextIO, cast

from agent.toll_agent import parse_prompt_points
from eval import golden

CONTRACT_PATH = Path(__file__).with_name("contract.json")
CONTRACT = json.loads(CONTRACT_PATH.read_text())
SPLITS = ("training", "holdout", "shadow")
PUBLIC = golden.V2 / "eval/active"
digest = golden.digest

# Frozen catalog counterparts. I-95 numeric stems are not access identities:
# 209NO/209SO, for example, are several miles apart. Keep other full IDs distinct.
_I95_ACCESS_ALIASES = {
    f"i95:{point}": f"i95:{group[0]}"
    for group in (
        ("200SO", "201ND", "201SD", "221NO", "227SD"),
        ("202ND", "202NO", "202SD", "202SO"),
        ("203NO", "203SD"),
        ("206ND", "206NO", "206SD", "206SO"),
        ("208ND", "208SO"),
        ("210NO", "210SD"),
        ("211ND", "211NO", "211SD"),
        ("213NO", "213SD"),
        ("214NO", "214SO", "215ND"),
        ("2192NO", "2202SD"),
        ("219NO", "220SD"),
        ("2229ND", "222ND", "222NO", "226SD", "226SO"),
        ("22329ND", "2232ND", "223SO"),
        ("2233SO", "2239ND", "223ND"),
        ("225NO", "225SD"),
        ("228ND", "229SO"),
        ("232NO", "233SD"),
        ("234NO", "235SD"),
    )
    for point in group
}


def runtime() -> dict[str, Any]:
    return {
        "python": list(sys.version_info[:3]),
        "platform": platform.machine(),
        "installed_dependencies_sha256": digest(
            {str(d.metadata["Name"]).casefold(): d.version for d in distributions()}
        ),
    }


def input_hashes(root: Path) -> dict[str, str]:
    allowed = {"cases.jsonl", "examples.json", "prompt-points.json"}
    if root.is_symlink() or any(p.is_symlink() for p in root.rglob("*")):
        raise ValueError("corpus inputs must be regular files")
    files = [
        *sorted(root.glob("fixtures/*.json")),
        *(root / name for name in sorted(allowed)),
    ]
    if any(p.is_symlink() or not p.is_file() for p in files):
        raise ValueError("suite inputs must be regular files")
    actual = {
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file()
        and str(p.relative_to(root)) not in {"manifest.json", "review.json"}
    }
    if actual != {str(p.relative_to(root)) for p in files}:
        raise ValueError("unexpected suite input; use only the input allowlist")
    return {
        str(p.relative_to(root)): golden.hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files
    }


def canonical_access(point_id: str) -> str:
    """Group catalog access IDs across entry/exit and direction variants."""
    if point_id.startswith("i95:"):
        return _I95_ACCESS_ALIASES.get(point_id, point_id)
    network, _, access = point_id.partition(":")
    access = access.split(":")[0]
    if network == "i495":
        # 9ND is the catalog's alternate approach from I-495 southbound.
        access = re.sub(r"(?:9ND|[NS][OD])$", "", access)
        # Opposite roles at the GW Pkwy and Jones Branch boundaries.
        access = {"180": "181", "184": "183"}.get(access, access)
    return f"{network}:{access}" if access else network


def route_pairs(fixture: golden.Fixture) -> set[tuple[str, ...]]:
    """Current, outbound and return endpoint pairs, independent of evidence."""
    pairs: set[tuple[str, ...]] = set()
    for leg in (
        fixture.input,
        fixture.input.get("outbound"),
        fixture.input.get("return"),
    ):
        if isinstance(leg, dict):
            origin = leg.get("origin_point_id")
            destination = leg.get("destination_point_id")
            if isinstance(origin, str) and isinstance(destination, str):
                pairs.add(tuple(sorted(map(canonical_access, (origin, destination)))))
    return pairs


def validate_splits(
    paths: dict[str, Path],
) -> dict[str, dict[str, str]]:
    groups: dict[str, str] = {}
    evidence: dict[str, str] = {}
    routes: dict[tuple[str, ...], str] = {}
    prompts: set[str] = set()
    ids: set[str] = set()
    reference_ids: set[str] = set()
    total_negative = 0
    result: dict[str, dict[str, str]] = {}
    if not paths or set(paths) - set(SPLITS):
        raise ValueError("select training, shadow, or holdout inputs")
    for split, directory in paths.items():
        if split == "holdout":
            require_external(directory)
        result[split] = input_hashes(directory)
        cases = golden.load_cases(directory)
        allocation = CONTRACT["splits"][split]
        if (
            len(cases) != allocation["count"]
            or {c.number for c in cases} != set(range(1, len(cases) + 1))
            or Counter(c.kind for c in cases) != allocation["workflow"]
            or Counter(c.coverage_family for c in cases) != allocation["coverage"]
        ):
            raise ValueError(
                f"{split}: coverage, workflow, or numbering allocation mismatch"
            )
        points = parse_prompt_points(
            json.loads((directory / "prompt-points.json").read_text())
        )
        golden.validate_payload(
            cases, directory, {p.point_id for p in points}, complete=False
        )
        if any(case.actor.max_turns != 5 for case in cases):
            raise ValueError("actor budget must be five turns including the opening")
        examples = [
            golden.Example.model_validate(e)
            for e in json.loads((directory / "examples.json").read_text())
        ]
        for example in examples:
            reference_id = f"{example.case_id}-{example.label}"
            if reference_id in reference_ids:
                raise ValueError("duplicate calibration reference identity")
            reference_ids.add(reference_id)
        good = {
            e.case_id
            for e in examples
            if e.expected
            and all(e.expected.model_dump().values())
            and e.actor_validity == "valid"
            and not e.expected_failures
        }
        if good != {c.id for c in cases}:
            raise ValueError("each case needs a complete passing reference")
        total_negative += sum(
            e.expected is not None and not all(e.expected.model_dump().values())
            for e in examples
        )
        pairs: dict[str, list[golden.GoldenCase]] = {}
        for case in cases:
            if (
                case.contract_version != 2
                or not case.split_group
                or case.held_out != (split == "holdout")
            ):
                raise ValueError(
                    "explicit v2 scenario group and correct held_out flag required"
                )
            if case.id in ids or groups.setdefault(case.split_group, split) != split:
                raise ValueError("duplicate case ID or scenario group crosses splits")
            ids.add(case.id)
            normalized = re.sub(r"\W+", " ", case.prompt.casefold()).strip()
            if normalized in prompts:
                raise ValueError("duplicate opening request")
            prompts.add(normalized)
            for tag in case.coverage_tags:
                if tag.startswith("pair:"):
                    pairs.setdefault(tag, []).append(case)
            for step in case.steps:
                fixture = golden.load_fixture(step.fixture, directory)
                for pair in route_pairs(fixture):
                    if routes.setdefault(pair, split) != split:
                        raise ValueError("canonical route pair crosses splits")
                key = digest(
                    {k: v for k, v in fixture.model_dump().items() if k != "provenance"}
                )
                if evidence.setdefault(key, split) != split:
                    raise ValueError("equivalent fixture evidence crosses splits")
        for members in pairs.values():
            types = {
                tag
                for c in members
                for tag in c.coverage_tags
                if tag.startswith("pair_type:")
            }
            if (
                len(members) != 2
                or len({c.split_group for c in members}) != 1
                or len(types) != 1
                or not types <= {"pair_type:contrastive", "pair_type:invariance"}
            ):
                raise ValueError(
                    "behavioral pair must have two members in one scenario group"
                )
    if set(paths) == set(SPLITS) and total_negative < 20:
        raise ValueError("suite needs at least 20 labeled negative references")
    return result


def require_external(path: Path) -> None:
    """Also exclude the main checkout and sibling worktrees through common Git."""
    common = subprocess.check_output(
        [
            "git",
            "-C",
            str(golden.V2),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        text=True,
    ).strip()
    roots = {golden.V2.parent.resolve(), Path(common).resolve().parent}
    if any(
        candidate.is_relative_to(root)
        for root in roots
        for candidate in (path.absolute(), path.resolve())
    ):
        raise ValueError(
            "holdout inputs and detailed output must stay outside the repository"
        )


def private_path(path: Path) -> bool:
    try:
        require_external(path)
    except ValueError:
        return False
    return True


@contextmanager
def console(
    path: Path, output: Path | None = None, *, private: bool | None = None
) -> Generator[bool]:
    """External commands keep their diagnostics on the host, including tracebacks."""
    if private is None:
        try:
            metadata = json.loads((path / "manifest.json").read_text())
            identity = metadata.get("identity", {})
            private = metadata.get("evaluation_scope") == "holdout" or identity.get(
                "corpus", {}
            ).get("evaluation_scope") in {"holdout", "suite"}
        except (OSError, ValueError):
            private = False
    if not private:
        yield False
        return
    destination = output if output is not None else path
    require_external(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    log = destination.parent / ("." + destination.name + ".console.log")
    require_external(log)
    failed = False
    handlers: list[tuple[logging.StreamHandler[TextIO], TextIO]] = []
    loggers = [
        logging.getLogger(),
        *(
            value
            for value in logging.Logger.manager.loggerDict.values()
            if isinstance(value, logging.Logger)
        ),
    ]
    for logger in loggers:
        for handler in logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                stream_handler = cast("logging.StreamHandler[TextIO]", handler)
                if stream_handler.stream in (sys.stdout, sys.stderr):
                    handlers.append((stream_handler, stream_handler.stream))
    descriptor = os.open(
        log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    with (
        os.fdopen(descriptor, "a") as stream,
        redirect_stdout(stream),
        redirect_stderr(stream),
    ):
        os.fchmod(stream.fileno(), 0o600)
        for handler, _ in handlers:
            handler.setStream(stream)
        try:
            yield True
        except BaseException:
            traceback.print_exc()
            failed = True
        finally:
            for handler, original in handlers:
                handler.setStream(original)
    if failed:
        raise SystemExit(
            "External corpus command failed; inspect the host-side diagnostic log."
        ) from None


def version(value: str) -> tuple[int, ...]:
    if not re.fullmatch(
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value
    ):
        raise ValueError("corpus version must be semantic version 5.0.0 or newer")
    parsed = tuple(map(int, value.split(".")))
    if parsed < (5, 0, 0):
        raise ValueError("new local corpora start at 5.0.0")
    return parsed


def contract(root: Path, split: str, corpus_version: str) -> dict[str, Any]:
    version(corpus_version)
    files = validate_splits({split: root})[split]
    hashes = {**files, **golden.source_hashes()}
    return {
        "format_version": 1,
        "version": corpus_version,
        "evaluation_scope": split,
        "case_count": CONTRACT["splits"][split]["count"],
        "trials_per_case": 1,
        "actor_model": "gpt-6-luna",
        "judge_model": "gpt-6-luna",
        "tool_description_policy": golden.TOOL_DESCRIPTION_POLICY,
        "hashes": hashes,
        "corpus_sha256": digest(hashes),
    }


def freeze(root: Path, split: str, corpus_version: str) -> dict[str, Any]:
    manifest = contract(root, split, corpus_version)
    path = root / "manifest.json"
    if path.exists():
        previous = json.loads(path.read_text())
        if previous == manifest:
            return manifest
        if version(corpus_version) <= version(previous["version"]):
            raise ValueError("changed inputs require a newer corpus version")
    review = {
        "status": "pending",
        "corpus_sha256": manifest["corpus_sha256"],
        "reviewer": "",
        "evidence": "",
    }
    # Invalidate approval first; interruption cannot approve a changed manifest.
    (root / "review.json").write_text(json.dumps(review, indent=2) + "\n")
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def validate(root: Path) -> dict[str, Any]:
    golden.load_cases(root)
    path = root / "manifest.json"
    if not path.is_file():
        raise ValueError("No active golden corpus; archival references cannot execute")
    manifest = json.loads(path.read_text())
    if (
        manifest.get("format_version") != 1
        or manifest.get("evaluation_scope") not in SPLITS
    ):
        raise ValueError("No active golden corpus; archival references cannot execute")
    expected = contract(root, manifest["evaluation_scope"], manifest["version"])
    if manifest != expected:
        raise ValueError(
            "corpus inputs or protected sources changed; freeze a new version"
        )
    review = json.loads((root / "review.json").read_text())
    if (
        review.get("status") not in {"pending", "approved"}
        or review.get("corpus_sha256") != manifest["corpus_sha256"]
    ):
        raise ValueError("review must identify this exact corpus")
    if review["status"] == "approved" and (
        not review.get("reviewer") or not review.get("evidence")
    ):
        raise ValueError("approval requires an actual reviewer and evidence")
    if root.absolute() == (PUBLIC / "training").absolute():
        validate(PUBLIC / "shadow")
        validate_splits({"training": root, "shadow": PUBLIC / "shadow"})
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("validate")
    check.add_argument("--training", type=Path, default=PUBLIC / "training")
    check.add_argument("--shadow", type=Path, default=PUBLIC / "shadow")
    check.add_argument("--holdout", type=Path)
    pin = commands.add_parser("freeze")
    pin.add_argument("--corpus", type=Path, required=True)
    pin.add_argument("--split", choices=SPLITS, required=True)
    pin.add_argument("--version", required=True)
    args = parser.parse_args()
    if args.command == "validate":
        paths = {"training": args.training, "shadow": args.shadow}
        if args.holdout is not None:
            require_external(args.holdout)
            paths["holdout"] = args.holdout
        with console(args.holdout or args.training, private=args.holdout is not None):
            validate_splits(paths)
    else:
        if args.split == "holdout":
            require_external(args.corpus)
        with console(args.corpus, private=args.split == "holdout"):
            freeze(args.corpus, args.split, args.version)
    print(
        "Selected corpora validated"
        if args.command == "validate"
        else "Corpus frozen; human review pending"
    )


if __name__ == "__main__":
    main()
