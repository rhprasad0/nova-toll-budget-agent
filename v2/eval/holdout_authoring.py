"""Export the public authoring kit; validate private data only in its isolated copy."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from eval import golden

V2 = Path(__file__).resolve().parents[1]
KIT_VERSION = "1.0.1"
# Explicit files, never a directory copy: development data and agent prompts
# must not enter the independent authoring session.
EXPORT_FILES = (
    "pyproject.toml",
    "uv.lock",
    "eval/HOLDOUT_AUTHORING.md",
    "eval/holdout_authoring.py",
    "eval/holdout_teaching.py",
    "eval/golden.py",
    "agent_tools/currency.py",
    "agent_tools/current_price_domain.py",
    "agent_tools/get_annual_toll_ballpark.py",
    "agent_tools/validate_toll_route.py",
)


def encoded(value: object) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def export_kit(destination: Path) -> None:
    """Build only from public contracts; no user-provided corpus is read."""
    from eval.holdout_teaching import teaching_payload

    case_schema = golden.GoldenCase.model_json_schema()
    for name, value in (
        ("held_out", True),
        ("critical", False),
        ("contract_version", 2),
    ):
        case_schema["properties"][name] = {"const": value}
        if name not in case_schema["required"]:
            case_schema["required"].append(name)
    case_schema["properties"]["coverage_family"] = {"enum": list(golden.COVERAGE)}
    case_schema["properties"]["split_group"] = {"type": "string", "minLength": 1}
    case_schema["required"].extend(["coverage_family", "split_group"])
    content = {name: (V2 / name).read_bytes() for name in EXPORT_FILES}
    content["START_HERE.md"] = content["eval/HOLDOUT_AUTHORING.md"]
    content["public/prompt-points.json"] = (
        V2 / "eval/golden/prompt-points.json"
    ).read_bytes()
    content["public/schemas.json"] = encoded(
        {
            "case": case_schema,
            "fixture": golden.Fixture.model_json_schema(),
            "example": golden.Example.model_json_schema(),
            "current_input": golden.current._PricingRequest.model_json_schema(),
            "current_result": golden.current._OUTPUT_ADAPTER.json_schema(),
            "current_error": golden.current._OperationError.model_json_schema(),
            "annual_input": golden.annual._BallparkRequest.model_json_schema(),
            "annual_result": golden.annual._OUTPUT_ADAPTER.json_schema(),
            "annual_error": golden.annual._OperationError.model_json_schema(),
        }
    )
    content["public/rubric.txt"] = golden.JUDGE_PROMPT.encode("utf-8")
    content["public/actor-prompt.txt"] = golden.ACTOR_PROMPT.encode("utf-8")
    for name, data in teaching_payload().items():
        content["teaching/" + name] = data
    content["teaching/prompt-points.json"] = content["public/prompt-points.json"]
    content["kit.json"] = encoded(
        {
            "version": KIT_VERSION,
            "coverage": golden.COVERAGE,
            "hashes": {name: sha256(data) for name, data in sorted(content.items())},
        }
    )
    # Never overwrite an archive whose identity may already be in private use.
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(content.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)


def verify_kit() -> str:
    """Detect accidental kit drift, not authenticate a maliciously replaced kit."""
    raw = (V2 / "kit.json").read_bytes()
    manifest = json.loads(raw)
    if manifest["version"] != KIT_VERSION or manifest["coverage"] != golden.COVERAGE:
        raise ValueError("unsupported kit contract")
    for name, expected in manifest["hashes"].items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("unsafe kit path")
        source = V2 / path
        if source.is_symlink() or sha256(source.read_bytes()) != expected:
            raise ValueError("kit file drift; restore the reviewed export")
    return sha256(raw)


def payload_files(root: Path) -> dict[str, str]:
    """Reject links, unexpected files, and unbounded input before parsing it."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("corpus must be a real directory")
    paths: list[Path] = []
    for path in root.rglob("*"):
        paths.append(path)
        if len(paths) > 406:
            raise ValueError("too many corpus files")
    total = 0
    hashes: dict[str, str] = {}
    for path in sorted(paths):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError("corpus symlinks are forbidden")
        if path.is_dir() and name == "fixtures":
            continue
        if not path.is_file() or not (
            name
            in {"cases.jsonl", "examples.json", "prompt-points.json", "manifest.json"}
            or re.fullmatch(r"fixtures/[a-z0-9_-]+\.json", name)
        ):
            raise ValueError("unexpected corpus path")
        total += path.stat().st_size
        if total > 50_000_000:
            raise ValueError("corpus exceeds 50 MB")
        data = path.read_bytes()
        # Avoid contradictory fields being silently accepted by JSON decoders.
        documents = data.splitlines() if name.endswith(".jsonl") else [data]
        for document in documents:
            if document.strip():
                json.loads(
                    document,
                    object_pairs_hook=unique_keys,
                    parse_constant=reject_constant,
                )
        if name != "manifest.json":
            hashes[name] = sha256(data)
    if not {"cases.jsonl", "examples.json", "prompt-points.json"} <= hashes.keys():
        raise ValueError("missing required corpus files")
    return hashes


