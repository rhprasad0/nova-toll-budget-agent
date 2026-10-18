"""Live Terraform for the development custom domain and the DNS role.

The production foundation DNS role stays until a separate foundation change
removes it, so its OIDC/SSM boundary keeps a test until then.
"""

from typing import cast

from tests.infrastructure_support import (
    APPLICATION_VARIABLES,
    DEVELOPMENT_DELIVERY_WORKFLOW,
    DEVELOPMENT_TFVARS,
    ENVIRONMENT_TF,
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
