# S3 gateway endpoint — free path for the in-VPC loader Lambda to reach S3
# without a NAT Gateway.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = data.aws_vpc.default.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = concat(data.aws_route_tables.default.ids, [aws_route_table.tollchat_private.id])
}

data "aws_prefix_list" "s3" {
  name = "com.amazonaws.${data.aws_region.current.region}.s3"
}

resource "aws_db_subnet_group" "main" {
  name       = "nova-toll-db"
  subnet_ids = data.aws_subnets.default.ids
}

# --- security groups -----------------------------------------------------

resource "aws_security_group" "rds" {
  name        = "nova-toll-rds"
  description = "toll-poller RDS instance"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_security_group" "tailscale_router" {
  name        = "nova-toll-tailscale-router"
  description = "Tailscale subnet router -- bridges the tailnet (CI, dev laptop, exit-node traffic) to RDS"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_tailscale" {
  security_group_id            = aws_security_group.rds.id
  description                  = "Tailscale subnet router"
  referenced_security_group_id = aws_security_group.tailscale_router.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

# Allow-all, not scoped like the loader SG's egress: this box is also a
# Tailscale exit node, so it must be able to forward its peer's traffic to
# arbitrary internet destinations, not just RDS.
resource "aws_vpc_security_group_egress_rule" "tailscale_router_egress" {
  security_group_id = aws_security_group.tailscale_router.id
  description       = "Exit-node + DERP/coordination + package installs"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}
