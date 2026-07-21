# S3 gateway endpoint — free path for the in-VPC loader Lambda to reach S3
# without a NAT Gateway.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = data.aws_vpc.default.id
  service_name      = "com.amazonaws.${data.aws_region.current.name}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = data.aws_route_tables.default.ids
}

data "aws_prefix_list" "s3" {
  name = "com.amazonaws.${data.aws_region.current.name}.s3"
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

resource "aws_security_group" "loader" {
  name        = "nova-toll-loader"
  description = "toll-loader Lambda ENIs"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_home" {
  security_group_id = aws_security_group.rds.id
  description       = "home IP psql access"
  cidr_ipv4         = "${var.home_ip}/32"
  from_port         = 5432
  to_port           = 5432
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_loader" {
  security_group_id            = aws_security_group.rds.id
  description                  = "toll-loader Lambda"
  referenced_security_group_id = aws_security_group.loader.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "loader_to_rds" {
  security_group_id            = aws_security_group.loader.id
  description                  = "RDS only"
  referenced_security_group_id = aws_security_group.rds.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

# NOT in the spec's "SG egress to RDS SG only" line — added because it's
# required for the loader to reach the S3 gateway endpoint at all (AWS:
# a restricted-egress SG on a gateway endpoint needs an explicit rule for
# the service's prefix list, gateway endpoints don't bypass SG evaluation).
# Flagged to the team lead as a spec gap; without this the loader can never
# read raw/ objects. https://docs.aws.amazon.com/vpc/latest/privatelink/gateway-endpoints.html#gateway-endpoint-security
resource "aws_vpc_security_group_egress_rule" "loader_to_s3" {
  security_group_id = aws_security_group.loader.id
  description       = "S3 gateway endpoint (required, not just RDS)"
  prefix_list_id    = data.aws_prefix_list.s3.id
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}
