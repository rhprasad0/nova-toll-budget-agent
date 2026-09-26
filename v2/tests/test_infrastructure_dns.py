import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from textwrap import dedent
from typing import cast

import pytest
import yaml

from tests.infrastructure_support import (
    APPLICATION_VARIABLES,
    DEPLOYMENT,
    DEVELOPMENT_DELIVERY_WORKFLOW,
    DEVELOPMENT_TFVARS,
    ENVIRONMENT_TF,
    FOUNDATION_DNS_WORKFLOW,
    FOUNDATION_IAM,
    SITE_TF,
    parsed_policy_document,
    policy_by_sid,
    terraform_block,
)


def test_slice_3_development_custom_domain_is_explicit_and_production_preserving() -> (
    None
):
    assert 'variable "enable_development_custom_domain"' in APPLICATION_VARIABLES
    variable = terraform_block(
        APPLICATION_VARIABLES, 'variable "enable_development_custom_domain"'
    )
    assert "default     = false" in variable
    assert 'environment == "development"' in variable
    assert "enable_development_custom_domain = true" in DEVELOPMENT_TFVARS.replace(
        "      ", " "
    )
    assert "development_custom_domain_enabled" in ENVIRONMENT_TF
    assert "https://${local.domains[0]}" in ENVIRONMENT_TF
    assert "-var enable_development_custom_domain=" not in DEVELOPMENT_DELIVERY_WORKFLOW

    distribution = terraform_block(
        SITE_TF, 'resource "aws_cloudfront_distribution" "site"'
    )
    assert (
        "aliases                         = local.custom_domain_enabled ? local.domains : []"
        in distribution
    )
    assert (
        "cloudfront_default_certificate = !local.custom_domain_enabled" in distribution
    )
    assert (
        'minimum_protocol_version       = local.custom_domain_enabled ? "TLSv1.2_2021" : "TLSv1"'
        in distribution
    )
    assert (
        "local.development_custom_domain_enabled ? aws_acm_certificate.site[0].arn"
        in distribution
    )
    certificate = terraform_block(SITE_TF, 'resource "aws_acm_certificate" "site"')
    assert (
        "count                     = local.custom_domain_enabled ? 1 : 0" in certificate
    )
    assert "domain_name               = local.domains[0]" in certificate
    assert 'validation_method         = "DNS"' in certificate
    assert 'data "cloudflare_zone" "tollchat"' in SITE_TF
    assert "count  = local.is_production ? 1 : 0" in SITE_TF
    assert 'output "development_acm_certificate_arn"' in SITE_TF
    assert 'output "development_acm_validation_records"' in SITE_TF


def test_slice_3_development_delivery_cannot_administer_custom_domain() -> None:
    policy = terraform_block(
        FOUNDATION_IAM, 'data "aws_iam_policy_document" "development_delivery"'
    )
    assert "cloudfront:UpdateDistribution" not in policy
    assert "acm:RequestCertificate" not in policy
    assert "cloudflare" not in policy.lower()
    statements = parsed_policy_document(FOUNDATION_IAM, "development_delivery")
    certificate = policy_by_sid(statements)["ReadDevelopmentCertificate"]
    assert certificate["actions"] == [
        "acm:DescribeCertificate",
        "acm:ListTagsForCertificate",
    ]
    assert certificate["resources"] == [
        "arn:aws:acm:us-east-1:903859731897:certificate/0c2c3578-fee5-41b3-9985-ea7465c16a20"
    ]
    assert [
        action
        for statement in statements
        for action in cast(list[str], statement["actions"])
        if action.startswith("acm:")
    ] == certificate["actions"]


