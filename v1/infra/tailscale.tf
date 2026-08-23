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
  tailscale_router_ami = "ami-03c42c6db44b3949a"
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

    tailscale up \
      --authkey="$AUTHKEY" \
      --advertise-routes=${data.aws_vpc.default.cidr_block} \
      --advertise-exit-node \
      --advertise-tags=tag:nova-toll-router \
      --ssh
    set -x
  EOF

  tags = {
    Name = "nova-toll-tailscale-router"
  }
}
