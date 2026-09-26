import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

import pytest

V2_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = V2_ROOT.parent
MAIN_TF = (V2_ROOT / "infra" / "main.tf").read_text()
TIMED_CHECKS_TF = (V2_ROOT / "infra" / "timed_checks.tf").read_text()
PUBLISHER_HANDLER = (V2_ROOT / "lambdas" / "publisher" / "handler.py").read_text()
ENVIRONMENT_TF = (V2_ROOT / "infra" / "environment.tf").read_text()
SITE_TF = (V2_ROOT / "infra" / "site.tf").read_text()
DEVELOPMENT_TFVARS = (V2_ROOT / "infra" / "development.tfvars").read_text()
CI_WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
TERRAFORM_WORKFLOW = (REPO_ROOT / ".github" / "workflows" / "terraform.yml").read_text()
PRODUCTION_PLAN_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-production-plan.yml"
).read_text()
TIMED_CHECKS_MODULE = (V2_ROOT / "timed_checks.py").read_text()
VERSIONS_TF = (V2_ROOT / "infra" / "versions.tf").read_text()
FOUNDATION_ROOT = REPO_ROOT / "infra"
FOUNDATION_TRIGGERS = (FOUNDATION_ROOT / "triggers.tf").read_text()
FOUNDATION_LAMBDA = (FOUNDATION_ROOT / "lambda.tf").read_text()
FOUNDATION_IAM = (FOUNDATION_ROOT / "iam.tf").read_text()
MEASUREMENT_INFRA = (V2_ROOT / "infra" / "agent_measurement.tf").read_text()
FOUNDATION_AGENTCORE = (FOUNDATION_ROOT / "agentcore.tf").read_text()
FOUNDATION_PROVIDER = (FOUNDATION_ROOT / "providers.tf").read_text()
FOUNDATION_TAILSCALE = (FOUNDATION_ROOT / "tailscale.tf").read_text()
FOUNDATION_BUDGET = FOUNDATION_ROOT / "budget.tf"
APPLICATION_VARIABLES = (V2_ROOT / "infra" / "variables.tf").read_text()
FOUNDATION_FIELDS = (
    "vpc_id",
    "vpc_cidr_block",
    "private_subnet_ids",
    "rds_security_group_id",
    "agentcore_endpoint_security_group_id",
    "eventbridge_endpoint_security_group_id",
    "agentcore_vpc_endpoint_id",
    "agentcore_vpc_endpoint_dns_name",
    "tollchat_api_vpc_endpoint_id",
    "raw_bucket_name",
    "raw_kms_key_arn",
    "agentcore_artifacts_bucket_name",
    "db_instance",
    "alerts_topic_arn",
    "telemetry_guardrail",
)
DEVELOPMENT_DELIVERY_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-development-delivery.yml"
).read_text()
DEVELOPMENT_DELIVERY_PRIVILEGED_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-development-delivery-privileged.yml"
).read_text()
DEVELOPMENT_PLAN_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-development-plan.yml"
).read_text()
DEVELOPMENT_CONNECTIVITY_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-development-connectivity-verification.yml"
).read_text()
DEVELOPMENT_MIGRATIONS_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-development-migrations.yml"
).read_text()
DEVELOPMENT_MIGRATION_HELPER = (
    V2_ROOT / "scripts" / "run_development_migrations_workflow.sh"
).read_text()
DEVELOPMENT_FOUNDATION_PLAN_VALIDATOR = (
    V2_ROOT / "scripts" / "validate_development_foundation_plan.py"
)
FOUNDATION_DNS_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "v2-production-foundation-dns.yml"
).read_text()
RUNBOOK = (V2_ROOT / "RUNBOOK.md").read_text()
RUNBOOKS = V2_ROOT / "runbooks"
DEVELOPMENT_BOOTSTRAP = (RUNBOOKS / "development-bootstrap-import.md").read_text()
DEVELOPMENT_RELEASE = (RUNBOOKS / "development-release.md").read_text()
DEVELOPMENT_FOUNDATION_330 = (
    RUNBOOKS / "development-foundation-330-archive.md"
).read_text()
DEVELOPMENT_FOUNDATION_REPLACEMENT = (
    RUNBOOKS / "development-foundation-replacement.md"
).read_text()
LEGACY_DEVELOPMENT_RETIREMENT = (
    RUNBOOKS / "legacy-development-retirement.md"
).read_text()


