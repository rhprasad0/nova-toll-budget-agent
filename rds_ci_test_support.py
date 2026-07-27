"""Shared, credential-free setup for CI tests that read RDS as pricing_reader."""

import os

import boto3

AWS_REGION = "us-east-1"
DB_IDENTIFIER = "nova-toll-db"  # infra/rds.tf identifier


def configure_pricing_reader_rds_env() -> None:
    """Resolve RDS's non-public endpoint for an IAM-auth pricing-reader test.

    DB_USER, DB_NAME, and DB_CA_BUNDLE_PATH intentionally remain workflow
    inputs: the helper must not embed credentials, database endpoints, or a
    local AWS profile in the repository.
    """
    instance = boto3.client("rds", region_name=AWS_REGION).describe_db_instances(
        DBInstanceIdentifier=DB_IDENTIFIER
    )["DBInstances"][0]
    os.environ["DB_HOST"] = instance["Endpoint"]["Address"]
    os.environ["DB_PORT"] = str(instance["Endpoint"]["Port"])


def connect_as_pricing_reader():
    """Open an independent IAM-auth RDS connection for expected-value reads."""
    import psycopg

    host = os.environ["DB_HOST"]
    port = int(os.environ["DB_PORT"])
    user = os.environ["DB_USER"]
    token = boto3.client("rds", region_name=AWS_REGION).generate_db_auth_token(
        DBHostname=host,
        Port=port,
        DBUsername=user,
    )
    return psycopg.connect(
        host=host,
        port=port,
        dbname=os.environ["DB_NAME"],
        user=user,
        password=token,
        sslmode="verify-full",
        sslrootcert=os.environ["DB_CA_BUNDLE_PATH"],
    )
