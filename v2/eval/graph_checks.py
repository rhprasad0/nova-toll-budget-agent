# pyright: basic
"""Offline metric for eval-graph. No agent execution or orchestration."""

from __future__ import annotations

import hashlib
import json
import math
import re
import stat
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
ANNUAL_IDENTITY = (
    *IDENTITY,
    "model_settings_hash",
    "prompt_context_hash",
    "render_date",
    "source_digest",
    "rate_card_source",
    "rate_card_version",
    "rate_card_hash",
    "rate_card_values_hash",
)
ANNUAL_HASH_FIELDS = set(ANNUAL_IDENTITY) - {
    "model",
    "commit",
    "trial_id",
    "render_date",
    "rate_card_source",
    "rate_card_version",
}


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
        "run_evaluation.py",
        "fixture_runner.py",
        "fixture_eval.py",
        "golden_corpus.py",
    ):
        path = ROOT / name
        if path.is_file():
            sha.update(name.encode() + b"\0" + path.read_bytes() + b"\0")
    return sha.hexdigest()


def source_digest() -> str:
    """Hash raw, in-scope source bytes, including dirty worktree content."""
    files: list[Path] = []
    for relative in ("../agent", "../agent_tools", "../agent-sops"):
        base = (ROOT / relative).resolve()
        if base.exists():
            files.extend(
                path
                for path in base.rglob("*")
                if path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix != ".pyc"
                and ".git" not in path.parts
                and path.suffix.lower() in {".py", ".md", ".json"}
            )
    for relative in ("pyproject.toml", "uv.lock"):
        path = ROOT.parent / relative
        if path.is_file():
            files.append(path)
    for relative in ("fixture_runner.py", "fixture_eval.py"):
        path = ROOT / relative
        if path.is_file():
            files.append(path)
    entries: list[list[str]] = []
    for path in sorted(set(files)):
        name = path.relative_to(ROOT.parent).as_posix()
        entries.append([name, digest(path)])
    return hashlib.sha256(
        json.dumps(
            entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def inside(root: Path, name: str) -> Path:
    require(isinstance(name, str) and bool(name), "invalid artifact path")
    require(not Path(name).is_absolute(), "absolute artifact path")
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()), "artifact path escapes root")
    return path


def _annual_artifact_file(root: Path, name: str) -> Path:
    """Resolve one annual artifact only when it is a private regular file."""
    candidate = root / name
    require(not candidate.is_symlink(), "annual artifact symlink is not allowed")
    try:
        metadata = candidate.stat()
    except OSError as error:
        raise ValueError("annual artifact is unavailable") from error
    require(stat.S_ISREG(metadata.st_mode), "annual artifact must be a regular file")
    require(metadata.st_nlink == 1, "annual artifact hard links are not allowed")
    return inside(root, name)


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


def valid_annual_identity(identity: dict[str, Any], trial: bool = True) -> None:
    keys = set(ANNUAL_IDENTITY) | ({"trial_id"} if trial else set())
    require(
        type(identity) is dict and identity.keys() == keys,
        "annual identity fields missing or unknown",
    )
    require(
        all(type(value) is str and value for value in identity.values()),
        "missing annual identity",
    )
    require(
        all(re.fullmatch(r"[0-9a-f]{64}", identity[key]) for key in ANNUAL_HASH_FIELDS),
        "invalid annual identity digest",
    )
    require(
        re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", identity["commit"]),
        "invalid annual commit",
    )
    require(
        re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", identity["render_date"]),
        "invalid annual render date",
    )


def _annual_corpus(manifest_path: Path | None = None) -> object:
    try:
        from golden_corpus import validate as validate_corpus
    except ModuleNotFoundError:
        from eval.golden_corpus import validate as validate_corpus

    return validate_corpus(manifest_path or (ROOT / "golden" / "manifest.json"))


