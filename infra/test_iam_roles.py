from pathlib import Path


def block(config: str, name: str) -> str:
    start = config.index(f'data "aws_iam_policy_document" "{name}"')
    next_data = config.find('\ndata "aws_iam_policy_document"', start + 1)
    next_resource = config.find('\nresource "aws_iam_', start + 1)
    ends = [end for end in (next_data, next_resource) if end != -1]
    return config[start : min(ends) if ends else None]


def main() -> None:
    config = Path(__file__).with_name("iam.tf").read_text()
    main_subject = "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:ref:refs/heads/main"
    production_subject = "repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:production"

    for name, subject in {
        "trusted_planner_assume": main_subject,
        "development_deploy_assume": main_subject,
        "production_deploy_assume": production_subject,
    }.items():
        policy = block(config, name)
        assert "sts:AssumeRoleWithWebIdentity" in policy
        assert "aws_iam_openid_connect_provider.github.arn" in policy
        assert 'variable = "token.actions.githubusercontent.com:aud"' in policy
        assert subject in policy

    development = block(config, "development_deploy")
    production = block(config, "production_deploy")
    assert "nova-toll/v2/development/terraform.tfstate" in development
    assert 'nova-toll/v2/terraform.tfstate"]' in production
    assert "development" not in production
    assert "release_plan" not in production
    for policy in (development, production):
        assert 'actions   = ["s3:GetObject", "s3:PutObject"]' in policy
        assert 'actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]' in policy
        assert 'actions   = ["kms:Decrypt", "kms:GenerateDataKey"]' in policy
        assert "resources = [aws_kms_key.tfstate.arn]" in policy
        assert 'variable = "kms:EncryptionContext:aws:s3:arn"' in policy

    assert "nova-toll/v2/development/terraform.tfstate.tflock" in development
    assert "nova-toll/v2/terraform.tfstate.tflock" in production
    assert "nova-toll/v2/terraform.tfstate.tflock" not in development
    assert "nova-toll/v2/development/terraform.tfstate" not in production
    for policy, state in (
        (development, "nova-toll/v2/development/terraform.tfstate"),
        (production, "nova-toll/v2/terraform.tfstate"),
    ):
        assert f'''actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.tfstate.arn]
    condition {{
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values = [
        "${{aws_s3_bucket.tfstate.arn}}/{state}",
        "${{aws_s3_bucket.tfstate.arn}}/{state}.tflock",
      ]''' in policy

    boundary = block(config, "trusted_planner_boundary")
    assert "nova-toll/v2/terraform.tfstate.tflock" in boundary
    assert "production/*/*/release.tfplan" in boundary
    assert "kms:EncryptionContext:aws:s3:arn" in boundary
    assert "kms:*" not in boundary
    assert 'actions   = ["kms:Decrypt"]' in boundary
    assert 'actions   = ["kms:GenerateDataKey"]' in boundary
    assert boundary.count("resources = [aws_kms_key.tfstate.arn]") == 2
    assert "nova-toll/v2/terraform.tfstate.tflock" in boundary
    assert "nova-toll/v2/development/terraform.tfstate" not in boundary
    assert '''actions   = ["kms:GenerateDataKey"]
    resources = [aws_kms_key.tfstate.arn]
    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:s3:arn"
      values   = ["${aws_s3_bucket.tfstate.arn}/nova-toll/v2/terraform.tfstate.tflock"]''' in boundary
    planner = block(config, "trusted_planner")
    assert "source_policy_documents = [data.aws_iam_policy_document.trusted_planner_boundary.json]" in planner
    assert 'permissions_boundary = aws_iam_policy.trusted_planner_boundary.arn' in config
    assert "job_workflow_ref" not in config
    assert "sts:TagSession" not in config


if __name__ == "__main__":
    main()