def test_slice_3_foundation_dns_role_has_exact_oidc_and_ssm_boundary() -> None:
    trust = terraform_block(
        FOUNDATION_IAM,
        'data "aws_iam_policy_document" "production_foundation_dns_assume"',
    )
    assert 'actions = ["sts:AssumeRoleWithWebIdentity"]' in trust
    assert 'variable = "token.actions.githubusercontent.com:aud"' in trust
    assert 'values   = ["sts.amazonaws.com"]' in trust
    assert (
        'values   = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:production-foundation-dns"]'
        in trust
    )
    assert 'sts:AssumeRole"' not in trust

    policy = terraform_block(
        FOUNDATION_IAM, 'data "aws_iam_policy_document" "production_foundation_dns"'
    )
    assert 'count = var.environment == "production" ? 1 : 0' in policy
    assert len(parsed_policy_document(FOUNDATION_IAM, "production_foundation_dns")) == 1
    assert 'actions   = ["ssm:GetParameter"]' in policy
    assert "resources = [local.production_foundation_dns_parameter_arn]" in policy
    assert (
        "arn:aws:ssm:us-east-1:920534282028:parameter/nova-toll/cloudflare-development-dns-api-token"
        in FOUNDATION_IAM
    )
    assert 'resource "aws_iam_role" "production_foundation_dns"' in FOUNDATION_IAM
    role = terraform_block(
        FOUNDATION_IAM, 'resource "aws_iam_role" "production_foundation_dns"'
    )
    assert 'count                = var.environment == "production" ? 1 : 0' in role
    assert (
        'name                 = "nova-toll-production-foundation-dns"' in FOUNDATION_IAM
    )
    assert "kms:Decrypt" not in policy
    assert "secretsmanager:" not in policy


def test_slice_3_dns_workflow_is_manual_protected_and_secret_safe() -> None:
    workflow = cast(dict[str, object], yaml.safe_load(FOUNDATION_DNS_WORKFLOW))
    assert "workflow_dispatch:" in FOUNDATION_DNS_WORKFLOW
    assert "push:" not in FOUNDATION_DNS_WORKFLOW
    assert "pull_request" not in FOUNDATION_DNS_WORKFLOW
    assert "refs/heads/main" in FOUNDATION_DNS_WORKFLOW
    assert (
        "github.repository == 'rhprasad0/nova-toll-budget-agent'"
        in FOUNDATION_DNS_WORKFLOW
    )
    assert "environment: production-foundation-dns" in FOUNDATION_DNS_WORKFLOW
    assert (
        "role-to-assume: arn:aws:iam::920534282028:role/nova-toll-production-foundation-dns"
        in FOUNDATION_DNS_WORKFLOW
    )
    assert "id-token: write" in FOUNDATION_DNS_WORKFLOW
    assert "contents: read" in FOUNDATION_DNS_WORKFLOW
    assert "--with-decryption" in FOUNDATION_DNS_WORKFLOW
    assert "/nova-toll/cloudflare-development-dns-api-token" in FOUNDATION_DNS_WORKFLOW
    assert "accounts/{account_id}/tokens/verify" in FOUNDATION_DNS_WORKFLOW
    assert "tokens/verify" in FOUNDATION_DNS_WORKFLOW
    assert 'EXPECTED_ZONE = "tollchat.ai"' in FOUNDATION_DNS_WORKFLOW
    assert 'EXPECTED_DEV_NAME = "dev.tollchat.ai"' in FOUNDATION_DNS_WORKFLOW
    assert 'EXPECTED_DISTRIBUTION = "E33DVF3KT7BTAC"' in FOUNDATION_DNS_WORKFLOW
    assert (
        'EXPECTED_CLOUDFRONT_HOSTNAME = "d1wqry4fbd92w5.cloudfront.net"'
        in FOUNDATION_DNS_WORKFLOW
    )
    assert (
        'EXPECTED_LEGACY_TARGET = "dmsiz11apblcv.cloudfront.net"'
        in FOUNDATION_DNS_WORKFLOW
    )
    assert '"stage-validation", "cutover", "rollback"' in FOUNDATION_DNS_WORKFLOW
    assert '"POST"' in FOUNDATION_DNS_WORKFLOW and '"PUT"' in FOUNDATION_DNS_WORKFLOW
    assert "DELETE" not in FOUNDATION_DNS_WORKFLOW
    assert "GITHUB_STEP_SUMMARY" not in FOUNDATION_DNS_WORKFLOW
    assert "upload-artifact" not in FOUNDATION_DNS_WORKFLOW
    assert "secrets." not in FOUNDATION_DNS_WORKFLOW
    assert "Authorization" in FOUNDATION_DNS_WORKFLOW
    assert "set +x" in FOUNDATION_DNS_WORKFLOW
    assert workflow
    for action in re.findall(r"uses:\s*([^\s#]+)", FOUNDATION_DNS_WORKFLOW):
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action)


