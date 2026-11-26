"""Phoenix in AWS (v2/plans/FACTORY-PLAN.md, Stage 3), read from root infra/'s development plan."""

import base64
import re
import shlex
from typing import Any

import yaml

from tests.infrastructure_support import REPO_ROOT

Plan = dict[str, dict[str, Any]]
SECRETS = ("PHOENIX_SECRET", "PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD")
SETTINGS = {
    "PHOENIX_SQL_DATABASE_URL": "postgresql://phoenix_factory@db.example:5432/phoenix?sslmode=verify-full&sslrootcert=/rds/rds-ca.pem",
    "PHOENIX_POSTGRES_USE_AWS_IAM_AUTH": "true",
    "AWS_DEFAULT_REGION": "us-east-1",
    "PHOENIX_PORT": "6006",
    "PHOENIX_ENABLE_AUTH": "true",
    "PHOENIX_USE_SECURE_COOKIES": "true",
    "PHOENIX_DISABLE_AGENT_ASSISTANT": "true",
    "PHOENIX_AGENTS_DISABLE_BASH": "true",
    "PHOENIX_AGENTS_DISABLE_WEB_ACCESS": "true",
    "PHOENIX_AGENTS_DISABLE_GITHUB": "true",
    "PHOENIX_ALLOWED_SANDBOX_PROVIDERS": "NONE",
    "PHOENIX_ENABLE_MCP_SERVER": "false",
    "PHOENIX_TELEMETRY_ENABLED": "false",
    "PHOENIX_DEFAULT_RETENTION_POLICY_DAYS": "30",
    "PHOENIX_DISABLE_MODEL_COST_AUTO_UPDATE": "true",
}


def boot_script(plan: Plan) -> str:
    user_data = base64.b64decode(
        plan["aws_instance.phoenix[0]"]["user_data_base64"]
    ).decode()
    assert "cloud_final_modules:\n  - [scripts-user, always]" in user_data
    return user_data.split("#!/bin/bash\n", 1)[1]


def docker_run(script: str) -> list[str]:
    (command,) = [
        line
        for line in script.replace("\\\n", " ").splitlines()
        if line.startswith("docker run ")
    ]
    return shlex.split(command)


def test_phoenix_instance_is_private_and_requires_imdsv2(
    foundation_development_plan: Plan,
) -> None:
    instance = foundation_development_plan["aws_instance.phoenix[0]"]
    assert instance["instance_type"] == "t4g.small"
    assert instance["associate_public_ip_address"] is False
    assert instance["iam_instance_profile"] == "tollchat-phoenix"
    assert instance["credit_specification"] == [{"cpu_credits": "standard"}]
    (metadata,) = instance["metadata_options"]
    assert metadata["http_tokens"] == "required"
    assert metadata["http_put_response_hop_limit"] == 1
    (root,) = instance["root_block_device"]
    assert root["encrypted"] is True


def test_phoenix_runs_the_compose_image_with_auth_and_features_off(
    foundation_development_plan: Plan,
) -> None:
    arguments = docker_run(boot_script(foundation_development_plan))
    compose = yaml.safe_load((REPO_ROOT / "factory/compose.yaml").read_text())
    image = compose["services"]["phoenix"]["image"]
    assert re.fullmatch(
        r"arizephoenix/phoenix:version-[\d.]+@sha256:[0-9a-f]{64}", image
    )
    assert arguments[-1] == image
    assert arguments[arguments.index("--restart") + 1] == "always"
    assert arguments[arguments.index("--network") + 1] == "host"
    environment = [
        arguments[index + 1]
        for index, argument in enumerate(arguments)
        if argument == "--env"
    ]
    assert [item for item in environment if "=" not in item] == list(SECRETS)
    assert dict(item.split("=", 1) for item in environment if "=" in item) == SETTINGS


