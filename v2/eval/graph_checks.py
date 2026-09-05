# pyright: basic
"""Offline metric for eval-graph. No agent execution or orchestration."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, NoReturn, cast

ROOT = Path(__file__).resolve().parent
IDENTITY = (
    "model",
    "prompt_hash",
    "tool_contract_hash",
    "dataset_hash",
    "commit",
    "artifact_digest",
    "grader_digest",
)
HASH_FIELDS = set(IDENTITY) - {"model", "commit"}


def require(condition: object, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def read_json(path: Path) -> Any:  # noqa: ANN401 - arbitrary JSON boundary
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def constant(_: str) -> NoReturn:
        raise ValueError("non-finite JSON number")

    return json.loads(
        path.read_text(), object_pairs_hook=pairs, parse_constant=constant
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def grader_digest() -> str:
    sha = hashlib.sha256()
    for name in (
        "grade.sh",
        "compare.sh",
        "graph_checks.py",
        "schemas/scorecard.schema.json",
    ):
        sha.update(name.encode() + b"\0" + (ROOT / name).read_bytes() + b"\0")
    return sha.hexdigest()


def inside(root: Path, name: str) -> Path:
    require(isinstance(name, str) and bool(name), "invalid artifact path")
    require(not Path(name).is_absolute(), "absolute artifact path")
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()), "artifact path escapes root")
    return path


def validate(value: object, schema: dict[str, Any]) -> None:
    """Validate the deliberately small JSON Schema vocabulary used by our schema."""
    types = {
        "object": lambda x: type(x) is dict,
        "array": lambda x: type(x) is list,
        "string": lambda x: type(x) is str,
        "boolean": lambda x: type(x) is bool,
        "integer": lambda x: type(x) is int,
        "number": lambda x: type(x) in (int, float) and math.isfinite(x),
        "null": lambda x: x is None,
    }
    wanted = schema.get("type", list(types))
    require(
        any(types[t](value) for t in ([wanted] if isinstance(wanted, str) else wanted)),
        "schema type",
    )
    if "enum" in schema:
        require(value in schema["enum"], "schema enum")
    if isinstance(value, dict):
        require(
            set(schema.get("required", ())) <= value.keys(), "schema required field"
        )
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            require(value.keys() <= props.keys(), "schema unknown field")
        for key in value.keys() & props.keys():
            validate(value[key], props[key])
    if isinstance(value, list):
        require(len(value) >= schema.get("minItems", 0), "schema empty array")
        for item in value:
            validate(item, schema.get("items", {}))
    if isinstance(value, str):
        require(len(value) >= schema.get("minLength", 0), "schema empty string")
        require(
            re.search(schema.get("pattern", ""), value) is not None, "schema pattern"
        )
    if type(value) in (int, float) and "minimum" in schema:
        require(value >= schema["minimum"], "schema negative number")


def valid_identity(identity: dict[str, Any], trial: bool = False) -> None:
    keys = set(IDENTITY) | ({"trial_id"} if trial else set())
    require(
        type(identity) is dict and identity.keys() == keys,
        "identity fields missing or unknown",
    )
    require(all(type(x) is str and x for x in identity.values()), "missing identity")
    require(
        all(re.fullmatch(r"[0-9a-f]{64}", identity[k]) for k in HASH_FIELDS),
        "invalid identity digest",
    )
    require(
        re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", identity["commit"]), "invalid commit"
    )


def grade(artifact: Path, case_path: Path) -> int:
    artifact = artifact.resolve()
    score: dict[str, Any] = {
        "case_id": "invalid-case",
        "pass": False,
        "checks": [],
        "rubric": [],
        "grader": grader_digest(),
        "identity": dict.fromkeys((*IDENTITY, "trial_id")),
        "failure_class": "infra_dependency",
        "tokens": None,
        "latency_ms": None,
    }

    def check(name: str, passed: bool) -> None:
        score["checks"].append(
            {
                "id": name,
                "pass": bool(passed),
                "reason": "matched" if passed else "check failed",
            }
        )

    try:
        case = read_json(case_path)
        require(type(case) is dict, "case object required")
        require(
            type(case.get("case_id")) is str and bool(case["case_id"]),
            "case ID required",
        )
        score["case_id"] = case["case_id"]
        rubric = case.get("rubric")
        require(
            type(rubric) is list and all(type(x) is str and x for x in rubric),
            "rubric IDs required",
        )
        score["rubric"] = rubric
        run = read_json(inside(artifact, "run.json"))
        valid_identity(run["identity"], trial=True)
        score["identity"] = run["identity"]
        require(
            run["identity"]["grader_digest"] == score["grader"],
            "grader identity mismatch",
        )
        require(run["case_digest"] == digest(case_path), "case digest mismatch")
        for key in ("tokens", "latency_ms"):
            value = run[key]
            require(
                value is None or (type(value) is int and value >= 0),
                "invalid measurement",
            )
            score[key] = value
        require(
            run["failure_class"] in ("none", "infra_dependency"),
            "invalid execution failure class",
        )
        require(run["failure_class"] == "none", "execution infrastructure failed")
        expected = case["expected"]
        allowed = {
            "exit_code",
            "stdout_contains",
            "stdout_not_contains",
            "file_exists",
            "regex",
            "json_path",
        }
        require(
            type(expected) is dict and bool(expected) and expected.keys() <= allowed,
            "invalid expected checks",
        )
        stdout = inside(artifact, "stdout.txt").read_text()
        exit_code = read_json(inside(artifact, "exit_code.json"))
        require(type(exit_code) is int, "invalid exit code")
        for kind, values in cast(dict[str, Any], expected).items():
            if kind == "exit_code":
                require(type(values) is int, "invalid expected exit code")
                check(kind, exit_code == values)
                continue
            require(
                type(values) is list and bool(values),
                "empty or invalid expected check list",
            )
            for index, value in enumerate(values):
                name = f"{kind}:{index}"
                if kind == "json_path":
                    require(
                        type(value) is dict and value.keys() == {"path", "equals"},
                        "invalid JSON check",
                    )
                    path = value["path"]
                    require(
                        type(path) is list
                        and all(
                            type(k) is str or (type(k) is int and k >= 0) for k in path
                        ),
                        "invalid JSON path",
                    )
                    # Invalid JSON is observable agent output, not a broken grader.
                    try:
                        found = read_json(inside(artifact, "output.json"))
                        for key in path:
                            if (type(found) is dict and type(key) is str) or (
                                type(found) is list and type(key) is int
                            ):
                                found = cast(Any, found)[key]
                            else:
                                raise ValueError("JSON path type mismatch")
                        check(
                            name,
                            json.dumps(found, sort_keys=True)
                            == json.dumps(value["equals"], sort_keys=True),
                        )
                    except (OSError, ValueError, KeyError, IndexError, TypeError):
                        check(name, False)
                else:
                    require(
                        type(value) is str and bool(value), "invalid expected string"
                    )
                    if kind == "stdout_contains":
                        passed = value in stdout
                    elif kind == "stdout_not_contains":
                        passed = value not in stdout
                    elif kind == "regex":
                        passed = re.search(value, stdout) is not None
                    else:
                        # Resolve against the artifact root first to reject a symlinked files/ root.
                        require(not Path(value).is_absolute(), "absolute file check")
                        passed = inside(artifact, "files/" + value)
                        require(
                            passed.is_relative_to(artifact / "files"),
                            "file check escapes files",
                        )
                        passed = passed.is_file()
                    check(name, passed)
        score["pass"] = all(item["pass"] for item in score["checks"])
        score["failure_class"] = "none" if score["pass"] else "agent_quality"
    except (OSError, ValueError, KeyError, TypeError, re.error):
        check("harness", False)
        score["pass"] = False
        score["failure_class"] = "infra_dependency"
    validate(score, read_json(ROOT / "schemas/scorecard.schema.json"))
    target = artifact / "scorecard.json"
    require(not target.is_symlink(), "scorecard cannot be a symlink")
    temporary = artifact / "scorecard.json.tmp"
    require(not temporary.is_symlink(), "temporary scorecard cannot be a symlink")
    temporary.write_text(json.dumps(score, indent=2, allow_nan=False) + "\n")
    temporary.replace(target)
    return 0 if score["pass"] else 1


def load_run(root: Path) -> tuple[dict[str, Any], dict[tuple[str, str], bool]]:
    manifest = read_json(root / "manifest.json")
    require(manifest["mode"] in ("pin", "improve", "gate"), "invalid mode")
    valid_identity(manifest["identity"])
    require(
        manifest["identity"]["grader_digest"] == grader_digest(),
        "frozen grader changed",
    )
    cases, trials = manifest["cases"], manifest["trials"]
    for items in (cases, trials):
        require(
            type(items) is list
            and bool(items)
            and all(type(x) is str and x for x in items),
            "invalid case/trial set",
        )
        require(len(items) == len(set(items)), "duplicate case/trial declaration")
    if manifest["mode"] == "gate":
        count = manifest.get("trial_count", 3)
        require(
            type(count) is int and count >= 1 and len(trials) == count,
            "gate trial count mismatch",
        )
    schema = read_json(ROOT / "schemas/scorecard.schema.json")
    scores = {}
    require(type(manifest["scorecards"]) is list, "scorecard paths required")
    for name in manifest["scorecards"]:
        score = read_json(inside(root, name))
        validate(score, schema)
        valid_identity(score["identity"], trial=True)
        require(
            {key: score["identity"][key] for key in IDENTITY} == manifest["identity"],
            "scorecard identity mismatch",
        )
        require(
            score["grader"] == manifest["identity"]["grader_digest"],
            "scorecard grader mismatch",
        )
        checks = score["checks"]
        require(len({x["id"] for x in checks}) == len(checks), "duplicate check ID")
        require(
            score["pass"] == all(x["pass"] for x in checks),
            "inconsistent check results",
        )
        require(
            (score["failure_class"] == "none") == score["pass"],
            "inconsistent failure class",
        )
        require(
            score["failure_class"] != "infra_dependency",
            "infrastructure evidence cannot promote",
        )
        key = (score["case_id"], score["identity"]["trial_id"])
        require(key not in scores, "duplicate scorecard")
        scores[key] = score["pass"]
    require(
        scores.keys() == {(case, trial) for case in cases for trial in trials},
        "missing or unexpected trial",
    )
    for case in cases:
        results = {scores[case, trial] for trial in trials}
        if len(results) > 1:
            print("finding: flaky case (mixed trial outcomes)", file=sys.stderr)
    return manifest, scores


def pair(
    before: Path, after: Path
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[tuple[str, str], bool],
    dict[tuple[str, str], bool],
]:
    bm, bs = load_run(before)
    am, ass = load_run(after)
    require(
        bm["mode"] == am["mode"] and bs.keys() == ass.keys(), "suite/trial mismatch"
    )
    for key in ("dataset_hash", "grader_digest"):
        require(bm["identity"][key] == am["identity"][key], "frozen metric changed")
    # Check IDs/rubrics/case digests are frozen by the human-approved dataset hash.
    return bm, am, bs, ass


def compare(before: Path, after: Path, held_out: Path | None = None) -> int:
    bm, am, bs, ass = pair(before, after)
    regressed = any(bs[key] and not ass[key] for key in bs)
    improved = any(not bs[key] and ass[key] for key in bs)
    if am["mode"] in ("improve", "gate"):
        require(held_out is not None, "sealed held-out evidence required")
    held_after_scores: dict[tuple[str, str], bool] = {}
    if held_out is not None:
        hb, ha, hbs, held_after_scores = pair(held_out / "before", held_out / "after")
        require(
            hb["mode"] == bm["mode"] and ha["mode"] == am["mode"],
            "held-out mode mismatch",
        )
        for public, sealed in ((bm, hb), (am, ha)):
            if public["mode"] == "gate":
                require(
                    set(public["trials"]) == set(sealed["trials"]),
                    "held-out gate trial set mismatch",
                )
            for key in set(IDENTITY) - {"dataset_hash"}:
                require(
                    public["identity"][key] == sealed["identity"][key],
                    "held-out candidate mismatch",
                )
        regressed |= any(hbs[key] and not held_after_scores[key] for key in hbs)
        improved |= any(not hbs[key] and held_after_scores[key] for key in hbs)
    gate_failed = am["mode"] == "gate" and (
        not all(ass.values()) or not all(held_after_scores.values())
    )
    print("regressed" if regressed else "improved" if improved else "unchanged")
    if gate_failed:
        print(
            "gate failed: pass^k requires every public and held-out trial",
            file=sys.stderr,
        )
    return 1 if regressed or gate_failed else 0


def main() -> int:
    args = sys.argv[1:]
    try:
        if len(args) == 3 and args[0] == "grade":
            return grade(Path(args[1]), Path(args[2]))
        if len(args) in (3, 4) and args[0] == "compare":
            return compare(*(Path(x) for x in args[1:]))
        raise ValueError(
            "usage: grade <artifact-dir> <case.json> | compare <before> <after> [held-out-dir]"
        )
    except (OSError, ValueError, KeyError, TypeError):
        if args and args[0] == "compare":
            print("regressed")
        # Never echo exception text: paths and malformed input can contain PII.
        print(
            "infra_dependency: invalid or incomplete eval evidence; no promotion",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