def test_slice_3_dns_allowlist_contract_covers_adversarial_records_and_order() -> None:
    for required in (
        "result_info",
        "total_count != count",
        "total_pages != 1",
        'zone.get("name") != EXPECTED_ZONE',
        'zone.get("status") != "active"',
        "returned_account != account_id",
        'status") != "active"',
        "len(dev_records) != 1",
        "len(found) > 1",
        "EXPECTED_VALIDATION_TTL = 60",
        "EXPECTED_DEV_TTL = 1",
        'proxied"] is not False',
        "\\.dev\\.tollchat\\.ai",
        "acm-validations\\.aws",
        'CERTIFICATE_STATUS") != "ISSUED"',
        'CLOUDFRONT_STATUS") != "Deployed"',
        'LEGACY_ALIAS_RELEASED") != "true"',
        'method not in {"POST", "PUT"}',
        "ROLLBACK_SNAPSHOT",
        'old_snapshot["id"]',
        "cloudflare DNS gate failed closed",
        "rollback_legacy_https_health",
        "--proto '=https' --tlsv1.2",
        "https://dmsiz11apblcv.cloudfront.net/",
    ):
        assert required in FOUNDATION_DNS_WORKFLOW
    assert FOUNDATION_DNS_WORKFLOW.index(
        '"stage-validation"'
    ) < FOUNDATION_DNS_WORKFLOW.index('"cutover"')
    assert FOUNDATION_DNS_WORKFLOW.index(
        '"CERTIFICATE_STATUS"'
    ) < FOUNDATION_DNS_WORKFLOW.index('mutate(zone_id, account_id, "PUT"')
    assert (
        "LEGACY_ALIAS_RELEASED: ${{ inputs.legacy_alias_released }}"
        in FOUNDATION_DNS_WORKFLOW
    )
    assert "alias_attached:" not in FOUNDATION_DNS_WORKFLOW


def _slice3_dns_python_source() -> str:
    embedded = FOUNDATION_DNS_WORKFLOW.split(
        "CLOUDFLARE_TOKEN=\"$TOKEN\" python3 - <<'PY'\n", maxsplit=1
    )[1].split("\n          PY", maxsplit=1)[0]
    source = dedent(embedded)
    assert "\ntry:\n    main()\n" in source
    return source.split("\ntry:\n    main()\n", maxsplit=1)[0] + "\n"


def _dns_zone(zone_id: str = "a" * 32, account_id: str = "b" * 32) -> dict[str, object]:
    return {
        "id": zone_id,
        "name": "tollchat.ai",
        "status": "active",
        "account": {"id": account_id},
    }


def _dns_record(
    record_id: str,
    record_name: str,
    content: str,
    *,
    ttl: int = 1,
    proxied: bool = False,
) -> dict[str, object]:
    return {
        "id": record_id,
        "zone_id": "a" * 32,
        "name": record_name,
        "type": "CNAME",
        "content": content,
        "ttl": ttl,
        "proxied": proxied,
    }


