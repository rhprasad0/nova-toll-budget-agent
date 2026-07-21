resource "aws_db_instance" "main" {
  identifier     = "nova-toll-db"
  engine         = "postgres"
  engine_version = "17"
  instance_class = "db.t4g.micro"

  db_name  = "nova_toll"
  username = "nova_toll_admin"

  allocated_storage     = 20
  max_allocated_storage = 40
  storage_type          = "gp3"
  storage_encrypted     = true

  multi_az            = false
  publicly_accessible = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  manage_master_user_password         = true
  iam_database_authentication_enabled = true

  backup_retention_period = 7
  deletion_protection     = true
  skip_final_snapshot     = false
}