def test_phoenix_reads_secrets_from_ssm_and_checks_the_rds_bundle(
    foundation_development_plan: Plan,
) -> None:
    script = boot_script(foundation_development_plan)
    assert script.startswith("set -euo pipefail\n")
    assert "set -x" not in script
    pinned = re.search(
        r'local ca_sha256="([0-9a-f]{64})"',
        (REPO_ROOT / "v2/scripts/build_loader_zip.sh").read_text(),
    )
    assert pinned
    assert f"'{pinned[1]}  /etc/phoenix/rds-ca.pem.new' | sha256sum --check\n" in script
    policy = foundation_development_plan["data.aws_iam_policy_document.phoenix[0]"]
    statements = {item["sid"]: item for item in policy["statement"]}
    assert set(statements) == {"ReadPhoenixSecrets", "ConnectPhoenixDatabase"}
    assert statements["ReadPhoenixSecrets"]["actions"] == ["ssm:GetParameter"]
    parameters = sorted(
        arn.split(":parameter", 1)[1]
        for arn in statements["ReadPhoenixSecrets"]["resources"]
    )
    for parameter in parameters:
        assert f"--name '{parameter}' --with-decryption" in script
    assert parameters == [
        "/nova-toll/factory/phoenix-admin-password",
        "/nova-toll/factory/phoenix-secret",
    ]
    assert statements["ConnectPhoenixDatabase"]["actions"] == ["rds-db:connect"]
    assert statements["ConnectPhoenixDatabase"]["resources"] == [
        "arn:aws:rds-db:us-east-1:903859731897:dbuser:db-RESOURCE/phoenix_factory"
    ]
    attachment = foundation_development_plan[
        "aws_iam_role_policy_attachment.phoenix_ssm[0]"
    ]
    assert attachment["policy_arn"] == (
        "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
    )


def test_factory_connects_only_to_its_own_databases(
    foundation_development_plan: Plan,
) -> None:
    policy = foundation_development_plan["data.aws_iam_policy_document.factory[0]"]
    statements = {item["sid"]: item for item in policy["statement"]}
    assert statements["ConnectFactoryDatabases"]["actions"] == ["rds-db:connect"]
    assert set(statements["ConnectFactoryDatabases"]["resources"]) == {
        "arn:aws:rds-db:us-east-1:903859731897:dbuser:db-RESOURCE/phoenix_factory",
        "arn:aws:rds-db:us-east-1:903859731897:dbuser:db-RESOURCE/chaos_lab",
        "arn:aws:rds-db:us-east-1:903859731897:dbuser:db-RESOURCE/factory_sandbox",
        "arn:aws:rds-db:us-east-1:903859731897:dbuser:db-RESOURCE/factory_sandbox_reader",
    }


def test_phoenix_network_admits_only_cloudfront_and_reaches_only_https_and_rds(
    foundation_development_plan: Plan,
) -> None:
    rules = {
        address: value
        for address, value in foundation_development_plan.items()
        if address.startswith("aws_vpc_security_group_") and "phoenix" in address
    }
    ports = {
        address.split(".")[1]: (
            value["from_port"],
            value["to_port"],
            value["ip_protocol"],
        )
        for address, value in rules.items()
    }
    assert ports == {
        "phoenix_from_cloudfront[0]": (6006, 6006, "tcp"),
        "phoenix_https[0]": (443, 443, "tcp"),
        "phoenix_rds[0]": (5432, 5432, "tcp"),
        "rds_from_phoenix[0]": (5432, 5432, "tcp"),
    }
    ingress = rules["aws_vpc_security_group_ingress_rule.phoenix_from_cloudfront[0]"]
    assert ingress["cidr_ipv4"] is None and ingress["prefix_list_id"]
    assert rules["aws_vpc_security_group_egress_rule.phoenix_https[0]"][
        "cidr_ipv4"
    ] == ("0.0.0.0/0")


def test_phoenix_distribution_forwards_everything_uncached_over_https(
    foundation_development_plan: Plan,
) -> None:
    (endpoint,) = foundation_development_plan["aws_cloudfront_vpc_origin.phoenix[0]"][
        "vpc_origin_endpoint_config"
    ]
    assert endpoint["origin_protocol_policy"] == "http-only"
    assert endpoint["http_port"] == 6006
    distribution = foundation_development_plan["aws_cloudfront_distribution.phoenix[0]"]
    assert distribution["enabled"] is True
    assert distribution["aliases"] is None
    (certificate,) = distribution["viewer_certificate"]
    assert certificate["cloudfront_default_certificate"] is True
    assert certificate["acm_certificate_arn"] is None
    (origin,) = distribution["origin"]
    assert origin["custom_origin_config"] == []
    assert len(origin["vpc_origin_config"]) == 1
    (behavior,) = distribution["default_cache_behavior"]
    assert behavior["viewer_protocol_policy"] == "https-only"
    assert set(behavior["allowed_methods"]) == {
        "DELETE",
        "GET",
        "HEAD",
        "OPTIONS",
        "PATCH",
        "POST",
        "PUT",
    }
    assert behavior["cache_policy_id"] == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    assert (
        behavior["origin_request_policy_id"] == "b689b0a8-53d0-40ab-baf2-68738e2966ac"
    )
