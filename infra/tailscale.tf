# Tailscale subnet router: one t4g.nano in the default VPC that bridges the
# tailnet to the private preview and RDS for owner access, plus exit-node
# coverage on public wifi.
#
# Auth key, ACL policy, and route approval are set up out-of-band in the
# Tailscale admin console -- same "seed a placeholder, real value set via
# CLI" spirit as the SSM tokens in ssm.tf.

# Pinned deliberately, not read from the "latest AL2023 arm64" SSM alias
# (/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64).
# That alias moves whenever Amazon publishes a new image, and since `ami`
# forces replacement, every unrelated infra change would plan a destroy +
# recreate of this router -- taking the RDS bridge (CI, dev laptop, exit
# node) down until the new node re-registers with the tailnet, in a PR that
# had nothing to do with Tailscale. Caught exactly that way: the S3/lambda
# cleanup in PR #5 planned a replacement it never asked for.
#
# This is the image the router has been running since the bridge was built:
# al2023-ami-2023.12.20260724.0-kernel-6.1-arm64 (published 2026-07-24).
# Tradeoff: pinning means OS-image security fixes no longer arrive by
# surprise, so bump this deliberately -- change the id, apply, then confirm
# the new node rejoined the tailnet and its subnet route is live before
# assuming the bridge is back.
locals {
  tailscale_router_ami        = "ami-03c42c6db44b3949a"
  production_account_id       = jsondecode(file("${path.module}/account-contract.json")).accounts.production.id
  development_account_id      = jsondecode(file("${path.module}/account-contract.json")).accounts.development.id
  development_tailscale_route = "fd7a:115c:a1e0:b1a:0:1:ac1f:0/112"
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "tailscale_router" {
  name               = "nova-toll-tailscale-router"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

data "aws_iam_policy_document" "tailscale_router" {
  statement {
    sid       = "ReadAuthkey"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter${var.tailscale_authkey_param_name}"]
  }
}

resource "aws_iam_role_policy" "tailscale_router" {
  name   = "nova-toll-tailscale-router"
  role   = aws_iam_role.tailscale_router.id
  policy = data.aws_iam_policy_document.tailscale_router.json
}

# The authkey SSM param is seeded with a placeholder (see ssm.tf) until it's
# set out-of-band, so first boot's `tailscale up` will fail. Session Manager
# is the recovery path in that window -- no key pair, no SSH ingress rule,
# and Tailscale SSH is unavailable until tailscaled successfully joins.
resource "aws_iam_role_policy_attachment" "tailscale_router_ssm" {
  role       = aws_iam_role.tailscale_router.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "tailscale_router" {
  name = "nova-toll-tailscale-router"
  role = aws_iam_role.tailscale_router.name
}

# data.aws_subnets.default.ids[0] isn't safe to use directly here: it can
# land on an AZ (observed: us-east-1e) that doesn't support t4g instances.
# Pin to a specific AZ known to support it instead.
data "aws_subnet" "tailscale_router" {
  vpc_id = data.aws_vpc.default.id
  filter {
    name   = "availability-zone"
    values = ["us-east-1c"]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

resource "aws_instance" "tailscale_router" {
  ami                    = local.tailscale_router_ami
  instance_type          = "t4g.nano"
  subnet_id              = data.aws_subnet.tailscale_router.id
  vpc_security_group_ids = [aws_security_group.tailscale_router.id]
  iam_instance_profile   = aws_iam_instance_profile.tailscale_router.name

  lifecycle {
    precondition {
      condition     = !var.tailscale_advertise_routes || (var.environment == "production" && data.aws_caller_identity.current.account_id == local.production_account_id) || (var.environment == "development" && data.aws_caller_identity.current.account_id == local.development_account_id)
      error_message = "Tailscale route advertisement is allowed only for the account-local production route or the reviewed development site-1 route."
    }
  }

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  # Subnet-router/exit-node duty requires IP forwarding -- Tailscale won't
  # forward traffic without it.
  user_data = <<-EOF
    #!/bin/bash
    set -euxo pipefail
    curl -fsSL https://tailscale.com/install.sh | sh

    echo 'net.ipv4.ip_forward = 1' > /etc/sysctl.d/99-tailscale.conf
    echo 'net.ipv6.conf.all.forwarding = 1' >> /etc/sysctl.d/99-tailscale.conf
    sysctl -p /etc/sysctl.d/99-tailscale.conf

    systemctl enable --now tailscaled

    # `set +x` around the key: `-x` would otherwise echo the decrypted
    # authkey into cloud-init's log, readable via console-output.
    set +x
    AUTHKEY=$(aws ssm get-parameter \
      --name '${var.tailscale_authkey_param_name}' \
      --with-decryption \
      --query Parameter.Value \
      --output text \
      --region ${data.aws_region.current.region})

    # Development joins without advertising a route or shared ACL tag unless
    # the reviewed site-1 route is explicitly enabled for this account.
    tailscale up \
      --authkey="$AUTHKEY" \
%{if var.tailscale_advertise_routes && var.environment == "production"~}
      --advertise-routes=${data.aws_vpc.default.cidr_block} \
      --advertise-exit-node \
      --advertise-tags=tag:nova-toll-router \
%{endif~}
%{if var.tailscale_advertise_routes && var.environment == "development"~}
      --advertise-routes=${local.development_tailscale_route} \
%{endif~}
      --ssh
    set -x
  EOF

  tags = {
    Name = "nova-toll-tailscale-router"
  }

  volume_tags = {
    project     = "nova-toll-budget-agent"
    environment = "shared"
    shared_with = "development"
  }
}

# Route approval is foundation-owned: application delivery cannot change the
# role trust, command document, or command permissions used to inspect the router.
data "aws_iam_policy_document" "route_control_assume" {
  count = var.environment == "development" ? 1 : 0

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:rhprasad0@91573985/nova-toll-budget-agent@1306930324:environment:development"]
    }
  }
}

resource "aws_ssm_document" "route_control" {
  count           = var.environment == "development" ? 1 : 0
  name            = "nova-toll-v2-route-control-status-dev"
  document_type   = "Command"
  document_format = "YAML"
  content         = <<-DOC
    schemaVersion: '2.2'
    description: Read the enrolled router's local Tailscale identity.
    mainSteps:
      - action: aws:runShellScript
        name: readTailscaleStatus
        inputs:
          timeoutSeconds: '20'
          runCommand:
            - set -eu
            - tailscale status --json
    DOC
}

resource "aws_iam_role" "route_control" {
  count              = var.environment == "development" ? 1 : 0
  name               = "nova-toll-v2-route-control-dev"
  assume_role_policy = data.aws_iam_policy_document.route_control_assume[0].json
}

data "aws_iam_policy_document" "route_control" {
  count = var.environment == "development" ? 1 : 0

  statement {
    sid     = "SendRouterStatusCommand"
    actions = ["ssm:SendCommand"]
    resources = [
      "arn:aws:ec2:us-east-1:903859731897:instance/i-0d33b9a9c15db93fc",
      "arn:aws:ssm:us-east-1:903859731897:document/nova-toll-v2-route-control-status-dev",
    ]
  }

  statement {
    sid       = "ReadRouterStatusCommand"
    actions   = ["ssm:GetCommandInvocation"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestedRegion"
      values   = ["us-east-1"]
    }
  }
}

resource "aws_iam_role_policy" "route_control" {
  count  = var.environment == "development" ? 1 : 0
  name   = "nova-toll-v2-route-control-dev"
  role   = aws_iam_role.route_control[0].id
  policy = data.aws_iam_policy_document.route_control[0].json
}