# Preserve the original logical ordering for whole-runbook contract assertions.
_BEFORE_HANDOFF, _AFTER_HANDOFF = RUNBOOK.split(
    "### Development handoff (non-operative)", maxsplit=1
)
_NON_OPERATIVE, _PRODUCTION = _AFTER_HANDOFF.split(
    "### Guarded production release", maxsplit=1
)
DEPLOYMENT = "\n".join(
    (
        _BEFORE_HANDOFF,
        DEVELOPMENT_BOOTSTRAP,
        DEVELOPMENT_RELEASE,
        "### Development handoff (non-operative)",
        _NON_OPERATIVE,
        DEVELOPMENT_FOUNDATION_330,
        DEVELOPMENT_FOUNDATION_REPLACEMENT,
        "### Guarded production release",
        _PRODUCTION,
        LEGACY_DEVELOPMENT_RETIREMENT,
    )
)
AGENTS = (REPO_ROOT / "AGENTS.md").read_text()
ACCOUNT_CONTRACT = json.loads(
    (REPO_ROOT / "infra" / "account-contract.json").read_text()
)
LEGACY_DEVELOPMENT_INVENTORY = (
    REPO_ROOT / "infra" / "legacy-development-inventory.md"
).read_text()


def terraform_block(source: str, header: str) -> str:
    """Return one top-level Terraform block, excluding the following block."""
    remainder = source.split(header, maxsplit=1)[1]
    following = re.search(r"\n(?:resource|data) ", remainder)
    return remainder[: following.start()] if following else remainder


def assert_assignment(block: str, name: str, value: str) -> None:
    assert re.search(rf"(?m)^\s*{re.escape(name)}\s*=\s*{re.escape(value)}\s*$", block)


def _balanced_text(source: str, start: int, opening: str, closing: str) -> str:
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(source)):
        character = source[index]
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return source[start + 1 : index]
    raise AssertionError(f"unclosed HCL delimiter {opening!r}")


def hcl_named_blocks(source: str, name: str) -> list[str]:
    pattern = re.compile(rf"(?m)^\s*{re.escape(name)}\s*\{{")
    blocks: list[str] = []
    for match in pattern.finditer(source):
        opening = source.find("{", match.start(), match.end())
        blocks.append(_balanced_text(source, opening, "{", "}"))
    return blocks


def hcl_attribute(source: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(name)}\s*=\s*", source)
    if not match:
        return ""
    start = match.end()
    while start < len(source) and source[start].isspace():
        start += 1
    if start < len(source) and source[start] == "[":
        return _balanced_text(source, start, "[", "]")
    quoted = re.match(r'"(?:\\.|[^"\\])*"', source[start:])
    if quoted:
        return quoted.group(0)
    return source[start:].splitlines()[0].strip()


def hcl_expression(source: str, name: str) -> str:
    """Return an HCL attribute expression, including nested delimiters."""
    match = re.search(rf"(?m)^\s*{re.escape(name)}\s*=\s*", source)
    if not match:
        return ""
    start = match.end()
    while start < len(source) and source[start].isspace():
        start += 1
    opening = source[start] if start < len(source) else ""
    if opening not in "[({" and re.match(r"[A-Za-z_][\w.]*\(", source[start:]):
        function_opening = source.find("(", start)
        opening = "("
        expression_start = start
        start = function_opening
    else:
        expression_start = start
    if opening not in "[({":
        return source[start:].splitlines()[0].strip()
    closing = {"[": "]", "(": ")", "{": "}"}[opening]
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(source)):
        character = source[index]
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return source[expression_start : index + 1].strip()
    raise AssertionError(f"unclosed HCL expression {name!r}")


def _hcl_expression_tokens(expression: str) -> list[str]:
    expression = expression.strip()
    if expression.startswith("concat("):
        expression = re.sub(r"\s+", " ", expression)
        expression = expression.replace("( ", "(").replace(" )", ")")
        return [re.sub(r",\s*\)$", ")", expression)]
    tokens: list[str] = []
    for match in re.finditer(r'"(?:\\.|[^"\\])*"|[A-Za-z_][\w.:-]*|\*', expression):
        token = match.group(0)
        tokens.append(json.loads(token) if token.startswith('"') else token)
    return tokens