def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def validate_private(
    root: Path, *, final: bool, kit_sha256: str, public_points: Path
) -> dict[str, Any]:
    hashes = payload_files(root)
    if hashes["prompt-points.json"] != sha256(public_points.read_bytes()):
        raise ValueError("public point catalog changed")
    cases = golden.load_cases(root)
    if not 1 <= len(cases) <= 100 or (final and len(cases) != 100):
        raise ValueError("draft needs 1-100 cases; final needs exactly 100")
    if {c.number for c in cases} != set(range(1, len(cases) + 1)):
        raise ValueError("case numbers must be unique and contiguous from 1")
    if len({c.id for c in cases}) != len(cases):
        raise ValueError("duplicate case ID")
    if len({c.split_group for c in cases}) != len(cases):
        raise ValueError("holdout requires distinct scenario groups")
    counts = Counter(c.coverage_family for c in cases)
    if any(count > golden.COVERAGE.get(family, 0) for family, count in counts.items()):
        raise ValueError("unknown or overfilled coverage family")
    if final and counts != Counter(golden.COVERAGE):
        raise ValueError("final coverage allocation is incomplete")
    for case in cases:
        if (
            not case.held_out
            or case.contract_version != 2
            or not case.split_group.strip()
            or case.critical
            or case.provenance.kind != "synthetic"
            or case.kind != case.coverage_family.split("_")[0]
        ):
            raise ValueError("invalid holdout case contract")
        if any(tag.startswith(("pair:", "pair_type:")) for tag in case.coverage_tags):
            raise ValueError("author distinct scenarios, not paired holdout variants")
        if final and case.id.startswith("teaching-"):
            raise ValueError("teaching examples are not holdout cases")
        if any(step.optional for step in case.steps):
            raise ValueError("holdout steps must be required")
    points = json.loads(public_points.read_bytes())
    golden.validate_payload(
        cases, root, {p["point_id"] for p in points}, complete=final
    )
    # The common checks permit historical fixture provenance; new holdout data
    # must be independently synthetic and must not recycle exposed scenarios.
    for name in hashes:
        if (
            name.startswith("fixtures/")
            and golden.load_fixture(Path(name).name, root).provenance.kind
            != "synthetic"
        ):
            raise ValueError("holdout fixture must have synthetic provenance")
    for item in json.loads((root / "examples.json").read_bytes()):
        example = golden.Example.model_validate(item)
        if not example.label.strip():
            raise ValueError("reference label must be nonempty")
        if (
            example.expected_failures
            and example.expected
            and all(example.expected.model_dump().values())
        ):
            raise ValueError(
                "reference with mechanical failures cannot have all passing labels"
            )
    identity = {"kit_sha256": kit_sha256, "hashes": hashes}
    manifest = {
        "version": KIT_VERSION,
        "evaluation_scope": "private_holdout",
        "case_count": len(cases),
        "trials_per_case": 3,
        "review_status": "pending",
        **identity,
        "holdout_sha256": golden.digest(identity),
    }
    frozen = root / "manifest.json"
    if frozen.exists() and json.loads(frozen.read_bytes()) != manifest:
        raise ValueError("frozen corpus drift; never silently replace a frozen holdout")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="public kit only, run in repository")
    export.add_argument("archive", type=Path)
    validate = commands.add_parser("validate", help="run only in the isolated kit")
    validate.add_argument("corpus", type=Path)
    validate.add_argument(
        "--final", action="store_true", help="freeze or verify 100 cases"
    )
    args = parser.parse_args()
    if args.command == "export":
        export_kit(args.archive)
        print("Public authoring kit exported; no private cases included.")
        return
    if not (V2 / "kit.json").is_file():
        parser.error("validate private data only in the exported isolated kit")
    try:
        manifest = validate_private(
            args.corpus,
            final=args.final,
            kit_sha256=verify_kit(),
            public_points=V2 / "public/prompt-points.json",
        )
        if args.final:
            path = args.corpus / "manifest.json"
            if not path.exists():
                with path.open("x", encoding="utf-8") as output:
                    output.write(encoded(manifest).decode("utf-8"))
            print(
                "100 cases structurally validated and frozen; private review pending."
            )
        else:
            print(
                "Draft checks passed; incomplete references are allowed. Not release-ready."
            )
    except (ValueError, OSError, KeyError) as error:
        parser.exit(
            1,
            f"Private validation failed: {error}\nKeep details in the private environment.\n",
        )


if __name__ == "__main__":
    main()