def _annual_fixture_corpus_hash(corpus: object, manifest_path: Path | None) -> str:
    path = manifest_path or (ROOT / "golden" / "manifest.json")
    entries = []
    for declaration in cast(Any, corpus).manifest["fixtures"]:
        fixture_path = path.parent / declaration["path"]
        entries.append(
            {
                "id": declaration["id"],
                "result_kind": declaration["result_kind"],
                "sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
            }
        )
    entries.sort(key=lambda item: item["id"])
    return hashlib.sha256(
        json.dumps(
            entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def annual_json_digest(value: dict[str, Any]) -> str:
    """Digest trusted JSON evidence using the annual canonical encoding."""
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def annual_rate_card_values_digest(rate_card: dict[str, Any]) -> str:
    """Digest the trusted numeric card retained in a sealed annual run."""
    return annual_json_digest(rate_card)


def _annual_contract_versions(corpus: object) -> dict[str, Any]:
    prompt_manifest = read_json(ROOT.parent / "agent" / "contract-manifest.json")
    tool_manifest = read_json(ROOT.parent / "agent_tools" / "contract-manifest.json")
    manifest = cast(Any, corpus).manifest
    return {
        "dataset_version": manifest["dataset_version"],
        "system_prompt": prompt_manifest["system_prompt"]["current"],
        "system_prompt_renderer": prompt_manifest["system_prompt_renderer"]["current"],
        "tools": {
            name: tool_manifest[name]["current"] for name in sorted(tool_manifest)
        },
        "renderer_constant": prompt_manifest["system_prompt_renderer"]["current"],
        "prompt_constant": prompt_manifest["system_prompt"]["current"],
    }


def _annual_case(case: dict[str, Any], corpus: object) -> dict[str, Any]:
    case_id = case.get("case_id")
    require(type(case_id) is str and case_id, "annual case ID required")
    rows = [row for row in cast(Any, corpus).annual_rows if row.get("id") == case_id]
    if rows:
        require(len(rows) == 1, "annual case ID is duplicated")
        require(case.get("suite") == "annual", "annual suite marker required")
        return rows[0]
    require(
        case.get("suite") == "annual"
        and case.get("holdout") is True
        and type(case.get("row")) is dict,
        "annual case is outside validated corpus",
    )
    holdout = cast(dict[str, Any], case["row"])
    require(holdout.get("id") == case_id, "holdout case ID mismatch")
    return holdout


def _annual_cost(run: dict[str, Any]) -> None:
    cost_value = run.get("cost")
    require(type(cost_value) is dict, "annual cost evidence required")
    cost = cast(dict[str, Any], cost_value)
    rates_value = cost.get("rate_card")
    require(type(rates_value) is dict, "annual rate-card provenance required")
    rates = cast(dict[str, Any], rates_value)
    require(
        set(rates)
        == {
            "source",
            "version",
            "digest",
            "input_rate_usd_per_million",
            "output_rate_usd_per_million",
            "cache_rate_usd_per_million",
        },
        "annual rate-card fields incomplete",
    )
    require(type(rates["source"]) is str and rates["source"], "rate source required")
    require(type(rates["version"]) is str and rates["version"], "rate version required")
    require(re.fullmatch(r"[0-9a-f]{64}", rates["digest"]), "rate digest invalid")
    for key in (
        "input_rate_usd_per_million",
        "output_rate_usd_per_million",
        "cache_rate_usd_per_million",
    ):
        value = cast(float, rates[key])
        require(
            type(value) in (int, float) and math.isfinite(value) and value >= 0,
            "invalid rate",
        )
    for key in ("input_usd", "output_usd", "cache_usd"):
        value = cast(float, cost.get(key))
        require(
            type(value) in (int, float) and math.isfinite(value) and value >= 0,
            "invalid model cost",
        )
    for cost_key, token_key, rate_key in (
        ("output_usd", "output_tokens", "output_rate_usd_per_million"),
        ("cache_usd", "cache_tokens", "cache_rate_usd_per_million"),
    ):
        tokens = run.get(token_key)
        require(type(tokens) is int and tokens >= 0, "token aggregate is missing")
        expected = tokens * rates[rate_key] / 1_000_000
        require(
            math.isclose(cost[cost_key], expected, rel_tol=1e-12, abs_tol=1e-15),
            "model cost does not match usage",
        )
    input_value = run.get("input_tokens")
    cache_value = run.get("cache_tokens")
    require(
        type(input_value) is int
        and input_value >= 0
        and type(cache_value) is int
        and 0 <= cache_value <= input_value,
        "input token aggregate is invalid",
    )
    input_tokens = cast(int, input_value)
    cache_tokens = cast(int, cache_value)
    expected_input = (
        (input_tokens - cache_tokens) * rates["input_rate_usd_per_million"] / 1_000_000
    )
    require(
        math.isclose(cost["input_usd"], expected_input, rel_tol=1e-12, abs_tol=1e-15),
        "model cost does not match uncached input usage",
    )


def _annual_live_marker(value: object) -> bool:
    marker = re.compile(
        r"(?<![\w])(?:live_tool|rds|ssm|boto3|network_endpoint)(?![\w])",
        re.IGNORECASE,
    )
    if isinstance(value, str):
        return marker.search(value) is not None
    if isinstance(value, dict):
        return any(
            _annual_live_marker(key) or _annual_live_marker(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_annual_live_marker(item) for item in value)
    return False


def grade_annual(
    artifact: Path,
    case_path: Path,
    manifest_path: Path | None = None,
) -> int:
    """Grade one fixture trajectory through the shared annual evaluator."""
    artifact = artifact.resolve()
    score: dict[str, Any] = {
        "case_id": "invalid-case",
        "pass": False,
        "checks": [],
        "rubric": [],
        "grader": grader_digest(),
        "identity": dict.fromkeys((*ANNUAL_IDENTITY, "trial_id")),
        "failure_class": "infra_dependency",
        "tokens": None,
        "latency_ms": None,
        "input_tokens": None,
        "output_tokens": None,
        "cache_tokens": None,
        "cost": None,
        "model_settings": None,
        "contract_versions": None,
        "candidate_artifact": None,
    }

    def check(name: str, passed: bool, reason: str | None = None) -> None:
        score["checks"].append(
            {
                "id": name,
                "pass": bool(passed),
                "reason": "matched" if passed else "check failed",
            }
        )

    try:
        case = read_json(case_path)
        require(type(case) is dict, "annual case object required")
        corpus = _annual_corpus(manifest_path)
        row = _annual_case(case, corpus)
        score["case_id"] = row["id"]
        run = read_json(_annual_artifact_file(artifact, "run.json"))
        require(
            run.get("artifact_type") == "annual_fixture_trial",
            "annual artifact marker required",
        )
        identity = run["identity"]
        valid_annual_identity(identity)
        score["identity"] = identity
        require(
            identity["grader_digest"] == score["grader"],
            "annual grader identity mismatch",
        )
        current_source = source_digest()
        require(
            identity["source_digest"] == current_source,
            "annual source identity mismatch",
        )
        require(
            identity["artifact_digest"] == current_source,
            "annual artifact identity mismatch",
        )
        expected_dataset = (
            case.get("dataset_hash")
            if case.get("holdout") is True
            else cast(Any, corpus).manifest["dataset_sha256"]
        )
        require(
            identity["dataset_hash"] == expected_dataset,
            "annual dataset identity mismatch",
        )
        if case.get("holdout") is True:
            membership = case.get("holdout_membership")
            fixture_corpus_hash = case.get("fixture_corpus_hash")
            row_digest = hashlib.sha256(
                json.dumps(
                    row,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            # A holdout case carries the complete shared bundle membership.  The
            # selected row must be one exact member, while the bundle hash binds
            # all opaque rows used by the comparison.
            require(
                type(membership) is list
                and type(fixture_corpus_hash) is str
                and re.fullmatch(r"[0-9a-f]{64}", fixture_corpus_hash)
                and fixture_corpus_hash
                == _annual_fixture_corpus_hash(corpus, manifest_path)
                and all(
                    type(item) is list
                    and len(item) == 2
                    and type(item[0]) is str
                    and type(item[1]) is str
                    and re.fullmatch(r"[0-9a-f]{64}", item[1])
                    for item in cast(list[object], membership)
                )
                and cast(list[list[str]], membership)
                == sorted(cast(list[list[str]], membership))
                and len({item[0] for item in cast(list[list[str]], membership)})
                == len(cast(list[list[str]], membership))
                and [row["id"], row_digest] in cast(list[list[str]], membership)
                and type(case.get("row_digest")) is str
                and case["row_digest"] == row_digest
                and type(case.get("membership_hash")) is str
                and case["membership_hash"] == case["dataset_hash"]
                and case["dataset_hash"]
                == hashlib.sha256(
                    json.dumps(
                        {
                            "fixture_corpus_hash": fixture_corpus_hash,
                            "rows": membership,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")
                ).hexdigest(),
                "holdout membership identity mismatch",
            )
        require(run.get("case_id") == row["id"], "annual case mismatch")
        require(
            run.get("case_digest")
            == hashlib.sha256(
                json.dumps(
                    row, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                ).encode("utf-8")
            ).hexdigest(),
            "annual case digest mismatch",
        )
        require(
            run.get("fixture_id") == row.get("fixture_id"), "annual fixture mismatch"
        )
        require(
            run.get("fixture_result_kind")
            == (
                None
                if row.get("fixture_id") is None
                else cast(Any, corpus).fixtures[row["fixture_id"]]["result_kind"]
            ),
            "annual fixture result kind mismatch",
        )
        require(not _annual_live_marker(run), "live-tool marker")
        for key in ("tokens", "latency_ms"):
            value = run.get(key)
            require(type(value) is int and value >= 0, "annual measurement required")
            score[key] = value
        _annual_cost(run)
        score["input_tokens"] = run["input_tokens"]
        score["output_tokens"] = run["output_tokens"]
        score["cache_tokens"] = run["cache_tokens"]
        score["cost"] = run["cost"]
        model_settings = run.get("model_settings")
        contract_versions = run.get("contract_versions")
        candidate_artifact = run.get("candidate_artifact")
        require(
            type(model_settings) is dict
            and type(model_settings.get("model_id")) is str
            and type(model_settings.get("stateful")) is bool
            and type(model_settings.get("params")) is dict,
            "annual sanitized model settings are required",
        )
        require(
            model_settings["model_id"] == identity["model"]
            and identity["model_settings_hash"] == annual_json_digest(model_settings),
            "annual model settings identity mismatch",
        )
        require(
            type(contract_versions) is dict
            and type(contract_versions.get("dataset_version")) is str
            and type(contract_versions.get("system_prompt")) is str
            and type(contract_versions.get("system_prompt_renderer")) is str
            and type(contract_versions.get("tools")) is dict,
            "annual contract versions are required",
        )
        require(
            contract_versions == _annual_contract_versions(corpus),
            "annual contract versions do not match trusted manifests",
        )
        require(
            type(candidate_artifact) is dict
            and candidate_artifact.get("kind") == "source-snapshot"
            and candidate_artifact.get("digest") == identity["artifact_digest"]
            and type(candidate_artifact.get("artifact_id")) is str
            and candidate_artifact.get("artifact_id")
            == f"source-snapshot:{identity['artifact_digest']}"
            and candidate_artifact.get("deployment_identity") == "pending",
            "annual candidate artifact identity is incomplete",
        )
        score["model_settings"] = model_settings
        score["contract_versions"] = contract_versions
        score["candidate_artifact"] = candidate_artifact
        rates = cast(dict[str, Any], cast(dict[str, Any], run["cost"])["rate_card"])
        trusted_rate_card = run.get("trusted_rate_card")
        require(
            type(trusted_rate_card) is dict
            and trusted_rate_card == rates
            and identity["rate_card_values_hash"]
            == annual_rate_card_values_digest(trusted_rate_card),
            "annual numeric rate-card evidence is not trusted",
        )
        require(
            identity["rate_card_source"] == rates["source"]
            and identity["rate_card_version"] == rates["version"]
            and identity["rate_card_hash"] == rates["digest"],
            "annual rate-card identity mismatch",
        )
        output = read_json(_annual_artifact_file(artifact, "output.json"))
        require(type(output) is dict, "annual output object required")
        require(
            set(output) <= {"case_id", "output", "trajectory", "measurements", "cost"},
            "runner verdict or metadata is not allowed",
        )
        require(output.get("case_id") == row["id"], "annual output case mismatch")
        require(output.get("cost") == run["cost"], "annual cost evidence mismatch")
        trajectory = output.get("trajectory")
        require(
            type(trajectory) is list and trajectory,
            "complete annual trajectory required",
        )
        require(
            all(
                type(turn) is dict
                and {"response", "calls"} <= turn.keys()
                and type(turn["calls"]) is list
                for turn in trajectory
            ),
            "annual turns incomplete",
        )
        expected_turns = list(row.get("conversation", [row["prompt"]]))
        if row.get("follow_up") and row["follow_up"] not in expected_turns:
            expected_turns.append(row["follow_up"])
        require(
            len(trajectory) == len(expected_turns),
            "annual trajectory turn count mismatch",
        )
        require(
            all(
                type(turn.get("prompt")) is str
                and turn["prompt"] == expected_turns[index]
                for index, turn in enumerate(cast(list[dict[str, Any]], trajectory))
            ),
            "annual trajectory prompt mismatch",
        )
        measurements = output.get("measurements")
        require(type(measurements) is dict, "annual raw measurements missing")
        turn_measurements = cast(Any, measurements).get("turns")
        typed_turn_measurements = cast(list[dict[str, Any]], turn_measurements)
        require(
            type(turn_measurements) is list
            and len(turn_measurements) == len(trajectory)
            and all(
                type(item) is dict
                and type(item.get("tokens")) is int
                and item["tokens"] >= 0
                and type(item.get("input_tokens")) is int
                and item["input_tokens"] >= 0
                and type(item.get("output_tokens")) is int
                and item["output_tokens"] >= 0
                and type(item.get("cache_tokens")) is int
                and item["cache_tokens"] >= 0
                and type(item.get("latency_ms")) is int
                and item["latency_ms"] >= 0
                and item["tokens"] == item["input_tokens"] + item["output_tokens"]
                and item["cache_tokens"] <= item["input_tokens"]
                for item in typed_turn_measurements
            ),
            "annual per-turn measurements missing",
        )
        require(
            measurements.get("tokens") == run["tokens"]
            and measurements.get("latency_ms") == run["latency_ms"],
            "annual measurement aggregate mismatch",
        )
        require(
            measurements.get("tokens")
            == sum(item["tokens"] for item in typed_turn_measurements)
            and measurements.get("latency_ms")
            == sum(item["latency_ms"] for item in typed_turn_measurements)
            and run.get("tokens")
            == sum(item["tokens"] for item in typed_turn_measurements)
            and run.get("latency_ms")
            == sum(item["latency_ms"] for item in typed_turn_measurements)
            and run.get("input_tokens")
            == sum(item["input_tokens"] for item in typed_turn_measurements)
            and run.get("output_tokens")
            == sum(item["output_tokens"] for item in typed_turn_measurements)
            and run.get("cache_tokens")
            == sum(item["cache_tokens"] for item in typed_turn_measurements),
            "annual measurement totals are inconsistent",
        )
        require(
            run.get("output_digest")
            == hashlib.sha256(
                b"".join(
                    name.encode()
                    + b"\0"
                    + _annual_artifact_file(artifact, name).read_bytes()
                    + b"\0"
                    for name in ("output.json", "stdout.txt", "exit_code.json")
                )
            ).hexdigest(),
            "annual raw artifact digest mismatch",
        )
        require(not _annual_live_marker(output), "live-tool marker")
        expected_fixture = (
            cast(Any, corpus).fixtures[row["fixture_id"]]
            if row.get("fixture_id") is not None
            else None
        )
        call_ids: set[str] = set()
        for turn in cast(list[dict[str, Any]], trajectory):
            for call in turn["calls"]:
                tool_use_id = call.get("toolUseId")
                require(
                    type(tool_use_id) is str
                    and bool(tool_use_id)
                    and tool_use_id not in call_ids,
                    "annual tool-use IDs must be unique and nonempty",
                )
                call_ids.add(tool_use_id)
                require(
                    call.get("resultToolUseId") == tool_use_id,
                    "annual tool-use/result IDs are not correlated",
                )
                require(
                    call.get("name")
                    in {"get_current_toll_price", "get_annual_toll_ballpark"},
                    "unknown tool in fixture trajectory",
                )
                if not call.get("is_error"):
                    require(
                        "tool_result" in call,
                        "successful tool call is missing its correlated result",
                    )
                if call.get("name") == "get_current_toll_price" and not call.get(
                    "is_error"
                ):
                    raise ValueError("current-price fixture success is not permitted")
                if call.get("name") == "get_annual_toll_ballpark" and not call.get(
                    "is_error"
                ):
                    require(expected_fixture is not None, "unexpected fixture success")
                    typed_fixture = cast(dict[str, Any], expected_fixture)
                    require(
                        call.get("input") == typed_fixture["request"],
                        "fixture request mismatch",
                    )
                    require(
                        call.get("tool_result") == typed_fixture["payload"],
                        "fixture payload mismatch",
                    )
        require(
            run.get("failure_class") == "none", "annual execution infrastructure failed"
        )
        try:
            from run_evaluation import TollChatEvaluator
        except ModuleNotFoundError:
            from eval.run_evaluation import TollChatEvaluator
        from strands_evals.types.evaluation import EvaluationData

        evaluations = TollChatEvaluator().evaluate(
            EvaluationData(
                input=row["prompt"],
                actual_output=str(output.get("output", "")),
                actual_trajectory=trajectory,
                metadata=row,
                name=row["id"],
            )
        )
        require(evaluations, "annual evaluator returned no result")
        for index, evaluation in enumerate(evaluations):
            check(
                f"annual:{index}:{evaluation.label or 'evaluation'}",
                bool(evaluation.test_pass),
                evaluation.reason,
            )
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
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(score, indent=2, allow_nan=False) + "\n")
    temporary.replace(target)
    return 0 if score["pass"] else 1


def grade(artifact: Path, case_path: Path) -> int:
    artifact = artifact.resolve()
    try:
        marker = read_json(inside(artifact, "run.json"))
    except (OSError, ValueError, KeyError, TypeError):
        marker = None
    if type(marker) is dict and marker.get("artifact_type") == "annual_fixture_trial":
        return grade_annual(artifact, case_path)
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
        require(
            type(case.get("prompt")) is str and bool(case["prompt"]),
            "nonempty runner prompt required",
        )
        require(type(case.get("setup")) is dict, "runner setup object required")
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
    # Exclusive creation rejects pre-existing hard links as well as symlinks.
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(score, indent=2, allow_nan=False) + "\n")
    temporary.replace(target)
    return 0 if score["pass"] else 1


def load_run(root: Path) -> tuple[dict[str, Any], dict[tuple[str, str], bool]]:
    manifest = read_json(root / "manifest.json")
    require(manifest["mode"] in ("pin", "improve", "gate"), "invalid mode")
    annual = manifest.get("suite") in {"annual", "annual-heldout"}
    if annual:
        valid_annual_identity(manifest["identity"], trial=False)
        require(
            len(manifest.get("trials", [])) == 3
            and manifest["trials"] == ["1", "2", "3"],
            "annual runs require exactly three default trials",
        )
        if manifest.get("suite") == "annual":
            corpus = _annual_corpus()
            public_cases = [row["id"] for row in cast(Any, corpus).annual_rows]
            require(
                manifest.get("cases") == public_cases,
                "annual public run requires the ordered public case set",
            )
        else:
            corpus = _annual_corpus()
            public_cases = {row["id"] for row in cast(Any, corpus).rows}
            require(
                type(manifest.get("cases")) is list
                and public_cases.isdisjoint(manifest["cases"]),
                "annual held-out cases must be disjoint from public cases",
            )
    else:
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
    if annual:
        require(
            len(manifest["scorecards"]) == len(cases) * len(trials),
            "annual scorecard set is incomplete",
        )
    for name in manifest["scorecards"]:
        score = read_json(inside(root, name))
        validate(score, schema)
        if annual:
            valid_annual_identity(score["identity"], trial=True)
        else:
            valid_identity(score["identity"], trial=True)
        identity_fields = ANNUAL_IDENTITY if annual else IDENTITY
        require(
            {key: score["identity"][key] for key in identity_fields}
            == manifest["identity"],
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
        if bm.get("suite") == "annual" or am.get("suite") == "annual":
            require(
                bm.get("suite") == "annual"
                and am.get("suite") == "annual"
                and hb.get("suite") == "annual-heldout"
                and ha.get("suite") == "annual-heldout",
                "annual comparisons require sealed held-out suites",
            )
            require(
                set(hb["cases"]).isdisjoint(set(bm["cases"]))
                and set(ha["cases"]).isdisjoint(set(am["cases"])),
                "annual held-out cases must be disjoint from public cases",
            )
            require(
                hb["cases"] == ha["cases"],
                "annual held-out case membership changed",
            )
            require(
                hb["identity"]["dataset_hash"] == ha["identity"]["dataset_hash"],
                "annual held-out membership identity changed",
            )
        for public, sealed in ((bm, hb), (am, ha)):
            if public["mode"] == "gate":
                require(
                    set(public["trials"]) == set(sealed["trials"]),
                    "held-out gate trial set mismatch",
                )
            identity_fields = (
                set(ANNUAL_IDENTITY)
                if public.get("suite") == "annual"
                else set(IDENTITY)
            ) - {"dataset_hash"}
            for key in identity_fields:
                require(
                    public["identity"][key] == sealed["identity"][key],
                    "held-out candidate identity mismatch",
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