class _DnsApiMock:
    def __init__(
        self,
        *,
        zones: list[dict[str, object]],
        token_account: str = "b" * 32,
        dev_records: list[dict[str, object]] | None = None,
        validation_records: list[dict[str, object]] | None = None,
    ) -> None:
        validation: list[dict[str, object]] = validation_records or [
            _dns_record(
                "d" * 32,
                "_validation.dev.tollchat.ai",
                "_token.acm-validations.aws",
                ttl=60,
            )
        ]
        self.zones = zones
        self.token_account = token_account
        self.records: dict[str, list[dict[str, object]]] = {
            cast(str, record["name"]): [record] for record in validation
        }
        self.records["dev.tollchat.ai"] = dev_records or [
            _dns_record(
                "c" * 32,
                "dev.tollchat.ai",
                "dmsiz11apblcv.cloudfront.net",
            )
        ]
        self.calls: list[
            tuple[str, str, dict[str, str] | None, dict[str, object] | None]
        ] = []

    @property
    def mutations(self) -> list[tuple[str, str, dict[str, object] | None]]:
        return [
            (method, path, payload)
            for method, path, _, payload in self.calls
            if method in {"POST", "PUT"}
        ]

    @staticmethod
    def _page(result: list[dict[str, object]]) -> dict[str, object]:
        return {
            "success": True,
            "result": result,
            "result_info": {
                "page": 1,
                "count": len(result),
                "per_page": max(1, len(result)),
                "total_count": len(result),
                "total_pages": 1,
            },
        }

    def __call__(
        self,
        method: str,
        path: str,
        query: dict[str, str] | None = None,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.calls.append((method, path, query, payload))
        if method == "GET" and path == "zones":
            return self._page(self.zones)
        if method == "GET" and path.endswith("/tokens/verify"):
            return {
                "success": True,
                "result": {"status": "active", "account_id": self.token_account},
            }
        if method == "GET" and path.endswith("/dns_records"):
            record_name = (query or {}).get("name", "")
            return self._page(self.records.get(record_name, []))
        if method == "POST" and path.endswith("/dns_records") and payload is not None:
            record = {**payload, "id": "e" * 32, "zone_id": "a" * 32}
            self.records.setdefault(str(record["name"]), []).append(record)
            return {"success": True, "result": record}
        if method == "PUT" and "/dns_records/" in path and payload is not None:
            record_id = path.rsplit("/", maxsplit=1)[1]
            for record_name, records in self.records.items():
                for index, record in enumerate(records):
                    if record["id"] == record_id:
                        updated = {**payload, "id": record_id, "zone_id": "a" * 32}
                        records[index] = updated
                        if updated["name"] != record_name:
                            del records[index]
                            self.records.setdefault(str(updated["name"]), []).append(
                                updated
                            )
                        return {"success": True, "result": updated}
        raise AssertionError(f"unexpected mock call: {method} {path}")


def _set_dns_inputs(
    monkeypatch: pytest.MonkeyPatch, *, operation: str = "stage-validation"
) -> None:
    monkeypatch.setenv("OPERATION", operation)
    monkeypatch.setenv(
        "ACM_CERTIFICATE_ARN",
        "arn:aws:acm:us-east-1:903859731897:certificate/" + "0" * 36,
    )
    monkeypatch.setenv(
        "VALIDATION_RECORDS",
        json.dumps(
            [
                {
                    "name": "_validation.dev.tollchat.ai",
                    "type": "CNAME",
                    "value": "_token.acm-validations.aws",
                    "ttl": 60,
                    "proxied": False,
                }
            ]
        ),
    )
    monkeypatch.setenv("DISTRIBUTION_ID", "E33DVF3KT7BTAC")
    monkeypatch.setenv("CLOUDFRONT_HOSTNAME", "d1wqry4fbd92w5.cloudfront.net")
    monkeypatch.setenv("CERTIFICATE_STATUS", "ISSUED")
    monkeypatch.setenv("CLOUDFRONT_STATUS", "Deployed")
    monkeypatch.setenv("LEGACY_ALIAS_RELEASED", "true")
    monkeypatch.setenv("OLD_DEV_TARGET", "dmsiz11apblcv.cloudfront.net")
    monkeypatch.setenv(
        "ROLLBACK_SNAPSHOT",
        json.dumps(
            {
                "id": "c" * 32,
                "name": "dev.tollchat.ai",
                "type": "CNAME",
                "content": "dmsiz11apblcv.cloudfront.net",
                "ttl": 1,
                "proxied": False,
            }
        ),
    )


def _dns_namespace(mock: _DnsApiMock) -> dict[str, object]:
    namespace: dict[str, object] = {}
    exec(_slice3_dns_python_source(), namespace)
    namespace["TOKEN"] = "fixture-token"
    namespace["api"] = mock
    return namespace


def test_slice3_dns_gate_rejects_adversarial_inputs_before_any_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    zone = _dns_zone()
    cases: list[tuple[str, dict[str, str], _DnsApiMock]] = []
    for zones in ([], [zone, _dns_zone("f" * 32, "b" * 32)]):
        cases.append(("zone cardinality", {}, _DnsApiMock(zones=zones)))

    cases.append(
        ("wrong token account", {}, _DnsApiMock(zones=[zone], token_account="f" * 32))
    )

    cases.append(
        (
            "malformed validation record",
            {
                "VALIDATION_RECORDS": json.dumps(
                    [
                        {
                            "name": "_validation.dev.tollchat.ai",
                            "type": "A",
                            "value": "bad",
                            "ttl": 60,
                            "proxied": False,
                        }
                    ]
                )
            },
            _DnsApiMock(zones=[zone]),
        )
    )

    cases.append(
        (
            "unrelated CloudFront host",
            {"CLOUDFRONT_HOSTNAME": "dattacker.cloudfront.net"},
            _DnsApiMock(zones=[zone]),
        )
    )

    cases.append(
        (
            "unreviewed rollback target",
            {"OLD_DEV_TARGET": "dother.cloudfront.net"},
            _DnsApiMock(zones=[zone]),
        )
    )

    cases.append(
        (
            "stale snapshot",
            {},
            _DnsApiMock(
                zones=[zone],
                dev_records=[
                    _dns_record(
                        "f" * 32, "dev.tollchat.ai", "dmsiz11apblcv.cloudfront.net"
                    )
                ],
            ),
        )
    )

    for label, overrides, mock in cases:
        _set_dns_inputs(monkeypatch)
        for key, value in overrides.items():
            monkeypatch.setenv(key, value)
        namespace = _dns_namespace(mock)
        gate_error = cast(type[Exception], namespace["GateError"])
        main = cast(Callable[[], object], namespace["main"])
        with pytest.raises(gate_error):
            main()
        assert not mock.mutations, label


@pytest.mark.parametrize(
    ("released", "certificate", "distribution", "accepted"),
    [
        ("true", "ISSUED", "Deployed", True),
        ("false", "ISSUED", "Deployed", False),
        (None, "ISSUED", "Deployed", False),
        ("", "ISSUED", "Deployed", False),
        ("TRUE", "ISSUED", "Deployed", False),
        ("true", "PENDING_VALIDATION", "Deployed", False),
        ("true", "ISSUED", "InProgress", False),
    ],
)
def test_slice3_dns_cutover_precedes_new_alias_but_requires_legacy_release(
    monkeypatch: pytest.MonkeyPatch,
    released: str | None,
    certificate: str,
    distribution: str,
    accepted: bool,
) -> None:
    _set_dns_inputs(monkeypatch, operation="cutover")
    monkeypatch.delenv("ALIAS_ATTACHED", raising=False)
    if released is None:
        monkeypatch.delenv("LEGACY_ALIAS_RELEASED")
    else:
        monkeypatch.setenv("LEGACY_ALIAS_RELEASED", released)
    monkeypatch.setenv("CERTIFICATE_STATUS", certificate)
    monkeypatch.setenv("CLOUDFRONT_STATUS", distribution)
    mock = _DnsApiMock(zones=[_dns_zone()])
    namespace = _dns_namespace(mock)
    main = cast(Callable[[], object], namespace["main"])
    if accepted:
        main()
        assert len(mock.mutations) == 1
        method, path, payload = mock.mutations[0]
        assert method == "PUT"
        assert path == "zones/" + "a" * 32 + "/dns_records/" + "c" * 32
        assert payload == {
            "name": "dev.tollchat.ai",
            "type": "CNAME",
            "content": "d1wqry4fbd92w5.cloudfront.net",
            "ttl": 1,
            "proxied": False,
        }
    else:
        with pytest.raises(cast(type[Exception], namespace["GateError"])):
            main()
        assert not mock.mutations


def test_slice3_dns_gate_rollback_puts_only_the_captured_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_dns_inputs(monkeypatch, operation="rollback")
    mock = _DnsApiMock(
        zones=[_dns_zone()],
        dev_records=[
            _dns_record("c" * 32, "dev.tollchat.ai", "d1wqry4fbd92w5.cloudfront.net")
        ],
    )
    namespace = _dns_namespace(mock)
    cast(Callable[[], object], namespace["main"])()
    assert len(mock.mutations) == 1
    method, path, payload = mock.mutations[0]
    assert method == "PUT"
    assert path.endswith("/dns_records/" + "c" * 32)
    assert payload is not None
    assert payload["content"] == "dmsiz11apblcv.cloudfront.net"
    assert (
        mock.records["dev.tollchat.ai"][0]["content"] == "dmsiz11apblcv.cloudfront.net"
    )


@pytest.mark.parametrize(
    ("zone_id", "accepted"),
    [("absent", True), ("a" * 32, True), ("f" * 32, False), (None, False)],
)
def test_slice3_dns_zone_scoped_response_allows_only_absent_or_matching_zone_id(
    monkeypatch: pytest.MonkeyPatch, zone_id: str | None, accepted: bool
) -> None:
    _set_dns_inputs(monkeypatch, operation="cutover")
    mock = _DnsApiMock(zones=[_dns_zone()])
    for records in mock.records.values():
        for record in records:
            if zone_id == "absent":
                record.pop("zone_id")
            else:
                record["zone_id"] = zone_id
    namespace = _dns_namespace(mock)
    main = cast(Callable[[], object], namespace["main"])
    if accepted:
        main()
        assert len(mock.mutations) == 1
        assert mock.mutations[0][:2] == (
            "PUT",
            "zones/" + "a" * 32 + "/dns_records/" + "c" * 32,
        )
    else:
        with pytest.raises(cast(type[Exception], namespace["GateError"])):
            main()
        assert not mock.mutations


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        ("_token.acm-validations.aws", True),
        ("_token.jkddzztszm.acm-validations.aws", True),
        ("_token.extra.route.acm-validations.aws", False),
        ("_token.-route.acm-validations.aws", False),
        ("_token.route-.acm-validations.aws", False),
        ("_token.route..acm-validations.aws", False),
        ("_token.route.acm-validations.aws.evil.test", False),
        ("_token.route.attacker.aws", False),
    ],
)
def test_slice3_dns_accepts_only_bounded_acm_validation_values(
    monkeypatch: pytest.MonkeyPatch, value: str, accepted: bool
) -> None:
    _set_dns_inputs(monkeypatch)
    records = json.loads(os.environ["VALIDATION_RECORDS"])
    records[0]["value"] = value
    monkeypatch.setenv("VALIDATION_RECORDS", json.dumps(records))
    mock = _DnsApiMock(
        zones=[_dns_zone()],
        validation_records=[
            _dns_record("d" * 32, "_validation.dev.tollchat.ai", value, ttl=60)
        ],
    )
    namespace = _dns_namespace(mock)
    main = cast(Callable[[], object], namespace["main"])
    if accepted:
        main()
    else:
        with pytest.raises(cast(type[Exception], namespace["GateError"])):
            main()
    assert not mock.mutations