def parsed_policy_tuple_map(
    source: str, name: str
) -> dict[
    str,
    tuple[
        tuple[str, ...], tuple[str, ...], tuple[tuple[str, str, tuple[str, ...]], ...]
    ],
]:
    document = terraform_block(source, f'data "aws_iam_policy_document" "{name}"')
    result: dict[
        str,
        tuple[
            tuple[str, ...],
            tuple[str, ...],
            tuple[tuple[str, str, tuple[str, ...]], ...],
        ],
    ] = {}
    for statement in hcl_named_blocks(document, "statement"):
        conditions: list[tuple[str, str, tuple[str, ...]]] = []
        for condition in hcl_named_blocks(statement, "condition"):
            values = tuple(_hcl_expression_tokens(hcl_expression(condition, "values")))
            values = tuple(
                "us-east-1" if value == "local.development_delivery_region" else value
                for value in values
            )
            conditions.append(
                (
                    hcl_scalar(condition, "test"),
                    hcl_scalar(condition, "variable"),
                    values,
                )
            )
        sid = hcl_scalar(statement, "sid")
        result[sid] = (
            tuple(hcl_strings(hcl_attribute(statement, "actions"))),
            tuple(_hcl_expression_tokens(hcl_expression(statement, "resources"))),
            tuple(conditions),
        )
    return result


def hcl_strings(expression: str) -> list[str]:
    return [json.loads(value) for value in re.findall(r'"(?:\\.|[^"\\])*"', expression)]


def _hcl_values(expression: str) -> list[str]:
    if expression.startswith("concat("):
        return []
    values: list[str] = []
    for value in expression.split(","):
        value = value.strip()
        if not value:
            continue
        values.append(json.loads(value) if value.startswith('"') else value)
    return values


def hcl_scalar(source: str, name: str) -> str:
    values = hcl_strings(hcl_attribute(source, name))
    return values[0] if values else ""


def parsed_policy_document(source: str, name: str) -> list[dict[str, object]]:
    document = terraform_block(source, f'data "aws_iam_policy_document" "{name}"')
    statements: list[dict[str, object]] = []
    for statement in hcl_named_blocks(document, "statement"):
        conditions: list[dict[str, object]] = []
        for condition in hcl_named_blocks(statement, "condition"):
            conditions.append(
                {
                    "test": hcl_scalar(condition, "test"),
                    "variable": hcl_scalar(condition, "variable"),
                    "values": hcl_strings(hcl_attribute(condition, "values")),
                }
            )
        statements.append(
            {
                "sid": hcl_scalar(statement, "sid"),
                "actions": hcl_strings(hcl_attribute(statement, "actions")),
                "resources": _hcl_values(hcl_attribute(statement, "resources")),
                "conditions": conditions,
            }
        )
    return statements


def policy_by_sid(statements: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {cast(str, statement["sid"]): statement for statement in statements}


def top_level_terraform_block(source: str, header: str, occurrence: int = 0) -> str:
    matches = list(re.finditer(rf"(?m)^{re.escape(header)}\s*\{{", source))
    if occurrence >= len(matches):
        raise AssertionError(f"missing Terraform block {header!r}")
    match = matches[occurrence]
    opening = source.find("{", match.start(), match.end())
    depth = 0
    quoted = False
    escaped = False
    for index in range(opening, len(source)):
        character = source[index]
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[match.start() : index + 1]
    raise AssertionError(f"unclosed Terraform block {header!r}")


def workflow_trigger(workflow: dict[str, object]) -> object:
    # PyYAML 1.1 treats the YAML 1.2 `on` key as boolean True.
    return workflow.get("on", cast(Mapping[object, object], workflow).get(True))


def workflow_run_source(job: dict[str, object]) -> str:
    return "\n".join(
        cast(str, step.get("run", ""))
        for step in cast(list[dict[str, object]], job.get("steps", []))
    )


def must_reject(
    assertion: Callable[[str], None], source: str, original: str, replacement: str
) -> None:
    mutated = source.replace(original, replacement, 1)
    assert mutated != source
    with pytest.raises(AssertionError):
        assertion(mutated)


def must_reject_after_marker(
    assertion: Callable[[str], None],
    source: str,
    marker: str,
    original: str,
    replacement: str,
) -> None:
    marker_index = source.index(marker)
    mutated = source[:marker_index] + source[marker_index:].replace(
        original, replacement, 1
    )
    assert mutated != source
    with pytest.raises(AssertionError):
        assertion(mutated)


SLICE_2A_POLICY = (REPO_ROOT / "infra" / "policy.hujson").read_text()