def test_slice3_rollback_legacy_https_health_fails_closed(
    tmp_path: Path,
) -> None:
    function = re.search(
        r"(?ms)^          rollback_legacy_https_health\(\) \{\n(.*?)^          \}\n          if test",
        FOUNDATION_DNS_WORKFLOW,
    )
    assert function is not None
    shell_function = dedent(
        "rollback_legacy_https_health() {\n" + function.group(1) + "}\n"
    )
    for status, expected in (("200", 0), ("500", 1)):
        script = dedent(
            f"""
            set -euo pipefail
            RUNNER_TEMP={tmp_path}
            FAKE_CURL_STATUS={status}
            curl() {{
              if test "$FAKE_CURL_STATUS" = "200"; then
                printf '200'
                return 0
              fi
              printf '500'
              return 22
            }}
            {shell_function}
            rollback_legacy_https_health
            """
        )
        result = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, check=False
        )
        assert result.returncode == expected, result.stderr


def test_slice_3_runbook_documents_the_staged_order_and_rollback() -> None:
    handoff = DEPLOYMENT.split("##### Exact DNS workflow operations and ordering", 1)[1]
    assert handoff.index("legacy_alias_released=true") < handoff.index(
        "before applying the reviewed development alias"
    )
    recovery = DEPLOYMENT.split("##### Failed-cutover recovery and cleanup gate", 1)[1]
    assert recovery.index("first release") < recovery.index("operation=rollback")
    assert recovery.index("operation=rollback") < recovery.index(
        "restore only the old alias"
    )
    for required in (
        "Slice 3 development custom-domain and DNS handoff",
        "enable_development_custom_domain",
        "production-foundation-dns",
        "GET /accounts/{derived_account_id}/tokens/verify",
        "stage-validation",
        "certificate_status=ISSUED",
        "cloudfront_status=Deployed",
        "legacy_alias_released=true",
        "dmsiz11apblcv.cloudfront.net",
        "E1JXKQYNAN39E4",
        "X-Robots-Tag: noindex",
        "operation=rollback",
        "captured snapshot",
        "#333 cleanup",
    ):
        assert required in DEPLOYMENT
